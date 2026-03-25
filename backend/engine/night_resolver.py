“””
night_resolver.py — 夜行動同時解決、呪殺、GJ、Day0処理
“””

from **future** import annotations
from dataclasses import dataclass, field
from typing import Optional

from .roles import RoleName, divine_result, medium_result
from .state import GameState, Phase, DeathCause, NightAction, DivineRecord, MediumRecord

@dataclass
class NightResolutionResult:
deaths: list[dict] = field(default_factory=list)
divine_results: list[dict] = field(default_factory=list)
medium_results: list[dict] = field(default_factory=list)
guard_success: bool = False
messages: list[str] = field(default_factory=list)

class NightResolver:
def **init**(self, state: GameState):
self.state = state

```
def resolve_day0(self) -> NightResolutionResult:
    result = NightResolutionResult()
    fv_id = self.state.first_victim_id
    if fv_id:
        fv = self.state.players[fv_id]
        self.state.kill_player(fv_id, DeathCause.FIRST_VICTIM)
        result.deaths.append({"player_id": fv_id, "name": fv.name, "cause": DeathCause.FIRST_VICTIM.value})
    divine_action = self._find_action("divine")
    if divine_action:
        self._resolve_divine(divine_action, result, is_day0=True)
    return result

def resolve(self) -> NightResolutionResult:
    result = NightResolutionResult()
    curse_kill_id: Optional[str] = None
    divine_action = self._find_action("divine")
    if divine_action:
        curse_kill_id = self._resolve_divine(divine_action, result)

    guard_target_id: Optional[str] = None
    guard_action = self._find_action("guard")
    if guard_action:
        guard_target_id = guard_action.target_id
        hunter = self.state.players[guard_action.actor_id]
        hunter.last_guard_target = guard_target_id

    attack_target_id: Optional[str] = None
    attack_action = self._find_action("attack")
    if attack_action:
        attack_target_id = attack_action.target_id

    if curse_kill_id:
        target = self.state.players[curse_kill_id]
        if target.is_alive:
            self.state.kill_player(curse_kill_id, DeathCause.CURSED)
            result.deaths.append({"player_id": curse_kill_id, "name": target.name, "cause": DeathCause.CURSED.value})

    if attack_target_id:
        target = self.state.players[attack_target_id]
        attack_blocked = False
        if target.role == RoleName.FOX:
            attack_blocked = True
        elif guard_target_id == attack_target_id:
            attack_blocked = True
            result.guard_success = True
        if not attack_blocked and target.is_alive:
            self.state.kill_player(attack_target_id, DeathCause.ATTACKED)
            result.deaths.append({"player_id": attack_target_id, "name": target.name, "cause": DeathCause.ATTACKED.value})

    if self.state.today_executed_id:
        self._resolve_medium(result)

    if not result.deaths:
        result.messages.append("昨夜は誰も襲われませんでした")
    return result

def _find_action(self, action_type: str) -> Optional[NightAction]:
    for action in self.state.current_night_actions:
        if action.action_type == action_type:
            return action
    return None

def _resolve_divine(self, action: NightAction, result: NightResolutionResult, is_day0: bool = False) -> Optional[str]:
    target = self.state.players[action.target_id]
    div_result = divine_result(target.role)
    record = DivineRecord(day=self.state.day, target_id=action.target_id, result=div_result)
    seer = self.state.players[action.actor_id]
    seer.divine_results.append(record)
    result.divine_results.append({
        "actor_id": action.actor_id, "target_id": action.target_id,
        "target_name": target.name, "result": div_result,
    })
    if target.role == RoleName.FOX and target.is_alive and not is_day0:
        return action.target_id
    return None

def _resolve_medium(self, result: NightResolutionResult) -> None:
    executed_id = self.state.today_executed_id
    if not executed_id:
        return
    for med in self.state.get_players_by_role(RoleName.MEDIUM):
        if not med.is_alive:
            continue
        target = self.state.players[executed_id]
        med_result = medium_result(target.role)
        record = MediumRecord(day=self.state.day, target_id=executed_id, result=med_result)
        med.medium_results.append(record)
        result.medium_results.append({
            "actor_id": med.player_id, "target_id": executed_id,
            "target_name": target.name, "result": med_result,
        })
```

def validate_night_action(state: GameState, actor_id: str, action_type: str, target_id: str) -> tuple[bool, str]:
actor = state.get_player(actor_id)
target = state.get_player(target_id)
if not actor:
return False, “プレイヤーが存在しません”
if not target:
return False, “対象プレイヤーが存在しません”
if not actor.is_alive:
return False, “死亡プレイヤーは行動できません”

```
if action_type == "divine":
    if actor.role != RoleName.SEER:
        return False, "占い師ではありません"
    if not target.is_alive and not target.is_first_victim:
        return False, "死亡者は占えません"
    if target_id == actor_id:
        return False, "自分自身は占えません"
    for dr in actor.divine_results:
        if dr.target_id == target_id:
            return False, "既に占い済みです"
elif action_type == "guard":
    if actor.role != RoleName.HUNTER:
        return False, "狩人ではありません"
    if state.day <= 1:
        return False, "1日目は護衛できません"
    if target_id == actor_id:
        return False, "自分自身は護衛できません"
    if not target.is_alive:
        return False, "死亡者は護衛できません"
elif action_type == "attack":
    if actor.role != RoleName.WEREWOLF:
        return False, "人狼ではありません"
    if state.alpha_tracker and not state.alpha_tracker.is_alpha_wolf(actor_id):
        return False, "アルファ狼のみが襲撃先を決定できます"
    if not target.is_alive:
        return False, "死亡者は襲撃できません"
    if target.role == RoleName.WEREWOLF:
        return False, "仲間の人狼は襲撃できません"
else:
    return False, f"不明な行動タイプ: {action_type}"
return True, ""
```
