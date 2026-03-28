# test_all.py — エンジン + AI全モジュールテスト
import pytest, sys, os, asyncio
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from backend.engine.roles import (RoleName, Team, ROLE_DEFINITIONS, RoleAssigner,
    AlphaWolfTracker, build_role_list, divine_result, medium_result, get_team, is_wolf)
from backend.engine.state import GameState, Phase, DeathCause, NightAction, ChatMessage
from backend.engine.night_resolver import NightResolver, validate_night_action
from backend.engine.vote import VoteManager
from backend.engine.victory import VictoryChecker, VictoryType
from backend.engine.game import GameController
from backend.ai.personalities import (Personality, PERSONALITY_PRESETS, assign_personalities,
    TONE_DESCRIPTIONS, THINKING_DESCRIPTIONS)
from backend.ai.wolf_strategy import StrategyAssigner, FakeResultGuard
from backend.ai.strategy import StrategyAnalyzer, should_show_rola_guide
from backend.ai.context import (ContextBuilder, DaySummaryManager, build_system_prompt,
    build_game_state_context, build_role_context)
from backend.ai.ai_player import (AIPlayer, ClaudeClient, ReasoningMemo,
    filter_meta_expressions, truncate_message, parse_json_response)
from backend.ai.coordinator import AICoordinator

# ═══ エンジンテスト ═══
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
        assert divine_result(RoleName.WEREWOLF) == "人狼"
        assert divine_result(RoleName.FOX) == "人狼ではない"
    def test_medium(self):
        assert medium_result(RoleName.WEREWOLF) == "人狼"
        assert medium_result(RoleName.MADMAN) == "人狼ではない"

class TestAssigner:
    def test_assign_17(self):
        ids = [f"p{i}" for i in range(17)]
        r = RoleAssigner(seed=42).assign(ids, "p16")
        assert len(r) == 17
        from collections import Counter
        c = Counter(r.values())
        assert c[RoleName.VILLAGER] == 7
    def test_victim_safe(self):
        for s in range(100):
            r = RoleAssigner(seed=s).assign([f"p{i}" for i in range(17)], "p16")
            assert r["p16"] not in (RoleName.WEREWOLF, RoleName.FOX)

class TestAlpha:
    def test_select(self):
        t = AlphaWolfTracker(["w1","w2","w3"], seed=42)
        assert t.get_alpha() in ["w1","w2","w3"]
    def test_succession(self):
        t = AlphaWolfTracker(["w1","w2","w3"], seed=42)
        a = t.get_alpha()
        n = t.on_wolf_death(a, ["w1","w2","w3"])
        assert n is not None and n != a
    def test_non_alpha_death(self):
        t = AlphaWolfTracker(["w1","w2","w3"], seed=42)
        a = t.get_alpha()
        na = [w for w in ["w1","w2","w3"] if w != a][0]
        assert t.on_wolf_death(na, ["w1","w2","w3"]) is None

class TestState:
    def test_basic(self):
        s = GameState("t"); s.add_player("p1","太郎",RoleName.VILLAGER,is_human=True)
        assert len(s.players) == 1
    def test_kill(self):
        s = GameState("t"); s.add_player("p1","太郎",RoleName.VILLAGER)
        s.kill_player("p1", DeathCause.ATTACKED)
        assert not s.players["p1"].is_alive
    def test_view_hides_roles(self):
        s = GameState("t")
        s.add_player("p1","太郎",RoleName.VILLAGER); s.add_player("p2","花子",RoleName.WEREWOLF)
        v = s.get_player_view("p1")
        for p in v["players"]:
            if p["player_id"] != "p1": assert "role" not in p

