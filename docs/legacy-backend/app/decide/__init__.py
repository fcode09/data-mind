"""Seam determinista F1: router + verifier + adapter Jev (F2a)."""

from .router import decide, route
from .verify import verify, verify_routed

__all__ = ["decide", "route", "verify", "verify_routed"]
