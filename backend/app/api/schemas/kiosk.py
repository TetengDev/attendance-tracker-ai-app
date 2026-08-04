from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from backend.app.errors import ErrorCode


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ClientMessageType(str, Enum):
    HELLO = "hello"
    HEARTBEAT = "heartbeat"
    FRAME_BURST = "frame_burst"


class ServerMessageType(str, Enum):
    READY = "ready"
    DETECTED = "detected"
    CHECKING = "checking"
    RESULT = "result"
    SETTINGS_PUSH = "settings_push"
    BACKPRESSURE = "backpressure"
    ERROR = "error"
    TOKEN_ROTATION = "token_rotation"


class Hello(StrictModel):
    type: Literal[ClientMessageType.HELLO] = ClientMessageType.HELLO
    device_token_jwt: str
    app_version: str
    camera_label: str | None = None


class Heartbeat(StrictModel):
    type: Literal[ClientMessageType.HEARTBEAT] = ClientMessageType.HEARTBEAT
    fps: float = Field(ge=0)
    queue_depth: int = Field(ge=0)
    error_count: int = Field(ge=0)
    clock_skew_ms: int


class FrameItem(StrictModel):
    jpeg_b64: str
    bbox: tuple[int, int, int, int]
    monotonic_offset_ms: int = Field(ge=0)

    @field_validator("bbox")
    @classmethod
    def bbox_must_be_ordered(cls, value: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        x1, y1, x2, y2 = value
        if x2 <= x1 or y2 <= y1:
            raise ValueError("bbox must be ordered as x1 < x2 and y1 < y2")
        return value


class GateMetrics(StrictModel):
    bbox_area_pct: float | None = None
    interocular_px: int | None = None
    center_offset_pct: float | None = None
    sharpness: float | None = None
    luma: int | None = None
    stability_iou: float | None = None
    stability_frames: int | None = None


class FrameBurst(StrictModel):
    type: Literal[ClientMessageType.FRAME_BURST] = ClientMessageType.FRAME_BURST
    idempotency_key: str
    burst_seq: int = Field(ge=0)
    frames: list[FrameItem] = Field(min_length=1, max_length=5)
    gate_metrics: GateMetrics | None = None


ClientMessage = Hello | Heartbeat | FrameBurst


class Ready(StrictModel):
    type: Literal[ServerMessageType.READY] = ServerMessageType.READY
    gallery_version: int = Field(ge=0)
    settings_version: int = Field(ge=0)


class Detected(StrictModel):
    type: Literal[ServerMessageType.DETECTED] = ServerMessageType.DETECTED


class Checking(StrictModel):
    type: Literal[ServerMessageType.CHECKING] = ServerMessageType.CHECKING


class Person(StrictModel):
    id: str
    display_name: str
    photo_url: str | None = None


class Result(StrictModel):
    type: Literal[ServerMessageType.RESULT] = ServerMessageType.RESULT
    status: str
    person: Person | None = None
    direction: str | None = None
    occurred_at: datetime
    record_status: str | None = None
    committed: Literal[True] = True


class SettingsPush(StrictModel):
    type: Literal[ServerMessageType.SETTINGS_PUSH] = ServerMessageType.SETTINGS_PUSH
    settings_version: int = Field(ge=0)
    payload: dict[str, Any]


class Backpressure(StrictModel):
    type: Literal[ServerMessageType.BACKPRESSURE] = ServerMessageType.BACKPRESSURE
    retry_after_ms: int = Field(ge=0)


class ErrorBody(StrictModel):
    code: ErrorCode
    message: str
    details: dict[str, Any] | None = None


class ErrorMessage(StrictModel):
    type: Literal[ServerMessageType.ERROR] = ServerMessageType.ERROR
    error: ErrorBody


class TokenRotation(StrictModel):
    type: Literal[ServerMessageType.TOKEN_ROTATION] = ServerMessageType.TOKEN_ROTATION
    device_token: str


ServerMessage = Ready | Detected | Checking | Result | SettingsPush | Backpressure | ErrorMessage | TokenRotation
