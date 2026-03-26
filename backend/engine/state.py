# state.py — GameState, PlayerState, フェーズ遷移, 視点別情報

from __future__ import annotations
import time
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, Any

from .roles import (
    RoleName, Team, ROLE_DEFINITIONS,
    get_role_def, get_team, is_wolf, AlphaWolfTracker,
)


class Phase(str, Enum):
    WAITING = "waiting"
    NIGHT = "night"
    DAWN = "dawn"
    DISCUSSION = "discussion"
    VOTING = "voting"
    VOTE_RESULT = "vote_result"
    RUNOFF = "runoff"
    GAME_OVER = "game_over"


class DeathCause(str, Enum):
    EXECUTED = "executed"
    ATTACKED = "attacked"
    CURSED = "cursed"
    FIRST_VICTIM = "first_victim"


@dataclass
class COInfo:
    player_id: str
    claimed_role: RoleName
    day: int
    timestamp: float = field(default_factory=time.time)


@dataclass
class DivineRecord:
    day: int
    target_id: str
    result: str


@dataclass
class MediumRecord:
    day: int
    target_id: str
    result: str


@dataclass
class VoteRecord:
    day: int
    round: int
    voter_id: str
    target_id: str


@dataclass
class DeathRecord:
    player_id: str
    day: int
    cause: DeathCause
    role: RoleName


@dataclass
class ChatMessage:
    sender_id: str
    sender_name: str
    content: str
    channel: str
    day: int
    phase: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class PlayerState:
    player_id: str
    name: str
    role: RoleName
    is_alive: bool = True
    is_human: bool = False
    is_first_victim: bool = False
    divine_results: list[DivineRecord] = field(default_factory=list)
    medium_results: list[MediumRecord] = field(default_factory=list)
    last_guard_target: Optional[str] = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "player_id": self.player_id,
            "name": self.name,
            "is_alive": self.is_alive,
            "is_human": self.is_human,
            "is_first_victim": self.is_first_victim,
        }

    def to_private_dict(self) -> dict[str, Any]:
        d = self.to_public_dict()
        d["role"] = self.role.value
        d["role_display"] = get_role_def(self.role).display_name
        d["divine_results"] = [
            {"day": r.day, "target_id": r.target_id, "result": r.result}
            for r in self.divine_results
        ]
        d["medium_results"] = [
            {"day": r.day, "target_id": r.target_id, "result": r.result}
            for r in self.medium_results
        ]
        return d


@dataclass
class NightAction:
    actor_id: str
    action_type: str
    target_id: str