class TestNight:
    def _state(self):
        s = GameState("t")
        for pid, name, role in [("seer","占",RoleName.SEER),("hunter","狩",RoleName.HUNTER),
            ("w1","狼1",RoleName.WEREWOLF),("w2","狼2",RoleName.WEREWOLF),("w3","狼3",RoleName.WEREWOLF),
            ("fox","狐",RoleName.FOX),("v1","村1",RoleName.VILLAGER),("v2","村2",RoleName.VILLAGER),
            ("med","霊",RoleName.MEDIUM)]:
            s.add_player(pid, name, role)
        s.add_player("npc","旅人",RoleName.VILLAGER,is_first_victim=True)
        s.alpha_tracker = AlphaWolfTracker(["w1","w2","w3"], seed=42)
        s.day = 2; s.set_phase(Phase.NIGHT)
        return s
    def test_attack(self):
        s = self._state(); s.add_night_action(NightAction("seer","divine","v1"))
        a = s.alpha_tracker.get_alpha(); s.add_night_action(NightAction(a,"attack","v2"))
        r = NightResolver(s).resolve(); assert any(d["player_id"]=="v2" for d in r.deaths)
    def test_gj(self):
        s = self._state(); s.add_night_action(NightAction("seer","divine","v1"))
        a = s.alpha_tracker.get_alpha()
        s.add_night_action(NightAction("hunter","guard","v2")); s.add_night_action(NightAction(a,"attack","v2"))
        r = NightResolver(s).resolve(); assert r.guard_success and len(r.deaths)==0
    def test_fox_immune(self):
        s = self._state(); s.add_night_action(NightAction("seer","divine","v1"))
        a = s.alpha_tracker.get_alpha(); s.add_night_action(NightAction(a,"attack","fox"))
        r = NightResolver(s).resolve(); assert len(r.deaths)==0
    def test_curse(self):
        s = self._state(); s.add_night_action(NightAction("seer","divine","fox"))
        a = s.alpha_tracker.get_alpha(); s.add_night_action(NightAction(a,"attack","v2"))
        r = NightResolver(s).resolve(); ids = [d["player_id"] for d in r.deaths]
        assert "fox" in ids and "v2" in ids
    def test_curse_and_attack_fox(self):
        s = self._state(); s.add_night_action(NightAction("seer","divine","fox"))
        a = s.alpha_tracker.get_alpha(); s.add_night_action(NightAction(a,"attack","fox"))
        r = NightResolver(s).resolve(); assert [d["player_id"] for d in r.deaths] == ["fox"]
    def test_guard_no_block_curse(self):
        s = self._state(); s.add_night_action(NightAction("seer","divine","fox"))
        s.add_night_action(NightAction("hunter","guard","fox"))
        a = s.alpha_tracker.get_alpha(); s.add_night_action(NightAction(a,"attack","v1"))
        r = NightResolver(s).resolve(); assert any(d["player_id"]=="fox" for d in r.deaths)
    def test_day0(self):
        s = self._state(); s.day = 1
        s.add_night_action(NightAction("seer","divine","v1"))
        r = NightResolver(s).resolve_day0(); assert any(d["player_id"]=="npc" for d in r.deaths)

class TestVote:
    def _state(self):
        s = GameState("t")
        for i in range(5): s.add_player(f"p{i}",f"P{i}",RoleName.VILLAGER)
        s.day=2; s.set_phase(Phase.VOTING); return s
    def test_majority(self):
        s = self._state(); vm = VoteManager(s)
        for v in ["p0","p2","p3","p4"]: vm.collect_vote(v,"p1")
        vm.collect_vote("p1","p0"); assert vm.resolve_votes().executed_id == "p1"
    def test_tie(self):
        s = self._state(); vm = VoteManager(s)
        vm.collect_vote("p0","p1"); vm.collect_vote("p1","p0")
        vm.collect_vote("p2","p1"); vm.collect_vote("p3","p0"); vm.collect_vote("p4","p2")
        assert vm.resolve_votes().is_tie
    def test_self_vote(self):
        s = self._state(); vm = VoteManager(s); ok, _ = vm.collect_vote("p0","p0"); assert not ok
    def test_draw(self):
        s = self._state(); s.vote_round=4; vm = VoteManager(s)
        vm.collect_vote("p0","p1"); vm.collect_vote("p1","p0")
        vm.collect_vote("p2","p1"); vm.collect_vote("p3","p0"); vm.collect_vote("p4","p2")
        assert vm.resolve_votes().is_draw

class TestVictory:
    def _s(self, alive, dead=None):
        s = GameState("t"); i=0
        for r in alive: s.add_player(f"p{i}",f"P{i}",r); i+=1
        for r in (dead or []): p = s.add_player(f"p{i}",f"P{i}",r); p.is_alive=False; i+=1
        return s
    def test_village_win(self):
        r = VictoryChecker(self._s([RoleName.VILLAGER]*3,[RoleName.WEREWOLF]*3)).check()
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
        assert not r.is_game_over

