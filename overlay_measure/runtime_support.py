from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path


def app_data_root() -> Path:
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    base = Path(local_app_data) if local_app_data else Path.home() / ".local" / "share"
    root = base / "OverlayMeasure"
    root.mkdir(parents=True, exist_ok=True)
    return root


def build_runtime_logger() -> logging.Logger:
    logger = logging.getLogger("overlay_measure")
    if logger.handlers:
        return logger
    log_dir = app_data_root() / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(log_dir / "overlay_measure.log", maxBytes=5_000_000, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return logger


class RecoveryStore:
    def __init__(self):
        self.path = app_data_root() / "pending_measurement.json"

    def save(self, payload: dict) -> str:
        job_id = str(payload.get("job_id") or f"JOB-{uuid.uuid4().hex[:12].upper()}")
        data = {
            "job_id": job_id,
            "state": "running",
            "saved_at": datetime.now().isoformat(timespec="seconds"),
            **payload,
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(self.path)
        return job_id

    def load(self) -> dict | None:
        if not self.path.exists():
            return None
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if data.get("state", "running") == "running" else None
        except (OSError, ValueError, TypeError):
            return None

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)

    def finish(self, state: str, **updates) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            self.clear()
            return
        data.update(updates)
        data["state"] = state
        data["finished_at"] = datetime.now().isoformat(timespec="seconds")
        history = app_data_root() / "recovery_history.jsonl"
        with history.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(data, ensure_ascii=False) + "\n")
        self.clear()
