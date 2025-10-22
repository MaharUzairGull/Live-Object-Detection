# app/schemas.py
from pydantic import BaseModel
from datetime import datetime

class BoundingBox(BaseModel):
    x1: int
    y1: int
    x2: int
    y2: int

class DetectionIn(BaseModel):
    object_name: str
    confidence: float
    bbox: BoundingBox

class DetectionOut(DetectionIn):
    id: int
    timestamp: datetime

    class Config:
        from_attributes = True
