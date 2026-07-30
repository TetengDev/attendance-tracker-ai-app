from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime


class Hello(BaseModel):
    device_token_jwt: str
    app_version: str
    camera_label: Optional[str] = None


class Heartbeat(BaseModel):
    fps: float
    queue_depth: int
    error_count: int
    clock_skew_ms: int


class FrameItem(BaseModel):
    jpeg_b64: str
    bbox: List[int]
    monotonic_offset_ms: int


class FrameBurst(BaseModel):
    idempotency_key: str
    burst_seq: int
    frames: List[FrameItem]
    gate_metrics: Optional[dict] = None


class Ready(BaseModel):
    gallery_version: int
    settings_version: int


class Result(BaseModel):
    status: str
    person: Optional[dict] = None
    direction: Optional[str] = None
    occurred_at: Optional[datetime] = None
    record_status: Optional[str] = None
    committed: bool = Field(default=False)
