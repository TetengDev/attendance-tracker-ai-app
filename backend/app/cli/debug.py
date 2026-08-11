# mypy: ignore-errors
import argparse
import asyncio
import time

import numpy as np

# ANSI colors
RESET = "\033[0m"
GREEN = "\033[32m"
BLUE = "\033[34m"
YELLOW = "\033[33m"
RED = "\033[31m"
CYAN = "\033[36m"
BOLD = "\033[1m"

def print_step(msg):
    print(f"{BLUE}[*]{RESET} {msg}")

def print_success(msg, duration_ms=None):
    if duration_ms is not None:
        print(f"{GREEN}[+]{RESET} {msg} {CYAN}({duration_ms:.2f}ms){RESET}")
    else:
        print(f"{GREEN}[+]{RESET} {msg}")

def print_error(msg):
    print(f"{RED}[-]{RESET} {msg}")

def get_engine():
    print_step("Loading face engine (this may take a few seconds)...")
    t0 = time.perf_counter()
    from backend.app.face.engine import ONNXFaceEngine
    engine = ONNXFaceEngine()
    t1 = time.perf_counter()
    print_success("Face engine loaded.", (t1 - t0) * 1000)
    return engine

async def load_gallery_from_db():
    print_step("Fetching embeddings from DB to load gallery...")
    t0 = time.perf_counter()
    
    from sqlalchemy import select

    from backend.app.crypto.envelope import decrypt_embedding
    from backend.app.db.session import get_session_factory
    from backend.app.face.gallery import GalleryEntry, GalleryIndex
    from backend.app.models.biometrics import FaceEmbedding
    
    gallery = GalleryIndex()
    entries = []
    
    async with get_session_factory()() as session:
        result = await session.execute(
            select(FaceEmbedding).where(FaceEmbedding.is_active == True)
        )
        embeddings = result.scalars().all()
        
        for emb in embeddings:
            vector = decrypt_embedding(emb)
            entries.append(GalleryEntry(
                person_id=emb.person_id,
                embedding_id=emb.id,
                vector=vector
            ))
            
    stats = gallery.load(entries)
    t1 = time.perf_counter()
    print_success(f"Gallery loaded with {len(entries)} entries.", (t1 - t0) * 1000)
    return gallery, stats, embeddings

async def cmd_gallery_stats(args):
    _gallery, stats, embeddings = await load_gallery_from_db()
    models = {e.model_version for e in embeddings}
    print("\n--- Gallery Stats ---")
    print(f"Size: {stats.size} entries")
    print(f"Model version(s): {', '.join(models) if models else 'None'}")
    print(f"Embedding dimensions: {stats.dimensions}")
    print(f"Gallery version: {stats.version}")

async def cmd_probe(args):
    import cv2
    image_path = args.image_path
    
    print_step(f"Reading image {image_path}...")
    bgr = cv2.imread(image_path)
    if bgr is None:
        print_error("Failed to read image.")
        return
        
    engine = get_engine()
    gallery, _stats, _embeddings = await load_gallery_from_db()
    
    print_step("Running detection...")
    t0 = time.perf_counter()
    faces = engine.detect(bgr)
    t1 = time.perf_counter()
    print_success(f"Found {len(faces)} face(s).", (t1 - t0) * 1000)
    
    if not faces:
        return
        
    # Take the largest face (assuming first one or sorting by area)
    face = faces[0]
    landmarks = face.landmarks
    
    print_step("Aligning face...")
    t0 = time.perf_counter()
    aligned = engine.align(bgr, landmarks)
    t1 = time.perf_counter()
    print_success("Face aligned.", (t1 - t0) * 1000)
    
    print_step("Extracting embedding...")
    t0 = time.perf_counter()
    embedding = engine.embed(aligned)
    t1 = time.perf_counter()
    print_success("Embedding extracted.", (t1 - t0) * 1000)
    
    print_step("Matching against gallery...")
    t0 = time.perf_counter()
    candidates = gallery.top_k(embedding, k=5)
    t1 = time.perf_counter()
    print_success("Match completed.", (t1 - t0) * 1000)
    
    print("\n--- Top 5 Matches ---")
    
    if not candidates:
        print("No candidates found (gallery is empty).")
        return
        
    # Fetch people names
    from sqlalchemy import select

    from backend.app.db.session import get_session_factory
    from backend.app.models.people import Person
    
    person_ids = [c.person_id for c in candidates]
    async with get_session_factory()() as session:
        result = await session.execute(select(Person).where(Person.id.in_(person_ids)))
        people = {p.id: p.display_name for p in result.scalars().all()}
        
    for i, candidate in enumerate(candidates):
        name = people.get(candidate.person_id, str(candidate.person_id))
        print(f"{i+1}. {name} (Score: {candidate.score:.4f})")

