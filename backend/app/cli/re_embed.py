"""CLI job to re-embed all encrypted original images for a new model version.

This script loads all active enrollment original images, decrypts them using the KEK
and their recorded filename/DPO AAD, generates embeddings with the current active
face engine version, and encrypts/stores the new embeddings.
"""

from __future__ import annotations

import asyncio
import logging

import cv2
import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.app.api.enrollment import (
    _asset_aad,
    _embedding_aad,
    _payload_columns,
    get_face_engine,
)
from backend.app.crypto.envelope import EncryptedPayload, decrypt_bytes, encrypt_embedding
from backend.app.db.session import get_session_factory
from backend.app.models.biometrics import EnrollmentAsset, EnrollmentAssetKind, FaceEmbedding

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def run_re_embed() -> None:
    logger.info("Initializing active FaceEngine...")
    face_engine = get_face_engine()
    model_name = face_engine.model_name
    model_version = face_engine.model_version
    logger.info("Active model version: %s / %s", model_name, model_version)

    session_factory = get_session_factory()
    async with session_factory() as session:
        # Load all original image assets with their associated consent
        stmt = (
            select(EnrollmentAsset)
            .where(EnrollmentAsset.kind == EnrollmentAssetKind.ORIGINAL_IMAGE)
            .options(selectinload(EnrollmentAsset.consent))
        )
        result = await session.execute(stmt)
        assets = list(result.scalars())
        logger.info("Found %d original enrollment assets to process", len(assets))

        processed = 0
        skipped = 0
        failed = 0

        for asset in assets:
            try:
                # 1. Check if the embedding already exists for this model
                exists_stmt = select(FaceEmbedding).where(
                    FaceEmbedding.person_id == asset.person_id,
                    FaceEmbedding.model_name == model_name,
                    FaceEmbedding.model_version == model_version,
                    FaceEmbedding.asset_id == asset.id,
                )
                exists_result = await session.execute(exists_stmt)
                if exists_result.scalar_one_or_none() is not None:
                    skipped += 1
                    continue

                # 2. Reconstruct EncryptedPayload
                payload = EncryptedPayload(
                    version=asset.envelope_version,
                    payload_alg=asset.payload_alg,
                    dek_wrap_alg=asset.dek_wrap_alg,
                    encryption_key_id=asset.encryption_key_id,
                    wrapped_dek=asset.wrapped_dek,
                    dek_nonce=asset.dek_nonce,
                    payload_nonce=asset.payload_nonce,
                    ciphertext=asset.ciphertext,
                )

                # 3. Decrypt original image bytes using the original filename and person ID AAD
                aad = _asset_aad(person_id=asset.person_id, filename=asset.filename)
                decrypted_bytes = decrypt_bytes(payload, aad=aad)

                # 4. Decode into BGR image
                np_arr = np.frombuffer(decrypted_bytes, np.uint8)
                bgr = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                if bgr is None:
                    logger.error("Failed to decode image for asset %s", asset.id)
                    failed += 1
                    continue

                # 5. Extract landmarks and align face
                dets = face_engine.detect(bgr)
                if not dets:
                    logger.warning(
                        "No face detected in original image for asset %s, skipping", asset.id
                    )
                    failed += 1
                    continue

                aligned = face_engine.align(bgr, dets[0].landmarks)
                emb = face_engine.embed(aligned)

                # 6. Encrypt the new embedding
                embedding_aad = _embedding_aad(person_id=asset.person_id, asset_id=asset.id)
                embedding_payload = encrypt_embedding(emb.vector, aad=embedding_aad)

                # 7. Persist new FaceEmbedding record
                new_embedding = FaceEmbedding(
                    person_id=asset.person_id,
                    consent_id=asset.consent_id,
                    asset_id=asset.id,
                    encryption_asset_id=asset.id,
                    model_name=model_name,
                    model_version=model_version,
                    policy_version=asset.consent.policy_version,
                    embedding_dimensions=512,
                    is_active=True,
                    quality={
                        "score": 1.0,
                        "det_score": float(dets[0].det_score),
                    },
                    **_payload_columns(embedding_payload),
                )
                session.add(new_embedding)
                processed += 1

                # Flush periodically
                if processed % 10 == 0:
                    await session.flush()

            except Exception:
                logger.exception("Failed to re-embed asset %s", asset.id)
                failed += 1

        if processed > 0:
            await session.commit()

        logger.info(
            "Re-embedding complete. Processed: %d, Skipped (already existed): %d, Failed: %d",
            processed,
            skipped,
            failed,
        )


if __name__ == "__main__":
    asyncio.run(run_re_embed())