class GameState:
    def __init__(self, game_id: str):
        self.game_id = game_id
        self.phase: Phase = Phase.WAITING
        self.day: int = 0
        self.vote_round: int = 1
        self.max_vote_rounds: int = 4
        self.players: dict[str, PlayerState] = {}
        self.player_order: list[str] = []
        self.first_victim_id: Optional[str] = None
        self.alpha_tracker: Optional[AlphaWolfTracker] = None
        self.co_list: list[COInfo] = []
        self.chat_log: list[ChatMessage] = []
        self.vote_history: list[VoteRecord] = []
        self.death_records: list[DeathRecord] = []
        self.current_night_actions: list[NightAction] = []
        self.today_executed_id: Optional[str] = None
        self.winner: Optional[str] = None
        self.victory_reason: Optional[str] = None
        self.freemason_ids: list[str] = []

    def add_player(self, player_id: str, name: str, role: RoleName,
                   is_human: bool = False, is_first_victim: bool = False) -> PlayerState:
        ps = PlayerState(player_id=player_id, name=name, role=role,
                         is_human=is_human, is_first_victim=is_first_victim)
        self.players[player_id] = ps
        self.player_order.append(player_id)
        if is_first_victim:
            self.first_victim_id = player_id
        if role == RoleName.FREEMASON:
            self.freemason_ids.append(player_id)
        return ps

    def get_player(self, player_id: str) -> Optional[PlayerState]:
        return self.players.get(player_id)

    def get_alive_players(self) -> list[PlayerState]:
        return [p for p in self.players.values() if p.is_alive]

    def get_alive_player_ids(self) -> list[str]:
        return [p.player_id for p in self.players.values() if p.is_alive]

    def get_alive_wolves(self) -> list[PlayerState]:
        return [p for p in self.players.values() if p.is_alive and p.role == RoleName.WEREWOLF]

    def get_alive_wolf_ids(self) -> list[str]:
        return [p.player_id for p in self.get_alive_wolves()]

    def get_players_by_role(self, role: RoleName) -> list[PlayerState]:
        return [p for p in self.players.values() if p.role == role]

    def get_wolf_ids(self) -> list[str]:
        return [p.player_id for p in self.players.values() if p.role == RoleName.WEREWOLF]

    def kill_player(self, player_id: str, cause: DeathCause) -> DeathRecord:
        p = self.players[player_id]
        p.is_alive = False
        record = DeathRecord(player_id=player_id, day=self.day, cause=cause, role=p.role)
        self.death_records.append(record)
        if p.role == RoleName.WEREWOLF and self.alpha_tracker:
            alive_wolves = self.get_alive_wolf_ids()
            self.alpha_tracker.on_wolf_death(player_id, alive_wolves)
        return record

    def set_phase(self, phase: Phase) -> None:
        self.phase = phase

    def advance_day(self) -> None:
        self.day += 1
        self.vote_round = 1
        self.today_executed_id = None
        self.current_night_actions.clear()

    def next_vote_round(self) -> int:
        self.vote_round += 1
        return self.vote_round

    def add_co(self, player_id: str, claimed_role: RoleName) -> COInfo:
        co = COInfo(player_id=player_id, claimed_role=claimed_role, day=self.day)
        self.co_list.append(co)
        return co

    def get_co_for_player(self, player_id: str) -> Optional[COInfo]:
        for co in reversed(self.co_list):
            if co.player_id == player_id:
                return co
        return None

    def get_co_summary(self) -> dict[str, list[str]]:
        summary: dict[str, list[str]] = {}
        seen: set[str] = set()
        for co in self.co_list:
            if co.player_id in seen:
                continue
            seen.add(co.player_id)
            role_name = get_role_def(co.claimed_role).display_name
            if role_name not in summary:
                summary[role_name] = []
            summary[role_name].append(self.players[co.player_id].name)
        return summary

    def add_chat(self, sender_id: str, content: str, channel: str = "public") -> ChatMessage:
        p = self.players[sender_id]
        msg = ChatMessage(sender_id=sender_id, sender_name=p.name, content=content,
                          channel=channel, day=self.day, phase=self.phase.value)
        self.chat_log.append(msg)
        return msg

    def add_system_message(self, content: str, channel: str = "public") -> ChatMessage:
        msg = ChatMessage(sender_id="system", sender_name="システム", content=content,
                          channel=channel, day=self.day, phase=self.phase.value)
        self.chat_log.append(msg)
        return msg

    def get_chat_log(self, channel: str = "public", day: Optional[int] = None) -> list[ChatMessage]:
        msgs = [m for m in self.chat_log if m.channel == channel]
        if day is not None:
            msgs = [m for m in msgs if m.day == day]
        return msgs

    def add_night_action(self, action: NightAction) -> None:
        self.current_night_actions = [
            a for a in self.current_night_actions
            if not (a.actor_id == action.actor_id and a.action_type == action.action_type)
        ]
        self.current_night_actions.append(action)

    def get_night_action(self, actor_id: str, action_type: str) -> Optional[NightAction]:
        for a in self.current_night_actions:
            if a.actor_id == actor_id and a.action_type == action_type:
                return a
        return None

    def add_vote(self, voter_id: str, target_id: str) -> VoteRecord:
        record = VoteRecord(day=self.day, round=self.vote_round, voter_id=voter_id, target_id=target_id)
        self.vote_history.append(record)
        return record

    def get_votes_for_round(self, day: Optional[int] = None, vote_round: Optional[int] = None) -> list[VoteRecord]:
        d = day if day is not None else self.day
        r = vote_round if vote_round is not None else self.vote_round
        return [v for v in self.vote_history if v.day == d and v.round == r]

    def get_player_view(self, player_id: str) -> dict[str, Any]:
        player = self.players[player_id]
        view: dict[str, Any] = {
            "game_id": self.game_id,
            "phase": self.phase.value,
            "day": self.day,
            "vote_round": self.vote_round,
            "my_info": player.to_private_dict(),
            "players": [p.to_public_dict() for p in self.players.values()],
            "alive_players": [p.to_public_dict() for p in self.get_alive_players()],
            "co_summary": self.get_co_summary(),
            "death_records": [
                {"player_id": d.player_id, "name": self.players[d.player_id].name,
                 "day": d.day, "cause": d.cause.value}
                for d in self.death_records
            ],
            "vote_history": [
                {"day": v.day, "round": v.round,
                 "voter": self.players[v.voter_id].name,
                 "target": self.players[v.target_id].name}
                for v in self.vote_history
            ],
        }
        if player.role == RoleName.WEREWOLF:
            wolf_ids = self.get_wolf_ids()
            view["wolf_allies"] = [
                {"player_id": wid, "name": self.players[wid].name}
                for wid in wolf_ids if wid != player_id
            ]
            if self.alpha_tracker:
                view["is_alpha"] = self.alpha_tracker.is_alpha_wolf(player_id)
                view["alpha_id"] = self.alpha_tracker.get_alpha()
        if player.role == RoleName.FREEMASON:
            view["freemason_partner"] = [
                {"player_id": fid, "name": self.players[fid].name}
                for fid in self.freemason_ids if fid != player_id
            ]
        if self.phase == Phase.GAME_OVER:
            view["winner"] = self.winner
            view["victory_reason"] = self.victory_reason
            view["all_roles"] = {
                pid: {"name": p.name, "role": p.role.value,
                      "role_display": get_role_def(p.role).display_name,
                      "team": get_team(p.role).value}
                for pid, p in self.players.items()
            }
        return view

    def to_debug_dict(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id, "phase": self.phase.value,
            "day": self.day, "vote_round": self.vote_round,
            "players": {
                pid: {"name": p.name, "role": p.role.value, "is_alive": p.is_alive,
                      "is_human": p.is_human, "is_first_victim": p.is_first_victim}
                for pid, p in self.players.items()
            },
            "alpha_wolf": self.alpha_tracker.get_alpha() if self.alpha_tracker else None,
            "death_count": len(self.death_records),
            "winner": self.winner,
        }