class TestGameController:
    def test_create(self):
        gc = GameController(seed=42); r = gc.create_game("テスト"); assert r["player_count"] == 17
    def test_start(self):
        gc = GameController(seed=42); gc.create_game("テスト"); r = gc.start_game()
        assert r["phase"] == "night"
    def test_full_day(self):
        gc = GameController(seed=42); gc.create_game("テスト"); gc.start_game()
        seer = next((p for p in gc.state.players.values()
                     if p.role==RoleName.SEER and not p.is_first_victim), None)
        if seer:
            targets = [pid for pid in gc.state.get_alive_player_ids()
                       if pid != seer.player_id and pid != gc.state.first_victim_id]
            if targets: gc.submit_night_action(seer.player_id, "divine", targets[0])
        r = gc.resolve_night(); assert r["status"] in ("resolved","game_over")
        if r["status"]=="game_over": return
        gc.start_discussion(); alive = gc.state.get_alive_player_ids()
        gc.chat(alive[0], "おはよう"); gc.end_discussion()
        for v in alive: t = [p for p in alive if p!=v][0]; gc.vote(v, t)
        vr = gc.resolve_votes(); assert vr["status"] in ("executed","runoff","game_over","draw")

# ═══ StrategyAnalyzer テスト（新規）═══
class TestStrategyAnalyzer:
    def _make_game(self):
        gc = GameController(seed=42); gc.create_game("太郎"); gc.start_game(); return gc
    def test_rope_odd_9(self):
        s = GameState("t")
        for i in range(9): s.add_player(f"p{i}",f"P{i}",RoleName.VILLAGER)
        assert StrategyAnalyzer(s).calc_rope_count() == 4
    def test_rope_even_8(self):
        s = GameState("t")
        for i in range(8): s.add_player(f"p{i}",f"P{i}",RoleName.VILLAGER)
        assert StrategyAnalyzer(s).calc_rope_count() == 3
    def test_rope_16(self):
        s = GameState("t")
        for i in range(16): s.add_player(f"p{i}",f"P{i}",RoleName.VILLAGER)
        assert StrategyAnalyzer(s).calc_rope_count() == 7
    def test_rope_15(self):
        s = GameState("t")
        for i in range(15): s.add_player(f"p{i}",f"P{i}",RoleName.VILLAGER)
        assert StrategyAnalyzer(s).calc_rope_count() == 7
    def test_rope_3(self):
        s = GameState("t")
        for i in range(3): s.add_player(f"p{i}",f"P{i}",RoleName.VILLAGER)
        assert StrategyAnalyzer(s).calc_rope_count() == 1
    def test_parity(self):
        s = GameState("t")
        for i in range(9): s.add_player(f"p{i}",f"P{i}",RoleName.VILLAGER)
        assert StrategyAnalyzer(s).get_parity() == "奇数進行"
    def test_gray_all_initially(self):
        gc = self._make_game(); gc.resolve_night(); gc.start_discussion()
        a = StrategyAnalyzer(gc.state)
        grays = a.get_gray_player_ids("player_human")
        alive = gc.state.get_alive_player_ids()
        assert len(grays) == len(alive) - 1
    def test_gray_excludes_co(self):
        gc = self._make_game(); gc.resolve_night(); gc.start_discussion()
        alive = gc.state.get_alive_player_ids()
        co_pid = [p for p in alive if p != "player_human"][0]
        gc.co(co_pid, "seer")
        assert co_pid not in StrategyAnalyzer(gc.state).get_gray_player_ids("player_human")
    def test_co_composition(self):
        gc = self._make_game(); gc.resolve_night(); gc.start_discussion()
        ai = [p for p in gc.state.get_alive_player_ids() if p != "player_human"]
        gc.co(ai[0],"seer"); gc.co(ai[1],"seer"); gc.co(ai[2],"medium")
        comp = StrategyAnalyzer(gc.state).get_co_composition()
        assert comp.get("seer") == 2 and comp.get("medium") == 1
    def test_situation_summary(self):
        gc = self._make_game(); gc.resolve_night(); gc.start_discussion()
        s = StrategyAnalyzer(gc.state).build_situation_summary("player_human")
        assert "盤面分析" in s and "縄数" in s and "グレー" in s
    def test_rola_false(self):
        gc = self._make_game(); gc.resolve_night()
        assert not should_show_rola_guide(gc.state)
    def test_rola_true(self):
        gc = self._make_game(); gc.resolve_night(); gc.start_discussion()
        ai = [p for p in gc.state.get_alive_player_ids() if p != "player_human"]
        gc.co(ai[0],"medium"); gc.co(ai[1],"medium")
        assert should_show_rola_guide(gc.state)

