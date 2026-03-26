# server_ai.py — AI統合FastAPIサーバー

from __future__ import annotations
import asyncio
import os
from typing import Optional
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from backend.engine.game import GameController, GameEvent
from backend.engine.state import Phase
from backend.engine.roles import RoleName
from .ai_player import ClaudeClient
from .coordinator import AICoordinator


class CreateGameRequest(BaseModel):
    player_name: str
    seed: Optional[int] = None


class ChatRequest(BaseModel):
    content: str


class NightActionRequest(BaseModel):
    action_type: str
    target_id: str


class VoteRequest(BaseModel):
    target_id: str


class CORequest(BaseModel):
    claimed_role: str


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
game_controller: Optional[GameController] = None
ai_coordinator: Optional[AICoordinator] = None
human_player_id: Optional[str] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="AI人狼ゲーム", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


async def dispatch_event(event: GameEvent):
    data = {"type": event.event_type, "data": event.data, "timestamp": event.timestamp}
    if event.recipients is None:
        await ws_manager.broadcast(data)
    else:
        await ws_manager.send_to_group(event.recipients, data)


async def on_ai_typing(pid: str, typing: bool):
    name = game_controller.state.players[pid].name if game_controller else ""
    await ws_manager.broadcast({"type": "typing_start" if typing else "typing_stop",
                                "data": {"player_id": pid, "player_name": name}})


async def on_ai_message(msg_data: dict):
    await ws_manager.broadcast({"type": "chat_message", "data": msg_data})


@app.post("/api/game/create")
async def create_game(req: CreateGameRequest):
    global game_controller, ai_coordinator, human_player_id
    game_controller = GameController(seed=req.seed)
    def on_event(e): asyncio.ensure_future(dispatch_event(e))
    game_controller.add_event_listener(on_event)
    result = game_controller.create_game(req.player_name)
    human_player_id = result["human_player_id"]
    ai_coordinator = AICoordinator(game_controller, ClaudeClient(), seed=req.seed)
    ai_coordinator.on_typing = on_ai_typing
    ai_coordinator.on_message = on_ai_message
    ai_coordinator.initialize()
    return {**result, "human_role": game_controller.get_player_view(human_player_id)["my_info"]}


@app.post("/api/game/start")
async def start_game():
    if not game_controller: return {"error": "ゲームが作成されていません"}
    result = game_controller.start_game()
    if ai_coordinator: asyncio.ensure_future(_run_day0_night())
    return result


async def _run_day0_night():
    await asyncio.sleep(1)
    if ai_coordinator:
        await ai_coordinator.execute_night_phase()
        resolve_result = game_controller.resolve_night()
        if resolve_result.get("status") == "resolved":
            await asyncio.sleep(1)
            game_controller.start_discussion()
            if ai_coordinator:
                await ai_coordinator.handle_ai_co()


@app.get("/api/game/state")
async def get_game_state():
    if not game_controller: return {"error": "ゲームが作成されていません"}
    return game_controller.get_game_state()


@app.get("/api/game/view")
async def get_player_view():
    if not game_controller or not human_player_id: return {"error": "ゲームが作成されていません"}
    return game_controller.get_player_view(human_player_id)


@app.post("/api/game/chat")
async def chat(req: ChatRequest):
    if not game_controller or not human_player_id: return {"error": "ゲームが作成されていません"}
    result = game_controller.chat(human_player_id, req.content)
    if "error" not in result and ai_coordinator:
        asyncio.ensure_future(ai_coordinator.run_discussion_round())
    return result


@app.post("/api/game/end-discussion")
async def end_discussion():
    if not game_controller: return {"error": "ゲームが作成されていません"}
    return game_controller.end_discussion()


@app.post("/api/game/vote")
async def vote(req: VoteRequest):
    if not game_controller or not human_player_id: return {"error": "ゲームが作成されていません"}
    vote_result = game_controller.vote(human_player_id, req.target_id)
    if "error" in vote_result: return vote_result
    if ai_coordinator:
        await ai_coordinator.generate_all_votes()
    resolve_result = game_controller.resolve_votes()
    if resolve_result.get("status") == "executed" and ai_coordinator:
        asyncio.ensure_future(ai_coordinator.generate_day_summary(game_controller.state.day))
    return resolve_result


@app.post("/api/game/start-night")
async def start_night():
    if not game_controller: return {"error": "ゲームが作成されていません"}
    return game_controller.start_night()


@app.post("/api/game/night-action")
async def night_action(req: NightActionRequest):
    if not game_controller or not human_player_id: return {"error": "ゲームが作成されていません"}
    return game_controller.submit_night_action(human_player_id, req.action_type, req.target_id)


@app.post("/api/game/resolve-night")
async def resolve_night():
    if not game_controller: return {"error": "ゲームが作成されていません"}
    if ai_coordinator:
        await ai_coordinator.execute_night_phase()
    result = game_controller.resolve_night()
    if result.get("status") == "resolved":
        await asyncio.sleep(0.5)
        game_controller.start_discussion()
        if ai_coordinator:
            await ai_coordinator.handle_ai_co()
    return result


@app.post("/api/game/co")
async def co(req: CORequest):
    if not game_controller or not human_player_id: return {"error": "ゲームが作成されていません"}
    return game_controller.co(human_player_id, req.claimed_role)


@app.post("/api/game/wolf-chat")
async def wolf_chat(req: ChatRequest):
    if not game_controller or not human_player_id: return {"error": "ゲームが作成されていません"}
    return game_controller.chat(human_player_id, req.content, channel="wolf")


@app.post("/api/game/freemason-chat")
async def freemason_chat(req: ChatRequest):
    if not game_controller or not human_player_id: return {"error": "ゲームが作成されていません"}
    return game_controller.chat(human_player_id, req.content, channel="freemason")


@app.websocket("/ws/{player_id}")
async def websocket_endpoint(ws: WebSocket, player_id: str):
    await ws_manager.connect(player_id, ws)
    try:
        while True:
            data = await ws.receive_text()
            if data == "ping": await ws.send_text("pong")
    except WebSocketDisconnect:
        ws_manager.disconnect(player_id)


@app.get("/api/health")
async def health():
    return {"status": "ok", "mock_mode": not os.environ.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-")}


# ── 静的ファイル配信 ──

from fastapi.responses import FileResponse, HTMLResponse

# フロントエンドディレクトリを探す
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
        # MIME types
        content_type = "text/plain"
        if filename.endswith(".jsx") or filename.endswith(".js"):
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
