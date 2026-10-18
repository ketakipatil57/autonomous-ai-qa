"""Milestone 2 acceptance tests: TestPlan execution and evidence capture.

Verifies:
1. Action and TestPlan schema validation (step limits, action types).
2. End-to-end execution of a hand-written TestPlan via TestExecutor.
3. Outcome status reporting (PASSED vs FAILED).
4. Evidence collection on failure: screenshot (failure.png) and evidence.json.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest
from pydantic import ValidationError

from backend.app.agent.evidence import EvidenceData
from backend.app.agent.executor import TestExecutor
from backend.app.agent.plan_models import Action, TestCase, TestPlan
from backend.app.config import settings

SAMPLE_APP_URL = "http://localhost:3000"


def test_plan_models_validation():
    """Verify that Pydantic models reject invalid actions, >15 steps, and >8 tests."""
    # 1. Invalid action type
    with pytest.raises(ValidationError):
        Action(type="delete_all_files", target="#cart", value="boom")

    # 2. Maximum 15 steps per TestCase
    valid_step = Action(type="click", target="#btn")
    sixteen_steps = [valid_step] * 16
    with pytest.raises(ValidationError):
        TestCase(
            id="TC-TOO-LONG",
            title="Too many steps",
            category="functional",
            steps=sixteen_steps,
            expected="Should fail validation",
        )

    # 3. Maximum 8 tests per TestPlan
    valid_tc = TestCase(
        id="TC-01",
        title="Valid TC",
        category="functional",
        steps=[valid_step],
        expected="Valid",
    )
    nine_tests = [
        TestCase(
            id=f"TC-0{i}",
            title=f"Test {i}",
            category="functional",
            steps=[valid_step],
            expected="Valid",
        )
        for i in range(1, 10)
    ]
    with pytest.raises(ValidationError):
        TestPlan(
            source="fallback",
            branch="instruction",
            tests=nine_tests,
        )


def test_handwritten_test_plan_execution():
    """Execute a hand-written TestPlan containing one passing and one failing test."""
    session_id = "m2_verification_session"

    # Define hand-written test plan
    plan = TestPlan(
        source="fallback",
        branch="instruction",
        tests=[
            # 1. Passing Test: Add Headphones and verify cart summary
            TestCase(
                id="TC-PASS-01",
                title="Add product to cart and verify count",
                category="functional",
                steps=[
                    Action(type="goto", value=f"{SAMPLE_APP_URL}/index.html"),
                    Action(type="click", target="#add-p1"),
                    Action(type="expect_text", target="#cart-count", value="1"),
                ],
                expected="Cart count displays 1",
            ),
            # 2. Failing Test: Check for impossible total to verify failure handling
            TestCase(
                id="TC-FAIL-01",
                title="Assert incorrect total to test failure capture",
                category="functional",
                steps=[
                    Action(type="goto", value=f"{SAMPLE_APP_URL}/checkout.html"),
                    # Will fail because default total is $0.00
                    Action(type="expect_text", target="#checkout-total", value="$999.99"),
                ],
                expected="Checkout total matches $999.99 (intentionally fails)",
            ),
        ],
    )

    executor = TestExecutor()
    outcomes = executor.run_session(session_id=session_id, plan=plan)

    assert len(outcomes) == 2, f"Expected 2 outcomes, got {len(outcomes)}"

    # Check passing test outcome
    pass_outcome = next((o for o in outcomes if o.tc_id == "TC-PASS-01"), None)
    assert pass_outcome is not None
    assert pass_outcome.outcome == "passed", f"Expected passed, got {pass_outcome.outcome}"
    assert pass_outcome.failure_message is None

    # Check failing test outcome
    fail_outcome = next((o for o in outcomes if o.tc_id == "TC-FAIL-01"), None)
    assert fail_outcome is not None
    assert fail_outcome.outcome == "failed", f"Expected failed, got {fail_outcome.outcome}"
    assert fail_outcome.failure_message is not None
    assert "$999.99" in fail_outcome.failure_message

    # Verify evidence collection for the failing test
    storage_tc_dir = settings.STORAGE_DIR / session_id / "TC-FAIL-01"
    assert storage_tc_dir.exists(), f"Evidence directory {storage_tc_dir} does not exist"

    # 1. Screenshot verification
    screenshot_file = storage_tc_dir / "failure.png"
    assert screenshot_file.exists(), "Failure screenshot was not saved"
    assert screenshot_file.stat().st_size > 1000, "Screenshot file is unexpectedly empty"

    # 2. Evidence JSON verification
    evidence_file = storage_tc_dir / "evidence.json"
    assert evidence_file.exists(), "evidence.json was not saved"

    evidence = EvidenceData.load(session_id, "TC-FAIL-01", settings.STORAGE_DIR)
    assert evidence is not None
    assert evidence.session_id == session_id
    assert evidence.tc_id == "TC-FAIL-01"
    assert evidence.screenshot_path is not None
    assert "checkout.html" in (evidence.final_url or "")
    assert "$999.99" in (evidence.failure_message or "")


def test_console_and_network_evidence_capture():
    """Verify that 4xx HTTP responses and console messages are captured in evidence."""
    session_id = "m2_network_console_session"

    plan = TestPlan(
        source="fallback",
        branch="instruction",
        tests=[
            TestCase(
                id="TC-NET-01",
                title="Trigger 404 request and assert failure to capture evidence",
                category="negative",
                steps=[
                    # Navigating to a non-existent static resource triggers HTTP 404 response
                    Action(type="goto", value=f"{SAMPLE_APP_URL}/non_existent_page_404.html"),
                    # Expect text that won't exist to trigger failure and evidence capture
                    Action(type="expect_text", target="h1", value="Should Not Be Found"),
                ],
                expected="Triggers network 404 and captures network error in evidence",
            )
        ],
    )

    executor = TestExecutor()
    outcomes = executor.run_session(session_id=session_id, plan=plan)

    assert len(outcomes) == 1
    assert outcomes[0].outcome == "failed"

    evidence = EvidenceData.load(session_id, "TC-NET-01", settings.STORAGE_DIR)
    assert evidence is not None
    assert len(evidence.network_errors) > 0, "Expected at least one network error entry"

    net_err = next((n for n in evidence.network_errors if n.status == 404), None)
    assert net_err is not None, f"Expected 404 network entry, got: {evidence.network_errors}"
    assert "non_existent_page_404.html" in net_err.url

