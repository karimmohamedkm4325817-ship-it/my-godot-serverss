import os
import random
import string
from typing import Dict

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from apinator import Apinator

app = FastAPI()

# =========================================================
# APINATOR
# =========================================================

APINATOR_APP_ID = os.environ.get(
    "APINATOR_APP_ID",
    "52d84745-14ab-4e38-9f99-8983670745f4"
)

APINATOR_KEY = os.environ.get(
    "APINATOR_KEY",
    "app_f96e96143ca0973612fc4f59ad960d22513b4e77"
)

APINATOR_SECRET = os.environ.get("APINATOR_SECRET", "")
APINATOR_CLUSTER = os.environ.get("APINATOR_CLUSTER", "eu")

apinator = None

if APINATOR_SECRET:
    apinator = Apinator(
        app_id=APINATOR_APP_ID,
        key=APINATOR_KEY,
        secret=APINATOR_SECRET,
        cluster=APINATOR_CLUSTER
    )


# =========================================================
# ROOMS
# =========================================================

rooms: Dict[str, dict] = {}


def generate_room_code(length: int = 5) -> str:
    chars = string.ascii_uppercase + string.digits

    while True:
        code = "".join(random.choice(chars) for _ in range(length))

        if code not in rooms:
            return code


class CreateRoomRequest(BaseModel):
    player_name: str = "Player 1"


class JoinRoomRequest(BaseModel):
    room_code: str
    player_name: str = "Player 2"


# =========================================================
# HOME
# =========================================================

@app.get("/")
async def home():
    return {
        "status": "online",
        "game": "The Bait Game",
        "rooms": len(rooms),
        "apinator": apinator is not None
    }


# =========================================================
# APINATOR AUTH
# =========================================================

@app.post("/realtime/auth")
async def realtime_auth(data: dict):

    socket_id = data.get("socket_id")
    channel_name = data.get("channel_name")

    if not socket_id or not channel_name:
        return {
            "success": False,
            "error": "MISSING_SOCKET_OR_CHANNEL"
        }

    if apinator is None:
        return {
            "success": False,
            "error": "APINATOR_SECRET_NOT_CONFIGURED"
        }

    # نسمح فقط بقنوات presence الخاصة بلعبتنا
    if not channel_name.startswith("presence-bait-"):
        return {
            "success": False,
            "error": "INVALID_CHANNEL"
        }

    # نستخرج كود الغرفة من:
    # presence-bait-ABCDE
    room_code = channel_name.replace("presence-bait-", "").upper()

    # لازم الغرفة تكون موجودة
    if room_code not in rooms:
        return {
            "success": False,
            "error": "ROOM_NOT_FOUND"
        }

    # اسم اللاعب القادم من الطلب إن وجد
    player_name = data.get("player_name", "Player")

    # Presence data
    channel_data = {
        "user_id": f"{room_code}-{socket_id}",
        "user_info": {
            "name": player_name
        }
    }

    auth = apinator.authenticate_channel(
        socket_id,
        channel_name,
        channel_data
    )

    return auth


# =========================================================
# CREATE ROOM
# =========================================================

@app.post("/create_room")
async def create_room(data: CreateRoomRequest):

    room_code = generate_room_code()

    rooms[room_code] = {
        "players": [
            {
                "name": data.player_name,
                "slot": 1
            }
        ],
        "connections": [],
        "game_started": False
    }

    return {
        "success": True,
        "room_code": room_code,
        "player_slot": 1,

        # اسم قناة Apinator التي سيشترك فيها اللاعب
        "channel": f"presence-bait-{room_code}"
    }


# =========================================================
# JOIN ROOM
# =========================================================

@app.post("/join_room")
async def join_room(data: JoinRoomRequest):

    room_code = data.room_code.upper().strip()

    if room_code not in rooms:
        return {
            "success": False,
            "error": "ROOM_NOT_FOUND"
        }

    room = rooms[room_code]

    if len(room["players"]) >= 2:
        return {
            "success": False,
            "error": "ROOM_FULL"
        }

    room["players"].append({
        "name": data.player_name,
        "slot": 2
    })

    room["game_started"] = True

    await broadcast(
        room_code,
        {
            "type": "player_joined",
            "player": data.player_name,
            "slot": 2
        }
    )

    return {
        "success": True,
        "room_code": room_code,
        "player_slot": 2,
        "players": room["players"],
        "game_started": True,
        "channel": f"presence-bait-{room_code}"
    }


# =========================================================
# OLD WEBSOCKET
# =========================================================

async def broadcast(room_code: str, message: dict):

    if room_code not in rooms:
        return

    dead_connections = []

    for websocket in rooms[room_code]["connections"]:

        try:
            await websocket.send_json(message)

        except Exception:
            dead_connections.append(websocket)

    for websocket in dead_connections:

        if websocket in rooms[room_code]["connections"]:
            rooms[room_code]["connections"].remove(websocket)


@app.websocket("/ws/{room_code}")
async def websocket_endpoint(
    websocket: WebSocket,
    room_code: str
):

    room_code = room_code.upper().strip()

    if room_code not in rooms:
        await websocket.close(code=4004)
        return

    room = rooms[room_code]

    if len(room["connections"]) >= 2:
        await websocket.close(code=4005)
        return

    await websocket.accept()

    room["connections"].append(websocket)

    await websocket.send_json({
        "type": "room_state",
        "room_code": room_code,
        "players": room["players"],
        "game_started": room["game_started"]
    })

    if len(room["connections"]) == 2:

        await broadcast(
            room_code,
            {
                "type": "game_start",
                "players": room["players"]
            }
        )

    try:

        while True:

            data = await websocket.receive_json()

            message_type = data.get("type")

            if message_type == "game_event":

                await broadcast(
                    room_code,
                    {
                        "type": "game_event",
                        "data": data.get("data")
                    }
                )

            elif message_type == "ping":

                await websocket.send_json({
                    "type": "pong"
                })

            elif message_type == "leave":

                break

    except WebSocketDisconnect:
        pass

    except Exception:
        pass

    finally:

        if websocket in room["connections"]:
            room["connections"].remove(websocket)

        await broadcast(
            room_code,
            {
                "type": "player_left"
            }
        )

        if len(room["connections"]) == 0:

            if room_code in rooms:
                del rooms[room_code]


# =========================================================
# START SERVER
# =========================================================

if __name__ == "__main__":

    import uvicorn

    port = int(os.environ.get("PORT", 8000))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )
