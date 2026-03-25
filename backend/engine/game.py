“””
game.py — GameController (ステートマシン)、GameEvent、CO
“””

from **future** import annotations
import random
import time
from dataclasses import dataclass, field
from typing import Optional, Callable, Any

from .roles import RoleName, Team, RoleAssigner, AlphaWolfTracker, get_role_def
from .state import GameState, Phase, PlayerState, NightAction, DeathCause, ChatMessage
from .night_resolver import NightResolver, validate_night_action
from .vote import VoteManager, VoteResult
from .victory import VictoryChecker, VictoryResult

@dataclass
class GameEvent:
event_type: str
data: dict = field(default_factory=dict)
recipients: Optional[list[str]] = None
timestamp: float = field(default_factory=time.time)

AI_NAMES = [
“アカリ”, “ソラ”, “ユウキ”, “ミナト”, “ハルカ”,
“レン”, “シオン”, “カエデ”, “リク”, “ヒナタ”,
“ツムギ”, “アオイ”, “ナギサ”, “コハク”, “イブキ”,
]

FIRST_VICTIM_NAME = “旅人”

class GameController:
def **init**(self, game_id: str = “game_001”, seed: Optional[int] = None):
self.state = GameState(game_id=game_id)
self.seed = seed
self.rng = random.Random(seed)
self.events: list[GameEvent] = []
self.event_listeners: list[Callable[[GameEvent], None]] = []
self.vote_manager: Optional[VoteManager] = None
self.night_resolver: Optional[NightResolver] = None
self.victory_checker: Optional[VictoryChecker] = None

