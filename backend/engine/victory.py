# victory.py — 勝利判定4パターン、個人勝敗

from __future__ import annotations
from dataclasses import dataclass
from typing import Optional

from .roles import RoleName, Team, get_team, get_role_def
from .state import GameState, Phase

class VictoryType:
VILLAGE = "village_win"
WEREWOLF = "werewolf_win"
FOX = "fox_win"
DRAW = "draw"

@dataclass
class VictoryResult:
is_game_over: bool
winner: Optional[str]
reason: str
player_results: dict[str, bool]

class VictoryChecker:
def __init__(self, state: GameState):
self.state = state

```
def check(self, is_draw: bool = False) -> VictoryResult:
    if is_draw:
        return self._make_result(VictoryType.DRAW, "投票が決着しませんでした（引き分け）")

    alive = self.state.get_alive_players()
    alive_wolves = [p for p in alive if p.role == RoleName.WEREWOLF]
    alive_fox = [p for p in alive if p.role == RoleName.FOX]
    alive_non_wolves = [p for p in alive if p.role != RoleName.WEREWOLF]

    if len(alive_wolves) == 0:
        if alive_fox:
            return self._make_result(VictoryType.FOX,
                "人狼は全滅しましたが、妖狐が生存しています。妖狐の勝利です！")
        return self._make_result(VictoryType.VILLAGE,
            "全ての人狼を退治しました。村人陣営の勝利です！")

    if len(alive_wolves) >= len(alive_non_wolves):
        if alive_fox:
            return self._make_result(VictoryType.FOX,
                "人狼が村を支配しようとしましたが、妖狐が生存しています。妖狐の勝利です！")
        return self._make_result(VictoryType.WEREWOLF,
            "人狼が村を支配しました。人狼陣営の勝利です！")

    return VictoryResult(is_game_over=False, winner=None, reason="", player_results={})

def _make_result(self, winner: str, reason: str) -> VictoryResult:
    player_results = self._calc_player_results(winner)
    self.state.winner = winner
    self.state.victory_reason = reason
    self.state.set_phase(Phase.GAME_OVER)
    return VictoryResult(is_game_over=True, winner=winner, reason=reason, player_results=player_results)

def _calc_player_results(self, winner: str) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for pid, player in self.state.players.items():
        if winner == VictoryType.DRAW:
            results[pid] = False
        elif winner == VictoryType.FOX:
            results[pid] = (player.role == RoleName.FOX)
        elif winner == VictoryType.VILLAGE:
            results[pid] = (get_team(player.role) == Team.VILLAGE)
        elif winner == VictoryType.WEREWOLF:
            results[pid] = (get_team(player.role) == Team.WEREWOLF)
        else:
            results[pid] = False
    return results
```
