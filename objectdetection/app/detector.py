# app/detector.py
import asyncio
import cv2
from ultralytics import YOLO
import time

class Detector:
    def __init__(self, queue: asyncio.Queue, device=0, model_name="yolov8n.pt", imgsz=640, conf=0.25):
        self.queue = queue
        self.device_index = device
        self.model_name = model_name
        self.imgsz = imgsz
        self.conf = conf
        self._stop = False
        self.model = YOLO(self.model_name)

    async def start(self):
        """Starts the detection loop in an async-friendly way."""
        # Run the blocking loop in a thread so it doesn't block the event loop
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, self._blocking_loop)

    def stop(self):
        self._stop = True

    def _blocking_loop(self):
        cap = cv2.VideoCapture(self.device_index, cv2.CAP_DSHOW)
        if not cap.isOpened():
            print("Detector: cannot open camera")
            return

        while not self._stop:
            ret, frame = cap.read()
            if not ret:
                time.sleep(0.05)
                continue

            # Run inference (blocking)
            results = self.model(frame, imgsz=self.imgsz, conf=self.conf, verbose=False)
            r = results[0]

            # Extract detections
            detections = []
            if r.boxes is not None:
                for b in r.boxes:
                    x1, y1, x2, y2 = b.xyxy[0].tolist()
                    cls_id = int(b.cls[0].item())
                    conf = float(b.conf[0].item())
                    name = r.names.get(cls_id, str(cls_id))
                    detections.append({
                        "object_name": name,
                        "confidence": round(conf, 4),
                        "bbox": {"x1": int(x1), "y1": int(y1), "x2": int(x2), "y2": int(y2)}
                    })

            # Put detections into the asyncio queue for the FastAPI app to consume
            if detections:
                # note: use asyncio.run to schedule putting into queue
                try:
                    asyncio.run(self.queue.put(detections))
                except RuntimeError:
                    # If event loop is already running (common), use loop.call_soon_threadsafe
                    loop = asyncio.get_event_loop()
                    loop.call_soon_threadsafe(asyncio.create_task, self.queue.put(detections))

        cap.release()
