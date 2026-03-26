# vote.py — 投票システム

from __future__ import annotations
import random
from dataclasses import dataclass, field
from typing import Optional
from collections import Counter

from .state import GameState, Phase, DeathCause, VoteRecord


@dataclass
class VoteResult:
    tally: dict[str, int]
    detail: list[dict]
    executed_id: Optional[str]
    executed_name: Optional[str]
    is_tie: bool
    tie_players: list[str]
    is_draw: bool = False
    round_number: int = 1


class VoteManager:
    def __init__(self, state: GameState, seed: Optional[int] = None):
        self.state = state
        self.rng = random.Random(seed)

    def validate_vote(self, voter_id: str, target_id: str) -> tuple[bool, str]:
        voter = self.state.get_player(voter_id)
        target = self.state.get_player(target_id)
        if not voter:
            return False, "投票者が存在しません"
        if not target:
            return False, "投票対象が存在しません"
        if not voter.is_alive:
            return False, "死亡者は投票できません"
        if not target.is_alive:
            return False, "死亡者には投票できません"
        if voter_id == target_id:
            return False, "自分自身には投票できません"
        return True, ""

    def collect_vote(self, voter_id: str, target_id: str) -> tuple[bool, str]:
        valid, msg = self.validate_vote(voter_id, target_id)
        if not valid:
            return False, msg
        self.state.add_vote(voter_id, target_id)
        return True, ""

    def resolve_votes(self) -> VoteResult:
        votes = self.state.get_votes_for_round()
        tally: Counter = Counter()
        detail: list[dict] = []
        for v in votes:
            tally[v.target_id] += 1
            detail.append({
                "voter_id": v.voter_id, "voter": self.state.players[v.voter_id].name,
                "target_id": v.target_id, "target": self.state.players[v.target_id].name,
            })
        alive_ids = self.state.get_alive_player_ids()
        tally_dict = {pid: tally.get(pid, 0) for pid in alive_ids}

        if not tally:
            return VoteResult(tally=tally_dict, detail=detail, executed_id=None,
                              executed_name=None, is_tie=True, tie_players=[],
                              round_number=self.state.vote_round)

        max_votes = max(tally.values())
        top_players = [pid for pid, count in tally.items() if count == max_votes]

        if len(top_players) == 1:
            executed_id = top_players[0]
            executed_name = self.state.players[executed_id].name
            self.state.kill_player(executed_id, DeathCause.EXECUTED)
            self.state.today_executed_id = executed_id
            return VoteResult(tally=tally_dict, detail=detail, executed_id=executed_id,
                              executed_name=executed_name, is_tie=False, tie_players=[],
                              round_number=self.state.vote_round)
        else:
            if self.state.vote_round >= self.state.max_vote_rounds:
                return VoteResult(tally=tally_dict, detail=detail, executed_id=None,
                                  executed_name=None, is_tie=True, tie_players=top_players,
                                  is_draw=True, round_number=self.state.vote_round)
            return VoteResult(tally=tally_dict, detail=detail, executed_id=None,
                              executed_name=None, is_tie=True, tie_players=top_players,
                              round_number=self.state.vote_round)

    def all_votes_in(self) -> bool:
        votes = self.state.get_votes_for_round()
        alive = self.state.get_alive_player_ids()
        return len({v.voter_id for v in votes}) >= len(alive)
