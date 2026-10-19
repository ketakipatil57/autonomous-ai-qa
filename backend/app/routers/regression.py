"""FastAPI router for saved regression tests and automated rerun triggering."""

from __future__ import annotations

import json
import threading
import uuid
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from backend.app.agent.orchestrator import PipelineOrchestrator
from backend.app.agent.plan_models import Action, TestCase, TestPlan
from backend.app.agent.safety import SafetyError, validate_test_plan_safety
from backend.app.config import settings
from backend.app.db import get_db
from backend.app.models import RegressionTestModel, TestSession
from backend.app.schemas import RegressionTestResponse, SessionResponse

router = APIRouter(prefix="/api/regression", tags=["regression"])


@router.get("", response_model=List[RegressionTestResponse])
def list_regression_tests(db: Session = Depends(get_db)):
    """List all saved regression test cases."""
    tests = (
        db.query(RegressionTestModel)
        .order_by(RegressionTestModel.created_at.desc())
        .all()
    )
    responses = []
    for test in tests:
        try:
            steps = json.loads(test.steps_json)
        except (json.JSONDecodeError, TypeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Saved regression test '{test.title}' has invalid steps: {exc}",
            ) from exc
        responses.append(
            RegressionTestResponse.model_validate(
                {**test.__dict__, "steps": steps}
            )
        )
    return responses


@router.post("/run", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
def run_regression_suite(db: Session = Depends(get_db)):
    """Rerun all saved regression tests as a new testing session."""
    saved_tests = (
        db.query(RegressionTestModel)
        .order_by(RegressionTestModel.created_at.asc(), RegressionTestModel.id.asc())
        .all()
    )
    if not saved_tests:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No saved regression tests found to run.",
        )

    # Reconstruct safe plans of at most the configured per-run maximum.
    test_cases: list[TestCase] = []
    plans: list[TestPlan] = []
    batch_size = min(8, settings.MAX_TESTS_PER_RUN)
    if batch_size < 1:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="MAX_TESTS_PER_RUN must be at least 1.",
        )
    for st in saved_tests:
        try:
            raw_steps = json.loads(st.steps_json)
            steps = [Action.model_validate(step) for step in raw_steps]
            tc = TestCase(
                # The database ID uniquely identifies a saved case even when two
                # source sessions used the same display test code.
                id=st.id,
                title=st.title,
                category=st.category if st.category in ("functional", "validation", "edge", "negative") else "functional",
                steps=steps,
                expected=st.expected,
            )
        except (json.JSONDecodeError, TypeError, ValidationError) as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Saved regression test '{st.title}' is invalid: {exc}",
            ) from exc

        test_cases.append(tc)
        if len(test_cases) == batch_size:
            plans.append(
                TestPlan(source="fallback", branch="instruction", tests=test_cases)
            )
            test_cases = []

    if test_cases:
        plans.append(
            TestPlan(source="fallback", branch="instruction", tests=test_cases)
        )

    if not plans:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to parse saved regression test definitions.",
        )

    try:
        for plan in plans:
            validate_test_plan_safety(plan)
    except SafetyError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Saved regression suite is not safe to run: {exc}",
        ) from exc

    # Find app_url from the last session or default
    last_session = (
        db.query(TestSession)
        .order_by(TestSession.created_at.desc())
        .first()
    )
    app_url = last_session.app_url if last_session else "http://localhost:3000"

    new_session_id = str(uuid.uuid4())
    new_session = TestSession(
        id=new_session_id,
        app_url=app_url,
        description="Regression test suite execution",
        instruction="Rerun saved regression tests",
        branch="instruction",
        planner_source=plans[0].source,
        status="RUNNING",
        stage="planning",
        current_step=(
            f"Initializing regression run with {len(saved_tests)} tests "
            f"in {len(plans)} batch(es)..."
        ),
        tests_done=0,
        tests_total=len(saved_tests),
    )
    db.add(new_session)
    db.commit()
    db.refresh(new_session)

    # Launch pipeline in background thread
    orchestrator = PipelineOrchestrator()
    worker_thread = threading.Thread(
        target=orchestrator.run_pipeline,
        args=(new_session_id, plans),
        name=f"regression-worker-{new_session_id[:8]}",
        daemon=True,
    )
    worker_thread.start()

    return new_session
