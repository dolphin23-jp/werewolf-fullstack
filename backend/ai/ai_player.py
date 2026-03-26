# ai_player.py — Claude API呼出し、JSONパース、メタフィルタ、ReasoningMemo、フォールバック


from __future__ import annotations
import json
import re
import os
import random
from typing import Optional
from dataclasses import dataclass, field

from .personalities import Personality

META_PATTERNS = [
    r"AIとして", r"プログラムとして", r"言語モデル", r"LLM", r"クロード", r"Claude",
    r"アシスタント", r"人工知能", r"機械学習", r"API", r"トークン", r"プロンプト",
    r"システムプロンプト", r"ロールプレイ", r"シミュレーション",
]
META_REGEX = re.compile("|".join(META_PATTERNS), re.IGNORECASE)


def filter_meta_expressions(text: str) -> str:
    sentences = re.split(r'(?<=[。！？\n])', text)
    filtered = [s for s in sentences if not META_REGEX.search(s)]
    return "".join(filtered).strip()


def truncate_message(text: str, max_chars: int = 300) -> str:
    if len(text) <= max_chars:
        return text
    truncated = text[:max_chars]
    last_period = max(truncated.rfind("。"), truncated.rfind("！"), truncated.rfind("？"))
    if last_period > max_chars // 2:
        return truncated[:last_period + 1]
    return truncated + "…"


