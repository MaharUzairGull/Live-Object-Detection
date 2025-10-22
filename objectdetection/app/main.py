# app/main.py
import asyncio
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from db import SessionLocal, engine, Base
import models 
import schemas
from ws_manager import ConnectionManager
from detector import Detector
import uvicorn

# create DB
Base.metadata.create_all(bind=engine)

app = FastAPI(title="FastAPI YOLO Realtime")
manager = ConnectionManager()

# shared asyncio queue used by detector -> main loop
app.state.queue = asyncio.Queue()
app.state.detector = None
app.state.detector_task = None

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.on_event("startup")
async def startup_event():
    # Start detector in background
    detector = Detector(queue=app.state.queue)
    app.state.detector = detector
    # background task to run detector.start()
    app.state.detector_task = asyncio.create_task(detector.start())
    # background consumer task: reads queue and saves + broadcasts
    app.state.consumer_task = asyncio.create_task(queue_consumer())
    print("Startup complete: detector started")

@app.on_event("shutdown")
async def shutdown_event():
    if app.state.detector:
        app.state.detector.stop()
    if app.state.detector_task:
        app.state.detector_task.cancel()
    if app.state.consumer_task:
        app.state.consumer_task.cancel()


async def queue_consumer():
    from datetime import datetime
    while True:
        detections = await app.state.queue.get()
        # Save each detection to DB and broadcast
        db = SessionLocal()
        saved = []
        try:
            for d in detections:
                det_model = models.Detection(
                    object_name=d["object_name"],
                    confidence=d["confidence"],
                    x1=d["bbox"]["x1"],
                    y1=d["bbox"]["y1"],
                    x2=d["bbox"]["x2"],
                    y2=d["bbox"]["y2"]
                )
                db.add(det_model)
                db.commit()
                db.refresh(det_model)
                saved.append({
                    "id": det_model.id,
                    "object_name": det_model.object_name,
                    "confidence": det_model.confidence,
                    "bbox": {"x1": det_model.x1, "y1": det_model.y1, "x2": det_model.x2, "y2": det_model.y2},
                    "timestamp": det_model.timestamp.isoformat()
                })
        finally:
            db.close()

        # broadcast saved detections
        await manager.broadcast_json({"type": "detections", "data": saved})

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            # Keep connection alive; we don't expect client messages
            msg = await websocket.receive_text()
            # simple echo or ignore
            await websocket.send_text(f"ack: {msg}")
    except WebSocketDisconnect:
        manager.disconnect(websocket)

@app.get("/detections/")
def list_detections(limit: int = 50, db: Session = Depends(get_db)):
    items = db.query(models.Detection).order_by(models.Detection.id.desc()).limit(limit).all()
    return [
        {
            "id": i.id,
            "object_name": i.object_name,
            "confidence": i.confidence,
            "bbox": {"x1": i.x1, "y1": i.y1, "x2": i.x2, "y2": i.y2},
            "timestamp": i.timestamp.isoformat()
        }
        for i in items
    ]

if __name__ == "__main__":
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
