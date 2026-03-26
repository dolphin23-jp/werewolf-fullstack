# context.py — 5層コンテキスト構造、トークン量推計

from __future__ import annotations
from typing import Optional, Any

from backend.engine.state import GameState, Phase, ChatMessage
from backend.engine.roles import RoleName, get_role_def
from .personalities import Personality


def estimate_tokens(text: str) -> int:
    jp_chars = sum(1 for c in text if ord(c) > 127)
    en_chars = len(text) - jp_chars
    return int(jp_chars * 1.5 + en_chars * 0.3)


MAX_CONTEXT_TOKENS = 100_000


def build_system_prompt(personality: Personality, player_name: str) -> str:
    return f"""あなたは人狼ゲームに参加しているプレイヤー「{player_name}」です。
17人参加のオンラインチャット型人狼ゲームです。

{personality.to_prompt_section()}

【重要な制約】

- 「AIとして」「プログラムとして」等のメタ発言は絶対に禁止
- 発言は200文字以内を目安にしてください
- 他のプレイヤーの発言内容に具体的に言及してください"""


def build_game_state_context(state: GameState, viewer_id: str) -> str:
    lines = [f"【ゲーム状態】{state.day}日目 {_phase_jp(state.phase)}"]
    alive = state.get_alive_players()
    alive_names = [f"{p.name}{'(自分)' if p.player_id == viewer_id else ''}" for p in alive]
    lines.append(f"生存者({len(alive)}人): {', '.join(alive_names)}")
    dead = [p for p in state.players.values() if not p.is_alive]
    if dead:
        dead_info = []
        cause_jp = {"executed": "処刑", "attacked": "襲撃", "cursed": "呪殺", "first_victim": "初日犠牲"}
        for d in dead:
            dr = [r for r in state.death_records if r.player_id == d.player_id]
            cause = cause_jp.get(dr[0].cause.value, "不明") if dr else "不明"
            dead_info.append(f"{d.name}({dr[0].day}日目{cause})" if dr else d.name)
        lines.append(f"死亡者: {', '.join(dead_info)}")
    co_summary = state.get_co_summary()
    if co_summary:
        lines.append("CO状況: " + " / ".join(f"{r}CO: {', '.join(n)}" for r, n in co_summary.items()))
    return "\n".join(lines)


def build_role_context(state: GameState, player_id: str) -> str:
    player = state.players[player_id]
    rd = get_role_def(player.role)
    lines = [f"【あなたの役職: {rd.display_name}】"]
    if player.role == RoleName.SEER:
        lines.append("毎夜1人を占い、人狼かどうかを知ることができます。")
        for dr in player.divine_results:
            lines.append(f"  {dr.day}日目夜: {state.players[dr.target_id].name} → {dr.result}")
    elif player.role == RoleName.MEDIUM:
        lines.append("処刑された人が人狼かどうかを知ることができます。")
        for mr in player.medium_results:
            lines.append(f"  {mr.day}日目: {state.players[mr.target_id].name} → {mr.result}")
    elif player.role == RoleName.HUNTER:
        lines.append("2日目夜から毎夜1人を護衛できます（自分は不可）。")
    elif player.role == RoleName.WEREWOLF:
        wolf_names = [state.players[wid].name for wid in state.get_wolf_ids() if wid != player_id]
        lines.append(f"あなたは人狼です。仲間: {', '.join(wolf_names)}")
        if state.alpha_tracker:
            if state.alpha_tracker.is_alpha_wolf(player_id):
                lines.append("あなたがアルファ狼です。襲撃先を決定してください。")
    elif player.role == RoleName.MADMAN:
        lines.append("あなたは狂人です。人狼陣営ですが、人狼が誰かはわかりません。")
    elif player.role == RoleName.FOX:
        lines.append("あなたは妖狐です。襲撃では死にませんが、占われると呪殺されます。")
    elif player.role == RoleName.FREEMASON:
        partner_names = [state.players[fid].name for fid in state.freemason_ids if fid != player_id]
        lines.append(f"あなたは共有者です。相方: {', '.join(partner_names)}")
    elif player.role == RoleName.VILLAGER:
        lines.append("あなたは村人です。議論と投票で人狼を追い詰めてください。")
    return "\n".join(lines)


def build_current_day_log(state: GameState, viewer_id: str, channel: str = "public") -> str:
    messages = state.get_chat_log(channel=channel, day=state.day)
    if not messages:
        return ""
    lines = [f"【{state.day}日目の議論ログ】"]
    for msg in messages:
        if msg.sender_id == "system":
            lines.append(f"[システム] {msg.content}")
        else:
            marker = "(自分)" if msg.sender_id == viewer_id else ""
            lines.append(f"{msg.sender_name}{marker}: {msg.content}")
    return "\n".join(lines)


class DaySummaryManager:
    def __init__(self):
        self.summaries: dict[int, str] = {}

    def add_summary(self, day: int, summary: str) -> None:
        self.summaries[day] = summary

    def build_context(self, current_day: int) -> str:
        if not self.summaries:
            return ""
        lines = ["【過去の議論要約】"]
        for day in sorted(self.summaries.keys()):
            if day < current_day:
                lines.append(f"--- {day}日目 ---")
                lines.append(self.summaries[day])
        return "\n".join(lines)

    def compress_oldest(self) -> None:
        if not self.summaries:
            return
        oldest = min(self.summaries.keys())
        s = self.summaries[oldest]
        if len(s) > 200:
            self.summaries[oldest] = s[:200] + "…（省略）"


