# context.py — コンテキスト構築（5層構造）
#
# [A] システムプロンプト（人格定義）
# [B] 役職固有情報
# [C] ゲーム状態 + 盤面分析（StrategyAnalyzer）
# [D] 過去日の要約
# [E] 当日全文ログ
#
# 変更点:
# - StrategyAnalyzer による盤面情報（グレー、縄数、CO構成）の自動注入
# - 役職別戦略ガイドの注入
# - 議論発言でJSON形式を直接指示（ai_player.py側の文字列replaceを廃止）
# - 共有者チャット専用コンテキストの新設
# - 狼襲撃先決定時に狼チャットログを注入

from __future__ import annotations
from typing import Optional

from backend.engine.state import GameState, Phase, ChatMessage
from backend.engine.roles import RoleName, get_role_def
from .personalities import Personality
from .strategy import (
    StrategyAnalyzer,
    SEER_NIGHT_GUIDE, HUNTER_NIGHT_GUIDE,
    WOLF_ATTACK_GUIDE, FREEMASON_CHAT_GUIDE,
    MEDIUM_ROLA_KNOWLEDGE, SEER_CONFLICT_GUIDE,
    build_wolf_rope_guide, build_village_rope_guide,
    should_show_rola_guide, should_show_seer_conflict_guide,
)


# ─────────────────────────────────────────────
#  基本ビルダー関数
# ─────────────────────────────────────────────

def build_system_prompt(personality: Personality, player_name: str) -> str:
    return f"""あなたは人狼ゲームに参加しているプレイヤー「{player_name}」です。
17人参加のオンラインチャット型人狼ゲームです。

{personality.to_prompt_section()}

【重要な制約】
- 「AIとして」「プログラムとして」等のメタ発言は絶対に禁止
- 発言は200文字以内を目安にしてください
- 他のプレイヤーの発言内容に具体的に言及してください
- 直前の発言を鵜呑みにせず、自分の推理に基づいた意見を持ってください
- 同じ意見が場を支配していると感じたら、あえて別角度から検証してください
- 他者の意見に賛同する場合も、同じ表現の繰り返しにならず独自の根拠を示してください"""


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
    already_co = state.get_co_for_player(player_id)

    if player.role == RoleName.SEER:
        lines.append("毎夜1人を占い、人狼かどうかを知ることができます。")
        if player.divine_results:
            lines.append("あなたの占い結果:")
            for dr in player.divine_results:
                lines.append(f"  {dr.day}日目夜: {state.players[dr.target_id].name} → {dr.result}")
        else:
            lines.append("  まだ占い結果はありません。")
        if state.day >= 2 and not already_co:
            lines.append(
                "【重要】今日の発言で「占い師COします」と明言してCOしてください。"
                "その後、占い結果を報告してください（例: 「占い師COします。昨夜はXXを占い、白でした」）。"
            )

    elif player.role == RoleName.MEDIUM:
        lines.append("処刑された人が人狼かどうかを知ることができます。")
        if player.medium_results:
            lines.append("あなたの霊媒結果:")
            for mr in player.medium_results:
                lines.append(f"  {mr.day}日目処刑者: {state.players[mr.target_id].name} → {mr.result}")
        else:
            lines.append(
                "  ※まだ霊媒結果はありません。"
                "初日(1日目)は処刑が行われないため、霊媒結果は2日目の処刑後から始まります。"
                "1日目議論では「1日目の霊媒結果は…」のような誤った発言は絶対にしないでください。"
            )
        if state.day >= 2 and not already_co:
            lines.append(
                "【重要】今日の発言で「霊媒師COします」と明言してCOしてください"
                "（例: 「霊媒師COします。昨日処刑されたXXは白でした」）。"
                "結果がない場合は「まだ結果はありません」と正直に伝えてください。"
            )

    elif player.role == RoleName.HUNTER:
        lines.append("2日目夜から毎夜1人を護衛できます（自分は不可）。")
        if state.day >= 2 and not already_co:
            lines.append(
                "【重要】状況次第では今日の発言で「狩人COします」とCOすることを検討してください。"
                "しかし狩人はCOすると標的になるリスクがあるため、状況を見て判断してください。"
            )

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
        if state.day >= 2 and not already_co:
            lines.append(
                "【重要】共有者としてCO戦略を判断してください。"
                "FOを選ぶ場合は「共有者COします」と発言してCOしてください。"
            )

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


def _phase_jp(phase: Phase) -> str:
    return {"waiting": "待機中", "night": "夜", "dawn": "朝", "discussion": "昼議論",
            "voting": "投票", "vote_result": "投票結果", "runoff": "決選投票",
            "game_over": "ゲーム終了"}.get(phase.value, str(phase))


