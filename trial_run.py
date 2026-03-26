#!/usr/bin/env python

# trial_run.py — サーバー起動＋HTTP経由E2Eテスト

# sk-ant- キーあり → リアルモード
# sk-ant- キーなし → モックモード

# 使い方:
#   python trial_run.py              # モックモード
#   ANTHROPIC_API_KEY=sk-ant-xxx python trial_run.py  # リアルモード

import asyncio
import sys
import os
import time

sys.path.insert(0, os.path.dirname(__file__))

from backend.engine.game import GameController
from backend.engine.state import Phase
from backend.engine.roles import RoleName, get_role_def
from backend.ai.ai_player import ClaudeClient
from backend.ai.coordinator import AICoordinator


def detect_mode():
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if key.startswith("sk-ant-"):
        return "real", key
    return "mock", ""


async def play_one_game(mode: str, api_key: str, max_days: int = 4):
    """1ゲームをプレイする"""
    print(f"\n{'🎮 リアルAPI' if mode == 'real' else '🤖 モック'}モードで開始\n")

    gc = GameController(seed=None)  # ランダムシード
    result = gc.create_game("プレイヤー")
    human_id = result["human_player_id"]
    human_role = gc.state.players[human_id].role
    print(f"役職: {get_role_def(human_role).display_name}")
    print(f"参加者: {result['player_count']}人\n")

    client = ClaudeClient(api_key=api_key, mock_mode=(mode == "mock"))
    coord = AICoordinator(gc, client)
    coord.initialize()

    # ゲーム開始
    gc.start_game()
    print("═" * 50)
    print("  1日目夜")
    print("═" * 50)

    # Day0
    await coord.execute_night_phase()
    resolve = gc.resolve_night()
    deaths = resolve.get("deaths", [])
    for d in deaths:
        print(f"  💀 {d['name']}が無残な姿で発見されました")

    day = 2
    while gc.state.phase != Phase.GAME_OVER and day <= max_days + 1:
        print(f"\n{'═' * 50}")
        print(f"  {day}日目 昼")
        print(f"{'═' * 50}")

        gc.start_discussion()

        # CO
        cos = await coord.handle_ai_co()
        for c in cos:
            name = gc.state.players[c["player_id"]].name
            print(f"  📢 {name}が{ROLE_DISPLAY.get(c['role'], c['role'])}をCO {'(偽)' if c['is_fake'] else ''}")

        # 議論2ラウンド
        gc.chat(human_id, f"{day}日目の議論です。怪しい人を推理しましょう。")
        print(f"\n  [議論ラウンド1]")
        t0 = time.time()
        r1 = await coord.run_discussion_round()
        elapsed = time.time() - t0
        for r in r1[:5]:
            content = r['content'][:50] + ('...' if len(r['content']) > 50 else '')
            print(f"    {r['name']}: {content}")
        if len(r1) > 5:
            print(f"    ... 他{len(r1)-5}人 ({elapsed:.1f}秒)")

        gc.chat(human_id, "投票先を決めましょう。")
        r2 = await coord.run_discussion_round()
        print(f"  [議論ラウンド2] {len(r2)}人発言")

        # 投票
        print(f"\n  [投票]")
        gc.end_discussion()

        alive = gc.state.get_alive_player_ids()
        import random
        vote_target = random.choice([p for p in alive if p != human_id])
        gc.vote(human_id, vote_target)
        print(f"    あなた → {gc.state.players[vote_target].name}")

        await coord.generate_all_votes()
        vote_result = gc.resolve_votes()

        if vote_result.get("status") == "executed":
            ex_id = vote_result["executed_id"]
            ex_role = get_role_def(gc.state.players[ex_id].role).display_name
            print(f"  ⚔️ {vote_result['executed_name']}が処刑されました（{ex_role}）")
        elif vote_result.get("status") == "runoff":
            print(f"  🔄 再投票（同数）")
            # 簡略化: 再投票は1回だけ
            gc.vote(human_id, vote_target)
            await coord.generate_all_votes()
            vote_result = gc.resolve_votes()
            if vote_result.get("status") == "executed":
                print(f"  ⚔️ {vote_result['executed_name']}が処刑されました")
        elif vote_result.get("status") in ("game_over", "draw"):
            break

        if gc.state.phase == Phase.GAME_OVER:
            break

        # 夜フェーズ
        print(f"\n{'═' * 50}")
        print(f"  {day}日目 夜")
        print(f"{'═' * 50}")

        gc.start_night()
        asyncio.ensure_future(coord.generate_day_summary(gc.state.day))

        # 人間の夜行動
        if human_role in (RoleName.SEER, RoleName.HUNTER, RoleName.WEREWOLF):
            action_map = {RoleName.SEER: "divine", RoleName.HUNTER: "guard", RoleName.WEREWOLF: "attack"}
            at = action_map[human_role]
            valid = [p for p in gc.state.get_alive_player_ids() if p != human_id]
            if human_role == RoleName.SEER:
                already = {dr.target_id for dr in gc.state.players[human_id].divine_results}
                valid = [p for p in valid if p not in already]
            if valid:
                target = random.choice(valid)
                gc.submit_night_action(human_id, at, target)
                print(f"  あなたの行動: {at} → {gc.state.players[target].name}")

        # AI夜行動
        await coord.execute_night_phase()

        # 解決
        resolve = gc.resolve_night()
        if resolve.get("deaths"):
            for d in resolve["deaths"]:
                cause = {"attacked": "襲撃", "cursed": "呪殺"}.get(d["cause"], d["cause"])
                print(f"  💀 {d['name']}が{cause}されました")
        else:
            print(f"  🌙 誰も死にませんでした")

        alive_n = len(gc.state.get_alive_players())
        wolf_n = len(gc.state.get_alive_wolves())
        print(f"  📊 生存{alive_n}人 (狼{wolf_n})")

        if gc.state.phase == Phase.GAME_OVER:
            break

        day += 1

    # 結果
    print(f"\n{'═' * 50}")
    if gc.state.phase == Phase.GAME_OVER:
        winner = gc.state.winner or "不明"
        reason = gc.state.victory_reason or ""
        emoji = {"village_win": "🏘️", "werewolf_win": "🐺", "fox_win": "🦊", "draw": "⚖️"}.get(winner, "❓")
        print(f"  {emoji} {reason}")
    else:
        print(f"  ⏰ {max_days}日で打ち切り")
    print(f"{'═' * 50}")

    # 全役職公開
    print(f"\n  【全役職公開】")
    for pid in gc.state.player_order:
        p = gc.state.players[pid]
        rd = get_role_def(p.role)
        status = "生存" if p.is_alive else "死亡"
        marker = " ← あなた" if pid == human_id else ""
        first = " (初日犠牲者)" if p.is_first_victim else ""
        print(f"    {p.name}: {rd.display_name} [{status}]{first}{marker}")


ROLE_DISPLAY = {
    "seer": "占い師", "medium": "霊媒師", "hunter": "狩人",
    "werewolf": "人狼", "madman": "狂人", "fox": "妖狐",
    "freemason": "共有者", "villager": "村人",
}

if __name__ == "__main__":
    mode, key = detect_mode()
    print(f"AI人狼ゲーム — Trial Run")
    print(f"モード: {mode}")
    asyncio.run(play_one_game(mode, key, max_days=4))
