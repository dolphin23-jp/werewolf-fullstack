# test_ai.py — AI全モジュールテスト
import pytest, sys, os, json
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ‘..’, ‘..’))

from backend.engine.roles import RoleName, AlphaWolfTracker
from backend.engine.state import GameState, Phase
from backend.engine.game import GameController

from backend.ai.personalities import (Personality, PERSONALITY_PRESETS, assign_personalities,
TONE_DESCRIPTIONS, THINKING_DESCRIPTIONS)
from backend.ai.wolf_strategy import StrategyAssigner, FakeResultGuard
from backend.ai.context import (ContextBuilder, DaySummaryManager, build_system_prompt,
build_game_state_context, build_role_context, estimate_tokens)
from backend.ai.ai_player import (AIPlayer, ClaudeClient, ReasoningMemo,
filter_meta_expressions, truncate_message, parse_json_response)
from backend.ai.coordinator import AICoordinator

class TestPersonalities:
def test_15(self): assert len(PERSONALITY_PRESETS) == 15
def test_unique_ids(self):
assert len({p.preset_id for p in PERSONALITY_PRESETS}) == 15
def test_valid_tones(self):
for p in PERSONALITY_PRESETS: assert p.tone in TONE_DESCRIPTIONS
def test_assign(self):
a = assign_personalities([f"a{i}" for i in range(15)], seed=42)
assert len(a) == 15
def test_prompt(self):
assert "口調" in PERSONALITY_PRESETS[0].to_prompt_section()
def test_fallback(self):
for p in PERSONALITY_PRESETS: assert len(p.get_fallback_message()) > 0

class TestWolfStrategy:
def test_assign(self):
s = StrategyAssigner(seed=42).assign_wolf_strategy(["w1","w2","w3"])
assert s.pattern in ("alpha","beta","gamma","delta")
def test_all_patterns(self):
ps = {StrategyAssigner(seed=s).assign_wolf_strategy(["w1","w2","w3"]).pattern for s in range(200)}
assert ps == {"alpha","beta","gamma","delta"}
def test_madman(self):
s = StrategyAssigner(seed=42).assign_madman_strategy()
assert s.strategy in ("fake_seer","fake_medium","lurk")
def test_guard_wolf_black(self):
g = FakeResultGuard("w1", RoleName.WEREWOLF, ["w1","w2","w3"])
ok, _ = g.validate_fake_divine("w2", "人狼", ["w1","w2","w3","v1"])
assert not ok
def test_guard_wolf_white(self):
g = FakeResultGuard("w1", RoleName.WEREWOLF, ["w1","w2","w3"])
ok, _ = g.validate_fake_divine("w2", "人狼ではない", ["w1","w2","w3","v1"])
assert ok
def test_guard_self(self):
g = FakeResultGuard("w1", RoleName.WEREWOLF, ["w1","w2"])
ok, _ = g.validate_fake_divine("w1", "人狼ではない", ["w1","w2","v1"])
assert not ok
def test_guard_repeat(self):
g = FakeResultGuard("w1", RoleName.WEREWOLF, ["w1","w2"])
g.record_result("v1")
ok, _ = g.validate_fake_divine("v1", "人狼ではない", ["w1","w2","v1"])
assert not ok
def test_valid_targets(self):
g = FakeResultGuard("w1", RoleName.WEREWOLF, ["w1","w2"])
g.record_result("v1")
t = g.get_valid_targets(["w1","w2","v1","v2"])
assert "w1" not in t and "v1" not in t and "v2" in t

