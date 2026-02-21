import cv2
import os
import mediapipe as mp
import time
import numpy as np
import json
import asyncio
from mediapipe.tasks import python
from mediapipe.tasks.python import vision
import pymongo
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from datetime import datetime
from dataclasses import dataclass, field
from typing import Dict, List

load_dotenv()

MODEL_PATH = "pose_landmarker_heavy.task"
MONGO_URI  = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
DB_NAME    = "FitnessTracker"
COLL_NAME  = "LegMarching"

try:
    client = pymongo.MongoClient(MONGO_URI, serverSelectionTimeoutMS = 3000)
    client.server_info()
    db = client[DB_NAME]
    collection = db[COLL_NAME]
    collection.create_index("user_id", unique = True)
    print("Connected to MongoDB!")
except Exception as e:
    print(f"MongoDB error: {e}")
    collection = None

@dataclass
class Session:
    user_id : str
    counter : int = 0
    left_up : bool = False
    right_up : bool = False
    feedback : str = "Sit straight on the chair"
    is_active : bool = True
    start_time : float = field(default_factory = time.time)
    landmarker : object = field(default = None, repr = False)
    frame_ts : int = 0  

sessions : Dict[str, Session] = {}

def build_landmarker():
    base = python.BaseOptions(model_asset_path = MODEL_PATH)
    opts = vision.PoseLandmarkerOptions(
        base_options = base,
        running_mode = vision.RunningMode.VIDEO,
        num_poses = 1,
        min_pose_detection_confidence = 0.5,
        min_tracking_confidence = 0.5,
    )
    return vision.PoseLandmarker.create_from_options(opts)

def update_session_from_landmarks(session : Session, landmarks):
    lm = landmarks[0]
    nose = lm[0]
    l_hip,  r_hip = lm[23], lm[24]
    l_knee, r_knee = lm[25], lm[26]

    hip_cx = (l_hip.x + r_hip.x) / 2
    if abs(nose.x - hip_cx) > 0.12:
        session.feedback = "Sit straight on the chair"
        return

    l_lift = (l_hip.y - l_knee.y) > 0.05
    r_lift = (r_hip.y - r_knee.y) > 0.05

    if l_lift and r_lift:
        session.feedback = "Raise one leg at a time"
    elif l_lift:
        session.left_up = True
        session.feedback = "Left leg raised! Now the right."
    elif r_lift:
        session.right_up = True
        session.feedback = "Right leg raised! Now the left."
    else:
        session.feedback = "March your legs!"

    if session.left_up and session.right_up:
        session.counter += 1
        session.left_up = False
        session.right_up = False
        session.feedback = f"Great rep! Keep going. ({session.counter})"

def process_jpeg_bytes(session : Session, raw : bytes) -> dict:
    arr = np.frombuffer(raw, np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        return {"error" : "Invalid image data"}

    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    mp_image = mp.Image(image_format = mp.ImageFormat.SRGB, data = rgb)

    session.frame_ts += 33  
    result = session.landmarker.detect_for_video(mp_image, session.frame_ts)

    lm_out : List[dict] = []
    if result.pose_landmarks:
        update_session_from_landmarks(session, result.pose_landmarks)
        lm_out = [
            {"x" : p.x, "y" : p.y, "z" : p.z, "v" : p.visibility}
            for p in result.pose_landmarks[0]
        ]

    return {
        "reps" : session.counter,
        "feedback" : session.feedback,
        "elapsed" : round(time.time() - session.start_time, 1),
        "landmarks" : lm_out,
    }

app = FastAPI(title = "Fitness Tracker - Seated Leg March")

app.add_middleware(
    CORSMiddleware,
    allow_origins = ["*"],
    allow_methods = ["*"],
    allow_headers = ["*"],
)

@app.post("/start_session/{user_id}")
def start_session(user_id : str):
    if user_id in sessions and sessions[user_id].is_active:
        return {"message" : "Session already running.", "user_id" : user_id}
    sessions[user_id] = Session(user_id = user_id, landmarker = build_landmarker())
    return {"message" : "Session started!", "user_id" : user_id}

@app.post("/stop_session/{user_id}")
def stop_session(user_id : str):
    if user_id not in sessions or not sessions[user_id].is_active:
        raise HTTPException(status_code = 404, detail = "No active session.")

    session = sessions[user_id]
    duration = round(time.time() - session.start_time, 2)
    reps = session.counter
    ts = datetime.now()

    try:
        session.landmarker.close()
    except Exception:
        pass

    if collection is not None:
        collection.update_one(
            {"user_id" : user_id},
            {
                "$setOnInsert" : {"created_at" : ts},
                "$inc" : {"total_reps" : reps, "total_duration" : duration},
                "$push" : {"session_history" : {"date" : ts, "reps" : reps, "duration" : duration}},
                "$set" : {"last_updated" : ts},
            },
            upsert = True,
        )

    session.is_active = False
    return {"message" : f"Saved! {reps} reps in {duration}s.", "reps" : reps, "duration" : duration}

@app.get("/progress/{user_id}")
def get_progress(user_id : str):
    if collection is None:
        raise HTTPException(status_code = 503, detail = "Database unavailable.")
    doc = collection.find_one({"user_id" : user_id}, {"_id" : 0})
    if not doc:
        raise HTTPException(status_code = 404, detail = "No progress found.")
    for key in ("created_at", "last_updated"):
        if key in doc:
            doc[key] = doc[key].isoformat()
    for s in doc.get("session_history", []):
        if "date" in s:
            s["date"] = s["date"].isoformat()
    return doc

@app.get("/leaderboard")
def leaderboard():
    if collection is None:
        raise HTTPException(status_code = 503, detail = "Database unavailable.")
    return list(
        collection.find({}, {"_id" : 0, "user_id" : 1, "total_reps" : 1, "total_duration" : 1})
        .sort("total_reps", pymongo.DESCENDING)
        .limit(10)
    )

@app.get("/health")
def health():
    return {"status" : "ok", "time" : datetime.now().isoformat()}

@app.websocket("/ws/{user_id}")
async def websocket_endpoint(websocket : WebSocket, user_id : str):
    await websocket.accept()
    print(f"[WS] {user_id} connected")

    if user_id not in sessions or not sessions[user_id].is_active:
        await websocket.send_text(json.dumps({"error" : "No active session. Call /start_session first."}))
        await websocket.close(code = 4001)
        return

    session = sessions[user_id]
    loop    = asyncio.get_event_loop()

    try:
        while True:
            raw = await websocket.receive_bytes()
            if not session.is_active:
                break

            result = await loop.run_in_executor(None, process_jpeg_bytes, session, raw)
            await websocket.send_text(json.dumps(result))

    except WebSocketDisconnect:
        print(f"[WS] {user_id} disconnected")
    except Exception as e:
        print(f"[WS] {user_id} error: {e}")
        try:
            await websocket.send_text(json.dumps({"error" : str(e)}))
        except Exception:
            pass


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host = "0.0.0.0", port = 8000)