import os
import random
import string
from typing import Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from pydantic import BaseModel

app = FastAPI()

# الغرف الموجودة في الذاكرة
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


@app.get("/")
async def home():
    return {
        "status": "online",
        "game": "The Bait Game",
        "rooms": len(rooms)
    }


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
        "player_slot": 1
    }


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

    # إبلاغ اللاعب الأول أن اللاعب الثاني دخل
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
        "game_started": True
    }


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
async def websocket_endpoint(websocket: WebSocket, room_code: str):
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

    # إرسال حالة الغرفة للاعب المتصل
    await websocket.send_json({
        "type": "room_state",
        "room_code": room_code,
        "players": room["players"],
        "game_started": room["game_started"]
    })

    # لو اللاعب الثاني اتصل، نبلغ الجميع
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

            # أي حدث من اللعبة يتم إرساله للاعب الآخر
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

        # إبلاغ اللاعب الآخر بخروج اللاعب
        await broadcast(
            room_code,
            {
                "type": "player_left"
            }
        )

        # نحذف الغرفة فقط لما ميبقاش فيها أي اتصال
        if len(room["connections"]) == 0:
            del rooms[room_code]


# مهم لخدمات الاستضافة التي تحدد PORT تلقائياً
if __name__ == "__main__":
    import uvicorn

    port = int(os.environ.get("PORT", 8000))

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port
    )
