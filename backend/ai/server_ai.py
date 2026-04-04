# server_ai.py — AI統合FastAPIサーバー
#
# 変更点:
# - グローバル変数3つ → GameSession に集約
# - ensure_future → _safe_background で例外ハンドリング

from __future__ import annotations
import asyncio
import os
import traceback
from typing import Optional
from dataclasses import dataclass
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.engine.game import GameController, GameEvent
from backend.engine.state import Phase
from backend.engine.roles import RoleName
from .ai_player import ClaudeClient
from .coordinator import AICoordinator


# ─────────────────────────────────────────────
#  リクエストモデル
# ─────────────────────────────────────────────

class CreateGameRequest(BaseModel):
    player_name: str
    seed: Optional[int] = None

class ChatRequest(BaseModel):
    content: str
    channel: str = "public"

class NightActionRequest(BaseModel):
    action_type: str
    target_id: str

class VoteRequest(BaseModel):
    target_id: str

class CORequest(BaseModel):
    claimed_role: str


# ─────────────────────────────────────────────
#  GameSession — ゲーム状態の一元管理
# ─────────────────────────────────────────────

@dataclass
class GameSession:
    controller: GameController
    coordinator: AICoordinator
    human_id: str


_session: Optional[GameSession] = None


def _get_session() -> Optional[GameSession]:
    return _session


# ─────────────────────────────────────────────
#  WebSocket接続管理
# ─────────────────────────────────────────────

class ConnectionManager:
    def __init__(self):
        self.connections: dict[str, WebSocket] = {}

    async def connect(self, player_id: str, ws: WebSocket):
        await ws.accept()
        self.connections[player_id] = ws

    def disconnect(self, player_id: str):
        self.connections.pop(player_id, None)

    async def broadcast(self, data: dict):
        bad = []
        for pid, ws in self.connections.items():
            try:
                await ws.send_json(data)
            except Exception:
                bad.append(pid)
        for pid in bad:
            self.disconnect(pid)

    async def send_to_group(self, pids: list[str], data: dict):
        for pid in pids:
            ws = self.connections.get(pid)
            if ws:
                try:
                    await ws.send_json(data)
                except Exception:
                    self.disconnect(pid)


ws_manager = ConnectionManager()


# ─────────────────────────────────────────────
#  安全なバックグラウンドタスク
# ─────────────────────────────────────────────

def _safe_background(coro):
    """fire-and-forget だが例外をログに出す"""
    async def _wrapper():
        try:
            await coro
        except Exception as e:
            print(f"[Background error] {e}")
            traceback.print_exc()
    asyncio.ensure_future(_wrapper())


# ─────────────────────────────────────────────
#  イベント配信
# ─────────────────────────────────────────────

async def dispatch_event(event: GameEvent):
    data = {"type": event.event_type, "data": event.data, "timestamp": event.timestamp}
    if event.recipients is None:
        await ws_manager.broadcast(data)
    else:
        await ws_manager.send_to_group(event.recipients, data)


async def on_ai_typing(pid: str, typing: bool):
    s = _get_session()
    name = s.controller.state.players[pid].name if s else ""
    await ws_manager.broadcast({
        "type": "typing_start" if typing else "typing_stop",
        "data": {"player_id": pid, "player_name": name},
    })


async def on_ai_message(msg_data: dict):
    await ws_manager.broadcast({"type": "chat_message", "data": msg_data})


# ─────────────────────────────────────────────
#  FastAPI アプリケーション
# ─────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="AI人狼ゲーム", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


@app.post("/api/game/create")
async def create_game(req: CreateGameRequest):
    global _session
    gc = GameController(seed=req.seed)

    def on_event(e):
        asyncio.ensure_future(dispatch_event(e))
    gc.add_event_listener(on_event)

    result = gc.create_game(req.player_name)
    human_id = result["human_player_id"]

    client = ClaudeClient.create()
    coord = AICoordinator(gc, client, seed=req.seed)
    coord.on_typing = on_ai_typing
    coord.on_message = on_ai_message
    coord.initialize()

    _session = GameSession(controller=gc, coordinator=coord, human_id=human_id)
    return {**result, "human_role": gc.get_player_view(human_id)["my_info"]}


@app.post("/api/game/start")
async def start_game():
    s = _get_session()
    if not s:
        return {"error": "ゲームが作成されていません"}
    result = s.controller.start_game()
    _safe_background(_run_day0_night())
    return result


async def _run_day0_night():
    s = _get_session()
    if not s:
        return
    await asyncio.sleep(1)
    await s.coordinator.execute_night_phase()
    resolve_result = s.controller.resolve_night()
    if resolve_result.get("status") == "resolved":
        await asyncio.sleep(1)
        s.controller.start_discussion()
        # handle_ai_co() は廃止: COは議論発言の中でのみ公開される


@app.get("/api/game/state")
async def get_game_state():
    s = _get_session()
    if not s:
        return {"error": "ゲームが作成されていません"}
    return s.controller.get_game_state()


@app.get("/api/game/view")
async def get_player_view():
    s = _get_session()
    if not s:
        return {"error": "ゲームが作成されていません"}
    return s.controller.get_player_view(s.human_id)


@app.post("/api/game/chat")
async def chat(req: ChatRequest):
    s = _get_session()
    if not s:
        return {"error": "ゲームが作成されていません"}
    result = s.controller.chat(s.human_id, req.content, req.channel)
    if "error" not in result and req.channel == "public":
        _safe_background(s.coordinator.run_discussion_round())
    return result


@app.post("/api/game/end-discussion")
async def end_discussion():
    s = _get_session()
    if not s:
        return {"error": "ゲームが作成されていません"}
    return s.controller.end_discussion()