def _format_memo(memo: dict) -> str:
    lines = []
    if memo.get("trusted_seer"):
        lines.append(f"信用占い師: {memo['trusted_seer']}")
    if memo.get("suspects"):
        lines.append("疑い: " + ", ".join(str(s) for s in memo["suspects"]))
    if memo.get("trusted"):
        lines.append("信頼: " + ", ".join(
            f"{t['name']}({t['level']})" if isinstance(t, dict) else str(t)
            for t in memo["trusted"]))
    if memo.get("execution_target"):
        lines.append(f"処刑候補: {memo['execution_target']}")
    if memo.get("overall_thought"):
        lines.append(f"総合判断: {memo['overall_thought']}")
    return "\n".join(lines) if lines else "（メモなし）"


# ─────────────────────────────────────────────
#  日次要約管理
# ─────────────────────────────────────────────

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

    def compress_if_needed(self, max_total_chars: int = 3000) -> None:
        """要約の合計文字数が閾値を超えたら最古の要約を圧縮"""
        total = sum(len(s) for s in self.summaries.values())
        while total > max_total_chars and self.summaries:
            oldest = min(self.summaries.keys())
            s = self.summaries[oldest]
            if len(s) > 200:
                self.summaries[oldest] = s[:200] + "…（省略）"
                total = sum(len(s) for s in self.summaries.values())
            else:
                break


# ─────────────────────────────────────────────
#  ContextBuilder
# ─────────────────────────────────────────────

# 議論発言のJSON出力指示（ai_player.pyのstring replaceを廃止するため直接定義）
DISCUSSION_OUTPUT_INSTRUCTION = """【独自視点の徹底】
- 直前の発言に流されず、ゲーム情報と自分の推理に基づいて判断してください。
- 同意する場合でも、単なる繰り返しにならず、あなた独自の根拠や新しい論点を加えてください。
- 流れに疑問があれば積極的に異論を唱えてください。人狼ゲームは多角的な視点が重要です。

以下のJSON形式で回答してください:
{"public_message": "あなたの発言(200文字以内、人格に合った口調)", "reasoning_memo": {"trusted_seer": "", "suspects": [], "trusted": [], "execution_target": "", "overall_thought": ""}}"""


