"""FastAPI router for session creation, background start, and status polling."""

from __future__ import annotations

import threading
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.app.agent.orchestrator import PipelineOrchestrator
from backend.app.agent.safety import SafetyError, validate_url
from backend.app.db import get_db
from backend.app.models import TestSession
from backend.app.schemas import (
    RunRequest,
    SessionCounts,
    SessionDetailResponse,
    SessionResponse,
)

router = APIRouter(prefix="/api/sessions", tags=["sessions"])


@router.post("", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def create_session(request: RunRequest, db: Session = Depends(get_db)):
    """Create a new test session in QUEUED status."""
    try:
        validate_url(request.app_url)
    except SafetyError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))

    branch = "instruction" if request.instruction and request.instruction.strip() else "exploration"
    session_id = str(uuid.uuid4())

    session = TestSession(
        id=session_id,
        app_url=request.app_url,
        description=request.description,
        instruction=request.instruction,
        branch=branch,
        planner_source="fallback",
        status="QUEUED",
        stage=None,
        current_step="Session queued for execution",
        tests_done=0,
        tests_total=0,
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return session


@router.post("/{session_id}/start", response_model=SessionResponse)
def start_session(session_id: str, db: Session = Depends(get_db)):
    """Start pipeline execution in a background worker thread."""
    session = db.query(TestSession).filter(TestSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    if session.status == "RUNNING":
        return session

    session.status = "RUNNING"
    session.stage = "planning" if session.branch == "instruction" else "exploring"
    session.current_step = "Initializing agent pipeline..."
    db.commit()
    db.refresh(session)

    # Launch Playwright sync pipeline in a separate background thread
    orchestrator = PipelineOrchestrator()
    worker_thread = threading.Thread(
        target=orchestrator.run_pipeline,
        args=(session_id,),
        name=f"pipeline-worker-{session_id[:8]}",
        daemon=True,
    )
    worker_thread.start()

    return session


@router.get("/{session_id}", response_model=SessionDetailResponse)
def get_session(session_id: str, db: Session = Depends(get_db)):
    """Retrieve session details, current stage, execution progress, and metrics."""
    session = db.query(TestSession).filter(TestSession.id == session_id).first()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")

    detail = SessionDetailResponse.model_validate(session)
    detail.counts = SessionCounts(
        total=session.total_count,
        passed=session.passed_count,
        failed=session.failed_count,
        needs_review=session.needs_review_count,
    )
    return detail


@router.get("", response_model=List[SessionResponse])
def list_sessions(limit: int = 20, db: Session = Depends(get_db)):
    """List recent testing sessions."""
    sessions = (
        db.query(TestSession)
        .order_by(TestSession.created_at.desc())
        .limit(limit)
        .all()
    )
    return sessions
