from __future__ import annotations

import argparse
import asyncio
import json
import logging
from collections.abc import Sequence
from typing import Any, cast
from uuid import UUID

import numpy as np
from cryptography.exceptions import InvalidTag
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.crypto.envelope import EncryptedPayload, decrypt_embedding
from backend.app.crypto.keys import KeyConfigurationError
from backend.app.face.gallery import GalleryEntry, GalleryIndex
from backend.app.models.biometrics import FaceEmbedding
from backend.app.models.people import Person
from backend.app.models.settings import Setting, SettingsVersion
from backend.app.settings.resolver import SettingContext, SettingValue, resolve_settings

logger = logging.getLogger(__name__)


async def load_active_gallery_entries(db: AsyncSession) -> list[GalleryEntry]:
    """Retrieve and decrypt all active face embeddings from the database."""
    result = await db.execute(select(FaceEmbedding).where(FaceEmbedding.is_active.is_(True)))
    db_embeddings = result.scalars().all()
    entries = []
    for emb in db_embeddings:
        payload = EncryptedPayload(
            version=emb.envelope_version,
            payload_alg=emb.payload_alg,
            dek_wrap_alg=emb.dek_wrap_alg,
            encryption_key_id=emb.encryption_key_id,
            wrapped_dek=emb.wrapped_dek,
            dek_nonce=emb.dek_nonce,
            payload_nonce=emb.payload_nonce,
            ciphertext=emb.ciphertext,
        )
        try:
            # Use the correct AAD matching enrollment.py
            aad = f"face-embedding:{emb.person_id}:{emb.encryption_asset_id}".encode()
            vector = decrypt_embedding(payload, aad=aad)
            entries.append(
                GalleryEntry(
                    person_id=emb.person_id,
                    embedding_id=emb.id,
                    vector=vector,
                )
            )
        except (KeyConfigurationError, InvalidTag) as exc:
            logger.error("Cryptographic decryption failed for embedding %s: %s", emb.id, exc)
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to decrypt embedding %s: %s", emb.id, exc)
    return entries


async def get_duplicate_threshold(session: AsyncSession) -> float:
    """Retrieve the face duplicate threshold setting from the database."""
    result = await session.execute(select(Setting))
    db_settings = result.scalars().all()
    values = [
        SettingValue(
            key=s.key,
            scope=s.scope,
            scope_id=s.scope_id,
            value=s.value,
            version=s.version,
        )
        for s in db_settings
    ]

    settings_ver = await session.execute(
        select(SettingsVersion.current_version).where(SettingsVersion.namespace == "global")
    )
    ver = settings_ver.scalar_one_or_none() or 1

    resolved = resolve_settings(values, SettingContext(), version=ver)
    return float(resolved.settings.get("face.duplicate_threshold", 0.75))


async def check_duplicate_enrollment(
    session: AsyncSession,
    embedding_vectors: Sequence[np.ndarray],
    current_person_id: UUID,
    gallery_index: GalleryIndex,
) -> list[dict[str, Any]]:
    """Checks if any of the candidate face embeddings are duplicates of existing enrollments.

    Only checks against embeddings belonging to a *different* person.
    Returns a list of duplicate candidate details if any duplicates are found.
    """
    # 1. Reload gallery index if stale
    await gallery_index.reload_if_stale(session, lambda: load_active_gallery_entries(session))

    # 2. Get duplicate threshold
    threshold = await get_duplicate_threshold(session)

    conflicts = []
    for vector in embedding_vectors:
        # Query top nearest neighbors in the gallery
        candidates = gallery_index.top_k(vector, k=5)
        for c in candidates:
            if c.person_id != current_person_id and c.score >= threshold:
                # Fetch details of conflicting person
                person = await session.get(Person, c.person_id)
                person_name = person.display_name if person else "Unknown"
                person_ext_id = person.external_id if person else None
                conflicts.append(
                    {
                        "person_id": str(c.person_id),
                        "display_name": person_name,
                        "external_id": person_ext_id,
                        "score": c.score,
                        "embedding_id": str(c.embedding_id),
                    }
                )
                # Break to avoid duplicate conflict logs for same person
                break

    return conflicts


