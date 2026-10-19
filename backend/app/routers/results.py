"""FastAPI router for test results, bug reports, and rendered HTML reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from backend.app.agent.evidence import EvidenceData
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.models import BugReportModel, TestCaseModel, TestResultModel
from backend.app.schemas import (
    BugReportResponse,
    TestResultDetailResponse,
    TestResultResponse,
)

router = APIRouter(tags=["results"])


def _execution_test_case_id(result: TestResultModel, fallback: str) -> str:
    """Resolve the evidence folder ID, which can differ from a displayed test code."""
    evidence_path = result.evidence_path or result.screenshot_path
    return Path(evidence_path).parent.name if evidence_path else fallback


@router.get("/api/sessions/{session_id}/results", response_model=List[TestResultResponse])
def get_session_results(session_id: str, db: Session = Depends(get_db)):
    """Retrieve all test results for a specific session."""
    results = (
        db.query(TestResultModel)
        .filter(TestResultModel.session_id == session_id)
        .order_by(TestResultModel.created_at.asc())
        .all()
    )

    out = []
    for r in results:
        tc = r.test_case
        tc_code = tc.tc_code if tc else "UNKNOWN"
        title = tc.title if tc else "Unknown Test"
        category = tc.category if tc else "functional"
        execution_tc_id = _execution_test_case_id(r, tc_code)

        screenshot_url = (
            f"/storage/{r.session_id}/{execution_tc_id}/failure.png"
            if r.screenshot_path and Path(r.screenshot_path).exists()
            else None
        )
        report_url = f"/api/bugs/{r.id}/report" if r.status == "FAILED" else None

        item = TestResultResponse(
            id=r.id,
            session_id=r.session_id,
            test_case_id=r.test_case_id,
            tc_code=tc_code,
            title=title,
            category=category,
            status=r.status,
            reason=r.reason,
            first_run_outcome=r.first_run_outcome,
            recheck_outcome=r.recheck_outcome,
            duration_ms=r.duration_ms,
            failure_message=r.failure_message,
            explanation=r.explanation,
            screenshot_url=screenshot_url,
            report_url=report_url,
        )
        out.append(item)

    return out


@router.get("/api/results/{result_id}", response_model=TestResultDetailResponse)
def get_result_detail(result_id: str, db: Session = Depends(get_db)):
    """Retrieve comprehensive result details including full evidence, console, and network logs."""
    r = db.query(TestResultModel).filter(TestResultModel.id == result_id).first()
    if not r:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Result not found")

    tc = r.test_case
    tc_code = tc.tc_code if tc else "UNKNOWN"
    title = tc.title if tc else "Unknown Test"
    category = tc.category if tc else "functional"

    steps = []
    if tc and tc.steps_json:
        try:
            steps = json.loads(tc.steps_json)
        except Exception:
            pass

    # Load evidence if present
    execution_tc_id = _execution_test_case_id(r, tc_code)
    evidence_data = EvidenceData.load(r.session_id, execution_tc_id, settings.STORAGE_DIR)
    console_logs = []
    network_errors = []
    final_url = None

    if evidence_data:
        console_logs = [c.model_dump() for c in evidence_data.console_logs]
        network_errors = [n.model_dump() for n in evidence_data.network_errors]
        final_url = evidence_data.final_url

    screenshot_url = (
        f"/storage/{r.session_id}/{execution_tc_id}/failure.png"
        if r.screenshot_path and Path(r.screenshot_path).exists()
        else None
    )
    report_url = f"/api/bugs/{r.id}/report" if r.status == "FAILED" else None

    return TestResultDetailResponse(
        id=r.id,
        session_id=r.session_id,
        test_case_id=r.test_case_id,
        tc_code=tc_code,
        title=title,
        category=category,
        status=r.status,
        reason=r.reason,
        first_run_outcome=r.first_run_outcome,
        recheck_outcome=r.recheck_outcome,
        duration_ms=r.duration_ms,
        failure_message=r.failure_message,
        explanation=r.explanation,
        screenshot_url=screenshot_url,
        report_url=report_url,
        steps=steps,
        expected=tc.expected if tc else None,
        console_logs=console_logs,
        network_errors=network_errors,
        final_url=final_url,
    )


@router.get("/api/bugs", response_model=List[BugReportResponse])
def list_bugs(session_id: Optional[str] = None, db: Session = Depends(get_db)):
    """List confirmed bug reports, optionally filtered by session ID."""
    query = db.query(BugReportModel)
    if session_id:
        query = query.filter(BugReportModel.session_id == session_id)

    bugs = query.order_by(BugReportModel.created_at.desc()).all()
    out = []
    for b in bugs:
        repro = []
        if b.reproduction_steps_json:
            try:
                repro = json.loads(b.reproduction_steps_json)
            except Exception:
                pass

        out.append(
            BugReportResponse(
                id=b.id,
                session_id=b.session_id,
                test_result_id=b.test_result_id,
                bug_code=b.bug_code,
                title=b.title,
                severity=b.severity,
                reproduction_steps=repro,
                expected=b.expected,
                actual=b.actual,
                report_url=f"/api/bugs/{b.id}/report",
                created_at=b.created_at,
            )
        )
    return out


@router.get("/api/bugs/{bug_identifier}/report", response_class=HTMLResponse)
def get_bug_report_html(bug_identifier: str, db: Session = Depends(get_db)):
    """Return raw rendered HTML for a bug report by bug ID, test_result_id, or bug code."""
    bug = (
        db.query(BugReportModel)
        .filter(
            (BugReportModel.id == bug_identifier)
            | (BugReportModel.test_result_id == bug_identifier)
            | (BugReportModel.bug_code == bug_identifier)
        )
        .first()
    )

    if bug and bug.report_path and Path(bug.report_path).exists():
        with open(bug.report_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    # Fallback search by session/tc if identifier is result_id
    res = db.query(TestResultModel).filter(TestResultModel.id == bug_identifier).first()
    if res and res.report_path and Path(res.report_path).exists():
        with open(res.report_path, "r", encoding="utf-8") as f:
            return HTMLResponse(content=f.read())

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="HTML bug report not found")
