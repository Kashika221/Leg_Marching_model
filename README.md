# Seated Leg March Tracker

An AI-powered exercise tracker that uses your webcam and real-time pose detection to count seated leg march repetitions. Built with FastAPI, MediaPipe, and MongoDB — with a WebSocket-based frontend for low-latency live feedback.

---

## How It Works

The browser captures your webcam feed and streams JPEG frames over a WebSocket connection to the backend. MediaPipe's pose landmarker detects your body landmarks on each frame and applies logic to determine when a full rep has been completed (left leg raised, then right leg raised, or vice versa). Results — rep count, elapsed time, coaching feedback, and skeleton landmarks — are sent back instantly over the same WebSocket and rendered on a canvas overlay in the browser.

Session data is persisted in MongoDB so your all-time rep count, total duration, and session history are saved across visits.

---

## Hosted API

The backend is deployed and publicly available at:

```
https://leg-marching-model.onrender.com
```

You can point the frontend at this URL instead of running the server locally. In `frontend/index.html`, update the config at the top of the script:

```js
const HTTP_API = "https://leg-marching-model.onrender.com";
const WS_API   = "wss://leg-marching-model.onrender.com";
```

> **Note:** Render spins down free-tier services after inactivity. The first request may take 30–60 seconds to wake the server. Subsequent requests will be fast.

---

## Features

- **Real-time pose detection** using MediaPipe Pose Landmarker (heavy model)
- **WebSocket streaming** — frames flow continuously with no per-request HTTP overhead; the client matches the server's processing speed automatically via backpressure
- **Skeleton overlay** drawn on a mirrored canvas with highlighted hip and knee joints
- **Coaching feedback** — warns if you're leaning sideways, raising both legs at once, or not marching
- **Per-user progress tracking** — total reps, total session time, full session history
- **Leaderboard endpoint** — top 10 users by total reps
- **Live RTT badge** — shows WebSocket round-trip latency in the UI

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python, FastAPI, Uvicorn |
| Pose Detection | MediaPipe Pose Landmarker |
| Database | MongoDB (via PyMongo) |
| Frontend | Vanilla HTML/CSS/JS, WebSocket API |
| Image Processing | OpenCV, NumPy |

---

## Prerequisites

- Python 3.9+
- MongoDB running locally on port `27017` (or a remote URI via `.env`)
- A webcam
- The MediaPipe heavy pose model file (see Setup)

---

## Setup

**1. Clone the repo and set up the virtual environment**

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**2. Download the MediaPipe pose model**

```bash
wget https://storage.googleapis.com/mediapipe-models/pose_landmarker/pose_landmarker_heavy/float16/latest/pose_landmarker_heavy.task
```

Place `pose_landmarker_heavy.task` inside the `backend/` folder alongside `app.py`.

**3. Configure environment variables**

Edit `backend/.env`:

```
MONGO_URI=mongodb+srv://user:pass@your-cluster.mongodb.net/
```

If no `.env` is present, it defaults to `mongodb://localhost:27017/`.

**4. Start the server**

```bash
cd backend
source venv/bin/activate        # if not already active
python app.py
```

The API will be available at `http://localhost:8000`.

**5. Open the frontend**

Open `frontend/index.html` directly in your browser. No build step required.

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/start_session/{user_id}` | Creates a new session and initialises the pose landmarker |
| `WebSocket` | `/ws/{user_id}` | Streams JPEG frames (binary) in, receives JSON results out |
| `POST` | `/stop_session/{user_id}` | Ends the session and saves data to MongoDB |
| `GET` | `/progress/{user_id}` | Returns all-time stats and session history for a user |
| `GET` | `/leaderboard` | Returns the top 10 users by total reps |
| `GET` | `/health` | Health check |

### WebSocket Protocol

The client sends raw JPEG bytes as binary messages. The server responds with a JSON text message after each frame:

```json
{
  "reps": 12,
  "feedback": "Left leg raised! Now the right.",
  "elapsed": 34.2,
  "landmarks": [
    { "x": 0.51, "y": 0.38, "z": -0.12, "v": 0.99 },
    ...
  ]
}
```

`landmarks` contains 33 points in MediaPipe's standard pose topology, with normalised `x`/`y` coordinates (0–1), `z` depth, and `v` visibility score. The frontend uses these to draw the skeleton overlay.

---

## Rep Counting Logic

A rep is counted when **both** legs have been raised at least once since the last rep. The backend tracks `left_up` and `right_up` boolean flags per session:

- A leg is considered "raised" when its knee y-coordinate is higher than its hip y-coordinate by more than a `0.05` normalised threshold
- If both legs are raised simultaneously, the user is prompted to alternate
- If the user's nose drifts more than `0.12` from the horizontal midpoint of their hips, a posture warning is shown

---

## Project Structure

```
LEG_MARCHING/
├── backend/
│   ├── venv/                      # Python virtual environment
│   ├── .env                       # MongoDB URI and other secrets
│   ├── .gitignore
│   ├── app.py                     # FastAPI backend with WebSocket endpoint
│   ├── pose_landmarker_heavy.task # MediaPipe model (downloaded separately)
│   └── requirements.txt           # Python dependencies
└── frontend/
    └── index.html                 # Single-file frontend (no build step)
```

---

## Troubleshooting

**WebSocket connection failed**
- Confirm the server is running (`python app.py`) and listening on port `8000` (or reachable at https://leg-marching-model.onrender.com if using the hosted API)
- Make sure `websockets` is installed: `pip install websockets`
- Check that nothing is blocking port `8000` (firewall, another process)

**"No active session" error from server**
- The WebSocket endpoint requires `/start_session/{user_id}` to have been called first via HTTP POST — the frontend does this automatically when you click Start Session

**Pose not detected**
- Ensure you are well-lit and your full upper body and legs are visible to the camera
- Try sitting further back from the camera so your hips and knees are both in frame

**MongoDB connection error**
- Confirm MongoDB is running: `mongod --dbpath /your/data/path`
- Or set a valid `MONGO_URI` in your `.env` file