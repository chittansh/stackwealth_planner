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


# LibreOffice keeps a workbook's *cached* formula results when it opens an xlsx,
# unless its "recalc on load" mode is set to Always. The default is Prompt (2),
# which in headless mode means NO recalc — so openpyxl-written inputs never
# propagate and every formula cell reads back as its stale cached value (blank /
# 0 in our cleared master). We force Always-recalc by pre-seeding the isolated
# user profile with this registry override before launching soffice.
#   OOXMLRecalcMode → .xlsx,  ODFRecalcMode → .ods.  0 = Always, 1 = Never, 2 = Prompt.
_RECALC_ALWAYS_XCU = (
    '<?xml version="1.0" encoding="UTF-8"?>\n'
    '<oor:items xmlns:oor="http://openoffice.org/2001/registry" '
    'xmlns:xs="http://www.w3.org/2001/XMLSchema" '
    'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">\n'
    ' <item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
    '<prop oor:name="OOXMLRecalcMode" oor:op="fuse"><value>0</value></prop></item>\n'
    ' <item oor:path="/org.openoffice.Office.Calc/Formula/Load">'
    '<prop oor:name="ODFRecalcMode" oor:op="fuse"><value>0</value></prop></item>\n'
    '</oor:items>\n'
)


def _seed_recalc_profile(profile_root: str) -> str:
    """Seed an isolated LibreOffice user-installation at ``profile_root`` with the
    Always-recalc override and return a ``file://`` URL for -env:UserInstallation.

    Using an explicit UserInstallation (rather than relying on $HOME) makes the
    profile path deterministic across OSes — the Linux default lives under
    ~/.config/libreoffice/4 but macOS uses ~/Library/Application Support, and we
    need the override to land wherever soffice will actually read it."""
    user_dir = os.path.join(profile_root, "user")
    os.makedirs(user_dir, exist_ok=True)
    with open(os.path.join(user_dir, "registrymodifications.xcu"), "w", encoding="utf-8") as fh:
        fh.write(_RECALC_ALWAYS_XCU)
    return f"file://{profile_root}"


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
    profile_url = _seed_recalc_profile(os.path.join(work, "lo_profile"))
    cmd = [
        soffice,
        f"-env:UserInstallation={profile_url}",
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
