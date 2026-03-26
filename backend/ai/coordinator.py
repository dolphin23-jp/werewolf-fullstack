# coordinator.py — 議論オーケストレーション、投票生成、夜フェーズ実行、要約

from __future__ import annotations
import asyncio
import random
from typing import Optional, Callable, Awaitable

from backend.engine.game import GameController
from backend.engine.state import GameState, Phase, NightAction, ChatMessage
from backend.engine.roles import RoleName

from .personalities import Personality, assign_personalities
from .wolf_strategy import StrategyAssigner, WolfStrategy, MadmanStrategy, FakeResultGuard
from .context import ContextBuilder, DaySummaryManager
from .ai_player import AIPlayer, ClaudeClient


class AICoordinator:
    def __init__(self, game: GameController, claude_client: Optional[ClaudeClient] = None,
                 seed: Optional[int] = None):
        self.game = game
        self.state = game.state
        self.rng = random.Random(seed)
        self.seed = seed
        self.client = claude_client or ClaudeClient()
        self.ai_players: dict[str, AIPlayer] = {}
        self.personalities: dict[str, Personality] = {}
        self.summary_manager = DaySummaryManager()
        self.context_builder: Optional[ContextBuilder] = None
        self.wolf_strategy: Optional[WolfStrategy] = None
        self.madman_strategy: Optional[MadmanStrategy] = None
        self.fake_guards: dict[str, FakeResultGuard] = {}
        self.on_typing: Optional[Callable[[str, bool], Awaitable[None]]] = None
        self.on_message: Optional[Callable[[dict], Awaitable[None]]] = None

    def initialize(self) -> None:
        ai_ids = [pid for pid, p in self.state.players.items()
                  if not p.is_human and not p.is_first_victim]
        self.personalities = assign_personalities(ai_ids, seed=self.seed)
        for pid in ai_ids:
            player = self.state.players[pid]
            self.ai_players[pid] = AIPlayer(pid, player.name, self.personalities[pid], self.client)
        self.context_builder = ContextBuilder(self.state, self.summary_manager)
        self._assign_strategies()

    def _assign_strategies(self) -> None:
        wolf_ids = self.state.get_wolf_ids()
        ai_wolf_ids = [wid for wid in wolf_ids if wid in self.ai_players]
        if len(ai_wolf_ids) >= 3:
            assigner = StrategyAssigner(seed=self.seed)
            self.wolf_strategy = assigner.assign_wolf_strategy(ai_wolf_ids[:3])
            for wid in ai_wolf_ids:
                self.fake_guards[wid] = FakeResultGuard(wid, RoleName.WEREWOLF, wolf_ids)
        madman_ai = [p for p in self.state.players.values()
                     if p.role == RoleName.MADMAN and not p.is_human and not p.is_first_victim]
        if madman_ai:
            assigner = StrategyAssigner(seed=self.seed)
            self.madman_strategy = assigner.assign_madman_strategy()
            for mp in madman_ai:
                self.fake_guards[mp.player_id] = FakeResultGuard(mp.player_id, RoleName.MADMAN, wolf_ids)

    async def run_discussion_round(self) -> list[dict]:
        alive_ai = [pid for pid in self.ai_players if self.state.players[pid].is_alive]
        self.rng.shuffle(alive_ai)
        results = []
        for pid in alive_ai:
            ai = self.ai_players[pid]
            player = self.state.players[pid]
            if not self.state.get_co_for_player(pid):
                co_role = None
                if player.role in (RoleName.SEER, RoleName.MEDIUM) and self.state.day >= 2:
                    co_role = player.role
                elif self.wolf_strategy and self.state.day >= 2:
                    if pid == self.wolf_strategy.fake_seer_id: co_role = RoleName.SEER
                    elif pid == self.wolf_strategy.fake_medium_id: co_role = RoleName.MEDIUM
                elif self.madman_strategy and self.state.day >= 2 and player.role == RoleName.MADMAN:
                    if self.madman_strategy.strategy == "fake_seer": co_role = RoleName.SEER
                    elif self.madman_strategy.strategy == "fake_medium": co_role = RoleName.MEDIUM
                if co_role:
                    self.game.co(pid, co_role.value)
            if self.on_typing:
                await self.on_typing(pid, True)
            system, messages = self.context_builder.build_discussion_context(pid, self.personalities[pid])
            msg, memo = await ai.generate_discussion_message(system, messages)
            delay = self.rng.uniform(0.5, 1.5)
            await asyncio.sleep(delay)
            if self.on_typing:
                await self.on_typing(pid, False)
            chat_result = self.game.chat(pid, msg)
            if chat_result.get("status") == "sent":
                data = {"player_id": pid, "name": self.state.players[pid].name, "content": msg}
                results.append(data)
                if self.on_message:
                    await self.on_message(data)
        return results

    async def generate_all_votes(self) -> list[dict]:
        alive_ai = [pid for pid in self.ai_players if self.state.players[pid].is_alive]
        alive_ids = self.state.get_alive_player_ids()
        alive_names = [self.state.players[pid].name for pid in alive_ids]
        name_to_id = {self.state.players[pid].name: pid for pid in alive_ids}
        results = []
        for pid in alive_ai:
            ai = self.ai_players[pid]
            system, messages = self.context_builder.build_vote_context(
                pid, self.personalities[pid], alive_ids, reasoning_memo=ai.get_memo())
            target_name, reason = await ai.generate_vote(system, messages, alive_names)
            target_id = name_to_id.get(target_name)
            if target_id and target_id != pid:
                self.game.vote(pid, target_id)
            else:
                valid_ids = [tid for tid in alive_ids if tid != pid]
                target_id = self.rng.choice(valid_ids) if valid_ids else alive_ids[0]
                self.game.vote(pid, target_id)
                target_name = self.state.players[target_id].name
            results.append({"player_id": pid, "target_name": target_name, "target_id": target_id, "reason": reason})
        return results

    async def execute_night_phase(self) -> dict:
        results = {"divine": None, "guard": None, "attack": None, "wolf_chat": [], "freemason_chat": []}
        results["divine"] = await self._execute_role_action(RoleName.SEER, "divine")
        if self.state.day >= 2:
            results["guard"] = await self._execute_role_action(RoleName.HUNTER, "guard")
        results["wolf_chat"] = await self._execute_wolf_chat()
        results["attack"] = await self._execute_wolf_attack()
        results["freemason_chat"] = await self._execute_group_chat(RoleName.FREEMASON, "freemason")
        return results

    async def _execute_role_action(self, role: RoleName, action_type: str) -> Optional[dict]:
        actors = [p for p in self.state.players.values()
                  if p.role == role and p.is_alive and not p.is_human and p.player_id in self.ai_players]
        if not actors:
            return None
        actor = actors[0]
        ai = self.ai_players[actor.player_id]
        valid_targets = [pid for pid in self.state.get_alive_player_ids() if pid != actor.player_id]
        if action_type == "divine":
            valid_targets = [pid for pid in valid_targets
                             if pid not in {dr.target_id for dr in actor.divine_results}]
        if not valid_targets:
            return None
        system, messages = self.context_builder.build_night_action_context(
            actor.player_id, self.personalities[actor.player_id], action_type, valid_targets,
            reasoning_memo=ai.get_memo())
        valid_names = [self.state.players[tid].name for tid in valid_targets]
        target_name, reason = await ai.generate_night_action(system, messages, valid_names)
        name_to_id = {self.state.players[tid].name: tid for tid in valid_targets}
        target_id = name_to_id.get(target_name, self.rng.choice(valid_targets))
        self.game.submit_night_action(actor.player_id, action_type, target_id)
        return {"actor": actor.player_id, "target": target_id, "reason": reason}

    async def _execute_wolf_chat(self) -> list[dict]:
        alive_wolves = [p for p in self.state.players.values()
                        if p.role == RoleName.WEREWOLF and p.is_alive
                        and not p.is_human and p.player_id in self.ai_players]
        if not alive_wolves:
            return []
        max_turns = 3 if self.state.day == 1 else 2
        results = []
        for _ in range(max_turns):
            for wolf in alive_wolves:
                ai = self.ai_players[wolf.player_id]
                wolf_log = self.state.get_chat_log(channel="wolf", day=self.state.day)
                system, messages = self.context_builder.build_wolf_chat_context(
                    wolf.player_id, self.personalities[wolf.player_id], wolf_log)
                msg = await ai.generate_wolf_chat(system, messages)
                self.game.chat(wolf.player_id, msg, channel="wolf")
                results.append({"player_id": wolf.player_id, "name": wolf.name, "content": msg})
                await asyncio.sleep(0.1)
        return results

    async def _execute_wolf_attack(self) -> Optional[dict]:
        if not self.state.alpha_tracker:
            return None
        alpha_id = self.state.alpha_tracker.get_alpha()
        if not alpha_id or alpha_id not in self.ai_players:
            return None
        if not self.state.players[alpha_id].is_alive:
            return None
        ai = self.ai_players[alpha_id]
        valid_targets = [pid for pid in self.state.get_alive_player_ids()
                         if self.state.players[pid].role != RoleName.WEREWOLF]
        if not valid_targets:
            return None
        system, messages = self.context_builder.build_night_action_context(
            alpha_id, self.personalities[alpha_id], "attack", valid_targets, reasoning_memo=ai.get_memo())
        valid_names = [self.state.players[tid].name for tid in valid_targets]
        target_name, reason = await ai.generate_night_action(system, messages, valid_names)
        name_to_id = {self.state.players[tid].name: tid for tid in valid_targets}
        target_id = name_to_id.get(target_name, self.rng.choice(valid_targets))
        self.game.submit_night_action(alpha_id, "attack", target_id)
        return {"actor": alpha_id, "target": target_id, "reason": reason}

    async def _execute_group_chat(self, role: RoleName, channel: str) -> list[dict]:
        members = [p for p in self.state.players.values()
                   if p.role == role and p.is_alive and not p.is_human and p.player_id in self.ai_players]
        if not members:
            return []
        results = []
        for m in members:
            ai = self.ai_players[m.player_id]
            log = self.state.get_chat_log(channel=channel, day=self.state.day)
            system, messages = self.context_builder.build_wolf_chat_context(
                m.player_id, self.personalities[m.player_id], log)
            msg = await ai.generate_wolf_chat(system, messages)
            self.game.chat(m.player_id, msg, channel=channel)
            results.append({"player_id": m.player_id, "name": m.name, "content": msg})
        return results

    async def generate_day_summary(self, day: int) -> str:
        system, messages = self.context_builder.build_summary_context(day)
        raw = await self.client.generate(system, messages, max_tokens=1024, temperature=0.3)
        if raw:
            self.summary_manager.add_summary(day, raw)
            return raw
        return f"{day}日目の要約: 議論が行われました。"

    async def handle_ai_co(self) -> list[dict]:
        results = []
        for pid, ai in self.ai_players.items():
            player = self.state.players[pid]
            if not player.is_alive or self.state.get_co_for_player(pid):
                continue
            if player.role == RoleName.SEER and self.state.day >= 2:
                r = self.game.co(pid, RoleName.SEER.value)
                if r.get("status") == "co_accepted":
                    results.append({"player_id": pid, "role": "seer", "is_fake": False})
            elif player.role == RoleName.MEDIUM and self.state.day >= 2:
                r = self.game.co(pid, RoleName.MEDIUM.value)
                if r.get("status") == "co_accepted":
                    results.append({"player_id": pid, "role": "medium", "is_fake": False})

        if self.wolf_strategy and self.state.day >= 2:
            for attr, role_val in [("fake_seer_id", RoleName.SEER), ("fake_medium_id", RoleName.MEDIUM)]:
                fake_id = getattr(self.wolf_strategy, attr)
                if fake_id and fake_id in self.ai_players and self.state.players[fake_id].is_alive \
                        and not self.state.get_co_for_player(fake_id):
                    r = self.game.co(fake_id, role_val.value)
                    if r.get("status") == "co_accepted":
                        results.append({"player_id": fake_id, "role": role_val.value, "is_fake": True})

        if self.madman_strategy and self.state.day >= 2:
            for mp in self.state.players.values():
                if mp.role != RoleName.MADMAN or mp.is_human or not mp.is_alive:
                    continue
                if self.state.get_co_for_player(mp.player_id):
                    continue
                role_map = {"fake_seer": RoleName.SEER, "fake_medium": RoleName.MEDIUM}
                target_role = role_map.get(self.madman_strategy.strategy)
                if target_role:
                    r = self.game.co(mp.player_id, target_role.value)
                    if r.get("status") == "co_accepted":
                        results.append({"player_id": mp.player_id, "role": target_role.value, "is_fake": True})
        return results
