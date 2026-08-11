from __future__ import annotations

import base64
import binascii
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect, status
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.api.common import CrudError, StrictSchema, authenticated_admin_user
from backend.app.api.enrollment import (
    EnrollmentService,
    FaceEngineDep,
    GalleryIndexDep,
    ImageCandidate,
    _apply_gallery_entries,
    get_enrollment_service,
)
from backend.app.db.session import get_session
from backend.app.models.admin import AdminUser
from backend.app.models.biometrics import EnrollmentPose

router = APIRouter(prefix="/api/enrollment", tags=["enrollment"])
GUIDED_POSE_SEQUENCE = (
    EnrollmentPose.FRONTAL,
    EnrollmentPose.YAW_LEFT,
    EnrollmentPose.YAW_RIGHT,
    EnrollmentPose.SLIGHT_UP,
)


@router.websocket("/{person_id}/guided")
async def guided_enrollment_session(
    websocket: WebSocket,
    person_id: UUID,
    session: Annotated[AsyncSession, Depends(get_session)],
    admin_user: Annotated[AdminUser, Depends(authenticated_admin_user)],
    service: Annotated[EnrollmentService, Depends(get_enrollment_service)],
    face_engine: FaceEngineDep,
    gallery_index: GalleryIndexDep,
) -> None:
    await websocket.accept()
    policy_version = websocket.query_params.get("policy_version")
    if not policy_version:
        await websocket.send_json({"type": "error", "detail": "policy_version is required"})
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return

    await websocket.send_json(
        {
            "type": "pose_sequence",
            "poses": [pose.value for pose in GUIDED_POSE_SEQUENCE],
            "next_pose": GUIDED_POSE_SEQUENCE[0].value,
        }
    )
    pose_index = 0
    try:
        while True:
            expected_pose = GUIDED_POSE_SEQUENCE[min(pose_index, len(GUIDED_POSE_SEQUENCE) - 1)]
            payload = await websocket.receive_json()
            try:
                frame = GuidedFrame.model_validate(payload)
                candidate = ImageCandidate(
                    filename=frame.filename,
                    content_type=frame.content_type,
                    payload=base64.b64decode(frame.image_base64, validate=True),
                    pose=frame.pose,
                )
            except (ValidationError, binascii.Error) as exc:
                await websocket.send_json({"type": "rejected", "detail": str(exc)})
                continue
            if frame.pose != expected_pose:
                await websocket.send_json(
                    {
                        "type": "rejected",
                        "detail": f"expected pose {expected_pose.value}",
                        "expected_pose": expected_pose.value,
                        "received_pose": frame.pose.value,
                    }
                )
                continue

            try:
                commit = await service.prepare_commit(
                    session,
                    admin_user,
                    person_id=person_id,
                    candidates=[candidate],
                    policy_version=policy_version,
                    face_engine=face_engine,
                    gallery_index=gallery_index,
                    now=datetime.now(UTC),
                )
                response = commit.response
                await session.commit()
                await _apply_gallery_entries(session, gallery_index, commit.gallery_entries)
                await session.commit()  # TEN-222: persist gallery version bump
            except CrudError as exc:
                await session.rollback()
                await websocket.send_json({"type": "error", "detail": exc.message})
                continue
            if response.accepted_count == 1 and pose_index < len(GUIDED_POSE_SEQUENCE) - 1:
                pose_index += 1
            next_pose = GUIDED_POSE_SEQUENCE[pose_index].value
            await websocket.send_json(
                {
                    "type": "capture_result",
                    "pose": frame.pose.value,
                    "accepted": response.accepted_count == 1,
                    "expected_pose": expected_pose.value,
                    "next_pose": next_pose,
                    "sequence_complete": response.accepted_count == 1
                    and pose_index == len(GUIDED_POSE_SEQUENCE) - 1,
                    "enrollment_complete": response.enrollment_complete,
                    "active_embeddings_count": response.active_embeddings_count,
                    "results": [result.model_dump(mode="json") for result in response.results],
                }
            )
    except WebSocketDisconnect:
        return


class GuidedFrame(StrictSchema):
    image_base64: str
    content_type: str = "image/jpeg"
    filename: str = "guided-frame"
    pose: EnrollmentPose
