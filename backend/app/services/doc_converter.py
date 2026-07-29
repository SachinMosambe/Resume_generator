"""Convert legacy .doc Word files to .docx for parsing and logo extraction."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# systemd often sets PATH to only the venv; LibreOffice's /usr/bin/soffice
# shell wrapper needs coreutils (dirname, basename, ls, sed, grep, uname).
_SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


class DocConversionError(ValueError):
    pass


def _subprocess_env() -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PATH", "")
    parts = [p for p in (_SAFE_PATH.split(":") + current.split(":")) if p]
    # Dedupe while preserving order; keep system bins first.
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        if part in seen:
            continue
        seen.add(part)
        ordered.append(part)
    env["PATH"] = ":".join(ordered)
    env.setdefault("HOME", str(Path.home()))
    env.setdefault("LANG", "C.UTF-8")
    # Avoid LibreOffice trying to use a display.
    env.setdefault("SAL_USE_VCLPLUGIN", "svp")
    return env


def find_libreoffice() -> str | None:
    """Locate LibreOffice binary used for .doc → .docx conversion.

    Prefer the native program binary over /usr/bin/soffice shell wrapper when
    available — the wrapper depends on PATH having coreutils.
    """
    env = _subprocess_env()
    path_env = env["PATH"]

    native_candidates = (
        "/usr/lib/libreoffice/program/soffice.bin",
        "/usr/lib/libreoffice/program/soffice",
        "/snap/bin/libreoffice",
    )
    for path in native_candidates:
        if Path(path).exists():
            return path

    for candidate in ("soffice", "libreoffice"):
        found = shutil.which(candidate, path=path_env)
        if found:
            return found

    for path in ("/usr/bin/soffice", "/usr/bin/libreoffice"):
        if Path(path).exists():
            return path
    return None


def convert_doc_to_docx(source: Path, output_dir: Path | None = None) -> Path:
    """Convert a .doc file to .docx via LibreOffice headless.

    Returns the path to the converted .docx. Raises DocConversionError on failure.
    """
    source = Path(source)
    if not source.exists():
        raise DocConversionError(f"DOC file not found: {source}")
    if source.suffix.lower() != ".doc":
        raise DocConversionError(f"Expected a .doc file, got: {source.suffix}")

    soffice = find_libreoffice()
    if not soffice:
        raise DocConversionError(
            "Legacy .doc support requires LibreOffice on the server. "
            "Install with: sudo apt-get install -y libreoffice-writer-nogui"
        )

    out_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="doc_convert_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    env = _subprocess_env()

    # Unique LibreOffice user profile avoids lock conflicts under systemd.
    profile_dir = Path(tempfile.mkdtemp(prefix="lo_profile_"))
    profile_uri = profile_dir.as_uri()

    try:
        result = subprocess.run(
            [
                soffice,
                "--headless",
                "--nologo",
                "--nofirststartwizard",
                "--norestore",
                f"-env:UserInstallation={profile_uri}",
                "--convert-to",
                "docx",
                "--outdir",
                str(out_dir),
                str(source.resolve()),
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
            env=env,
            cwd=str(out_dir),
        )
    except subprocess.TimeoutExpired as exc:
        raise DocConversionError("Timed out converting .doc to .docx") from exc
    except OSError as exc:
        raise DocConversionError(f"Failed to run LibreOffice: {exc}") from exc
    finally:
        shutil.rmtree(profile_dir, ignore_errors=True)

    converted = out_dir / f"{source.stem}.docx"
    if not converted.exists():
        # Some LibreOffice builds sanitize filenames; pick newest docx in out_dir.
        candidates = sorted(out_dir.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates:
            converted = candidates[0]
        else:
            stderr = (result.stderr or result.stdout or "").strip()
            logger.error("doc_conversion_failed soffice=%s stderr=%s", soffice, stderr[:500])
            raise DocConversionError(
                "Could not convert .doc to .docx. "
                + (stderr[:300] if stderr else "LibreOffice produced no output file.")
            )

    logger.info("Converted .doc → .docx via %s: %s", soffice, converted)
    return converted


def ensure_docx(path: Path) -> Path:
    """Return a .docx path, converting from .doc when needed."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".docx":
        return path
    if ext == ".doc":
        return convert_doc_to_docx(path, output_dir=path.parent)
    raise DocConversionError(f"Unsupported Word extension: {ext}")
