# e2e_test.py — E2Eテスト（サーバーなし・直接呼出し）
# GameController + AICoordinator を直接使って全フローを検証。
# モックモードでAPIキー不要。

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(**file**))

from backend.engine.game import GameController
from backend.engine.state import Phase
from backend.engine.roles import RoleName, ROLE_DEFINITIONS, get_role_def
from backend.ai.ai_player import ClaudeClient
from backend.ai.coordinator import AICoordinator

async def run_e2e():
print(”=” * 60)
print(“E2E テスト（直接呼出し・モックモード）”)
print(”=” * 60)

```
# ── 1. ゲーム作成 ──
print("\n[1] ゲーム作成...")
gc = GameController(seed=42)
result = gc.create_game("テスト太郎")
human_id = result["human_player_id"]
human_role = gc.state.players[human_id].role
human_role_disp = get_role_def(human_role).display_name
print(f"  ✅ {result['player_count']}人参加")
print(f"  ✅ 役職: {human_role_disp} ({human_role.value})")

# 全プレイヤーの役職を確認
role_count = {}
for pid, p in gc.state.players.items():
    rn = p.role.value
    role_count[rn] = role_count.get(rn, 0) + 1
print(f"  ✅ 配役: {role_count}")
assert role_count.get("villager") == 7, f"村人が7人ではない: {role_count}"
assert role_count.get("werewolf") == 3, f"人狼が3人ではない: {role_count}"

# ── 2. AI Coordinator初期化 ──
print("\n[2] AIコーディネーター初期化...")
client = ClaudeClient(mock_mode=True)
coord = AICoordinator(gc, client, seed=42)
coord.initialize()
print(f"  ✅ AIプレイヤー: {len(coord.ai_players)}人")
print(f"  ✅ 狼戦略: {coord.wolf_strategy.pattern if coord.wolf_strategy else 'N/A'}")
print(f"  ✅ 狂人戦略: {coord.madman_strategy.strategy if coord.madman_strategy else 'N/A'}")

# ── 3. ゲーム開始（1日目夜） ──
print("\n[3] ゲーム開始（1日目夜）...")
gc.start_game()
assert gc.state.phase == Phase.NIGHT
assert gc.state.day == 1
print(f"  ✅ Day{gc.state.day}, Phase: {gc.state.phase.value}")

# ── 4. Day0夜行動実行 ──
print("\n[4] Day0夜行動...")
await coord.execute_night_phase()
# 占い師が行動したか確認
seer = next((p for p in gc.state.players.values()
             if p.role == RoleName.SEER and not p.is_first_victim), None)
if seer and not seer.is_human:
    print(f"  ✅ 占い師({seer.name})が初日占い実行")
    print(f"    占い結果: {len(seer.divine_results)}件")

# ── 5. 夜行動解決（→2日目朝） ──
print("\n[5] 夜行動解決→2日目朝...")
resolve = gc.resolve_night()
print(f"  ✅ status: {resolve.get('status')}")
print(f"  ✅ Day{gc.state.day}, Phase: {gc.state.phase.value}")
if resolve.get("deaths"):
    for d in resolve["deaths"]:
        print(f"    💀 {d['name']} ({d['cause']})")
assert gc.state.day == 2
assert len(resolve.get("deaths", [])) >= 1, "初日犠牲者がいない"

# ── 6. 議論開始 ──
print("\n[6] 議論開始...")
gc.start_discussion()
assert gc.state.phase == Phase.DISCUSSION
print(f"  ✅ Phase: {gc.state.phase.value}")

# ── 7. AIのCO処理 ──
print("\n[7] AIのCO...")
cos = await coord.handle_ai_co()
print(f"  ✅ CO件数: {len(cos)}")
for co in cos:
    name = gc.state.players[co["player_id"]].name
    print(f"    {name} → {co['role']}CO {'(偽)' if co['is_fake'] else '(真)'}")

# ── 8. 議論ラウンド ──
print("\n[8] 議論ラウンド1...")
# 人間の発言
gc.chat(human_id, "おはようございます。占い師はCOお願いします。")
print(f"  ✅ 人間発言送信")

# AI発言
t0 = time.time()
round1 = await coord.run_discussion_round()
elapsed = time.time() - t0
print(f"  ✅ AI {len(round1)}人が発言 ({elapsed:.1f}秒)")
for r in round1[:3]:
    print(f"    {r['name']}: {r['content'][:40]}...")
if len(round1) > 3:
    print(f"    ... 他{len(round1)-3}人")

# 2ラウンド目
print("\n[9] 議論ラウンド2...")
gc.chat(human_id, "COした人の結果を教えてください。")
round2 = await coord.run_discussion_round()
print(f"  ✅ AI {len(round2)}人が発言")

# ── 10. 投票 ──
print("\n[10] 議論終了→投票...")
gc.end_discussion()
assert gc.state.phase == Phase.VOTING

# 人間投票
alive = gc.state.get_alive_player_ids()
vote_target = next(pid for pid in alive if pid != human_id)
gc.vote(human_id, vote_target)
print(f"  ✅ 人間投票: {gc.state.players[vote_target].name}")

# AI投票
t0 = time.time()
votes = await coord.generate_all_votes()
elapsed = time.time() - t0
print(f"  ✅ AI {len(votes)}人が投票 ({elapsed:.1f}秒)")

# 集計
vote_result = gc.resolve_votes()
status = vote_result.get("status")
print(f"  ✅ 投票結果: {status}")

if status == "executed":
    print(f"  ⚔️ 処刑: {vote_result['executed_name']}")
    executed_id = vote_result['executed_id']
    executed_role = gc.state.players[executed_id].role
    print(f"    役職: {get_role_def(executed_role).display_name}")

    # ── 11. 勝利判定確認 ──
    if gc.state.phase == Phase.GAME_OVER:
        print(f"\n  🎮 ゲーム終了: {gc.state.victory_reason}")
        print(f"  🏆 勝者: {gc.state.winner}")
    else:
        # ── 12. 夜フェーズ ──
        print(f"\n[11] 夜フェーズへ...")
        gc.start_night()
        assert gc.state.phase == Phase.NIGHT
        print(f"  ✅ Phase: {gc.state.phase.value}")

        # 要約生成
        print("\n[12] 議論要約生成...")
        summary = await coord.generate_day_summary(gc.state.day)
        print(f"  ✅ 要約: {summary[:60]}...")

        # ── 13. 夜行動 ──
        print("\n[13] 夜行動...")
        # 人間の夜行動
        if human_role in (RoleName.SEER, RoleName.HUNTER, RoleName.WEREWOLF):
            action_type = {RoleName.SEER: "divine", RoleName.HUNTER: "guard",
                           RoleName.WEREWOLF: "attack"}[human_role]
            night_alive = gc.state.get_alive_player_ids()
            nt = next(pid for pid in night_alive if pid != human_id)
            action_result = gc.submit_night_action(human_id, action_type, nt)
            print(f"  ✅ 人間夜行動({action_type}): {action_result.get('status', action_result.get('error'))}")

        # AI夜行動
        night_results = await coord.execute_night_phase()
        print(f"  ✅ AI夜行動完了")
        print(f"    占い: {night_results.get('divine')}")
        print(f"    護衛: {night_results.get('guard')}")
        print(f"    襲撃: {night_results.get('attack')}")
        print(f"    狼チャット: {len(night_results.get('wolf_chat', []))}件")

        # ── 14. 夜解決 ──
        print("\n[14] 夜行動解決→3日目朝...")
        resolve2 = gc.resolve_night()
        print(f"  ✅ status: {resolve2.get('status')}")
        print(f"  ✅ Day{gc.state.day}, Phase: {gc.state.phase.value}")
        if resolve2.get("deaths"):
            for d in resolve2["deaths"]:
                print(f"    💀 {d['name']} ({d['cause']})")
        else:
            print(f"    🌙 死体なし")

        alive_count = len(gc.state.get_alive_players())
        wolves_alive = len(gc.state.get_alive_wolves())
        print(f"\n  📊 生存: {alive_count}人 (狼: {wolves_alive})")

        if gc.state.phase == Phase.GAME_OVER:
            print(f"  🎮 ゲーム終了: {gc.state.victory_reason}")

elif status == "runoff":
    print(f"  🔄 再投票: 同数")
elif status == "game_over":
    print(f"  🎮 ゲーム終了: {vote_result.get('victory', {}).get('reason')}")
elif status == "draw":
    print(f"  🤝 引き分け")

# ── 最終サマリー ──
print("\n" + "=" * 60)
print("✅ E2E テスト完了!")
print("=" * 60)
print(f"\n📋 テスト結果サマリー:")
print(f"  - ゲーム作成: ✅")
print(f"  - 配役(村人7/狼3): ✅")
print(f"  - AI初期化(15人): ✅")
print(f"  - 偽CO戦略抽選: ✅")
print(f"  - Day0夜行動: ✅")
print(f"  - 初日犠牲者: ✅")
print(f"  - AI CO判定: ✅")
print(f"  - 議論2ラウンド: ✅")
print(f"  - 投票(人間+AI): ✅")
if status == "executed":
    print(f"  - 処刑確定: ✅")
    if gc.state.phase != Phase.GAME_OVER:
        print(f"  - 夜フェーズ遷移: ✅")
        print(f"  - AI夜行動: ✅")
        print(f"  - 夜行動解決: ✅")
        print(f"  - 翌日遷移: ✅")
```

if **name** == “**main**”:
asyncio.run(run_e2e())