class TestContext:
def test_system_prompt(self):
p = build_system_prompt(PERSONALITY_PRESETS[0], "テスト")
assert "テスト" in p and "人狼ゲーム" in p
def test_game_state(self):
gc = GameController(seed=42); gc.create_game("太郎"); gc.start_game()
ctx = build_game_state_context(gc.state, "player_human")
assert "生存者" in ctx
def test_role_ctx_seer(self):
s = GameState("t"); s.add_player("s1","占太郎",RoleName.SEER)
assert "占い師" in build_role_context(s, "s1")
def test_summary_mgr(self):
m = DaySummaryManager(); m.add_summary(2, "要約")
assert "2日目" in m.build_context(3)
def test_tokens(self):
assert estimate_tokens("日本語テスト") > 0
def test_builder(self):
gc = GameController(seed=42); gc.create_game("太郎"); gc.start_game()
b = ContextBuilder(gc.state, DaySummaryManager())
s, m = b.build_discussion_context("player_human", PERSONALITY_PRESETS[0])
assert len(s) > 0 and len(m) > 0

class TestAIPlayer:
def test_meta_filter(self):
assert filter_meta_expressions("AIとして考えると") == ""
assert filter_meta_expressions("おはよう。") == "おはよう。"
def test_truncate(self):
assert len(truncate_message("あ"*500)) <= 301
def test_parse_json(self):
assert parse_json_response(’{"a": 1}’)["a"] == 1
assert parse_json_response(’`json\n{"b": 2}\n`’)["b"] == 2
assert parse_json_response("not json") is None
def test_memo(self):
m = ReasoningMemo(); m.trusted_seer = "太郎"
m2 = ReasoningMemo.from_dict(m.to_dict())
assert m2.trusted_seer == "太郎"
def test_mock_client(self):
assert ClaudeClient(mock_mode=True).mock_mode

```
@pytest.mark.asyncio
async def test_mock_gen(self):
    c = ClaudeClient(mock_mode=True)
    r = await c.generate("sys", [{"role":"user","content":"hello"}])
    assert len(r) > 0

@pytest.mark.asyncio
async def test_mock_vote(self):
    c = ClaudeClient(mock_mode=True)
    r = await c.generate("sys", [{"role":"user","content":"投票候補: 太郎, 花子\nvote_target"}])
    p = parse_json_response(r)
    assert p and "vote_target" in p

@pytest.mark.asyncio
async def test_player_vote(self):
    c = ClaudeClient(mock_mode=True)
    ai = AIPlayer("p1","テスト",PERSONALITY_PRESETS[0],c)
    t, _ = await ai.generate_vote("sys",
        [{"role":"user","content":"投票候補: 太郎, 花子\nvote_target"}], ["太郎","花子"])
    assert t in ["太郎","花子"]
```

class TestCoordinator:
def _make(self):
gc = GameController(seed=42); gc.create_game("テスト"); gc.start_game()
co = AICoordinator(gc, ClaudeClient(mock_mode=True), seed=42)
co.initialize()
return gc, co

```
def test_init(self):
    gc, co = self._make()
    assert len(co.ai_players) == 15

def test_wolf_strategy(self):
    _, co = self._make()
    assert co.wolf_strategy is not None

@pytest.mark.asyncio
async def test_discussion(self):
    gc, co = self._make()
    gc.resolve_night(); gc.start_discussion()
    r = await co.run_discussion_round()
    assert len(r) > 0 and all("content" in x for x in r)

@pytest.mark.asyncio
async def test_votes(self):
    gc, co = self._make()
    gc.resolve_night(); gc.start_discussion(); gc.end_discussion()
    r = await co.generate_all_votes()
    assert len(r) > 0

@pytest.mark.asyncio
async def test_night(self):
    gc, co = self._make()
    gc.resolve_night(); gc.start_discussion(); gc.end_discussion()
    h = gc.get_human_player_id()
    alive = gc.state.get_alive_player_ids()
    gc.vote(h, [p for p in alive if p!=h][0])
    await co.generate_all_votes()
    vr = gc.resolve_votes()
    if gc.state.phase == Phase.VOTE_RESULT:
        gc.start_night()
        r = await co.execute_night_phase()
        assert isinstance(r, dict)

@pytest.mark.asyncio
async def test_co(self):
    gc, co = self._make()
    gc.resolve_night(); gc.start_discussion()
    r = await co.handle_ai_co()
    assert isinstance(r, list)
```

if __name__ == "__main__":
pytest.main([__file__, "-v"])
