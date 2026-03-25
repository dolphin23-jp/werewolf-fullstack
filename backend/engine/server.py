# server.py — FastAPI REST + WebSocket ConnectionManager（エンジン単体版）

from __future__ import annotations
import json
import asyncio
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .game import GameController, GameEvent

class CreateGameRequest(BaseModel):
player_name: str
seed: Optional[int] = None

class NightActionRequest(BaseModel):
actor_id: str
action_type: str
target_id: str

class ChatRequest(BaseModel):
sender_id: str
content: str
channel: str = "public"

class VoteRequest(BaseModel):
voter_id: str
target_id: str

class CORequest(BaseModel):
player_id: str
claimed_role: str

class ConnectionManager:
def __init__(self):
self.connections: dict[str, WebSocket] = {}

```
async def connect(self, player_id: str, websocket: WebSocket) -> None:
    await websocket.accept()
    self.connections[player_id] = websocket

def disconnect(self, player_id: str) -> None:
    self.connections.pop(player_id, None)

async def broadcast(self, data: dict) -> None:
    disconnected = []
    for pid, ws in self.connections.items():
        try:
            await ws.send_json(data)
        except Exception:
            disconnected.append(pid)
    for pid in disconnected:
        self.disconnect(pid)

async def send_to_group(self, player_ids: list[str], data: dict) -> None:
    for pid in player_ids:
        ws = self.connections.get(pid)
        if ws:
            try:
                await ws.send_json(data)
            except Exception:
                self.disconnect(pid)
```

app = FastAPI(title="AI人狼ゲーム（エンジン版）")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
allow_methods=["*"], allow_headers=["*"])

game_controller: Optional[GameController] = None
ws_manager = ConnectionManager()

async def dispatch_event(event: GameEvent) -> None:
data = {"type": event.event_type, "data": event.data, "timestamp": event.timestamp}
if event.recipients is None:
await ws_manager.broadcast(data)
else:
await ws_manager.send_to_group(event.recipients, data)

@app.post("/api/game/create")
async def create_game(req: CreateGameRequest):
global game_controller
game_controller = GameController(seed=req.seed)
def on_event(event): asyncio.ensure_future(dispatch_event(event))
game_controller.add_event_listener(on_event)
return game_controller.create_game(req.player_name)

@app.post("/api/game/start")
async def start_game():
if not game_controller: return {"error": "ゲームが作成されていません"}
return game_controller.start_game()

@app.get("/api/game/state")
async def get_game_state():
if not game_controller: return {"error": "ゲームが作成されていません"}
return game_controller.get_game_state()

@app.get("/api/game/view/{player_id}")
async def get_player_view(player_id: str):
if not game_controller: return {"error": "ゲームが作成されていません"}
return game_controller.get_player_view(player_id)

@app.post("/api/game/night-action")
async def submit_night_action(req: NightActionRequest):
if not game_controller: return {"error": "ゲームが作成されていません"}
return game_controller.submit_night_action(req.actor_id, req.action_type, req.target_id)

@app.post("/api/game/resolve-night")
async def resolve_night():
if not game_controller: return {"error": "ゲームが作成されていません"}
return game_controller.resolve_night()

@app.post("/api/game/start-discussion")
async def start_discussion():
if not game_controller: return {"error": "ゲームが作成されていません"}
return game_controller.start_discussion()

@app.post("/api/game/chat")
async def chat(req: ChatRequest):
if not game_controller: return {"error": "ゲームが作成されていません"}
return game_controller.chat(req.sender_id, req.content, req.channel)

@app.post("/api/game/end-discussion")
async def end_discussion():
if not game_controller: return {"error": "ゲームが作成されていません"}
return game_controller.end_discussion()

@app.post("/api/game/vote")
async def vote(req: VoteRequest):
if not game_controller: return {"error": "ゲームが作成されていません"}
return game_controller.vote(req.voter_id, req.target_id)

@app.post("/api/game/resolve-votes")
async def resolve_votes():
if not game_controller: return {"error": "ゲームが作成されていません"}
return game_controller.resolve_votes()

@app.post("/api/game/start-night")
async def start_night():
if not game_controller: return {"error": "ゲームが作成されていません"}
return game_controller.start_night()

@app.post("/api/game/co")
async def co(req: CORequest):
if not game_controller: return {"error": "ゲームが作成されていません"}
return game_controller.co(req.player_id, req.claimed_role)

@app.websocket("/ws/{player_id}")
async def websocket_endpoint(websocket: WebSocket, player_id: str):
await ws_manager.connect(player_id, websocket)
try:
while True:
await websocket.receive_text()
except WebSocketDisconnect:
ws_manager.disconnect(player_id)

@app.get("/api/health")
async def health():
return {"status": "ok"}
