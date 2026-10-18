"""Evidence collection and serialization models.

Captures failure screenshot, console errors/warnings, failed/4xx/5xx network requests,
final URL, page title, and pytest failure excerpts in storage/<session>/<tc>/evidence.json.
"""

from __future__ import annotations

import json
from pathlib import Path
from pydantic import BaseModel, Field


class ConsoleEntry(BaseModel):
    """Captured browser console error or warning."""

    type: str  # "error" | "warning"
    text: str
    location: str | None = None


class NetworkEntry(BaseModel):
    """Captured failed network request or HTTP error (>= 400)."""

    method: str
    url: str
    status: int | None = None
    failure: str | None = None


class EvidenceData(BaseModel):
    """Structured evidence package for a test execution."""

    session_id: str
    tc_id: str
    screenshot_path: str | None = None
    console_logs: list[ConsoleEntry] = Field(default_factory=list)
    network_errors: list[NetworkEntry] = Field(default_factory=list)
    final_url: str | None = None
    page_title: str | None = None
    failure_message: str | None = None

    def get_dir(self, storage_root: Path | str) -> Path:
        """Return the target directory for this session and test case."""
        p = Path(storage_root) / self.session_id / self.tc_id
        p.mkdir(parents=True, exist_ok=True)
        return p

    def save(self, storage_root: Path | str) -> Path:
        """Persist evidence data to storage/<session>/<tc>/evidence.json."""
        target_dir = self.get_dir(storage_root)
        file_path = target_dir / "evidence.json"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(self.model_dump_json(indent=2))
        return file_path

    @classmethod
    def load(cls, session_id: str, tc_id: str, storage_root: Path | str) -> EvidenceData | None:
        """Load evidence data from storage/<session>/<tc>/evidence.json if present."""
        file_path = Path(storage_root) / session_id / tc_id / "evidence.json"
        if not file_path.exists():
            return None
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)


def update_evidence_failure(
    session_id: str,
    tc_id: str,
    failure_message: str,
    storage_root: Path | str,
) -> EvidenceData | None:
    """Update existing evidence file with formatted pytest failure message."""
    evidence = EvidenceData.load(session_id, tc_id, storage_root)
    if evidence:
        evidence.failure_message = failure_message
        evidence.save(storage_root)
        return evidence
    return None
