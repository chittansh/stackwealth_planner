"""Headless LibreOffice recalculation via the Python-UNO bridge.

openpyxl can write input cells but cannot evaluate formulas — it only stores
them. To turn the firm's formulas into numbers we drive a headless LibreOffice
through UNO: open the workbook, ``calculateAll()``, store it back.

WHY UNO AND NOT ``--convert-to``: on Linux LibreOffice 25.2 (the deployed build)
``soffice --convert-to xlsx`` does NOT recalculate — it trusts the workbook's
cached formula results and just re-writes them. openpyxl can't compute caches,
so every formula came back blank/0 on the server (while macOS LibreOffice, which
recalcs on convert, masked this locally). calcId=0, fullCalcOnLoad, the
OOXMLRecalcMode registry override and ``--infilter`` were all tested on the
deployed build and none forced a recalc. Only an explicit ``calculateAll()`` via
UNO works. Verified: =A1*A2 → 42 on the container.

macOS dev note: install LibreOffice; ``officehelper`` ships inside the app
bundle at .../Contents/Resources and uno is on its python. If UNO can't be
imported locally we fall back to the legacy ``--convert-to`` path (which DOES
recalc on macOS), so local dev keeps working without python3-uno.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time

from ..logging_config import get_logger

_log = get_logger(__name__)

# Resolved once. Override with STACKWEALTH_SOFFICE if installed somewhere odd.
_CANDIDATES = [
    os.environ.get("STACKWEALTH_SOFFICE"),
    "soffice",
    "libreoffice",
    "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    "/usr/bin/soffice",
    "/usr/bin/libreoffice",
]

# Dirs that hold uno.py / unohelper.py / officehelper.py on Debian (python3-uno
# installs them outside the app's site-packages). Added to sys.path lazily.
_UNO_PATHS = [
    "/usr/lib/python3/dist-packages",
    "/usr/lib/libreoffice/program",
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
        "On Debian/Ubuntu: apt-get install -y libreoffice-calc python3-uno."
    )


class RecalcError(RuntimeError):
    pass


def _import_uno():
    """Import the UNO bridge, extending sys.path to the Debian UNO dirs first.
    Returns (uno, officehelper) or None if UNO isn't available on this host."""
    for p in _UNO_PATHS:
        if os.path.isdir(p) and p not in sys.path:
            sys.path.append(p)
    try:
        import uno  # type: ignore
        import officehelper  # type: ignore
        return uno, officehelper
    except Exception:
        return None


def _to_url(path: str) -> str:
    return "file://" + os.path.abspath(path)


def _recalc_via_uno(soffice: str, staged: str, out: str, work: str, env: dict, timeout: int) -> None:
    """Recalculate ``staged`` and write ``out`` by driving LibreOffice over UNO.

    We spawn soffice ourselves (rather than officehelper.bootstrap, which fails
    in the uvicorn process — its default profile path / HOME isn't writable). The
    explicit ``-env:UserInstallation`` gives soffice a writable, isolated profile,
    a unique pipe name avoids collisions between concurrent recalcs, and ``env``
    carries a writable HOME."""
    mods = _import_uno()
    if mods is None:
        raise RecalcError("uno-unavailable")
    uno, _officehelper = mods
    from com.sun.star.beans import PropertyValue  # type: ignore
    from com.sun.star.connection import NoConnectException  # type: ignore

    def pv(name, value):
        p = PropertyValue()
        p.Name = name
        p.Value = value
        return p

    pipe = "cfp_" + os.path.basename(work)
    profile = "file://" + os.path.join(work, "lo_profile")
    proc = subprocess.Popen(
        [
            soffice,
            f"-env:UserInstallation={profile}",
            "--headless",
            "--invisible",
            "--nodefault",
            "--norestore",
            "--nologo",
            "--nofirststartwizard",
            f"--accept=pipe,name={pipe};urp;StarOffice.ComponentContext",
        ],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )

    local_ctx = uno.getComponentContext()
    resolver = local_ctx.ServiceManager.createInstanceWithContext(
        "com.sun.star.bridge.UnoUrlResolver", local_ctx
    )
    url = f"uno:pipe,name={pipe};urp;StarOffice.ComponentContext"

    ctx = None
    deadline = time.monotonic() + min(timeout, 60)
    while time.monotonic() < deadline:
        try:
            ctx = resolver.resolve(url)
            break
        except NoConnectException:
            if proc.poll() is not None:
                raise RecalcError(f"soffice exited early (rc={proc.returncode}) before UNO was ready")
            time.sleep(0.3)
    if ctx is None:
        proc.terminate()
        raise RecalcError("timed out connecting to soffice over UNO")

    doc = None
    try:
        smgr = ctx.ServiceManager
        desktop = smgr.createInstanceWithContext("com.sun.star.frame.Desktop", ctx)
        doc = desktop.loadComponentFromURL(
            _to_url(staged), "_blank", 0, (pv("Hidden", True),)
        )
        doc.calculateAll()
        doc.storeToURL(_to_url(out), (pv("FilterName", "Calc MS Excel 2007 XML"),))
    finally:
        try:
            if doc is not None:
                doc.close(False)
        except Exception:
            pass
        try:
            desktop.terminate()
        except Exception:
            pass
        try:
            proc.wait(timeout=10)
        except Exception:
            proc.kill()


