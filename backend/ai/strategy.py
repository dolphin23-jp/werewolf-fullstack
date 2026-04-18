# strategy.py — 盤面分析（StrategyAnalyzer）＋役職別戦略プロンプト
#
# 第1層: コードで計算する確定情報（グレー、縄数、CO構成）
# 第2層: 役職別の戦略ガイダンス（人狼セオリーに基づく）

from __future__ import annotations
from backend.engine.state import GameState
from backend.engine.roles import RoleName, get_role_def


# ─────────────────────────────────────────────
#  第1層: StrategyAnalyzer — 盤面の確定情報を計算
# ─────────────────────────────────────────────

class StrategyAnalyzer:
    """盤面の確定情報を計算し、AIプロンプトに注入する"""

    def __init__(self, state: GameState):
        self.state = state

    def calc_rope_count(self) -> int:
        """残り吊り縄数を計算する。
        奇数進行: (alive - 1) / 2  例: 9→4, 7→3, 5→2, 3→1
        偶数進行: alive / 2 - 1    例: 8→3, 6→2, 4→1
        """
        alive = len(self.state.get_alive_players())
        if alive % 2 == 1:
            return (alive - 1) // 2
        else:
            return alive // 2 - 1

    def get_parity(self) -> str:
        alive = len(self.state.get_alive_players())
        return "奇数進行" if alive % 2 == 1 else "偶数進行"

    def get_gray_player_ids(self, viewer_id: str) -> list[str]:
        """グレー = COしておらず、公開占い結果でも名前が出ていない生存者"""
        co_pids = {co.player_id for co in self.state.co_list}
        reported_targets = self._extract_reported_target_ids()
        alive = self.state.get_alive_player_ids()
        return [pid for pid in alive
                if pid != viewer_id
                and pid not in co_pids
                and pid not in reported_targets]

    def _extract_reported_target_ids(self) -> set[str]:
        """占い師CO者の公開発言から、結果報告された対象のplayer_id群を抽出"""
        seer_co_names = set()
        for co in self.state.co_list:
            if co.claimed_role == RoleName.SEER:
                seer_co_names.add(self.state.players[co.player_id].name)
        if not seer_co_names:
            return set()

        name_to_id = {p.name: p.player_id for p in self.state.players.values()}
        result_keywords = ("白", "黒", "人狼", "村人", "人間")
        reported = set()
        for msg in self.state.get_chat_log(channel="public"):
            if msg.sender_name not in seer_co_names:
                continue
            for name, pid in name_to_id.items():
                if name in msg.content and any(w in msg.content for w in result_keywords):
                    reported.add(pid)
        return reported

    def get_co_composition(self) -> dict[str, int]:
        """生存CO者の構成 → {"seer": 2, "medium": 1} 等"""
        comp: dict[str, int] = {}
        seen: set[str] = set()
        for co in self.state.co_list:
            if co.player_id in seen:
                continue
            seen.add(co.player_id)
            if self.state.players[co.player_id].is_alive:
                rv = co.claimed_role.value
                comp[rv] = comp.get(rv, 0) + 1
        return comp

    def get_co_composition_str(self) -> str:
        """'占い3-霊能1' のような表記"""
        ROLE_DISP = {"seer": "占い", "medium": "霊能", "hunter": "狩人",
                     "freemason": "共有", "villager": "村人"}
        comp = self.get_co_composition()
        if not comp:
            return "CO者なし"
        return "-".join(f"{ROLE_DISP.get(r, r)}{c}" for r, c in comp.items())

    def estimate_remaining_hostiles(self) -> str:
        """残り人外の推定（公開情報ベースの概算）"""
        # 処刑・死亡した狼の数を死亡記録から推定（霊能結果の公開情報ベース）
        # 精密な推定はAI側の推理に委ねる
        dead_count = len(self.state.death_records)
        alive_count = len(self.state.get_alive_players())
        return f"死亡{dead_count}人（詳細な人外残数はあなた自身の推理で判断してください）"

    def build_situation_summary(self, viewer_id: str) -> str:
        """盤面サマリーを構築してプロンプトに注入する"""
        alive = len(self.state.get_alive_players())
        rope = self.calc_rope_count()
        parity = self.get_parity()
        comp = self.get_co_composition_str()
        gray_ids = self.get_gray_player_ids(viewer_id)
        gray_names = [self.state.players[pid].name for pid in gray_ids]

        lines = [
            "【盤面分析】",
            f"生存{alive}人 / {parity} / 残り縄数{rope}",
            f"CO構成: {comp}",
            f"グレー({len(gray_names)}人): {', '.join(gray_names) if gray_names else 'なし'}",
            self.estimate_remaining_hostiles(),
        ]
        return "\n".join(lines)


