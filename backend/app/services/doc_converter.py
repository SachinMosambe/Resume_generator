"""Convert legacy .doc Word files to .docx for parsing and logo extraction."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
import time
import uuid
from pathlib import Path

logger = logging.getLogger(__name__)

# systemd often sets PATH to only the venv; LibreOffice's /usr/bin/soffice
# shell wrapper needs coreutils (dirname, basename, ls, sed, grep, uname).
_SAFE_PATH = "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"


class DocConversionError(ValueError):
    pass


def _subprocess_env(home: Path | None = None) -> dict[str, str]:
    env = os.environ.copy()
    current = env.get("PATH", "")
    parts = [p for p in (_SAFE_PATH.split(":") + current.split(":")) if p]
    seen: set[str] = set()
    ordered: list[str] = []
    for part in parts:
        if part in seen:
            continue
        seen.add(part)
        ordered.append(part)
    env["PATH"] = ":".join(ordered)
    env["HOME"] = str(home or Path.home() or "/home/ubuntu")
    env["LANG"] = env.get("LANG") or "C.UTF-8"
    env["LC_ALL"] = env.get("LC_ALL") or "C.UTF-8"
    # Headless-friendly defaults.
    env["SAL_USE_VCLPLUGIN"] = "svp"
    env.pop("DISPLAY", None)
    # Ensure LibreOffice shared libs resolve when calling program/soffice.
    lo_program = "/usr/lib/libreoffice/program"
    if Path(lo_program).is_dir():
        existing = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{lo_program}:{existing}" if existing else lo_program
    return env


def find_libreoffice() -> str | None:
    """Locate LibreOffice CLI.

    Prefer the /usr/bin/soffice wrapper (sets up libs) over soffice.bin.
    """
    env = _subprocess_env()
    path_env = env["PATH"]

    preferred = (
        "/usr/bin/soffice",
        "/usr/bin/libreoffice",
    )
    for path in preferred:
        if Path(path).exists():
            return path

    for candidate in ("soffice", "libreoffice"):
        found = shutil.which(candidate, path=path_env)
        if found:
            return found

    # Last resort: program directory (needs LD_LIBRARY_PATH from _subprocess_env).
    for path in (
        "/usr/lib/libreoffice/program/soffice",
        "/usr/lib/libreoffice/program/soffice.bin",
    ):
        if Path(path).exists():
            return path
    return None


def _looks_like_ole_doc(path: Path) -> bool:
    """True for classic OLE Compound File .doc (D0 CF 11 E0)."""
    try:
        with path.open("rb") as handle:
            magic = handle.read(8)
        return magic.startswith(b"\xd0\xcf\x11\xe0")
    except Exception:
        return False


def _poll_docx(out_dir: Path, timeout_s: float = 8.0) -> Path | None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        candidates = sorted(out_dir.glob("*.docx"), key=lambda p: p.stat().st_mtime, reverse=True)
        if candidates and candidates[0].stat().st_size > 0:
            return candidates[0]
        time.sleep(0.25)
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

    final_out_dir = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="doc_convert_"))
    final_out_dir.mkdir(parents=True, exist_ok=True)

    # Isolated work dir with a simple ASCII filename — LO often fails on odd temp names.
    work_root = Path(tempfile.mkdtemp(prefix="doc2docx_"))
    work_home = work_root / "home"
    work_in = work_root / "in"
    work_out = work_root / "out"
    profile_dir = work_root / "profile"
    for folder in (work_home, work_in, work_out, profile_dir):
        folder.mkdir(parents=True, exist_ok=True)

    input_copy = work_in / f"input_{uuid.uuid4().hex[:8]}.doc"
    shutil.copy2(source, input_copy)

    if not _looks_like_ole_doc(input_copy):
        # Still try conversion — some valid docs differ — but warn in logs.
        logger.warning(
            "doc_magic_unexpected path=%s size=%s (may not be classic OLE .doc)",
            source,
            input_copy.stat().st_size,
        )

    env = _subprocess_env(home=work_home)
    profile_uri = profile_dir.resolve().as_uri()

    convert_targets = (
        "docx",
        "docx:MS Word 2007 XML",
    )
    logs: list[str] = []

    try:
        for target in convert_targets:
            # Clean previous attempts in work_out.
            for stale in work_out.glob("*"):
                try:
                    stale.unlink()
                except Exception:
                    pass

            cmd = [
                soffice,
                "--headless",
                "--invisible",
                "--nologo",
                "--nolockcheck",
                "--nodefault",
                "--nofirststartwizard",
                "--norestore",
                f"-env:UserInstallation={profile_uri}",
                "--convert-to",
                target,
                "--outdir",
                str(work_out.resolve()),
                str(input_copy.resolve()),
            ]
            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=180,
                    check=False,
                    env=env,
                    cwd=str(work_out.resolve()),
                )
            except subprocess.TimeoutExpired:
                logs.append(f"target={target} timeout")
                continue
            except OSError as exc:
                logs.append(f"target={target} os_error={exc}")
                continue

            stdout = (result.stdout or "").strip()
            stderr = (result.stderr or "").strip()
            logs.append(
                f"target={target} code={result.returncode} stdout={stdout[:200]} stderr={stderr[:200]}"
            )
            logger.info(
                "doc_conversion_attempt soffice=%s target=%s code=%s",
                soffice,
                target,
                result.returncode,
            )

            converted = _poll_docx(work_out, timeout_s=6.0)
            if converted:
                dest = final_out_dir / f"{source.stem}.docx"
                # Avoid overwrite collisions.
                if dest.exists():
                    dest = final_out_dir / f"{source.stem}_{uuid.uuid4().hex[:6]}.docx"
                shutil.copy2(converted, dest)
                logger.info("Converted .doc → .docx via %s (%s): %s", soffice, target, dest)
                return dest
    finally:
        shutil.rmtree(work_root, ignore_errors=True)

    detail = " | ".join(logs)[:500] if logs else "no converter output"
    logger.error("doc_conversion_failed soffice=%s detail=%s", soffice, detail)
    raise DocConversionError(
        "Could not convert .doc to .docx. "
        "Re-save the file as .docx in Word and upload again, or install full LibreOffice writer. "
        f"Details: {detail[:240]}"
    )


def ensure_docx(path: Path) -> Path:
    """Return a .docx path, converting from .doc when needed."""
    path = Path(path)
    ext = path.suffix.lower()
    if ext == ".docx":
        return path
    if ext == ".doc":
        return convert_doc_to_docx(path, output_dir=path.parent)
    raise DocConversionError(f"Unsupported Word extension: {ext}")
