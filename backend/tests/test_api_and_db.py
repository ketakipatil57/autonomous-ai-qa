"""Milestone 5 acceptance tests: FastAPI REST API, Database Layer, and Orchestrator.

Verifies:
1. Database schema and table creation on SQLite.
2. Session creation (POST /api/sessions) and safety validation.
3. Session start behavior (POST /api/sessions/{id}/start) returning quickly with RUNNING.
4. Session status retrieval (GET /api/sessions/{id}) with progress and counts.
5. Result retrieval (GET /api/sessions/{id}/results and GET /api/results/{id}).
6. Bug listing (GET /api/bugs) and rendered HTML report retrieval (GET /api/bugs/{id}/report).
7. Regression endpoints (GET /api/regression and POST /api/regression/run).
8. Orchestrator pipeline lifecycle with state persistence and regression saving.
"""

from __future__ import annotations

import json
import os
import tempfile
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

# Configure SQLite test database before importing app modules
TEST_DB_FILE = Path(tempfile.gettempdir()) / f"test_qa_{uuid.uuid4().hex[:8]}.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_FILE}"
os.environ["DATABASE_URL"] = TEST_DB_URL

from backend.app.agent.orchestrator import PipelineOrchestrator
from backend.app.agent.plan_models import Action, TestCase, TestOutcome, TestPlan, TestResult
from backend.app.config import settings
from backend.app.db import Base, get_db
from backend.app.main import app
from backend.app.models import (
    BugReportModel,
    EvidenceModel,
    RegressionTestModel,
    TestCaseModel,
    TestResultModel,
    TestSession,
)

test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)


def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()


app.dependency_overrides[get_db] = override_get_db


@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    """Create all database tables on test SQLite database and clean up afterward."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)
    if TEST_DB_FILE.exists():
        try:
            TEST_DB_FILE.unlink()
        except Exception:
            pass


@pytest.fixture
def db_session():
    """Provide a clean database session per test."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client():
    """FastAPI TestClient fixture."""
    return TestClient(app)


# --- 1. Database & Table Creation Tests ---

def test_db_table_creation():
    """Verify that all 6 required tables exist in the SQLite database."""
    tables = test_engine.table_names() if hasattr(test_engine, "table_names") else []
    if not tables:
        from sqlalchemy import inspect
        inspector = inspect(test_engine)
        tables = inspector.get_table_names()

    expected_tables = {
        "test_sessions",
        "test_cases",
        "test_results",
        "bug_reports",
        "evidence",
        "regression_tests",
    }
    assert expected_tables.issubset(set(tables)), f"Missing tables: {expected_tables - set(tables)}"


# --- 2. Session Creation & Safety Tests ---

def test_create_session_success(client: TestClient):
    """POST /api/sessions with valid URL returns 201 and status QUEUED."""
    payload = {
        "app_url": "http://localhost:3000",
        "description": "Sample Shop",
        "instruction": "Test login with wrong password",
        "max_tests": 5,
    }
    response = client.post("/api/sessions", json=payload)
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "QUEUED"
    assert data["branch"] == "instruction"
    assert data["app_url"] == "http://localhost:3000"
    assert "id" in data


def test_create_session_safety_rejection(client: TestClient):
    """POST /api/sessions with disallowed external host returns 400."""
    payload = {
        "app_url": "http://malicious-external-site.com",
        "description": "Blocked",
    }
    response = client.post("/api/sessions", json=payload)
    assert response.status_code == 400
    assert "blocked" in response.json()["detail"].lower()


# --- 3. Session Start & Polling Tests ---

def test_start_session_endpoint(client: TestClient):
    """POST /api/sessions/{id}/start immediately marks session as RUNNING without blocking."""
    # 1. Create session
    create_res = client.post("/api/sessions", json={"app_url": "http://localhost:3000"})
    session_id = create_res.json()["id"]

    # 2. Mock background worker to avoid launching real Playwright in this quick unit test
    with patch("backend.app.agent.orchestrator.PipelineOrchestrator.run_pipeline") as mock_pipeline:
        start_res = client.post(f"/api/sessions/{session_id}/start")
        assert start_res.status_code == 200
        data = start_res.json()
        assert data["status"] == "RUNNING"