@app.post("/api/game/vote")
async def vote(req: VoteRequest):
    s = _get_session()
    if not s:
        return {"error": "ゲームが作成されていません"}
    vote_result = s.controller.vote(s.human_id, req.target_id)
    if "error" in vote_result:
        return vote_result
    # AI全員の投票を並列実行
    await s.coordinator.generate_all_votes()
    resolve_result = s.controller.resolve_votes()
    if resolve_result.get("status") == "executed":
        _safe_background(s.coordinator.generate_day_summary(s.controller.state.day))
    return resolve_result


@app.post("/api/game/start-night")
async def start_night():
    s = _get_session()
    if not s:
        return {"error": "ゲームが作成されていません"}
    return s.controller.start_night()


@app.post("/api/game/night-action")
async def night_action(req: NightActionRequest):
    s = _get_session()
    if not s:
        return {"error": "ゲームが作成されていません"}
    return s.controller.submit_night_action(s.human_id, req.action_type, req.target_id)


@app.post("/api/game/resolve-night")
async def resolve_night():
    s = _get_session()
    if not s:
        return {"error": "ゲームが作成されていません"}
    await s.coordinator.execute_night_phase()
    result = s.controller.resolve_night()
    if result.get("status") == "resolved":
        await asyncio.sleep(0.5)
        s.controller.start_discussion()
    return result


@app.post("/api/game/co")
async def co(req: CORequest):
    s = _get_session()
    if not s:
        return {"error": "ゲームが作成されていません"}
    return s.controller.co(s.human_id, req.claimed_role)


@app.post("/api/game/wolf-chat")
async def wolf_chat(req: ChatRequest):
    s = _get_session()
    if not s:
        return {"error": "ゲームが作成されていません"}
    return s.controller.chat(s.human_id, req.content, channel="wolf")


@app.post("/api/game/freemason-chat")
async def freemason_chat(req: ChatRequest):
    s = _get_session()
    if not s:
        return {"error": "ゲームが作成されていません"}
    return s.controller.chat(s.human_id, req.content, channel="freemason")


@app.websocket("/ws/{player_id}")
async def websocket_endpoint(ws: WebSocket, player_id: str):
    await ws_manager.connect(player_id, ws)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping":
                await ws.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(player_id)


@app.get("/api/debug")
async def debug_full_state():
    """デバッグ用: 全プレイヤーの役職・夜行動・投票履歴・全チャットを返す"""
    s = _get_session()
    if not s:
        return {"error": "ゲームが作成されていません"}
    state = s.controller.state
    return {
        "game_id": state.game_id,
        "phase": state.phase.value,
        "day": state.day,
        "players": {
            pid: {
                "name": p.name,
                "role": p.role.value,
                "is_alive": p.is_alive,
                "is_human": p.is_human,
                "divine_results": [
                    {"day": r.day, "target": state.players[r.target_id].name, "result": r.result}
                    for r in p.divine_results
                ],
                "medium_results": [
                    {"day": r.day, "target": state.players[r.target_id].name, "result": r.result}
                    for r in p.medium_results
                ],
            }
            for pid, p in state.players.items()
        },
        "co_list": [
            {
                "player_id": co.player_id,
                "name": state.players[co.player_id].name,
                "claimed_role": co.claimed_role.value,
                "day": co.day,
            }
            for co in state.co_list
        ],
        "vote_history": [
            {
                "day": v.day, "round": v.round,
                "voter": state.players[v.voter_id].name,
                "target": state.players[v.target_id].name,
            }
            for v in state.vote_history
        ],
        "death_records": [
            {
                "name": state.players[d.player_id].name,
                "day": d.day,
                "cause": d.cause.value,
                "role": d.role.value,
            }
            for d in state.death_records
        ],
        "current_night_actions": [
            {
                "actor": state.players[a.actor_id].name,
                "action": a.action_type,
                "target": state.players[a.target_id].name,
            }
            for a in state.current_night_actions
        ],
        "chat_log_all": [
            {
                "sender_name": m.sender_name,
                "content": m.content,
                "channel": m.channel,
                "day": m.day,
                "phase": m.phase,
            }
            for m in state.chat_log
        ],
    }


@app.get("/api/health")
async def health():
    return {
        "status": "ok",
        "mock_mode": not os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-"),
    }


# ─────────────────────────────────────────────
#  静的ファイル配信
# ─────────────────────────────────────────────

from fastapi.responses import FileResponse, HTMLResponse

_frontend_dir = None
for candidate in [
    os.path.join(os.path.dirname(__file__), '..', '..', 'frontend'),
    os.path.join(os.getcwd(), 'frontend'),
    '/home/claude/werewolf-game/frontend',
]:
    if os.path.isdir(candidate):
        _frontend_dir = os.path.abspath(candidate)
        break


@app.get("/static/{filename:path}")
async def serve_static(filename: str):
    if not _frontend_dir:
        return HTMLResponse("Frontend directory not found", status_code=404)
    filepath = os.path.join(_frontend_dir, filename)
    if os.path.isfile(filepath):
        content_type = "text/plain"
        if filename.endswith((".jsx", ".js")):
            content_type = "application/javascript"
        elif filename.endswith(".css"):
            content_type = "text/css"
        elif filename.endswith(".html"):
            content_type = "text/html"
        return FileResponse(filepath, media_type=content_type)
    return HTMLResponse("File not found", status_code=404)


@app.get("/")
async def serve_index():
    if not _frontend_dir:
        return HTMLResponse("<h1>Frontend not found</h1>", status_code=404)
    index_path = os.path.join(_frontend_dir, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path, media_type="text/html")
    return HTMLResponse("<h1>index.html not found</h1>", status_code=404)
