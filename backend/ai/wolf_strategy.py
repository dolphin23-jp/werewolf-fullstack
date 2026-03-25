# wolf_strategy.py — 偽CO戦略(α/β/γ/δ)、FakeResultGuard

from **future** import annotations
import random
from dataclasses import dataclass, field
from typing import Optional

from backend.engine.roles import RoleName

WOLF_PATTERNS = [
(“alpha”, “偽占い1＋潜伏2”, 0.40),
(“beta”,  “偽霊能1＋潜伏2”, 0.20),
(“gamma”, “全潜伏”,         0.25),
(“delta”, “偽占い1＋偽霊能1＋潜伏1”, 0.15),
]

MADMAN_STRATEGIES = [
(“fake_seer”,   “占い騙り”, 0.45),
(“fake_medium”, “霊能騙り”, 0.25),
(“lurk”,        “潜伏”,     0.30),
]

@dataclass
class WolfStrategy:
pattern: str
description: str
fake_seer_id: Optional[str] = None
fake_medium_id: Optional[str] = None
lurking_ids: list[str] = field(default_factory=list)

@dataclass
class MadmanStrategy:
strategy: str
description: str

class StrategyAssigner:
def **init**(self, seed: Optional[int] = None):
self.rng = random.Random(seed)

```
def assign_wolf_strategy(self, wolf_ids: list[str]) -> WolfStrategy:
    assert len(wolf_ids) == 3
    names = [p[0] for p in WOLF_PATTERNS]
    weights = [p[2] for p in WOLF_PATTERNS]
    pattern = self.rng.choices(names, weights=weights, k=1)[0]
    shuffled = list(wolf_ids)
    self.rng.shuffle(shuffled)
    s = WolfStrategy(pattern=pattern, description="")
    if pattern == "alpha":
        s.description = "偽占い1＋潜伏2"
        s.fake_seer_id = shuffled[0]; s.lurking_ids = shuffled[1:]
    elif pattern == "beta":
        s.description = "偽霊能1＋潜伏2"
        s.fake_medium_id = shuffled[0]; s.lurking_ids = shuffled[1:]
    elif pattern == "gamma":
        s.description = "全潜伏"
        s.lurking_ids = shuffled[:]
    elif pattern == "delta":
        s.description = "偽占い1＋偽霊能1＋潜伏1"
        s.fake_seer_id = shuffled[0]; s.fake_medium_id = shuffled[1]; s.lurking_ids = [shuffled[2]]
    return s

def assign_madman_strategy(self) -> MadmanStrategy:
    names = [s[0] for s in MADMAN_STRATEGIES]
    weights = [s[2] for s in MADMAN_STRATEGIES]
    strategy = self.rng.choices(names, weights=weights, k=1)[0]
    return MadmanStrategy(strategy=strategy, description={s[0]: s[1] for s in MADMAN_STRATEGIES}[strategy])
```

class FakeResultGuard:
def **init**(self, actor_id: str, actor_role: RoleName, wolf_ids: list[str]):
self.actor_id = actor_id
self.actor_role = actor_role
self.wolf_ids = wolf_ids
self.past_targets: set[str] = set()

```
def validate_fake_divine(self, target_id: str, result: str, alive_ids: list[str]) -> tuple[bool, str]:
    if target_id not in alive_ids:
        return False, "対象は生存者でなければなりません"
    if target_id == self.actor_id:
        return False, "自分自身は対象にできません"
    if target_id in self.past_targets:
        return False, "既に報告済みの対象です"
    if result not in ("人狼", "人狼ではない"):
        return False, "結果は「人狼」か「人狼ではない」のみ"
    if self.actor_role == RoleName.WEREWOLF and target_id in self.wolf_ids and result == "人狼":
        return False, "仲間の人狼に黒を出すことはできません"
    return True, ""

def validate_fake_medium(self, target_id: str, result: str) -> tuple[bool, str]:
    if result not in ("人狼", "人狼ではない"):
        return False, "結果は「人狼」か「人狼ではない」のみ"
    return True, ""

def record_result(self, target_id: str) -> None:
    self.past_targets.add(target_id)

def get_valid_targets(self, alive_ids: list[str]) -> list[str]:
    return [pid for pid in alive_ids if pid != self.actor_id and pid not in self.past_targets]

def suggest_fake_result(self, target_id: str, alive_ids: list[str], seed: Optional[int] = None) -> str:
    rng = random.Random(seed)
    if self.actor_role == RoleName.WEREWOLF and target_id in self.wolf_ids:
        return "人狼ではない"
    return rng.choices(["人狼ではない", "人狼"], weights=[0.7, 0.3], k=1)[0]
```