# ─────────────────────────────────────────────
#  第2層: 役職別戦略プロンプト
# ─────────────────────────────────────────────

SEER_NIGHT_GUIDE = """【占い先選択の指針】
- 1日目夜: 情報がないので自由に選んでよい。理由は直感程度で構わない。
- 2日目夜以降の基本: グレー（COなし＋未占い）を優先して占う。
  狼・狐を発見し村に情報を蓄積する目的。
- 占い優先度が低い対象:
  ・昼の議論で吊られそうな人物（処刑で退場するなら占う意味が薄い）
  ・襲撃されそうな人物（占い先と襲撃先が一致すると結果が村に落ちない）
- 上級判断:
  ・対抗占いの白を占って「囲い」（偽占いが仲間狼に白出し）を検証する
  ・確定白（全占いから白をもらった人）を作る動きをする
  ・グレーが減ってきたら漫然とグレーを占い続けず、状況に応じて使い分ける"""

HUNTER_NIGHT_GUIDE = """【護衛先選択の指針】
- 基本: 役職CO者を護衛する。共有者の護衛優先度は低い。
- CO構成による判断:
  ・1人しかいない役職は護衛優先度が高い
    例: 占い3/霊能1 → 霊能護衛の優先度が高い
  ・占い2/霊能1（2-1構成）→ 占い護衛も考慮
  ・霊能2人の場合 → 占い護衛を優先（即噛み戦略への対抗）
- 役職者が全員退場した後:
  ・共有者、白を複数もらっている人物を護衛
  ・あえてグレーを護衛してGJを狙う判断もありうる"""

WOLF_ATTACK_GUIDE = """【襲撃先選択の指針】
■信用勝負路線（仲間が占い騙りしている場合に有効）:
  占いを噛まずにあえて残し、騙り占い vs 真占いの構図で村に選択を迫る。
  メリット: 信用勝負に勝てば囲い（仲間への白出し）も成立。
  グレーが狭まるので狐の位置も推測しやすくなる。
  序盤に囲いで仲間をグレランから保護可能。
  → 占い以外の脅威（霊能・狩人・白確定者）を優先的に噛む。

■即噛み路線（占い騙りしていない場合に多い）:
  2日目夜〜3日目夜に真占いを早期に噛んで占い情報を断つ。
  グレーが広くなり潜伏余地が増える。
  デメリット: 狼側からも狐処理が困難になる。
  → 占いCO者の中で真占いと思われる人物を最優先で噛む。

■共通:
  ・狩人護衛が予想される対象はあえて外す判断もある
  ・灰噛み（グレーを噛む）で情報を撹乱する手もある
  ・縄数に余裕がなくなってきたら確定白や強い村人を噛んで票を減らす"""

WOLF_ROPE_TEMPLATE = """【吊り縄の情報】
残り縄数={rope}（生存{alive}人、{parity}）。
狼と狐は処刑でしか処理できない（呪殺は当てにできない）。
縄数 > 残人外推定数 → グレー吊りの余裕がある。
縄数 ≒ 残人外推定数 → 決め打ち（どの占いを信用するか決断し、不信占いを吊る）の段階。
狼側としては縄数に余裕を与えず、村に難しい判断を迫りたい。"""