class ContextBuilder:
    def __init__(self, state: GameState, summary_manager: DaySummaryManager):
        self.state = state
        self.summary_manager = summary_manager

    def build_discussion_context(self, player_id: str, personality: Personality) -> tuple[str, list[dict]]:
        system = build_system_prompt(personality, self.state.players[player_id].name)
        analyzer = StrategyAnalyzer(self.state)

        parts = [
            build_role_context(self.state, player_id),
            build_game_state_context(self.state, player_id),
            analyzer.build_situation_summary(player_id),
            build_village_rope_guide(analyzer),
        ]

        # 霊能ロラガイドを条件付きで注入
        if should_show_rola_guide(self.state):
            parts.append(MEDIUM_ROLA_KNOWLEDGE)

        # 占い対抗ガイドを条件付きで注入（占いCO 2人以上の場合）
        if should_show_seer_conflict_guide(self.state):
            parts.append(SEER_CONFLICT_GUIDE)

        parts.extend([
            self.summary_manager.build_context(self.state.day),
            build_current_day_log(self.state, player_id),
            DISCUSSION_OUTPUT_INSTRUCTION,
        ])

        user_content = "\n\n".join(filter(None, parts))
        return system, [{"role": "user", "content": user_content}]

    def build_vote_context(self, player_id: str, personality: Personality,
                           alive_ids: list[str], reasoning_memo=None) -> tuple[str, list[dict]]:
        system = build_system_prompt(personality, self.state.players[player_id].name)
        analyzer = StrategyAnalyzer(self.state)

        parts = [
            build_role_context(self.state, player_id),
            build_game_state_context(self.state, player_id),
            analyzer.build_situation_summary(player_id),
            build_current_day_log(self.state, player_id),
        ]
        if reasoning_memo:
            parts.append(f"【あなたの推理メモ】\n{_format_memo(reasoning_memo)}")

        candidates = [self.state.players[pid].name for pid in alive_ids if pid != player_id]
        parts.append(f'投票候補: {", ".join(candidates)}')
        parts.append('以下のJSON形式で回答: {"vote_target": "名前", "reason": "理由"}')

        user_content = "\n\n".join(filter(None, parts))
        return system, [{"role": "user", "content": user_content}]

    def build_night_action_context(self, player_id: str, personality: Personality,
                                    action_type: str, valid_targets: list[str],
                                    reasoning_memo=None,
                                    wolf_chat_log: Optional[list[ChatMessage]] = None
                                    ) -> tuple[str, list[dict]]:
        system = build_system_prompt(personality, self.state.players[player_id].name)
        analyzer = StrategyAnalyzer(self.state)

        parts = [
            build_role_context(self.state, player_id),
            build_game_state_context(self.state, player_id),
            analyzer.build_situation_summary(player_id),
        ]

        # 役職別戦略ガイドを注入
        if action_type == "divine":
            parts.append(SEER_NIGHT_GUIDE)
            # 占い師にグレー情報を明示
            gray_ids = analyzer.get_gray_player_ids(player_id)
            gray_in_targets = [self.state.players[g].name
                               for g in gray_ids if g in valid_targets]
            if gray_in_targets:
                parts.append(f"現在のグレー: {', '.join(gray_in_targets)}")
        elif action_type == "guard":
            parts.append(HUNTER_NIGHT_GUIDE)
            parts.append(f"CO構成: {analyzer.get_co_composition_str()}")
        elif action_type == "attack":
            parts.append(WOLF_ATTACK_GUIDE)
            parts.append(build_wolf_rope_guide(analyzer))
            # 狼チャットの内容を注入
            if wolf_chat_log:
                chat_str = "\n".join(f"{m.sender_name}: {m.content}" for m in wolf_chat_log)
                parts.append(f"【仲間との相談内容】\n{chat_str}\n上記を踏まえて襲撃先を決定してください。")

        if reasoning_memo:
            parts.append(f"【推理メモ】\n{_format_memo(reasoning_memo)}")

        action_desc = {"divine": "占い先", "guard": "護衛先", "attack": "襲撃先"}.get(action_type, "行動先")
        target_names = [self.state.players[tid].name for tid in valid_targets]
        parts.append(f'{action_desc}候補: {", ".join(target_names)}')
        parts.append(f'{{"target": "プレイヤー名", "reason": "理由"}}')

        user_content = "\n\n".join(filter(None, parts))
        return system, [{"role": "user", "content": user_content}]

    def build_wolf_chat_context(self, player_id: str, personality: Personality,
                                 wolf_chat_log: list[ChatMessage]) -> tuple[str, list[dict]]:
        system = build_system_prompt(personality, self.state.players[player_id].name)
        analyzer = StrategyAnalyzer(self.state)
        chat_str = "\n".join(f"{m.sender_name}: {m.content}" for m in wolf_chat_log) or "（まだ発言なし）"

        parts = [
            build_role_context(self.state, player_id),
            build_game_state_context(self.state, player_id),
            analyzer.build_situation_summary(player_id),
            build_wolf_rope_guide(analyzer),
            f"【狼チャット】\n{chat_str}",
            "仲間と相談してください。襲撃先の希望、占い結果の偽装方針、潜伏戦略などを100文字以内で発言。",
        ]
        user_content = "\n\n".join(filter(None, parts))
        return system, [{"role": "user", "content": user_content}]

    def build_freemason_chat_context(self, player_id: str, personality: Personality,
                                      chat_log: list[ChatMessage]) -> tuple[str, list[dict]]:
        """共有者専用チャットコンテキスト"""
        system = build_system_prompt(personality, self.state.players[player_id].name)
        analyzer = StrategyAnalyzer(self.state)
        chat_str = "\n".join(f"{m.sender_name}: {m.content}" for m in chat_log) or "（まだ発言なし）"

        parts = [
            build_role_context(self.state, player_id),
            build_game_state_context(self.state, player_id),
            analyzer.build_situation_summary(player_id),
            FREEMASON_CHAT_GUIDE,
            f"【共有者チャット】\n{chat_str}",
            "相方と100文字以内で相談してください。",
        ]
        user_content = "\n\n".join(filter(None, parts))
        return system, [{"role": "user", "content": user_content}]

    def build_summary_context(self, day: int) -> tuple[str, list[dict]]:
        log = self.state.get_chat_log(channel="public", day=day)
        log_text = "\n".join(
            f"{m.sender_name}: {m.content}" if m.sender_id != "system"
            else f"[システム] {m.content}"
            for m in log
        )
        system = "あなたは人狼ゲームの議論要約を作成するアシスタントです。"
        user_content = f"以下の{day}日目の議論ログを500文字以内で要約してください。\n\n{log_text}\n\n要約:"
        return system, [{"role": "user", "content": user_content}]