async def cmd_parity_test(args):
    image_path = args.image_path
    
    print_step(f"Reading image {image_path}...")
    with open(image_path, "rb") as f:  # noqa: ASYNC230
        raw_bytes = f.read()
        
    print_step("Decoding using Enrollment path (PIL)...")
    t0 = time.perf_counter()
    from io import BytesIO

    from PIL import Image, ImageOps
    with Image.open(BytesIO(raw_bytes)) as img:
        img = ImageOps.exif_transpose(img)
        rgb = np.asarray(img.convert('RGB'), dtype=np.uint8)
        bgr_enroll = np.ascontiguousarray(rgb[:, :, ::-1])
    t1 = time.perf_counter()
    print_success("Enrollment decode done.", (t1 - t0) * 1000)
    
    print_step("Decoding using Scan path (OpenCV)...")
    t0 = time.perf_counter()
    import cv2
    buf = np.frombuffer(raw_bytes, dtype=np.uint8)
    bgr_scan = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    t1 = time.perf_counter()
    print_success("Scan decode done.", (t1 - t0) * 1000)
    
    engine = get_engine()
    
    # Run through both
    print_step("Processing Enrollment image...")
    faces_e = engine.detect(bgr_enroll)
    if not faces_e:
        print_error("No face detected in enrollment decode.")
        return
    aligned_e = engine.align(bgr_enroll, faces_e[0].landmarks)
    embed_e = engine.embed(aligned_e)
    
    print_step("Processing Scan image...")
    faces_s = engine.detect(bgr_scan)
    if not faces_s:
        print_error("No face detected in scan decode.")
        return
    aligned_s = engine.align(bgr_scan, faces_s[0].landmarks)
    embed_s = engine.embed(aligned_s)
    
    print_step("Computing similarity...")
    # Both embeddings are L2 normalized (as per the prompt: 512-d float32 L2-normalized vectors)
    # Cosine similarity is just the dot product
    similarity = float(np.dot(embed_e, embed_s))
    
    print(f"\nCosine Similarity: {similarity:.6f}")
    if similarity > 0.99:
        print(f"{GREEN}PASS{RESET}: Similarity is >0.99")
    else:
        print(f"{RED}FAIL{RESET}: Similarity is <=0.99")

async def cmd_list_users(args):
    from sqlalchemy import select

    from backend.app.db.session import get_session_factory
    from backend.app.models.biometrics import FaceEmbedding
    from backend.app.models.people import Person
    
    print_step("Querying database for users and their embeddings...")
    t0 = time.perf_counter()
    async with get_session_factory()() as session:
        people_result = await session.execute(select(Person))
        people = people_result.scalars().all()
        
        emb_result = await session.execute(select(FaceEmbedding))
        embeddings = emb_result.scalars().all()
        
    t1 = time.perf_counter()
    print_success(f"Retrieved {len(people)} people.", (t1 - t0) * 1000)
    
    # Group embeddings by person_id
    from collections import defaultdict
    embs_by_person = defaultdict(list)
    for e in embeddings:
        embs_by_person[e.person_id].append(e)
    
    print(f"\n{BOLD}{'Display Name':<30} | {'Active':<6} | {'Embeddings':<10} | {'Model Versions'}{RESET}")
    print("-" * 75)
    for p in people:
        embs = embs_by_person[p.id]
        count = len(embs)
        models = {e.model_version for e in embs}
        models_str = ", ".join(models) if models else "N/A"
        active_str = "Yes" if p.is_active else "No"
        print(f"{p.display_name:<30} | {active_str:<6} | {count:<10} | {models_str}")

def main():
    parser = argparse.ArgumentParser(description="Face Recognition Pipeline Debug CLI")
    subparsers = parser.add_subparsers(dest="command", required=True)
    
    subparsers.add_parser("gallery-stats", help="Print gallery size, model version, etc.")
    
    parser_probe = subparsers.add_parser("probe", help="Run a probe image through the pipeline")
    parser_probe.add_argument("image_path", help="Path to the probe image")
    
    parser_parity = subparsers.add_parser("parity-test", help="Test PIL vs OpenCV decode parity")
    parser_parity.add_argument("image_path", help="Path to the test image")
    
    subparsers.add_parser("list-users", help="List all people and their embeddings")
    
    args = parser.parse_args()
    
    # Run asyncio event loop
    loop = asyncio.get_event_loop()
    if args.command == "gallery-stats":
        loop.run_until_complete(cmd_gallery_stats(args))
    elif args.command == "probe":
        loop.run_until_complete(cmd_probe(args))
    elif args.command == "parity-test":
        loop.run_until_complete(cmd_parity_test(args))
    elif args.command == "list-users":
        loop.run_until_complete(cmd_list_users(args))

if __name__ == "__main__":
    main()
