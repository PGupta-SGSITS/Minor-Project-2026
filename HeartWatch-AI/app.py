"""ASGI entrypoint shim for running from repository root.

Allows: uvicorn app:app --host 0.0.0.0 --port 8000
"""

from backend.app import app