def test_get_session_status_and_counts(client: TestClient, db_session):
    """GET /api/sessions/{id} returns progress stages, steps, and metrics counts."""
    session_id = str(uuid.uuid4())
    session = TestSession(
        id=session_id,
        app_url="http://localhost:3000",
        branch="exploration",
        status="RUNNING",
        stage="executing",
        current_step="Executing test 2 of 5...",
        tests_done=2,
        tests_total=5,
        total_count=5,
        passed_count=1,
        failed_count=1,
        needs_review_count=0,
    )
    db_session.add(session)
    db_session.commit()

    res = client.get(f"/api/sessions/{session_id}")
    assert res.status_code == 200
    data = res.json()
    assert data["id"] == session_id
    assert data["stage"] == "executing"
    assert data["tests_done"] == 2
    assert data["tests_total"] == 5
    assert data["counts"]["passed"] == 1
    assert data["counts"]["failed"] == 1


# --- 4. Test Results & Detail Endpoints ---

def test_get_session_results_and_detail(client: TestClient, db_session):
    """Verify GET /api/sessions/{id}/results and GET /api/results/{id}."""
    session_id = str(uuid.uuid4())
    tc_id = str(uuid.uuid4())
    result_id = str(uuid.uuid4())

    session = TestSession(
        id=session_id,
        app_url="http://localhost:3000",
        branch="instruction",
        status="COMPLETED",
    )
    tc = TestCaseModel(
        id=tc_id,
        session_id=session_id,
        tc_code="TC-01",
        title="Check Login Error",
        category="negative",
        steps_json=json.dumps([{"type": "fill", "target": "#email", "value": "test@demo.com"}]),
        expected="Invalid password error",
    )
    res = TestResultModel(
        id=result_id,
        session_id=session_id,
        test_case_id=tc_id,
        status="FAILED",
        reason="Confirmed bug: consistent failure",
        first_run_outcome="failed",
        recheck_outcome="failed",
        duration_ms=450.0,
        failure_message="AssertionError: Expected error message not found",
        explanation="The login form allowed access instead of rejecting.",
    )
    db_session.add_all([session, tc, res])
    db_session.commit()

    # List results for session
    list_res = client.get(f"/api/sessions/{session_id}/results")
    assert list_res.status_code == 200
    results_data = list_res.json()
    assert len(results_data) == 1
    assert results_data[0]["tc_code"] == "TC-01"
    assert results_data[0]["status"] == "FAILED"

    # Detail endpoint
    detail_res = client.get(f"/api/results/{result_id}")
    assert detail_res.status_code == 200
    detail_data = detail_res.json()
    assert detail_data["id"] == result_id
    assert detail_data["explanation"] == "The login form allowed access instead of rejecting."
    assert len(detail_data["steps"]) == 1


