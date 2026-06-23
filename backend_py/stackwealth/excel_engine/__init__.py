"""CFP Excel calculation engine.

The firm's CFP workbook holds the authoritative deterministic financial-plan
math. This package injects a client's uploaded inputs into a pristine master,
recalculates with headless LibreOffice, and reads the results back — so the app
computes exactly what the planner designed, with no hand-ported Python mirror to
keep in sync.
"""

from .engine import compute_from_upload, MASTER_PATH  # noqa: F401