```
def add_event_listener(self, listener: Callable[[GameEvent], None]) -> None:
    self.event_listeners.append(listener)

def _emit(self, event: GameEvent) -> None:
    self.events.append(event)
    for listener in self.event_listeners:
        try:
            listener(event)
        except Exception:
            pass

def create_game(self, player_name: str) -> dict:
    if self.state.phase != Phase.WAITING:
        return {"error": "ゲームは既に開始されています"}

    ai_names = list(AI_NAMES)
    self.rng.shuffle(ai_names)

    human_id = "player_human"
    first_victim_id = "player_npc"
    player_ids = [human_id] + [f"player_ai_{i+1:02d}" for i in range(15)] + [first_victim_id]

    assigner = RoleAssigner(seed=self.seed)
    role_assignment = assigner.assign(player_ids, first_victim_id)

    self.state.add_player(human_id, player_name, role_assignment[human_id], is_human=True)
    for i in range(15):
        ai_id = f"player_ai_{i+1:02d}"
        self.state.add_player(ai_id, ai_names[i], role_assignment[ai_id])
    self.state.add_player(first_victim_id, FIRST_VICTIM_NAME, role_assignment[first_victim_id],
                          is_first_victim=True)

    wolf_ids = self.state.get_wolf_ids()
    self.state.alpha_tracker = AlphaWolfTracker(wolf_ids, seed=self.seed)
    self.vote_manager = VoteManager(self.state, seed=self.seed)
    self.night_resolver = NightResolver(self.state)
    self.victory_checker = VictoryChecker(self.state)

    self._emit(GameEvent(event_type="game_created", data={
        "game_id": self.state.game_id, "human_player_id": human_id,
        "players": [{"player_id": pid, "name": self.state.players[pid].name} for pid in player_ids],
    }))

    return {
        "game_id": self.state.game_id, "human_player_id": human_id,
        "player_count": len(player_ids),
        "players": [{"player_id": pid, "name": self.state.players[pid].name} for pid in player_ids],
    }

def start_game(self) -> dict:
    if self.state.phase != Phase.WAITING:
        return {"error": "ゲームは既に開始されています"}
    self.state.day = 1
    self.state.set_phase(Phase.NIGHT)

    if self.state.first_victim_id and self.state.alpha_tracker:
        alpha_id = self.state.alpha_tracker.get_alpha()
        if alpha_id:
            self.state.add_night_action(NightAction(
                actor_id=alpha_id, action_type="attack", target_id=self.state.first_victim_id))

    self._send_role_notifications()
    self._emit(GameEvent(event_type="game_started", data={"day": 1, "phase": "night"}))
    self._emit(GameEvent(event_type="phase_changed", data={"phase": "night", "day": 1}))
    return {"status": "started", "day": 1, "phase": "night"}

def _send_role_notifications(self) -> None:
    for pid, player in self.state.players.items():
        if player.is_first_victim:
            continue
        if player.role == RoleName.WEREWOLF:
            wolf_names = [self.state.players[wid].name for wid in self.state.get_wolf_ids() if wid != pid]
            is_alpha = self.state.alpha_tracker and self.state.alpha_tracker.is_alpha_wolf(pid)
            self._emit(GameEvent(event_type="role_info", data={
                "role": "werewolf", "allies": wolf_names, "is_alpha": is_alpha,
            }, recipients=[pid]))
        elif player.role == RoleName.FREEMASON:
            partner_names = [self.state.players[fid].name for fid in self.state.freemason_ids if fid != pid]
            self._emit(GameEvent(event_type="role_info", data={
                "role": "freemason", "partner": partner_names,
            }, recipients=[pid]))

def submit_night_action(self, actor_id: str, action_type: str, target_id: str) -> dict:
    if self.state.phase != Phase.NIGHT:
        return {"error": "夜フェーズではありません"}
    valid, msg = validate_night_action(self.state, actor_id, action_type, target_id)
    if not valid:
        return {"error": msg}
    self.state.add_night_action(NightAction(actor_id=actor_id, action_type=action_type, target_id=target_id))
    return {"status": "accepted", "action_type": action_type}

def resolve_night(self) -> dict:
    if self.state.phase != Phase.NIGHT:
        return {"error": "夜フェーズではありません"}
    resolver = NightResolver(self.state)
    result = resolver.resolve_day0() if self.state.day == 1 else resolver.resolve()

    self.state.advance_day()
    self.state.set_phase(Phase.DAWN)

    for death in result.deaths:
        self._emit(GameEvent(event_type="player_died", data={
            "player_id": death["player_id"], "name": death["name"],
            "cause": death["cause"], "day": self.state.day,
        }))
    for dr in result.divine_results:
        self._emit(GameEvent(event_type="divine_result", data={
            "target_id": dr["target_id"], "target_name": dr["target_name"], "result": dr["result"],
        }, recipients=[dr["actor_id"]]))
    for mr in result.medium_results:
        self._emit(GameEvent(event_type="medium_result", data={
            "target_id": mr["target_id"], "target_name": mr["target_name"], "result": mr["result"],
        }, recipients=[mr["actor_id"]]))

    victory = self.victory_checker.check()
    if victory.is_game_over:
        self._emit(GameEvent(event_type="victory", data={
            "winner": victory.winner, "reason": victory.reason,
            "player_results": victory.player_results,
        }))
        return {"status": "game_over", "deaths": result.deaths,
                "victory": {"winner": victory.winner, "reason": victory.reason}}

    if result.deaths:
        death_names = [d["name"] for d in result.deaths]
        msg = f"昨夜、{'と'.join(death_names)}が無残な姿で発見されました。"
    else:
        msg = "昨夜は誰も襲われませんでした。"
    self.state.add_system_message(msg)
    self._emit(GameEvent(event_type="night_result", data={
        "deaths": result.deaths, "message": msg, "guard_success": result.guard_success,
    }))
    self._emit(GameEvent(event_type="phase_changed", data={"phase": "dawn", "day": self.state.day}))
    return {"status": "resolved", "day": self.state.day, "deaths": result.deaths, "message": msg}

def start_discussion(self) -> dict:
    if self.state.phase not in (Phase.DAWN, Phase.VOTE_RESULT):
        return {"error": "議論を開始できるフェーズではありません"}
    self.state.set_phase(Phase.DISCUSSION)
    self._emit(GameEvent(event_type="phase_changed", data={"phase": "discussion", "day": self.state.day}))
    return {"status": "discussion_started", "day": self.state.day}

def chat(self, sender_id: str, content: str, channel: str = "public") -> dict:
    player = self.state.get_player(sender_id)
    if not player:
        return {"error": "プレイヤーが存在しません"}
    if channel == "public":
        if self.state.phase != Phase.DISCUSSION:
            return {"error": "議論フェーズではありません"}
        if not player.is_alive:
            return {"error": "死亡者は発言できません"}
    elif channel == "wolf":
        if player.role != RoleName.WEREWOLF:
            return {"error": "人狼チャットには人狼のみ参加可能です"}
    elif channel == "freemason":
        if player.role != RoleName.FREEMASON:
            return {"error": "共有者チャットには共有者のみ参加可能です"}
    else:
        return {"error": f"不明なチャネル: {channel}"}

    msg = self.state.add_chat(sender_id, content, channel)
    recipients = None
    if channel == "wolf":
        recipients = self.state.get_wolf_ids()
    elif channel == "freemason":
        recipients = list(self.state.freemason_ids)

    self._emit(GameEvent(event_type="chat_message", data={
        "sender_id": sender_id, "sender_name": player.name,
        "content": content, "channel": channel, "day": self.state.day,
    }, recipients=recipients))
    return {"status": "sent"}

def end_discussion(self) -> dict:
    if self.state.phase != Phase.DISCUSSION:
        return {"error": "議論フェーズではありません"}
    self.state.set_phase(Phase.VOTING)
    self._emit(GameEvent(event_type="phase_changed", data={"phase": "voting", "day": self.state.day}))
    return {"status": "voting_started", "day": self.state.day}

def vote(self, voter_id: str, target_id: str) -> dict:
    if self.state.phase not in (Phase.VOTING, Phase.RUNOFF):
        return {"error": "投票フェーズではありません"}
    ok, msg = self.vote_manager.collect_vote(voter_id, target_id)
    if not ok:
        return {"error": msg}
    return {"status": "voted"}

def resolve_votes(self) -> dict:
    if self.state.phase not in (Phase.VOTING, Phase.RUNOFF):
        return {"error": "投票フェーズではありません"}
    result = self.vote_manager.resolve_votes()

    self._emit(GameEvent(event_type="vote_result", data={
        "tally": {self.state.players[pid].name: count for pid, count in result.tally.items()},
        "detail": result.detail, "executed_name": result.executed_name,
        "is_tie": result.is_tie, "is_draw": result.is_draw, "round": result.round_number,
    }))

    if result.is_draw:
        victory = self.victory_checker.check(is_draw=True)
        self._emit(GameEvent(event_type="victory", data={
            "winner": victory.winner, "reason": victory.reason,
        }))
        return {"status": "draw", "result": result.__dict__}

    if result.is_tie:
        self.state.next_vote_round()
        self.state.set_phase(Phase.RUNOFF)
        self._emit(GameEvent(event_type="phase_changed", data={
            "phase": "runoff", "day": self.state.day, "round": self.state.vote_round,
        }))
        return {"status": "runoff", "round": self.state.vote_round,
                "tie_players": [self.state.players[pid].name for pid in result.tie_players]}

    self.state.set_phase(Phase.VOTE_RESULT)
    victory = self.victory_checker.check()
    if victory.is_game_over:
        self._emit(GameEvent(event_type="victory", data={
            "winner": victory.winner, "reason": victory.reason,
        }))
        return {"status": "game_over", "executed": result.executed_name,
                "victory": {"winner": victory.winner, "reason": victory.reason}}

    return {"status": "executed", "executed_id": result.executed_id,
            "executed_name": result.executed_name,
            "tally": {self.state.players[pid].name: count for pid, count in result.tally.items()}}

def start_night(self) -> dict:
    if self.state.phase != Phase.VOTE_RESULT:
        return {"error": "投票結果フェーズではありません"}
    self.state.set_phase(Phase.NIGHT)
    self.state.current_night_actions.clear()
    self._emit(GameEvent(event_type="phase_changed", data={"phase": "night", "day": self.state.day}))
    return {"status": "night_started", "day": self.state.day}

def co(self, player_id: str, claimed_role: str) -> dict:
    player = self.state.get_player(player_id)
    if not player:
        return {"error": "プレイヤーが存在しません"}
    if not player.is_alive:
        return {"error": "死亡者はCOできません"}
    try:
        role = RoleName(claimed_role)
    except ValueError:
        return {"error": f"不明な役職: {claimed_role}"}
    self.state.add_co(player_id, role)
    role_display = get_role_def(role).display_name
    msg = f"{player.name}が{role_display}をCOしました。"
    self.state.add_system_message(msg)
    self._emit(GameEvent(event_type="co_declared", data={
        "player_id": player_id, "player_name": player.name,
        "claimed_role": claimed_role, "role_display": role_display, "day": self.state.day,
    }))
    return {"status": "co_accepted", "message": msg}

def get_game_state(self) -> dict:
    return self.state.to_debug_dict()

def get_player_view(self, player_id: str) -> dict:
    return self.state.get_player_view(player_id)

def get_human_player_id(self) -> Optional[str]:
    for pid, p in self.state.players.items():
        if p.is_human:
            return pid
    return None

def get_alive_player_names(self) -> list[str]:
    return [p.name for p in self.state.get_alive_players()]
```