def test_regression_result_evidence_uses_execution_id(client: TestClient, db_session, tmp_path, monkeypatch):
    """Regression display codes can differ from the execution evidence folder ID."""
    from backend.app.agent.evidence import EvidenceData
    from backend.app.routers import results as results_router

    session_id = str(uuid.uuid4())
    test_case_id = str(uuid.uuid4())
    result_id = str(uuid.uuid4())
    execution_id = str(uuid.uuid4())
    storage_dir = tmp_path / "storage"
    evidence = EvidenceData(
        session_id=session_id,
        tc_id=execution_id,
        final_url="http://localhost:3000/index.html",
    )
    evidence_path = evidence.save(storage_dir)
    screenshot_path = storage_dir / session_id / execution_id / "failure.png"
    screenshot_path.write_bytes(b"image")
    monkeypatch.setattr(results_router.settings, "STORAGE_DIR", storage_dir)

    session = TestSession(
        id=session_id,
        app_url="http://localhost:3000",
        branch="instruction",
        status="COMPLETED",
    )
    test_case = TestCaseModel(
        id=test_case_id,
        session_id=session_id,
        tc_code="TC-01",
        title="Regression result",
        category="functional",
        steps_json=json.dumps(
            [{"type": "goto", "value": "http://localhost:3000/index.html"}]
        ),
        expected="Loads the products page",
    )
    result = TestResultModel(
        id=result_id,
        session_id=session_id,
        test_case_id=test_case_id,
        status="FAILED",
        reason="Confirmed bug",
        first_run_outcome="failed",
        screenshot_path=str(screenshot_path),
        evidence_path=str(evidence_path),
    )
    db_session.add_all([session, test_case, result])
    db_session.commit()

    list_response = client.get(f"/api/sessions/{session_id}/results")
    assert list_response.status_code == 200
    assert list_response.json()[0]["screenshot_url"] == (
        f"/storage/{session_id}/{execution_id}/failure.png"
    )

    detail_response = client.get(f"/api/results/{result_id}")
    assert detail_response.status_code == 200
    assert detail_response.json()["final_url"] == "http://localhost:3000/index.html"


# --- 5. Bug Reports & HTML View Endpoints ---

def test_bug_reports_and_html_view(client: TestClient, db_session, tmp_path):
    """Verify GET /api/bugs and GET /api/bugs/{id}/report."""
    session_id = str(uuid.uuid4())
    result_id = str(uuid.uuid4())
    bug_id = str(uuid.uuid4())

    # Create dummy bug report HTML file
    report_file = tmp_path / "bug_report.html"
    report_file.write_text("<html><body><h1>Bug Report BUG-001</h1></body></html>", encoding="utf-8")

    session = TestSession(
        id=session_id,
        app_url="http://localhost:3000",
        branch="instruction",
        status="COMPLETED",
    )
    res = TestResultModel(
        id=result_id,
        session_id=session_id,
        test_case_id=str(uuid.uuid4()),
        status="FAILED",
        reason="Confirmed bug",
        first_run_outcome="failed",
    )
    bug = BugReportModel(
        id=bug_id,
        session_id=session_id,
        test_result_id=result_id,
        bug_code="BUG-test-1",
        title="Login accepts wrong password",
        severity="HIGH",
        reproduction_steps_json=json.dumps(["Step 1", "Step 2"]),
        expected="Show error",
        actual="Logged in",
        report_path=str(report_file),
    )
    db_session.add_all([session, res, bug])
    db_session.commit()

    # Query bug reports
    bugs_res = client.get("/api/bugs")
    assert bugs_res.status_code == 200
    bugs = bugs_res.json()
    assert any(b["id"] == bug_id for b in bugs)

    # Fetch rendered HTML report
    html_res = client.get(f"/api/bugs/{bug_id}/report")
    assert html_res.status_code == 200
    assert "<h1>Bug Report BUG-001</h1>" in html_res.text


# --- 6. Regression Test Endpoints ---

def test_regression_endpoints(client: TestClient, db_session):
    """Verify GET /api/regression and POST /api/regression/run."""
    reg_id = str(uuid.uuid4())
    reg = RegressionTestModel(
        id=reg_id,
        source_session_id=str(uuid.uuid4()),
        test_case_id=str(uuid.uuid4()),
        tc_code="TC-01",
        title="Valid Login Flow",
        category="functional",
        steps_json=json.dumps([{"type": "fill", "target": "#email", "value": "test@demo.com"}]),
        expected="Redirects to index.html",
        last_status="PASSED",
        run_count=1,
    )
    db_session.add(reg)
    db_session.commit()

    # List regression tests
    list_res = client.get("/api/regression")
    assert list_res.status_code == 200
    reg_list = list_res.json()
    assert any(r["id"] == reg_id for r in reg_list)
    assert next(r for r in reg_list if r["id"] == reg_id)["steps"] == [
        {"type": "fill", "target": "#email", "value": "test@demo.com"}
    ]

    # Run regression suite
    with patch("backend.app.agent.orchestrator.PipelineOrchestrator.run_pipeline") as mock_pipeline:
        run_res = client.post("/api/regression/run")
        assert run_res.status_code == 201
        run_data = run_res.json()
        assert run_data["status"] == "RUNNING"
        assert run_data["instruction"] == "Rerun saved regression tests"