# ═══ AIモジュールテスト ═══
class TestPersonalities:
    def test_15(self): assert len(PERSONALITY_PRESETS) == 15
    def test_unique(self): assert len({p.preset_id for p in PERSONALITY_PRESETS}) == 15
    def test_tones(self):
        for p in PERSONALITY_PRESETS: assert p.tone in TONE_DESCRIPTIONS
    def test_assign(self): assert len(assign_personalities([f"a{i}" for i in range(15)], seed=42)) == 15
    def test_prompt(self): assert "口調" in PERSONALITY_PRESETS[0].to_prompt_section()
    def test_fallback(self):
        for p in PERSONALITY_PRESETS: assert len(p.get_fallback_message()) > 0

class TestWolfStrategyModule:
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
        g = FakeResultGuard("w1",RoleName.WEREWOLF,["w1","w2","w3"])
        ok, _ = g.validate_fake_divine("w2","人狼",["w1","w2","w3","v1"]); assert not ok
    def test_guard_wolf_white(self):
        g = FakeResultGuard("w1",RoleName.WEREWOLF,["w1","w2","w3"])
        ok, _ = g.validate_fake_divine("w2","人狼ではない",["w1","w2","w3","v1"]); assert ok
    def test_valid_targets(self):
        g = FakeResultGuard("w1",RoleName.WEREWOLF,["w1","w2"]); g.record_result("v1")
        t = g.get_valid_targets(["w1","w2","v1","v2"])
        assert "w1" not in t and "v1" not in t and "v2" in t

class TestContextModule:
    def test_system_prompt(self):
        p = build_system_prompt(PERSONALITY_PRESETS[0], "テスト")
        assert "テスト" in p and "人狼ゲーム" in p
    def test_game_state(self):
        gc = GameController(seed=42); gc.create_game("太郎"); gc.start_game()
        assert "生存者" in build_game_state_context(gc.state, "player_human")
    def test_role_seer(self):
        s = GameState("t"); s.add_player("s1","占太郎",RoleName.SEER)
        assert "占い師" in build_role_context(s, "s1")
    def test_summary_mgr(self):
        m = DaySummaryManager(); m.add_summary(2, "要約")
        assert "2日目" in m.build_context(3)
    def test_summary_compress(self):
        m = DaySummaryManager(); m.add_summary(2, "あ"*2000); m.add_summary(3, "い"*2000)
        m.compress_if_needed(max_total_chars=3000)
        assert len(m.summaries[2]) < 2000
    def test_discussion_has_json(self):
        gc = GameController(seed=42); gc.create_game("太郎"); gc.start_game()
        gc.resolve_night(); gc.start_discussion()
        b = ContextBuilder(gc.state, DaySummaryManager())
        _, m = b.build_discussion_context("player_human", PERSONALITY_PRESETS[0])
        assert "public_message" in m[0]["content"]
    def test_discussion_has_situation(self):
        gc = GameController(seed=42); gc.create_game("太郎"); gc.start_game()
        gc.resolve_night(); gc.start_discussion()
        b = ContextBuilder(gc.state, DaySummaryManager())
        _, m = b.build_discussion_context("player_human", PERSONALITY_PRESETS[0])
        assert "盤面分析" in m[0]["content"] and "縄数" in m[0]["content"]
    def test_night_seer_guide(self):
        gc = GameController(seed=42); gc.create_game("太郎"); gc.start_game()
        seer = next((p for p in gc.state.players.values()
                     if p.role==RoleName.SEER and not p.is_first_victim), None)
        if not seer: return
        b = ContextBuilder(gc.state, DaySummaryManager())
        targets = [pid for pid in gc.state.get_alive_player_ids() if pid != seer.player_id]
        _, m = b.build_night_action_context(seer.player_id, PERSONALITY_PRESETS[0], "divine", targets)
        assert "占い先選択の指針" in m[0]["content"]
    def test_night_attack_wolf_chat(self):
        gc = GameController(seed=42); gc.create_game("太郎"); gc.start_game()
        wolves = [p for p in gc.state.players.values() if p.role == RoleName.WEREWOLF]
        if not wolves: return
        wolf = wolves[0]
        fake_log = [ChatMessage(sender_id=wolf.player_id, sender_name=wolf.name,
                                content="占い噛もう", channel="wolf", day=1, phase="night")]
        b = ContextBuilder(gc.state, DaySummaryManager())
        targets = [pid for pid in gc.state.get_alive_player_ids()
                   if gc.state.players[pid].role != RoleName.WEREWOLF]
        _, m = b.build_night_action_context(wolf.player_id, PERSONALITY_PRESETS[0], "attack",
                                            targets, wolf_chat_log=fake_log)
        assert "仲間との相談内容" in m[0]["content"] and "占い噛もう" in m[0]["content"]
    def test_freemason_chat(self):
        gc = GameController(seed=42); gc.create_game("太郎"); gc.start_game()
        fm = next((p for p in gc.state.players.values()
                   if p.role==RoleName.FREEMASON and not p.is_first_victim), None)
        if not fm: return
        b = ContextBuilder(gc.state, DaySummaryManager())
        _, m = b.build_freemason_chat_context(fm.player_id, PERSONALITY_PRESETS[0], [])
        assert "共有者チャットの指針" in m[0]["content"] and "確定村人" in m[0]["content"]

