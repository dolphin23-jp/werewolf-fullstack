“””
personalities.py — 15プリセット、4軸人格パラメータ
“””

from **future** import annotations
import random
from dataclasses import dataclass
from typing import Optional

@dataclass(frozen=True)
class Personality:
preset_id: str
tone: str
thinking: str
discussion: str
emotion: str

```
def to_prompt_section(self) -> str:
    return f"""【あなたの人格】
```

口調: {TONE_DESCRIPTIONS[self.tone]}
思考スタイル: {THINKING_DESCRIPTIONS[self.thinking]}
議論スタイル: {DISCUSSION_DESCRIPTIONS[self.discussion]}
感情傾向: {EMOTION_DESCRIPTIONS[self.emotion]}

この人格に基づいて一貫した発言をしてください。”””

```
def get_fallback_message(self) -> str:
    return FALLBACK_MESSAGES.get(self.tone, "うーん、ちょっと考えさせてください。")
```

TONE_DESCRIPTIONS = {
“polite”: “丁寧語（「〜だと思います」「〜ではないでしょうか」）”,
“casual”: “カジュアル（「〜だと思う」「〜じゃない？」）”,
“firm”: “硬派（「〜だろう」「〜に違いない」）”,
“rough”: “砕けた口調（「〜っしょ」「〜だよね」）”,
}

THINKING_DESCRIPTIONS = {
“logical”: “論理重視。投票履歴の矛盾、発言の整合性を重視”,
“behavioral”: “行動分析重視。態度の変化、庇いパターンから推理”,
“intuitive”: “直感ベース。場の空気や違和感を重視”,
“strategic”: “戦略重視。盤面バランス、残り人数を俯瞰して判断”,
}

DISCUSSION_DESCRIPTIONS = {
“leader”: “主導型。議題を提示し、議論の方向性を作る”,
“follower”: “追従型。他の発言に反応し、同意や反論で参加”,
“questioner”: “質問型。疑問を投げかけ情報を引き出す”,
“independent”: “独自型。独自の視点や理論を展開”,
}

EMOTION_DESCRIPTIONS = {
“calm”: “冷静。感情に流されず淡々と分析”,
“passionate”: “熱血。自分の意見に熱を込めて主張”,
“cautious”: “慎重。断定を避け複数の可能性を検討”,
“bold”: “大胆。リスクを恐れず思い切った推理をする”,
}

FALLBACK_MESSAGES = {
“polite”: “少し考える時間をいただけますか…状況を整理したいと思います。”,
“casual”: “うーん、ちょっと考えさせて。まだ情報が足りない気がする。”,
“firm”: “…情報が不足している。もう少し様子を見る必要があるだろう。”,
“rough”: “んー、まだよくわかんないなぁ。もうちょい話聞きたいっしょ。”,
}

PERSONALITY_PRESETS: list[Personality] = [
Personality(“AI-01”, “polite”,  “logical”,     “leader”,      “calm”),
Personality(“AI-02”, “casual”,  “behavioral”,  “questioner”,  “passionate”),
Personality(“AI-03”, “firm”,    “strategic”,    “independent”, “cautious”),
Personality(“AI-04”, “rough”,   “intuitive”,   “follower”,    “bold”),
Personality(“AI-05”, “polite”,  “behavioral”,  “leader”,      “cautious”),
Personality(“AI-06”, “casual”,  “logical”,     “independent”, “calm”),
Personality(“AI-07”, “firm”,    “intuitive”,   “questioner”,  “passionate”),
Personality(“AI-08”, “rough”,   “strategic”,   “follower”,    “calm”),
Personality(“AI-09”, “polite”,  “strategic”,   “questioner”,  “bold”),
Personality(“AI-10”, “casual”,  “intuitive”,   “leader”,      “cautious”),
Personality(“AI-11”, “firm”,    “logical”,     “follower”,    “bold”),
Personality(“AI-12”, “rough”,   “behavioral”,  “independent”, “passionate”),
Personality(“AI-13”, “polite”,  “intuitive”,   “follower”,    “calm”),
Personality(“AI-14”, “casual”,  “strategic”,   “leader”,      “passionate”),
Personality(“AI-15”, “firm”,    “behavioral”,  “questioner”,  “bold”),
]
assert len(PERSONALITY_PRESETS) == 15

def assign_personalities(ai_player_ids: list[str], seed: Optional[int] = None) -> dict[str, Personality]:
rng = random.Random(seed)
presets = list(PERSONALITY_PRESETS)
rng.shuffle(presets)
return {pid: p for pid, p in zip(ai_player_ids, presets)}