# --- 7. Orchestrator Pipeline Unit Test with SQLite ---

def test_orchestrator_pipeline_mock_execution(db_session):
    """Verify that PipelineOrchestrator updates all stages, results, and regression tests."""
    session_id = str(uuid.uuid4())
    session = TestSession(
        id=session_id,
        app_url="http://localhost:3000",
        branch="instruction",
        instruction="Test login",
        status="QUEUED",
    )
    db_session.add(session)
    db_session.commit()

    # Mock planner, executor, verifier, reporter
    mock_plan = TestPlan(
        source="fallback",
        branch="instruction",
        tests=[
            TestCase(
                id="TC-01",
                title="Mock Test Passing",
                category="functional",
                steps=[Action(type="goto", value="http://localhost:3000/index.html")],
                expected="Loads index",
            )
        ],
    )

    mock_planner = MagicMock()
    mock_planner.plan_from_instruction.return_value = mock_plan

    mock_executor = MagicMock()
    mock_executor.run_session.return_value = [
        TestOutcome(tc_id="TC-01", outcome="passed", duration_ms=100.0)
    ]

    mock_verifier = MagicMock()
    mock_verifier.verify_session.return_value = [
        TestResult(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tc_id="TC-01",
            status="PASSED",
            reason="First run passed",
            first_run_outcome="passed",
            duration_ms=100.0,
        )
    ]

    mock_reporter = MagicMock()
    mock_reporter.generate_reports.return_value = []

    # Patch SessionLocal inside orchestrator to use test database
    with patch("backend.app.agent.orchestrator.SessionLocal", TestingSessionLocal):
        orchestrator = PipelineOrchestrator(
            planner=mock_planner,
            executor=mock_executor,
            verifier=mock_verifier,
            reporter=mock_reporter,
        )
        orchestrator.run_pipeline(session_id)

    # Verify session completed in database
    db_session.expire_all()
    finished = db_session.query(TestSession).filter(TestSession.id == session_id).first()
    assert finished.status == "COMPLETED"
    assert finished.stage == "done"
    assert finished.passed_count == 1
    assert finished.failed_count == 0

    # Verify passed test was saved to regression_tests
    reg_test = db_session.query(RegressionTestModel).filter(RegressionTestModel.title == "Mock Test Passing").first()
    assert reg_test is not None
    assert reg_test.last_status == "PASSED"


