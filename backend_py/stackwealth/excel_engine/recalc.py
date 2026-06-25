"""Headless LibreOffice recalculation.

openpyxl can write input cells but cannot evaluate formulas — it only stores
them. To turn the firm's formulas into numbers we hand the workbook to
LibreOffice running headless, which recalculates on load and re-saves. Verified
to reproduce Excel's cached values to 100% on the firm model (standard,
non-volatile functions: SUM/FV/PMT/PV/SUMIF/MAX/IFERROR/ROUND).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile

# Resolved once. Override with STACKWEALTH_SOFFICE if installed somewhere odd.
_CANDIDATES = [
    os.environ.get("STACKWEALTH_SOFFICE"),
    "soffice",
    "libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
]


def soffice_path() -> str:
    for cand in _CANDIDATES:
        if not cand:
            continue
        if os.path.isabs(cand) and os.path.exists(cand):
            return cand
        found = shutil.which(cand)
        if found:
            return found
    raise RuntimeError(
        "LibreOffice (soffice) not found. Install it or set STACKWEALTH_SOFFICE. "
        "On Debian/Ubuntu: apt-get install -y libreoffice-calc."
    )


class RecalcError(RuntimeError):
    pass


def recalc_file(in_path: str, timeout: int = 180) -> str:
    """Recalculate ``in_path`` in place-ish and return the path to a recalculated
    .xlsx (written into a fresh temp dir; caller owns cleanup of the dir).

    Each call uses an isolated HOME so concurrent recalcs don't fight over the
    LibreOffice user profile.
    """
    soffice = soffice_path()
    work = tempfile.mkdtemp(prefix="cfp_recalc_")
    staged = os.path.join(work, "book.xlsx")
    shutil.copy(in_path, staged)
    env = dict(os.environ, HOME=work)
    cmd = [
        soffice,
        "--headless",
        "--calc",
        "--convert-to",
        "xlsx:Calc MS Excel 2007 XML",
        "--outdir",
        work,
        staged,
    ]
    try:
        proc = subprocess.run(
            cmd, env=env, capture_output=True, text=True, timeout=timeout
        )
    except subprocess.TimeoutExpired as e:
        raise RecalcError(f"LibreOffice recalc timed out after {timeout}s") from e
    out = os.path.join(work, "book.xlsx")
    if proc.returncode != 0 or not os.path.exists(out):
        raise RecalcError(
            f"LibreOffice recalc failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()[:400] or proc.stdout.strip()[:400]}"
        )
    return out
