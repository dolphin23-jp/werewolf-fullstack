“”“test_engine.py — エンジンテスト”””
import pytest, sys, os
sys.path.insert(0, os.path.join(os.path.dirname(**file**), ‘..’, ‘..’))

from backend.engine.roles import (RoleName, Team, ROLE_DEFINITIONS, RoleAssigner,
AlphaWolfTracker, build_role_list, divine_result, medium_result, get_team, is_wolf)
from backend.engine.state import GameState, Phase, DeathCause, NightAction
from backend.engine.night_resolver import NightResolver, validate_night_action
from backend.engine.vote import VoteManager
from backend.engine.victory import VictoryChecker, VictoryType
from backend.engine.game import GameController

class TestRoles:
def test_total_17(self): assert len(build_role_list()) == 17
def test_villager_7(self): assert ROLE_DEFINITIONS[RoleName.VILLAGER].count == 7
def test_wolf_3(self): assert ROLE_DEFINITIONS[RoleName.WEREWOLF].count == 3
def test_wolf_not_victim(self): assert not ROLE_DEFINITIONS[RoleName.WEREWOLF].can_be_first_victim
def test_fox_not_victim(self): assert not ROLE_DEFINITIONS[RoleName.FOX].can_be_first_victim
def test_teams(self):
assert get_team(RoleName.VILLAGER) == Team.VILLAGE
assert get_team(RoleName.WEREWOLF) == Team.WEREWOLF
assert get_team(RoleName.FOX) == Team.FOX
def test_divine(self):
assert divine_result(RoleName.WEREWOLF) == “人狼”
assert divine_result(RoleName.FOX) == “人狼ではない”
def test_medium(self):
assert medium_result(RoleName.WEREWOLF) == “人狼”
assert medium_result(RoleName.MADMAN) == “人狼ではない”

class TestAssigner:
def test_assign_17(self):
ids = [f”p{i}” for i in range(17)]
r = RoleAssigner(seed=42).assign(ids, “p16”)
assert len(r) == 17
from collections import Counter
c = Counter(r.values())
assert c[RoleName.VILLAGER] == 7
def test_victim_safe(self):
for s in range(100):
r = RoleAssigner(seed=s).assign([f”p{i}” for i in range(17)], “p16”)
assert r[“p16”] not in (RoleName.WEREWOLF, RoleName.FOX)

class TestAlpha:
def test_select(self):
t = AlphaWolfTracker([“w1”,“w2”,“w3”], seed=42)
assert t.get_alpha() in [“w1”,“w2”,“w3”]
def test_succession(self):
t = AlphaWolfTracker([“w1”,“w2”,“w3”], seed=42)
a = t.get_alpha()
n = t.on_wolf_death(a, [“w1”,“w2”,“w3”])
assert n is not None and n != a
def test_non_alpha_death(self):
t = AlphaWolfTracker([“w1”,“w2”,“w3”], seed=42)
a = t.get_alpha()
na = [w for w in [“w1”,“w2”,“w3”] if w != a][0]
assert t.on_wolf_death(na, [“w1”,“w2”,“w3”]) is None

class TestState:
def test_basic(self):
s = GameState(“t”)
s.add_player(“p1”, “太郎”, RoleName.VILLAGER, is_human=True)
assert len(s.players) == 1
def test_kill(self):
s = GameState(“t”)
s.add_player(“p1”, “太郎”, RoleName.VILLAGER)
s.kill_player(“p1”, DeathCause.ATTACKED)
assert not s.players[“p1”].is_alive
def test_view_hides_roles(self):
s = GameState(“t”)
s.add_player(“p1”, “太郎”, RoleName.VILLAGER)
s.add_player(“p2”, “花子”, RoleName.WEREWOLF)
v = s.get_player_view(“p1”)
for p in v[“players”]:
if p[“player_id”] != “p1”:
assert “role” not in p

class TestNight:
def _state(self):
s = GameState(“t”)
s.add_player(“seer”, “占”, RoleName.SEER)
s.add_player(“hunter”, “狩”, RoleName.HUNTER)
s.add_player(“w1”, “狼1”, RoleName.WEREWOLF)
s.add_player(“w2”, “狼2”, RoleName.WEREWOLF)
s.add_player(“w3”, “狼3”, RoleName.WEREWOLF)
s.add_player(“fox”, “狐”, RoleName.FOX)
s.add_player(“v1”, “村1”, RoleName.VILLAGER)
s.add_player(“v2”, “村2”, RoleName.VILLAGER)
s.add_player(“med”, “霊”, RoleName.MEDIUM)
s.add_player(“npc”, “旅人”, RoleName.VILLAGER, is_first_victim=True)
s.alpha_tracker = AlphaWolfTracker([“w1”,“w2”,“w3”], seed=42)
s.day = 2; s.set_phase(Phase.NIGHT)
return s

