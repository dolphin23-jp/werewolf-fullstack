“””
roles.py — 役職定義、陣営、属性、配役、アルファ狼、RoleAssigner
17人構成: 村人x7, 人狼x3, 狂人x1, 占い師x1, 霊媒師x1, 狩人x1, 妖狐x1, 共有者x2
“””

from **future** import annotations
import random
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional

class Team(str, Enum):
VILLAGE = “village”
WEREWOLF = “werewolf”
FOX = “fox”

class RoleName(str, Enum):
VILLAGER = “villager”
WEREWOLF = “werewolf”
MADMAN = “madman”
SEER = “seer”
MEDIUM = “medium”
HUNTER = “hunter”
FOX = “fox”
FREEMASON = “freemason”

@dataclass(frozen=True)
class RoleDefinition:
name: RoleName
team: Team
display_name: str
count: int
can_be_first_victim: bool
has_night_action: bool
has_night_chat: bool
is_wolf: bool = False
immortal_to_attack: bool = False
counts_as_village: bool = True

ROLE_DEFINITIONS: dict[RoleName, RoleDefinition] = {
RoleName.VILLAGER: RoleDefinition(
name=RoleName.VILLAGER, team=Team.VILLAGE, display_name=“村人”, count=7,
can_be_first_victim=True, has_night_action=False, has_night_chat=False,
),
RoleName.WEREWOLF: RoleDefinition(
name=RoleName.WEREWOLF, team=Team.WEREWOLF, display_name=“人狼”, count=3,
can_be_first_victim=False, has_night_action=True, has_night_chat=True,
is_wolf=True, counts_as_village=False,
),
RoleName.MADMAN: RoleDefinition(
name=RoleName.MADMAN, team=Team.WEREWOLF, display_name=“狂人”, count=1,
can_be_first_victim=True, has_night_action=False, has_night_chat=False,
counts_as_village=True,
),
RoleName.SEER: RoleDefinition(
name=RoleName.SEER, team=Team.VILLAGE, display_name=“占い師”, count=1,
can_be_first_victim=True, has_night_action=True, has_night_chat=False,
),
RoleName.MEDIUM: RoleDefinition(
name=RoleName.MEDIUM, team=Team.VILLAGE, display_name=“霊媒師”, count=1,
can_be_first_victim=True, has_night_action=False, has_night_chat=False,
),
RoleName.HUNTER: RoleDefinition(
name=RoleName.HUNTER, team=Team.VILLAGE, display_name=“狩人”, count=1,
can_be_first_victim=True, has_night_action=True, has_night_chat=False,
),
RoleName.FOX: RoleDefinition(
name=RoleName.FOX, team=Team.FOX, display_name=“妖狐”, count=1,
can_be_first_victim=False, has_night_action=False, has_night_chat=False,
immortal_to_attack=True, counts_as_village=True,
),
RoleName.FREEMASON: RoleDefinition(
name=RoleName.FREEMASON, team=Team.VILLAGE, display_name=“共有者”, count=2,
can_be_first_victim=True, has_night_action=False, has_night_chat=True,
),
}

TOTAL_PLAYERS = sum(rd.count for rd in ROLE_DEFINITIONS.values())
assert TOTAL_PLAYERS == 17, f”配役合計が17人ではありません: {TOTAL_PLAYERS}”

def get_role_def(role: RoleName) -> RoleDefinition:
return ROLE_DEFINITIONS[role]

def is_wolf(role: RoleName) -> bool:
return ROLE_DEFINITIONS[role].is_wolf

def get_team(role: RoleName) -> Team:
return ROLE_DEFINITIONS[role].team

def divine_result(target_role: RoleName) -> str:
return “人狼” if target_role == RoleName.WEREWOLF else “人狼ではない”

def medium_result(target_role: RoleName) -> str:
return “人狼” if target_role == RoleName.WEREWOLF else “人狼ではない”

def build_role_list() -> list[RoleName]:
roles: list[RoleName] = []
for rd in ROLE_DEFINITIONS.values():
roles.extend([rd.name] * rd.count)
assert len(roles) == 17
return roles

class RoleAssigner:
def **init**(self, seed: Optional[int] = None):
self.rng = random.Random(seed)

```
def assign(self, player_ids: list[str], first_victim_id: str) -> dict[str, RoleName]:
    assert len(player_ids) == 17
    assert first_victim_id in player_ids
    roles = build_role_list()
    victim_ok = [r for r in roles if ROLE_DEFINITIONS[r].can_be_first_victim]
    victim_ng = [r for r in roles if not ROLE_DEFINITIONS[r].can_be_first_victim]
    self.rng.shuffle(victim_ok)
    victim_role = victim_ok.pop(0)
    remaining_roles = victim_ok + victim_ng
    self.rng.shuffle(remaining_roles)
    assignment: dict[str, RoleName] = {first_victim_id: victim_role}
    other_players = [pid for pid in player_ids if pid != first_victim_id]
    for pid, role in zip(other_players, remaining_roles):
        assignment[pid] = role
    return assignment
```

class AlphaWolfTracker:
def **init**(self, wolf_ids: list[str], seed: Optional[int] = None):
assert len(wolf_ids) >= 1
self.rng = random.Random(seed)
self.wolf_ids = list(wolf_ids)
self.alpha_id: str = self.rng.choice(wolf_ids)

```
def get_alpha(self) -> str:
    return self.alpha_id

def is_alpha_wolf(self, player_id: str) -> bool:
    return player_id == self.alpha_id

def on_wolf_death(self, dead_wolf_id: str, alive_wolf_ids: list[str]) -> Optional[str]:
    if dead_wolf_id != self.alpha_id:
        return None
    surviving = [wid for wid in alive_wolf_ids if wid != dead_wolf_id]
    if not surviving:
        self.alpha_id = ""
        return None
    self.alpha_id = self.rng.choice(surviving)
    return self.alpha_id
```
