# Production Dockerfile for Aegis FastAPI backend
FROM python:3.13-slim

# Install uv for fast dependency syncing
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Install system shared libraries required by OpenCV, ONNX Runtime, and WeasyPrint
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libgobject-2.0-0 \
    libpango-1.0-0 \
    libharfbuzz0b \
    libfontconfig1 \
    libpangoft2-1.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy configuration and sync dependencies
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy backend source code and ONNX models
COPY backend/ ./backend/
COPY models/ ./models/

# Ensure virtual env binaries are in path
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONUNBUFFERED=1

EXPOSE 8000

# Run FastAPI
CMD ["uvicorn", "backend.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
