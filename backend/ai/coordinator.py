# coordinator.py — AIオーケストレーション
#
# 変更点:
# - 投票を asyncio.gather で全AI並列実行 (14×T → T)
# - 夜行動: 占い・護衛・共有チャットを並列実行、狼チャット→襲撃は依存関係を維持
# - CO判定ロジックを handle_ai_co() に一本化（run_discussion_round から削除）
# - 狼チャット内容を襲撃先決定コンテキストに注入
# - 共有者チャットに専用コンテキスト使用
# - 狼チャットのターン数削減（各狼1発言/ラウンド）
# - 要約蓄積時に圧縮チェック呼び出し

from __future__ import annotations
import asyncio
import random
import re
import traceback
from typing import Optional, Callable, Awaitable

from backend.engine.game import GameController
from backend.engine.state import GameState, Phase, NightAction, ChatMessage
from backend.engine.roles import RoleName

from .personalities import Personality, assign_personalities
from .wolf_strategy import StrategyAssigner, WolfStrategy, MadmanStrategy, FakeResultGuard
from .context import ContextBuilder, DaySummaryManager
from .ai_player import AIPlayer, ClaudeClient


# ─────────────────────────────────────────────
#  チャットメッセージからCOを検知
# ─────────────────────────────────────────────

_CO_PATTERNS = [
    (re.compile(r'占い師\s*(CO|です|でした|をCO|として|カミングアウト)', re.IGNORECASE), RoleName.SEER),
    (re.compile(r'占い\s*CO', re.IGNORECASE), RoleName.SEER),
    (re.compile(r'霊(媒師?|能者?)\s*(CO|です|でした|をCO|として|カミングアウト)', re.IGNORECASE), RoleName.MEDIUM),
    (re.compile(r'霊(媒|能)\s*CO', re.IGNORECASE), RoleName.MEDIUM),
    (re.compile(r'狩人\s*(CO|です|でした|をCO|として|カミングアウト)', re.IGNORECASE), RoleName.HUNTER),
    (re.compile(r'共有者?\s*(CO|です|でした|をCO|として|カミングアウト)', re.IGNORECASE), RoleName.FREEMASON),
    (re.compile(r'共有\s*CO', re.IGNORECASE), RoleName.FREEMASON),
]


def _detect_co_in_message(message: str) -> Optional[RoleName]:
    """発言内容からCO宣言を検知し、該当役職を返す"""
    for pattern, role in _CO_PATTERNS:
        if pattern.search(message):
            return role
    return None


# ─────────────────────────────────────────────
#  安全な非同期実行ラッパー
# ─────────────────────────────────────────────

async def _safe_run(coro):
    """fire-and-forget タスクの例外を握り潰さずログに出す"""
    try:
        return await coro
    except Exception as e:
        print(f"[Background task error] {e}")
        traceback.print_exc()
        return None


# ─────────────────────────────────────────────
#  AICoordinator
# ─────────────────────────────────────────────