def test_orchestrator_regression_rerun_updates_saved_tests(db_session):
    """Every regression outcome updates its own saved row, including failures."""
    session_id = str(uuid.uuid4())
    regression_rows = [
        RegressionTestModel(
            id=str(uuid.uuid4()),
            source_session_id=str(uuid.uuid4()),
            test_case_id=str(uuid.uuid4()),
            tc_code=f"TC-0{index}",
            title=f"Regression case {index}",
            category="functional",
            steps_json=json.dumps(
                [{"type": "goto", "value": "http://localhost:3000/index.html"}]
            ),
            expected="Loads the products page",
            last_status="PASSED",
            run_count=1,
        )
        for index in (1, 2)
    ]
    session = TestSession(
        id=session_id,
        app_url="http://localhost:3000",
        branch="instruction",
        status="QUEUED",
    )
    db_session.add_all([session, *regression_rows])
    db_session.commit()

    custom_plan = TestPlan(
        source="fallback",
        branch="instruction",
        tests=[
            TestCase(
                id=regression.id,
                title=regression.title,
                category="functional",
                steps=[Action(type="goto", value="http://localhost:3000/index.html")],
                expected=regression.expected,
            )
            for regression in regression_rows
        ],
    )
    mock_executor = MagicMock()
    mock_executor.run_session.return_value = [
        TestOutcome(tc_id=regression_rows[0].id, outcome="passed", duration_ms=100.0),
        TestOutcome(tc_id=regression_rows[1].id, outcome="failed", duration_ms=120.0),
    ]
    mock_verifier = MagicMock()
    mock_verifier.verify_session.return_value = [
        TestResult(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tc_id=regression_rows[0].id,
            status="PASSED",
            reason="First run passed",
            first_run_outcome="passed",
            duration_ms=100.0,
        ),
        TestResult(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tc_id=regression_rows[1].id,
            status="FAILED",
            reason="Confirmed bug",
            first_run_outcome="failed",
            recheck_outcome="failed",
            duration_ms=240.0,
        ),
    ]

    with patch("backend.app.agent.orchestrator.SessionLocal", TestingSessionLocal):
        orchestrator = PipelineOrchestrator(
            executor=mock_executor,
            verifier=mock_verifier,
            reporter=MagicMock(),
        )
        orchestrator.run_pipeline(session_id, custom_plan)

    db_session.expire_all()
    updated_rows = {
        regression.id: regression
        for regression in db_session.query(RegressionTestModel)
        .filter(RegressionTestModel.id.in_([row.id for row in regression_rows]))
        .all()
    }
    assert updated_rows[regression_rows[0].id].last_status == "PASSED"
    assert updated_rows[regression_rows[0].id].run_count == 2
    assert updated_rows[regression_rows[1].id].last_status == "FAILED"
    assert updated_rows[regression_rows[1].id].run_count == 2
    assert all(row.last_run_at is not None for row in updated_rows.values())
    persisted_codes = {
        test_case.tc_code
        for test_case in db_session.query(TestCaseModel)
        .filter(TestCaseModel.session_id == session_id)
        .all()
    }
    assert persisted_codes == {"TC-01", "TC-02"}


