import random
import string
from fastapi import FastAPI, WebSocket, WebSocketDisconnect

app = FastAPI()

rooms = {}


def generate_room_code():
    while True:
        code = "".join(
            random.choices(string.ascii_uppercase + string.digits, k=5)
        )
        if code not in rooms:
            return code


@app.get("/")
def home():
    return {"status": "The Bait Game server is running"}


@app.post("/create_room")
def create_room(data: dict):
    name = data.get("name", "").strip()

    if not name:
        return {"ok": False, "error": "name_required"}

    code = generate_room_code()

    rooms[code] = {
        "players": [name],
        "connections": [],
        "game_started": False,
    }

    return {
        "ok": True,
        "room_code": code,
        "host": name,
    }


@app.post("/join_room")
def join_room(data: dict):
    code = data.get("room_code", "").upper().strip()
    name = data.get("name", "").strip()

    if not name:
        return {"ok": False, "error": "name_required"}

    if code not in rooms:
        return {"ok": False, "error": "room_not_found"}

    room = rooms[code]

    if len(room["players"]) >= 2:
        return {"ok": False, "error": "room_full"}

    room["players"].append(name)

    return {
        "ok": True,
        "room_code": code,
        "host": room["players"][0],
        "players": room["players"],
    }


@app.websocket("/ws/{room_code}")
async def websocket_endpoint(websocket: WebSocket, room_code: str):
    await websocket.accept()

    room_code = room_code.upper()

    if room_code not in rooms:
        await websocket.send_json({
            "type": "error",
            "message": "الغرفة غير موجودة"
        })
        await websocket.close()
        return

    room = rooms[room_code]

    room["connections"].append(websocket)

    try:
        await websocket.send_json({
            "type": "room_state",
            "players": room["players"],
            "game_started": room["game_started"],
        })

        for connection in room["connections"]:
            if connection != websocket:
                await connection.send_json({
                    "type": "player_joined",
                    "players": room["players"],
                })

        while True:
            message = await websocket.receive_json()

            for connection in room["connections"]:
                if connection != websocket:
                    await connection.send_json(message)

    except WebSocketDisconnect:
        if websocket in room["connections"]:
            room["connections"].remove(websocket)

        for connection in room["connections"]:
            await connection.send_json({
                "type": "player_left"
            })

        if not room["connections"]:
            rooms.pop(room_code, None)
