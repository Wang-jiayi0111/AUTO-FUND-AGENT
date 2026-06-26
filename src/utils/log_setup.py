from __future__ import annotations

import logging
import os
import sys
from datetime import datetime
from pathlib import Path


def prepare_log_file(path: Path) -> None:
    """If an old log was UTF-16 (PowerShell redirect), rotate it once."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        return
    head = path.read_bytes()[:2]
    if head in (b"\xff\xfe", b"\xfe\xff"):
        backup = path.with_suffix(path.suffix + ".old")
        if backup.exists():
            backup.unlink()
        path.rename(backup)


def append_log_line(message: str, log_file: str | None = None) -> None:
    path = Path(log_file or os.getenv("AUTO_FUND_LOG_FILE", "logs/app.log"))
    prepare_log_file(path)
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        handle.write(message + "\n")


def configure_logging(
    level: int = logging.INFO,
    log_file: str | None = None,
) -> None:
    """Configure logging; prefer explicit UTF-8 file (never shell redirect)."""
    target = (log_file or os.getenv("AUTO_FUND_LOG_FILE", "")).strip()
    handlers: list[logging.Handler] = []

    if target:
        path = Path(target)
        prepare_log_file(path)
        handlers.append(
            logging.FileHandler(path, mode="a", encoding="utf-8")
        )
    else:
        for stream in (sys.stdout, sys.stderr):
            reconfigure = getattr(stream, "reconfigure", None)
            if callable(reconfigure):
                try:
                    reconfigure(encoding="utf-8", errors="replace")
                except (OSError, ValueError):
                    pass
        handlers.append(logging.StreamHandler(sys.stdout))

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers,
        force=True,
    )


def log_job_banner(phase: str, log_file: str | None = None) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    append_log_line(f"=== {stamp} daily job {phase} ===", log_file)