async def find_all_gallery_duplicates(
    session: AsyncSession,
    gallery_index: GalleryIndex,
) -> list[dict[str, Any]]:
    """Scans the entire active gallery for pairs of different people who have duplicate face
    embeddings.

    Returns grouped duplicate candidate records.
    """
    # Ensure index is updated
    await gallery_index.reload_if_stale(session, lambda: load_active_gallery_entries(session))

    threshold = await get_duplicate_threshold(session)

    # We access the internal numpy arrays of GalleryIndex
    # Since we own the gallery index and we run in-process, this is safe and fast
    vectors = gallery_index._vectors
    person_ids = gallery_index._person_ids
    embedding_ids = gallery_index._embedding_ids

    if len(vectors) == 0:
        return []

    # Pairwise cosine similarities
    sim_matrix = vectors @ vectors.T
    n = len(vectors)

    duplicates = []
    for i in range(n):
        for j in range(i + 1, n):
            p1 = person_ids[i]
            p2 = person_ids[j]
            if p1 != p2:
                score = float(sim_matrix[i, j])
                if score >= threshold:
                    duplicates.append(
                        {
                            "person_id_1": p1,
                            "person_id_2": p2,
                            "embedding_id_1": embedding_ids[i],
                            "embedding_id_2": embedding_ids[j],
                            "score": score,
                        }
                    )

    # Group by person pair to avoid listing every pairwise embedding match
    grouped: dict[tuple[UUID, UUID], dict[str, Any]] = {}
    for dup in duplicates:
        p1 = cast(UUID, dup["person_id_1"])
        p2 = cast(UUID, dup["person_id_2"])
        emb1 = cast(UUID, dup["embedding_id_1"])
        emb2 = cast(UUID, dup["embedding_id_2"])
        score = cast(float, dup["score"])

        pair = (p1, p2) if p1 < p2 else (p2, p1)
        if pair not in grouped or score > cast(float, grouped[pair]["score"]):
            grouped[pair] = {
                "person_id_1": pair[0],
                "person_id_2": pair[1],
                "embedding_id_1": emb1 if pair[0] == p1 else emb2,
                "embedding_id_2": emb2 if pair[0] == p1 else emb1,
                "score": score,
            }

    # Resolve names/details for display
    results = []
    for pair_data in grouped.values():
        p1_obj = await session.get(Person, pair_data["person_id_1"])
        p2_obj = await session.get(Person, pair_data["person_id_2"])
        results.append(
            {
                "person_1": {
                    "id": str(pair_data["person_id_1"]),
                    "display_name": p1_obj.display_name if p1_obj else "Unknown",
                    "external_id": p1_obj.external_id if p1_obj else None,
                },
                "person_2": {
                    "id": str(pair_data["person_id_2"]),
                    "display_name": p2_obj.display_name if p2_obj else "Unknown",
                    "external_id": p2_obj.external_id if p2_obj else None,
                },
                "embedding_id_1": str(pair_data["embedding_id_1"]),
                "embedding_id_2": str(pair_data["embedding_id_2"]),
                "score": pair_data["score"],
            }
        )

    return results


def main() -> None:
    from backend.app.db.session import get_session_factory

    parser = argparse.ArgumentParser(
        description="Find all duplicate face enrollments in the gallery."
    )
    _ = parser.parse_args()

    async def _run() -> None:
        gallery_index = GalleryIndex()
        async with get_session_factory()() as session:
            duplicates = await find_all_gallery_duplicates(session, gallery_index)
            print(json.dumps({"status": "ok", "duplicates": duplicates}, sort_keys=True, indent=2))

    asyncio.run(_run())


if __name__ == "__main__":
    main()