def _format_memo(memo: dict) -> str:
    lines = []
    if memo.get("trusted_seer"): lines.append(f"信用占い師: {memo['trusted_seer']}")
    if memo.get("suspects"):
        lines.append("疑い: " + ", ".join(str(s) for s in memo["suspects"]))
    if memo.get("trusted"):
        lines.append("信頼: " + ", ".join(f"{t['name']}({t['level']})" for t in memo["trusted"]))
    if memo.get("execution_target"): lines.append(f"処刑候補: {memo['execution_target']}")
    if memo.get("overall_thought"): lines.append(f"総合判断: {memo['overall_thought']}")
    return "\n".join(lines) if lines else "（メモなし）"


def _phase_jp(phase: Phase) -> str:
    return {"waiting": "待機中", "night": "夜", "dawn": "朝", "discussion": "昼議論",
            "voting": "投票", "vote_result": "投票結果", "runoff": "決選投票",
            "game_over": "ゲーム終了"}.get(phase.value, str(phase))


class ContextBuilder:
    def __init__(self, state: GameState, summary_manager: DaySummaryManager):
        self.state = state
        self.summary_manager = summary_manager

    def build_discussion_context(self, player_id: str, personality: Personality) -> tuple[str, list[dict]]:
        player = self.state.players[player_id]
        system = build_system_prompt(personality, player.name)
        parts = [build_role_context(self.state, player_id),
                 build_game_state_context(self.state, player_id),
                 self.summary_manager.build_context(self.state.day),
                 build_current_day_log(self.state, player_id)]
        user_content = "\n\n".join(filter(None, parts))
        user_content += "\n\n上記の状況を踏まえて、あなたの発言を1つだけ生成してください。200文字以内で、あなたの人格に合った口調で発言してください。"
        return system, [{"role": "user", "content": user_content}]

    def build_vote_context(self, player_id: str, personality: Personality,
                           alive_ids: list[str], reasoning_memo=None) -> tuple[str, list[dict]]:
        player = self.state.players[player_id]
        system = build_system_prompt(personality, player.name)
        parts = [build_role_context(self.state, player_id),
                 build_game_state_context(self.state, player_id),
                 build_current_day_log(self.state, player_id)]
        user_content = "\n\n".join(filter(None, parts))
        if reasoning_memo:
            user_content += f"\n\n【あなたの推理メモ】\n{_format_memo(reasoning_memo)}"
        candidates = [self.state.players[pid].name for pid in alive_ids if pid != player_id]
        user_content += f'\n\n投票候補: {", ".join(candidates)}\n'
        user_content += '以下のJSON形式で回答: {"vote_target": "名前", "reason": "理由"}'
        return system, [{"role": "user", "content": user_content}]

    def build_night_action_context(self, player_id: str, personality: Personality,
                                    action_type: str, valid_targets: list[str],
                                    reasoning_memo=None) -> tuple[str, list[dict]]:
        player = self.state.players[player_id]
        system = build_system_prompt(personality, player.name)
        parts = [build_role_context(self.state, player_id),
                 build_game_state_context(self.state, player_id)]
        user_content = "\n\n".join(filter(None, parts))
        if reasoning_memo:
            user_content += f"\n\n【推理メモ】\n{_format_memo(reasoning_memo)}"
        action_desc = {"divine": "占い先", "guard": "護衛先", "attack": "襲撃先"}.get(action_type, "行動先")
        target_names = [self.state.players[tid].name for tid in valid_targets]
        user_content += f'\n\n{action_desc}候補: {", ".join(target_names)}\n'
        user_content += f'{{"target": "{action_desc}のプレイヤー名", "reason": "理由"}}'
        return system, [{"role": "user", "content": user_content}]

    def build_wolf_chat_context(self, player_id: str, personality: Personality,
                                 wolf_chat_log: list[ChatMessage]) -> tuple[str, list[dict]]:
        player = self.state.players[player_id]
        system = build_system_prompt(personality, player.name)
        chat_str = "\n".join(f"{m.sender_name}: {m.content}" for m in wolf_chat_log) or "（まだ発言なし）"
        user_content = f"{build_role_context(self.state, player_id)}\n\n{build_game_state_context(self.state, player_id)}\n\n【狼チャット】\n{chat_str}\n\n仲間と相談してください。100文字以内で発言。"
        return system, [{"role": "user", "content": user_content}]

    def build_summary_context(self, day: int) -> tuple[str, list[dict]]:
        log = self.state.get_chat_log(channel="public", day=day)
        log_text = "\n".join(f"{m.sender_name}: {m.content}" if m.sender_id != "system" else f"[システム] {m.content}" for m in log)
        system = "あなたは人狼ゲームの議論要約を作成するアシスタントです。"
        user_content = f"以下の{day}日目の議論ログを500文字以内で要約してください。\n\n{log_text}\n\n要約:"
        return system, [{"role": "user", "content": user_content}]