class AICoordinator:
    def __init__(self, game: GameController, claude_client: Optional[ClaudeClient] = None,
                 seed: Optional[int] = None):
        self.game = game
        self.state = game.state
        self.rng = random.Random(seed)
        self.seed = seed
        self.client = claude_client or ClaudeClient.create()
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

    # ─────────────────────────────────────────
    #  議論ラウンド（逐次 — 品質優先）
    # ─────────────────────────────────────────

    async def run_discussion_round(self) -> list[dict]:
        """AI全員が順番に発言する。前の発言を読んでから生成するため逐次実行"""
        alive_ai = [pid for pid in self.ai_players if self.state.players[pid].is_alive]
        self.rng.shuffle(alive_ai)
        results = []

        for pid in alive_ai:
            if self.on_typing:
                await self.on_typing(pid, True)

            system, messages = self.context_builder.build_discussion_context(
                pid, self.personalities[pid])
            ai = self.ai_players[pid]
            msg, memo = await ai.generate_discussion_message(system, messages)

            delay = self.rng.uniform(0.5, 1.5)
            await asyncio.sleep(delay)

            if self.on_typing:
                await self.on_typing(pid, False)

            chat_result = self.game.chat(pid, msg)
            if chat_result.get("status") == "sent":
                # 発言からCOを検知して登録（発言によってのみCOが公開される）
                detected_role = _detect_co_in_message(msg)
                if detected_role and not self.state.get_co_for_player(pid):
                    self.game.co(pid, detected_role.value)
                data = {"player_id": pid, "name": self.state.players[pid].name, "content": msg}
                results.append(data)
                if self.on_message:
                    await self.on_message(data)
        return results

    # ─────────────────────────────────────────
    #  投票（全AI並列 — 独立判断なので並列安全）
    # ─────────────────────────────────────────

    async def generate_all_votes(self) -> list[dict]:
        alive_ai = [pid for pid in self.ai_players if self.state.players[pid].is_alive]
        alive_ids = self.state.get_alive_player_ids()
        alive_names = [self.state.players[pid].name for pid in alive_ids]
        name_to_id = {self.state.players[pid].name: pid for pid in alive_ids}

        async def _vote_one(pid: str) -> dict:
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
            return {"player_id": pid, "target_name": target_name,
                    "target_id": target_id, "reason": reason}

        results = await asyncio.gather(*[_vote_one(pid) for pid in alive_ai])
        return list(results)

    # ─────────────────────────────────────────
    #  夜フェーズ（独立行動を並列 + 依存行動は順次）
    # ─────────────────────────────────────────

    async def execute_night_phase(self) -> dict:
        results = {"divine": None, "guard": None, "attack": None,
                   "wolf_chat": [], "freemason_chat": []}

        # Phase 1: 独立した行動を並列実行
        parallel_tasks = {}
        parallel_tasks["divine"] = self._execute_role_action(RoleName.SEER, "divine")
        if self.state.day >= 2:
            parallel_tasks["guard"] = self._execute_role_action(RoleName.HUNTER, "guard")
        parallel_tasks["freemason_chat"] = self._execute_freemason_chat()

        # 狼チャットも他の行動と並列に実行可能（襲撃決定とは別）
        parallel_tasks["wolf_chat"] = self._execute_wolf_chat()

        gathered = await asyncio.gather(
            *[_safe_run(task) for task in parallel_tasks.values()],
            return_exceptions=False
        )
        keys = list(parallel_tasks.keys())
        for i, key in enumerate(keys):
            results[key] = gathered[i]

        # Phase 2: 狼チャット内容を参照して襲撃先を決定（依存関係あり）
        results["attack"] = await self._execute_wolf_attack()

        return results

    async def _execute_role_action(self, role: RoleName, action_type: str) -> Optional[dict]:
        actors = [p for p in self.state.players.values()
                  if p.role == role and p.is_alive and not p.is_human
                  and p.player_id in self.ai_players]
        if not actors:
            return None
        actor = actors[0]
        ai = self.ai_players[actor.player_id]

        valid_targets = [pid for pid in self.state.get_alive_player_ids()
                         if pid != actor.player_id]
        if action_type == "divine":
            valid_targets = [pid for pid in valid_targets
                             if pid not in {dr.target_id for dr in actor.divine_results}]
        if not valid_targets:
            return None

        system, messages = self.context_builder.build_night_action_context(
            actor.player_id, self.personalities[actor.player_id],
            action_type, valid_targets, reasoning_memo=ai.get_memo())
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

        # ターン数削減: 各狼1発言（計3発言以下）
        results = []
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

        # 狼チャットログを襲撃先決定コンテキストに注入
        wolf_chat_log = self.state.get_chat_log(channel="wolf", day=self.state.day)
        system, messages = self.context_builder.build_night_action_context(
            alpha_id, self.personalities[alpha_id], "attack", valid_targets,
            reasoning_memo=ai.get_memo(), wolf_chat_log=wolf_chat_log)

        valid_names = [self.state.players[tid].name for tid in valid_targets]
        target_name, reason = await ai.generate_night_action(system, messages, valid_names)
        name_to_id = {self.state.players[tid].name: tid for tid in valid_targets}
        target_id = name_to_id.get(target_name, self.rng.choice(valid_targets))

        self.game.submit_night_action(alpha_id, "attack", target_id)
        return {"actor": alpha_id, "target": target_id, "reason": reason}

    async def _execute_freemason_chat(self) -> list[dict]:
        """共有者専用チャット（専用コンテキスト使用）"""
        members = [p for p in self.state.players.values()
                   if p.role == RoleName.FREEMASON and p.is_alive
                   and not p.is_human and p.player_id in self.ai_players]
        if not members:
            return []
        results = []
        for m in members:
            ai = self.ai_players[m.player_id]
            log = self.state.get_chat_log(channel="freemason", day=self.state.day)
            system, messages = self.context_builder.build_freemason_chat_context(
                m.player_id, self.personalities[m.player_id], log)
            msg = await ai.generate_wolf_chat(system, messages)  # 短文生成は同じメソッドで可
            self.game.chat(m.player_id, msg, channel="freemason")
            results.append({"player_id": m.player_id, "name": m.name, "content": msg})
        return results

    # ─────────────────────────────────────────
    #  要約生成
    # ─────────────────────────────────────────

    async def generate_day_summary(self, day: int) -> str:
        system, messages = self.context_builder.build_summary_context(day)
        raw = await self.client.generate(system, messages, max_tokens=1024, temperature=0.3)
        if raw:
            self.summary_manager.add_summary(day, raw)
            self.summary_manager.compress_if_needed()  # 安全弁: 蓄積しすぎ防止
            return raw
        return f"{day}日目の要約: 議論が行われました。"

    # ─────────────────────────────────────────
    #  CO処理（唯一の入口）
    # ─────────────────────────────────────────

    async def handle_ai_co(self) -> list[dict]:
        """AI全員のCO判定を行う。CO判定はここだけで実行する"""
        results = []

        # 真役職のCO
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

        # 人狼の偽CO
        if self.wolf_strategy and self.state.day >= 2:
            for attr, role_val in [("fake_seer_id", RoleName.SEER),
                                   ("fake_medium_id", RoleName.MEDIUM)]:
                fake_id = getattr(self.wolf_strategy, attr)
                if (fake_id and fake_id in self.ai_players
                        and self.state.players[fake_id].is_alive
                        and not self.state.get_co_for_player(fake_id)):
                    r = self.game.co(fake_id, role_val.value)
                    if r.get("status") == "co_accepted":
                        results.append({"player_id": fake_id,
                                        "role": role_val.value, "is_fake": True})

        # 狂人の偽CO
        if self.madman_strategy and self.state.day >= 2:
            role_map = {"fake_seer": RoleName.SEER, "fake_medium": RoleName.MEDIUM}
            target_role = role_map.get(self.madman_strategy.strategy)
            if target_role:
                for mp in self.state.players.values():
                    if (mp.role == RoleName.MADMAN and not mp.is_human
                            and mp.is_alive and not self.state.get_co_for_player(mp.player_id)):
                        r = self.game.co(mp.player_id, target_role.value)
                        if r.get("status") == "co_accepted":
                            results.append({"player_id": mp.player_id,
                                            "role": target_role.value, "is_fake": True})
        return results
