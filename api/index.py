"""Vercel serverless entrypoint. Exposes the FastAPI app for the @vercel/python runtime."""
import sys
from pathlib import Path

# Ensure the repo root (parent of /api) is on sys.path so `server.main` imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from server.main import app  # noqa: E402,F401