def parse_json_response(text: str) -> Optional[dict]:
    # 1. 全体をJSONとして試す（最優先）
    try:
        return json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        pass
    # 2. ```json ... ``` ブロックを抽出
    json_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?\s*```', text, re.DOTALL)
    if json_match:
        try:
            return json.loads(json_match.group(1))
        except (json.JSONDecodeError, ValueError):
            pass
    # 3. 最初の { から最後の } までを抽出（ネスト対応）
    first = text.find('{')
    last = text.rfind('}')
    if first != -1 and last > first:
        try:
            return json.loads(text[first:last+1])
        except (json.JSONDecodeError, ValueError):
            pass
    return None


@dataclass
class ReasoningMemo:
    trusted_seer: str = ""
    suspects: list[dict] = field(default_factory=list)
    trusted: list[dict] = field(default_factory=list)
    execution_target: str = ""
    overall_thought: str = ""

    def to_dict(self) -> dict:
        return {"trusted_seer": self.trusted_seer, "suspects": self.suspects,
                "trusted": self.trusted, "execution_target": self.execution_target,
                "overall_thought": self.overall_thought}

    @classmethod
    def from_dict(cls, data: dict) -> ReasoningMemo:
        m = cls()
        m.trusted_seer = data.get("trusted_seer", "")
        m.suspects = data.get("suspects", [])
        m.trusted = data.get("trusted", [])
        m.execution_target = data.get("execution_target", "")
        m.overall_thought = data.get("overall_thought", "")
        return m


class ClaudeClient:
    def __init__(self, api_key: Optional[str] = None, mock_mode: bool = False):
        self.mock_mode = mock_mode
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        if not self.api_key or not self.api_key.startswith("sk-ant-"):
            self.mock_mode = True
        self.client = None
        if not self.mock_mode:
            try:
                import anthropic
                self.client = anthropic.Anthropic(api_key=self.api_key)
            except Exception:
                self.mock_mode = True

    async def generate(self, system: str, messages: list[dict],
                       max_tokens: int = 1024, temperature: float = 0.8) -> str:
        if self.mock_mode:
            return self._mock_generate(system, messages)
        try:
            response = self.client.messages.create(
                model="claude-3-haiku-20240307", max_tokens=max_tokens,
                temperature=temperature, system=system, messages=messages)
            return response.content[0].text
        except Exception as e:
            print(f"[Claude API Error] {e}")
            return ""

    def _mock_generate(self, system: str, messages: list[dict]) -> str:
        user_msg = messages[0]["content"] if messages else ""
        if "vote_target" in user_msg:
            candidates_match = re.search(r'投票候補: (.+?)$', user_msg, re.MULTILINE)
            if candidates_match:
                candidates = [c.strip() for c in candidates_match.group(1).split(",")]
                return json.dumps({"vote_target": random.choice(candidates),
                                   "reason": "総合的に判断"}, ensure_ascii=False)
        if '"target"' in user_msg and "候補:" in user_msg:
            candidates_match = re.search(r'候補: (.+?)$', user_msg, re.MULTILINE)
            if candidates_match:
                candidates = [c.strip() for c in candidates_match.group(1).split(",")]
                return json.dumps({"target": random.choice(candidates),
                                   "reason": "状況判断"}, ensure_ascii=False)
        if "要約" in user_msg:
            return "この日は議論が行われました。"
        if "public_message" in user_msg:
            return json.dumps({"public_message": "状況を整理して考えましょう。",
                               "reasoning_memo": {"trusted_seer": "", "suspects": [],
                                "trusted": [], "execution_target": "",
                                "overall_thought": "情報収集段階"}}, ensure_ascii=False)
        return random.choice([
            "おはようございます。まずは情報を整理しましょう。",
            "昨夜の結果を踏まえて考えると、気になる点があるんだよね。",
            "状況を見る限り、怪しい動きをしている人がいるように思う。",
            "もう少し情報が欲しいところだな。",
            "ここまでの流れを見て、自分なりの考えをまとめたっしょ。",
        ])


class AIPlayer:
    def __init__(self, player_id: str, player_name: str, personality: Personality, claude_client: ClaudeClient):
        self.player_id = player_id
        self.player_name = player_name
        self.personality = personality
        self.client = claude_client
        self.reasoning_memo = ReasoningMemo()
        self.max_retries = 2

    async def generate_discussion_message(self, system: str, messages: list[dict]) -> tuple[str, Optional[dict]]:
        enhanced = list(messages)
        if enhanced:
            enhanced[-1] = {"role": "user", "content": enhanced[-1]["content"].replace(
                "あなたの発言を1つだけ生成してください。200文字以内で、あなたの人格に合った口調で発言してください。",
                '以下のJSON形式で回答: {"public_message": "発言(200文字以内)", "reasoning_memo": {"trusted_seer": "", "suspects": [], "trusted": [], "execution_target": "", "overall_thought": ""}}'
            )}
        for _ in range(self.max_retries + 1):
            raw = await self.client.generate(system, enhanced)
            if not raw:
                continue
            parsed = parse_json_response(raw)
            if parsed and "public_message" in parsed:
                msg = filter_meta_expressions(parsed["public_message"])
                msg = truncate_message(msg)
                memo = parsed.get("reasoning_memo")
                if memo:
                    self.reasoning_memo = ReasoningMemo.from_dict(memo)
                if msg:
                    return msg, self.reasoning_memo.to_dict()
            msg = filter_meta_expressions(raw)
            msg = truncate_message(msg)
            if msg:
                return msg, None
        return self.personality.get_fallback_message(), None

    async def generate_vote(self, system: str, messages: list[dict], alive_names: list[str]) -> tuple[str, str]:
        for _ in range(self.max_retries + 1):
            raw = await self.client.generate(system, messages, temperature=0.5)
            if not raw:
                continue
            parsed = parse_json_response(raw)
            if parsed and "vote_target" in parsed:
                target = parsed["vote_target"]
                if target in alive_names and target != self.player_name:
                    return target, parsed.get("reason", "")
        valid = [n for n in alive_names if n != self.player_name]
        return random.choice(valid) if valid else alive_names[0], "ランダム"

    async def generate_night_action(self, system: str, messages: list[dict],
                                     valid_target_names: list[str]) -> tuple[str, str]:
        for _ in range(self.max_retries + 1):
            raw = await self.client.generate(system, messages, temperature=0.5)
            if not raw:
                continue
            parsed = parse_json_response(raw)
            if parsed and "target" in parsed:
                target = parsed["target"]
                if target in valid_target_names:
                    return target, parsed.get("reason", "")
        return random.choice(valid_target_names), "ランダム"

    async def generate_wolf_chat(self, system: str, messages: list[dict]) -> str:
        raw = await self.client.generate(system, messages, max_tokens=256)
        if raw:
            msg = filter_meta_expressions(raw)
            msg = truncate_message(msg, max_chars=100)
            if msg:
                return msg
        return self.personality.get_fallback_message()

    def get_memo(self) -> dict:
        return self.reasoning_memo.to_dict()
