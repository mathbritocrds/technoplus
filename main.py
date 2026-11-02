"""ASGI entry point compatible with commands that load ``main:app``."""

from app.main import app

__all__ = ["app"]