FREEMASON_CHAT_GUIDE = """【共有者チャットの指針】
あなたたちは互いに確定村人です。以下を相談してください:
- CO戦略: FO（両方CO）で村のまとめ役になるか、HO（片方潜伏）で騙り占いの黒出しを抑制するか
  ・FO: グレーが減る。占いが共有を無駄に占う事故を防げる。まとめ役として機能。
  ・HO: 潜伏共有に黒出し→即共有CO→相方確認で偽占い破綻を狙える。
- 相方がCO済みで噛まれた場合、潜伏側は即座に共有COすること。
- 議論での立ち回り: 誰を信用するか、霊能ロラの提案、占い決め打ちのタイミング。"""

MEDIUM_ROLA_KNOWLEDGE = """【霊能ローラーの知識】
霊能が2人以上いる場合、ロラ（真含め順番に全員吊り）が提案されることが多い。
霊能は占いに比べて相対的に役割が薄い（特に複数時）ため、
全員吊ることで確実に偽1人を処理でき、その間に占い情報も蓄積する合理的な戦略。"""

SEER_CONFLICT_GUIDE = """【占い対抗（複数占い師CO）時の戦略知識】
複数の占い師がCOし黒結果が出ている場合の基本セオリー:
- どちらかの占い師が偽物（狼か狂人の騙り）確定。真偽判定が最優先課題。
- 【黒先吊りセオリー】黒結果を出したプレイヤーを吊り、霊能師の結果で確認するのが情報効率最大:
  例: 占いAが「Xは黒」→ Xを吊る → 霊能「黒確認」→ 占いAが真確定 / 霊能「白確認」→ 占いAが偽確定
  この手順により、1縄で占い師の真偽と黒プレイヤーの処理を同時に解決できる。
- 【グレー吊りとの比較】グレー吊りは情報を集める手段だが、対抗占いがあり黒結果が出ている状況では
  黒先吊りの方が得られる情報量が大きい。グレー吊り推しの理由が薄い場合は疑う価値がある。
- 占い師が「黒対象を吊るな」と主張する場合は自分の偽りを隠そうとしている可能性がある。
- 逆に「黒対象を吊れ」と主張する占い師が自分の信用維持目的で動いている可能性も0ではないが、
  それだけで黒先吊りを否定する理由にはならない。黒先吊りはセオリー通りの合理的な判断。"""

VILLAGE_ROPE_TEMPLATE = """【吊り縄の情報】
残り縄数={rope}（生存{alive}人、{parity}）。
狼と狐は処刑でしか処理できない。
縄数に余裕があればグレー吊りで情報を集められるが、
想定される残り人外数と縄数が拮抗してきたら決め打ち（占い信用の決断）が必要になる。"""


def build_wolf_rope_guide(analyzer: StrategyAnalyzer) -> str:
    return WOLF_ROPE_TEMPLATE.format(
        rope=analyzer.calc_rope_count(),
        alive=len(analyzer.state.get_alive_players()),
        parity=analyzer.get_parity(),
    )


def build_village_rope_guide(analyzer: StrategyAnalyzer) -> str:
    return VILLAGE_ROPE_TEMPLATE.format(
        rope=analyzer.calc_rope_count(),
        alive=len(analyzer.state.get_alive_players()),
        parity=analyzer.get_parity(),
    )


def should_show_rola_guide(state: GameState) -> bool:
    """霊能ロラガイドを表示すべきか: 霊能CO者が2人以上いる場合"""
    medium_co_count = 0
    seen: set[str] = set()
    for co in state.co_list:
        if co.player_id in seen:
            continue
        seen.add(co.player_id)
        if co.claimed_role == RoleName.MEDIUM and state.players[co.player_id].is_alive:
            medium_co_count += 1
    return medium_co_count >= 2


def should_show_seer_conflict_guide(state: GameState) -> bool:
    """占い対抗ガイドを表示すべきか: 占いCO者が2人以上いる場合"""
    seer_co_count = 0
    seen: set[str] = set()
    for co in state.co_list:
        if co.player_id in seen:
            continue
        seen.add(co.player_id)
        if co.claimed_role == RoleName.SEER and state.players[co.player_id].is_alive:
            seer_co_count += 1
    return seer_co_count >= 2