def test_regression_endpoint_batches_all_saved_tests_and_updates_metadata(
    client: TestClient, db_session, monkeypatch
):
    """Replay every saved case in plans of at most eight, preserving each ID."""
    monkeypatch.setattr(settings, "MAX_TESTS_PER_RUN", 20)
    db_session.query(RegressionTestModel).delete()
    db_session.commit()
    cases = []
    for index in range(10):
        case_id = str(uuid.uuid4())
        cases.append(
            RegressionTestModel(
                id=case_id,
                source_session_id=str(uuid.uuid4()),
                test_case_id=str(uuid.uuid4()),
                tc_code=f"TC-{index:02d}",
                title="Shared title" if index < 2 else f"Regression case {index}",
                category="functional",
                steps_json=json.dumps(
                    [
                        {
                            "type": "goto",
                            "value": "http://localhost:3000/index.html",
                        },
                        {
                            "type": "expect_text",
                            "target": "h1",
                            "value": f"case-{index}",
                        },
                    ]
                ),
                expected=f"Case {index} is valid",
                last_status="NEEDS_REVIEW",
                run_count=3,
            )
        )
    db_session.add_all(cases)
    db_session.commit()

    executor = MagicMock()
    executor.run_session.side_effect = lambda run_session_id, plan: [
        TestOutcome(tc_id=tc.id, outcome="passed", duration_ms=10.0)
        for tc in plan.tests
    ]
    verifier = MagicMock()
    verifier.verify_session.side_effect = lambda session_id, plan, first_run_outcomes, app_url: [
        TestResult(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tc_id=tc.id,
            status="PASSED",
            reason="First run passed",
            first_run_outcome="passed",
            duration_ms=10.0,
        )
        for tc in plan.tests
    ]
    orchestrator = PipelineOrchestrator(
        executor=executor,
        verifier=verifier,
        reporter=MagicMock(),
    )

    class ImmediateThread:
        def __init__(self, target, args, **kwargs):
            self.target = target
            self.args = args

        def start(self):
            self.target(*self.args)

    with (
        patch(
            "backend.app.routers.regression.PipelineOrchestrator",
            return_value=orchestrator,
        ),
        patch("backend.app.routers.regression.threading.Thread", ImmediateThread),
        patch("backend.app.agent.orchestrator.SessionLocal", TestingSessionLocal),
    ):
        response = client.post("/api/regression/run")

    assert response.status_code == 201
    run_session_id = response.json()["id"]
    assert client.get(f"/api/sessions/{run_session_id}").json()["tests_total"] == 10
    assert [len(call.args[1].tests) for call in executor.run_session.call_args_list] == [
        8,
        2,
    ]
    assert all(len(call.args[1].tests) <= 8 for call in executor.run_session.call_args_list)
    replayed_ids = [
        tc.id
        for call in executor.run_session.call_args_list
        for tc in call.args[1].tests
    ]
    assert set(replayed_ids) == {case.id for case in cases}
    assert len(replayed_ids) == len(set(replayed_ids)) == 10

    db_session.expire_all()
    updated_cases = (
        db_session.query(RegressionTestModel)
        .filter(RegressionTestModel.id.in_([case.id for case in cases]))
        .all()
    )
    assert len(updated_cases) == 10
    assert all(case.last_run_at is not None for case in updated_cases)
    assert all(case.last_status == "PASSED" for case in updated_cases)
    assert all(case.run_count == 4 for case in updated_cases)
    assert db_session.query(TestCaseModel).filter(
        TestCaseModel.session_id == run_session_id
    ).count() == 10


def test_orchestrator_autosaves_same_title_tests_as_distinct_cases(db_session):
    """Different test codes and definitions must not collapse on a shared title."""
    session_id = str(uuid.uuid4())
    db_session.add(
        TestSession(
            id=session_id,
            app_url="http://localhost:3000",
            instruction="Run duplicate-title tests",
            branch="instruction",
            status="QUEUED",
        )
    )
    db_session.commit()

    cases = [
        TestCase(
            id="TC-DUP-1",
            title="Same title",
            category="functional",
            steps=[Action(type="goto", value="http://localhost:3000/index.html")],
            expected="Index is shown",
        ),
        TestCase(
            id="TC-DUP-2",
            title="Same title",
            category="functional",
            steps=[Action(type="goto", value="http://localhost:3000/checkout.html")],
            expected="Checkout is shown",
        ),
    ]
    plan = TestPlan(source="fallback", branch="instruction", tests=cases)
    executor = MagicMock()
    executor.run_session.return_value = [
        TestOutcome(tc_id=tc.id, outcome="passed", duration_ms=10.0)
        for tc in cases
    ]
    verifier = MagicMock()
    verifier.verify_session.return_value = [
        TestResult(
            id=str(uuid.uuid4()),
            session_id=session_id,
            tc_id=tc.id,
            status="PASSED",
            reason="First run passed",
            first_run_outcome="passed",
            duration_ms=10.0,
        )
        for tc in cases
    ]
    planner = MagicMock()
    planner.plan_from_instruction.return_value = plan

    with patch("backend.app.agent.orchestrator.SessionLocal", TestingSessionLocal):
        PipelineOrchestrator(
            planner=planner,
            executor=executor,
            verifier=verifier,
            reporter=MagicMock(),
        ).run_pipeline(session_id)

    duplicate_title_rows = (
        db_session.query(RegressionTestModel)
        .filter(RegressionTestModel.title == "Same title")
        .all()
    )
    assert {row.tc_code for row in duplicate_title_rows} == {"TC-DUP-1", "TC-DUP-2"}
    assert len({row.id for row in duplicate_title_rows}) == 2