def _recalc_via_convert(soffice: str, staged: str, work: str, env: dict, timeout: int) -> str:
    """Legacy fallback: `soffice --convert-to`. Recalcs on macOS LibreOffice but
    NOT on the deployed Linux build — kept only so local dev works without UNO."""
    cmd = [
        soffice,
        f"-env:UserInstallation=file://{os.path.join(work, 'lo_profile')}",
        "--headless",
        "--calc",
        "--convert-to",
        "xlsx:Calc MS Excel 2007 XML",
        "--outdir",
        work,
        staged,
    ]
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as e:
        raise RecalcError(f"LibreOffice recalc timed out after {timeout}s") from e
    out = os.path.join(work, "book.xlsx")
    if proc.returncode != 0 or not os.path.exists(out):
        raise RecalcError(
            f"LibreOffice recalc failed (rc={proc.returncode}): "
            f"{proc.stderr.strip()[:400] or proc.stdout.strip()[:400]}"
        )
    return out


def recalc_file(in_path: str, timeout: int = 180) -> str:
    """Recalculate ``in_path`` and return the path to a recalculated .xlsx
    (written into a fresh temp dir; caller owns cleanup of the dir).

    Uses UNO when available (required on the deployed Linux build); falls back to
    `--convert-to` only where UNO isn't installed but convert-to still recalcs.
    Each call uses an isolated HOME so concurrent recalcs don't collide.
    """
    soffice = soffice_path()
    work = tempfile.mkdtemp(prefix="cfp_recalc_")
    staged = os.path.join(work, "book.xlsx")
    out = os.path.join(work, "recalced.xlsx")
    shutil.copy(in_path, staged)
    env = dict(os.environ, HOME=work)
    start = time.monotonic()
    path_method = "uno" if _import_uno() is not None else "convert"
    _log.info("recalc.start", extra={"method": path_method, "timeout_s": timeout,
                                     "size_bytes": os.path.getsize(staged), "category": "excel"})

    if path_method == "uno":
        try:
            _recalc_via_uno(soffice, staged, out, work, env, timeout)
        except RecalcError:
            _log.error("recalc.failed", extra={"method": "uno", "category": "excel",
                                               "duration_ms": round((time.monotonic() - start) * 1000, 1)}, exc_info=True)
            raise
        except Exception as e:
            _log.error("recalc.failed", extra={"method": "uno", "category": "excel",
                                               "duration_ms": round((time.monotonic() - start) * 1000, 1)}, exc_info=True)
            raise RecalcError(f"UNO recalc failed: {type(e).__name__}: {e}") from e
        if not os.path.exists(out):
            _log.error("recalc.no_output", extra={"method": "uno", "category": "excel"})
            raise RecalcError("UNO recalc produced no output")
        _log.info("recalc.done", extra={"method": "uno", "category": "excel",
                                        "duration_ms": round((time.monotonic() - start) * 1000, 1)})
        return out

    # No UNO on this host (e.g. local macOS without python3-uno) — convert-to
    # recalcs there, so fall back to it.
    try:
        res = _recalc_via_convert(soffice, staged, work, env, timeout)
    except Exception:
        _log.error("recalc.failed", extra={"method": "convert", "category": "excel",
                                           "duration_ms": round((time.monotonic() - start) * 1000, 1)}, exc_info=True)
        raise
    _log.info("recalc.done", extra={"method": "convert", "category": "excel",
                                    "duration_ms": round((time.monotonic() - start) * 1000, 1)})
    return res