class TestAIPlayerModule:
    def test_meta_filter(self):
        assert filter_meta_expressions("AIとして考えると") == ""
        assert filter_meta_expressions("おはよう。") == "おはよう。"
    def test_truncate(self): assert len(truncate_message("あ"*500)) <= 301
    def test_parse_json(self):
        assert parse_json_response('{"a":1}')["a"] == 1
        assert parse_json_response('```json\n{"b":2}\n```')["b"] == 2
        assert parse_json_response("not json") is None
    def test_memo(self):
        m = ReasoningMemo(); m.trusted_seer = "太郎"
        assert ReasoningMemo.from_dict(m.to_dict()).trusted_seer == "太郎"
    def test_mock_client(self): assert ClaudeClient(mock_mode=True).mock_mode
    def test_factory_no_key(self): assert ClaudeClient.create("").mock_mode
    @pytest.mark.asyncio
    async def test_mock_gen(self):
        c = ClaudeClient(mock_mode=True)
        r = await c.generate("sys", [{"role":"user","content":"hello"}]); assert len(r) > 0
    @pytest.mark.asyncio
    async def test_mock_vote(self):
        c = ClaudeClient(mock_mode=True)
        r = await c.generate("sys", [{"role":"user","content":"投票候補: 太郎, 花子\nvote_target"}])
        assert parse_json_response(r) and "vote_target" in parse_json_response(r)
    @pytest.mark.asyncio
    async def test_player_vote(self):
        c = ClaudeClient(mock_mode=True)
        ai = AIPlayer("p1","テスト",PERSONALITY_PRESETS[0],c)
        t, _ = await ai.generate_vote("sys",
            [{"role":"user","content":"投票候補: 太郎, 花子\nvote_target"}], ["太郎","花子"])
        assert t in ["太郎","花子"]

# ═══ Coordinator テスト ═══
class TestCoordinatorModule:
    def _make(self):
        gc = GameController(seed=42); gc.create_game("テスト"); gc.start_game()
        co = AICoordinator(gc, ClaudeClient(mock_mode=True), seed=42); co.initialize()
        return gc, co
    def test_init(self): gc, co = self._make(); assert len(co.ai_players) == 15
    def test_wolf_strategy(self): _, co = self._make(); assert co.wolf_strategy is not None
    @pytest.mark.asyncio
    async def test_discussion(self):
        gc, co = self._make(); gc.resolve_night(); gc.start_discussion()
        r = await co.run_discussion_round()
        assert len(r) > 0 and all("content" in x for x in r)
    @pytest.mark.asyncio
    async def test_votes_parallel(self):
        gc, co = self._make(); gc.resolve_night(); gc.start_discussion(); gc.end_discussion()
        r = await co.generate_all_votes()
        alive_ai = [pid for pid in co.ai_players if gc.state.players[pid].is_alive]
        assert len(r) == len(alive_ai)
    @pytest.mark.asyncio
    async def test_night_parallel(self):
        gc, co = self._make(); gc.resolve_night(); gc.start_discussion(); gc.end_discussion()
        h = gc.get_human_player_id(); alive = gc.state.get_alive_player_ids()
        gc.vote(h, [p for p in alive if p != h][0])
        await co.generate_all_votes(); vr = gc.resolve_votes()
        if gc.state.phase == Phase.VOTE_RESULT:
            gc.start_night(); r = await co.execute_night_phase()
            assert isinstance(r, dict)
            assert "divine" in r and "wolf_chat" in r and "freemason_chat" in r
    @pytest.mark.asyncio
    async def test_co_no_duplicate(self):
        gc, co = self._make(); gc.resolve_night(); gc.start_discussion()
        r1 = await co.handle_ai_co(); r2 = await co.handle_ai_co()
        assert {c["player_id"] for c in r1}.isdisjoint({c["player_id"] for c in r2})
    @pytest.mark.asyncio
    async def test_summary(self):
        gc, co = self._make(); gc.resolve_night(); gc.start_discussion()
        s = await co.generate_day_summary(gc.state.day)
        assert len(s) > 0 and gc.state.day in co.summary_manager.summaries

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