```
def test_attack(self):
    s = self._state()
    s.add_night_action(NightAction("seer","divine","v1"))
    a = s.alpha_tracker.get_alpha()
    s.add_night_action(NightAction(a,"attack","v2"))
    r = NightResolver(s).resolve()
    assert any(d["player_id"]=="v2" for d in r.deaths)

def test_gj(self):
    s = self._state()
    s.add_night_action(NightAction("seer","divine","v1"))
    a = s.alpha_tracker.get_alpha()
    s.add_night_action(NightAction("hunter","guard","v2"))
    s.add_night_action(NightAction(a,"attack","v2"))
    r = NightResolver(s).resolve()
    assert r.guard_success and len(r.deaths)==0

def test_fox_immune(self):
    s = self._state()
    s.add_night_action(NightAction("seer","divine","v1"))
    a = s.alpha_tracker.get_alpha()
    s.add_night_action(NightAction(a,"attack","fox"))
    r = NightResolver(s).resolve()
    assert len(r.deaths)==0

def test_curse(self):
    s = self._state()
    s.add_night_action(NightAction("seer","divine","fox"))
    a = s.alpha_tracker.get_alpha()
    s.add_night_action(NightAction(a,"attack","v2"))
    r = NightResolver(s).resolve()
    ids = [d["player_id"] for d in r.deaths]
    assert "fox" in ids and "v2" in ids

def test_curse_and_attack_fox(self):
    s = self._state()
    s.add_night_action(NightAction("seer","divine","fox"))
    a = s.alpha_tracker.get_alpha()
    s.add_night_action(NightAction(a,"attack","fox"))
    r = NightResolver(s).resolve()
    assert [d["player_id"] for d in r.deaths] == ["fox"]

def test_guard_no_block_curse(self):
    s = self._state()
    s.add_night_action(NightAction("seer","divine","fox"))
    s.add_night_action(NightAction("hunter","guard","fox"))
    a = s.alpha_tracker.get_alpha()
    s.add_night_action(NightAction(a,"attack","v1"))
    r = NightResolver(s).resolve()
    assert any(d["player_id"]=="fox" for d in r.deaths)

def test_day0(self):
    s = self._state(); s.day = 1
    s.add_night_action(NightAction("seer","divine","v1"))
    r = NightResolver(s).resolve_day0()
    assert any(d["player_id"]=="npc" for d in r.deaths)
```

class TestVote:
def _state(self):
s = GameState(“t”)
for i in range(5): s.add_player(f”p{i}”, f”P{i}”, RoleName.VILLAGER)
s.day=2; s.set_phase(Phase.VOTING)
return s

```
def test_majority(self):
    s = self._state(); vm = VoteManager(s)
    for v in ["p0","p2","p3","p4"]: vm.collect_vote(v, "p1")
    vm.collect_vote("p1","p0")
    assert vm.resolve_votes().executed_id == "p1"

def test_tie(self):
    s = self._state(); vm = VoteManager(s)
    vm.collect_vote("p0","p1"); vm.collect_vote("p1","p0")
    vm.collect_vote("p2","p1"); vm.collect_vote("p3","p0")
    vm.collect_vote("p4","p2")
    assert vm.resolve_votes().is_tie

def test_self_vote(self):
    s = self._state(); vm = VoteManager(s)
    ok, _ = vm.collect_vote("p0","p0")
    assert not ok

def test_draw(self):
    s = self._state(); s.vote_round=4; vm = VoteManager(s)
    vm.collect_vote("p0","p1"); vm.collect_vote("p1","p0")
    vm.collect_vote("p2","p1"); vm.collect_vote("p3","p0")
    vm.collect_vote("p4","p2")
    assert vm.resolve_votes().is_draw
```

class TestVictory:
def _s(self, alive, dead=None):
s = GameState(“t”); i=0
for r in alive: s.add_player(f”p{i}”,f”P{i}”,r); i+=1
for r in (dead or []):
p = s.add_player(f”p{i}”,f”P{i}”,r); p.is_alive=False; i+=1
return s

```
def test_village_win(self):
    r = VictoryChecker(self._s([RoleName.VILLAGER]*3, [RoleName.WEREWOLF]*3)).check()
    assert r.winner == VictoryType.VILLAGE
def test_wolf_win(self):
    r = VictoryChecker(self._s([RoleName.WEREWOLF,RoleName.WEREWOLF,RoleName.VILLAGER])).check()
    assert r.winner == VictoryType.WEREWOLF
def test_fox_win(self):
    r = VictoryChecker(self._s([RoleName.FOX,RoleName.VILLAGER],[RoleName.WEREWOLF])).check()
    assert r.winner == VictoryType.FOX
def test_continue(self):
    r = VictoryChecker(self._s([RoleName.VILLAGER]*3+[RoleName.WEREWOLF])).check()
    assert not r.is_game_over
def test_draw(self):
    r = VictoryChecker(self._s([RoleName.VILLAGER,RoleName.WEREWOLF])).check(is_draw=True)
    assert r.winner == VictoryType.DRAW
def test_madman_count(self):
    r = VictoryChecker(self._s([RoleName.WEREWOLF,RoleName.MADMAN,RoleName.VILLAGER])).check()
    assert not r.is_game_over  # wolf1 vs non-wolf2
```

class TestGameController:
def test_create(self):
r = GameController(seed=42).create_game(“テスト”)
# create_game returns but doesn’t start - need to verify
gc = GameController(seed=42)
r = gc.create_game(“テスト”)
assert r[“player_count”] == 17
def test_start(self):
gc = GameController(seed=42); gc.create_game(“テスト”)
r = gc.start_game()
assert r[“phase”] == “night”
def test_full_day(self):
gc = GameController(seed=42); gc.create_game(“テスト”); gc.start_game()
seer = next((p for p in gc.state.players.values()
if p.role==RoleName.SEER and not p.is_first_victim), None)
if seer:
targets = [pid for pid in gc.state.get_alive_player_ids()
if pid != seer.player_id and pid != gc.state.first_victim_id]
if targets: gc.submit_night_action(seer.player_id, “divine”, targets[0])
r = gc.resolve_night()
assert r[“status”] in (“resolved”,“game_over”)
if r[“status”]==“game_over”: return
gc.start_discussion()
alive = gc.state.get_alive_player_ids()
gc.chat(alive[0], “おはよう”)
gc.end_discussion()
for v in alive:
t = [p for p in alive if p!=v][0]
gc.vote(v, t)
vr = gc.resolve_votes()
assert vr[“status”] in (“executed”,“runoff”,“game_over”,“draw”)
