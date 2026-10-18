"""Milestone 4 acceptance tests: Verifier, Status Rules, Recheck Logic, and Reporter.

Verifies:
1. Failure message normalization (ignoring timings, hex pointers, UUIDs, random digits).
2. Section 6.8 status-transition rules:
   - First run passed -> PASSED.
   - Environment / setup error -> NEEDS_REVIEW with reason 'environment'.
   - Flaky test (failed first, passed recheck) -> NEEDS_REVIEW.
   - Consistent failure (same failure message) -> FAILED.
   - Inconsistent failure (different failure message or recheck error) -> NEEDS_REVIEW.
3. Jinja2 HTML bug report rendering into storage/<session>/<tc>/bug_report.html with all required fields.
4. Safe HTML escaping against XSS injection in user inputs and selectors.
5. Graceful handling of missing or malformed evidence files and screenshots.
6. End-to-end verifier and reporter execution against live sample application.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from backend.app.agent.evidence import ConsoleEntry, EvidenceData, NetworkEntry
from backend.app.agent.executor import TestExecutor
from backend.app.agent.plan_models import Action, TestCase, TestOutcome, TestPlan, TestResult
from backend.app.agent.planner import AIPlanner
from backend.app.agent.reporter import Reporter, action_to_plain_english, severity_from_category
from backend.app.agent.verifier import (
    Verifier,
    are_failure_messages_same,
    is_environment_error,
    normalize_failure_message,
)
from backend.app.config import settings

SAMPLE_APP_URL = "http://localhost:3000"


# --- 1. Message Normalization Tests ---

def test_normalize_failure_message_timings_and_pointers():
    """Verify that execution timings, hex memory addresses, and UUIDs are normalized away."""
    msg1 = "AssertionError: Timed out 20000ms waiting for locator('#btn') at 0x000001ADE5517870 uuid=123e4567-e89b-12d3-a456-426614174000"
    msg2 = "AssertionError: Timed out 15000ms waiting for locator('#btn') at 0x7FFF9821ABCD4321 uuid=987fcdeb-51a2-43d2-b123-111122223333"

    norm1 = normalize_failure_message(msg1)
    norm2 = normalize_failure_message(msg2)

    assert norm1 == norm2
    assert are_failure_messages_same(msg1, msg2) is True


def test_normalize_failure_message_distinct_errors():
    """Verify that genuinely different assertion errors are not considered identical."""
    msg1 = "AssertionError: Expected text 'Invalid email' not found in ''"
    msg2 = "AssertionError: Expected text '$198.00' not found in '$99.00'"

    assert are_failure_messages_same(msg1, msg2) is False


def test_environment_error_detection():
    """Verify setup / environment error detection."""
    assert is_environment_error("net::ERR_CONNECTION_REFUSED at http://localhost:3000") is True
    assert is_environment_error("Connection refused by target machine") is True
    assert is_environment_error("net::ERR_NAME_NOT_RESOLVED") is True
    assert is_environment_error("AssertionError: Expected text 'Foo' not found") is False
    assert is_environment_error(None) is False


# --- 2. Status Transition Rules Tests (Section 6.8) ---

def test_rule_1_first_run_passed():
    """Rule 1: First run passed -> status PASSED, no recheck."""
    mock_executor = MagicMock(spec=TestExecutor)
    verifier = Verifier(executor=mock_executor)

    tc = TestCase(
        id="TC-01",
        title="Valid Login",
        category="functional",
        steps=[Action(type="goto", value=f"{SAMPLE_APP_URL}/login.html")],
        expected="Success",
    )
    outcome = TestOutcome(tc_id="TC-01", outcome="passed", duration_ms=120.0)

    result = verifier.verify_test_case("session_test", tc, outcome)

    assert result.status == "PASSED"
    assert result.reason == "First run passed"
    assert result.recheck_outcome is None
    # No recheck should have been executed
    mock_executor.run_single_test_case.assert_not_called()


def test_rule_3_environment_error_needs_review():
    """Rule 3: Test errors because of setup / unreachable app -> NEEDS_REVIEW with reason 'environment'."""
    mock_executor = MagicMock(spec=TestExecutor)
    verifier = Verifier(executor=mock_executor)

    tc = TestCase(
        id="TC-ENV",
        title="Unreachable App",
        category="functional",
        steps=[Action(type="goto", value="http://localhost:9999")],
        expected="App loads",
    )
    outcome = TestOutcome(
        tc_id="TC-ENV",
        outcome="error",
        duration_ms=50.0,
        failure_message="net::ERR_CONNECTION_REFUSED at http://localhost:9999",
    )

    result = verifier.verify_test_case("session_env", tc, outcome)

    assert result.status == "NEEDS_REVIEW"
    assert result.reason == "environment"
    assert result.recheck_outcome is None
    mock_executor.run_single_test_case.assert_not_called()


def test_rule_2a_flaky_failure_needs_review():
    """Rule 2a: Failed first run, passed recheck -> status NEEDS_REVIEW (flaky test)."""
    mock_executor = MagicMock(spec=TestExecutor)
    mock_executor.run_single_test_case.return_value = TestOutcome(
        tc_id="TC-FLAKY",
        outcome="passed",
        duration_ms=100.0,
    )
    verifier = Verifier(executor=mock_executor)

    tc = TestCase(
        id="TC-FLAKY",
        title="Flaky Timing",
        category="functional",
        steps=[Action(type="goto", value=f"{SAMPLE_APP_URL}/index.html")],
        expected="Loaded",
    )
    first_outcome = TestOutcome(
        tc_id="TC-FLAKY",
        outcome="failed",
        duration_ms=250.0,
        failure_message="AssertionError: Element not ready within 500ms",
    )

    result = verifier.verify_test_case("session_flaky", tc, first_outcome)

    assert result.status == "NEEDS_REVIEW"
    assert "Flaky" in result.reason
    assert result.first_run_outcome == "failed"
    assert result.recheck_outcome == "passed"


def test_rule_2b_consistent_failure_confirmed_bug():
    """Rule 2b: Failed first run, failed recheck with SAME message -> status FAILED (confirmed bug)."""
    mock_executor = MagicMock(spec=TestExecutor)
    mock_executor.run_single_test_case.return_value = TestOutcome(
        tc_id="TC-BUG",
        outcome="failed",
        duration_ms=180.0,
        failure_message="AssertionError: Expected '$198.00' not found in '$99.00' (attempt 2 at 180ms)",
    )
    verifier = Verifier(executor=mock_executor)

    tc = TestCase(
        id="TC-BUG",
        title="Checkout Total Quantity",
        category="functional",
        steps=[Action(type="goto", value=f"{SAMPLE_APP_URL}/checkout.html")],
        expected="Total is $198.00",
    )
    first_outcome = TestOutcome(
        tc_id="TC-BUG",
        outcome="failed",
        duration_ms=200.0,
        failure_message="AssertionError: Expected '$198.00' not found in '$99.00' (attempt 1 at 200ms)",
    )

    result = verifier.verify_test_case("session_consistent", tc, first_outcome)

    assert result.status == "FAILED"
    assert "Confirmed bug" in result.reason
    assert result.first_run_outcome == "failed"
    assert result.recheck_outcome == "failed"


def test_rule_2c_inconsistent_different_failure_message():
    """Rule 2c: Failed first run, failed recheck with DIFFERENT message -> status NEEDS_REVIEW."""
    mock_executor = MagicMock(spec=TestExecutor)
    mock_executor.run_single_test_case.return_value = TestOutcome(
        tc_id="TC-INCONSISTENT",
        outcome="failed",
        duration_ms=150.0,
        failure_message="AssertionError: Button '#login-btn' was disabled",
    )
    verifier = Verifier(executor=mock_executor)

    tc = TestCase(
        id="TC-INCONSISTENT",
        title="Unstable Flow",
        category="edge",
        steps=[Action(type="goto", value=f"{SAMPLE_APP_URL}/login.html")],
        expected="Logged in",
    )
    first_outcome = TestOutcome(
        tc_id="TC-INCONSISTENT",
        outcome="failed",
        duration_ms=160.0,
        failure_message="AssertionError: Message 'Invalid email' not displayed",
    )

    result = verifier.verify_test_case("session_diff", tc, first_outcome)

    assert result.status == "NEEDS_REVIEW"
    assert "Inconsistent" in result.reason
    assert result.first_run_outcome == "failed"
    assert result.recheck_outcome == "failed"


# --- 3. Reporter and Jinja2 Template Tests ---

def test_reporter_generates_html_with_all_spec_fields():
    """Verify that Reporter renders bug_report.html with all required sections."""
    session_id = "m4_report_session"
    tc_id = "TC-REP-01"

    tc = TestCase(
        id=tc_id,
        title="Checkout total calculation bug",
        category="functional",
        steps=[
            Action(type="goto", value=f"{SAMPLE_APP_URL}/index.html"),
            Action(type="click", target="#add-p1"),
            Action(type="click", target="#add-p1"),
            Action(type="goto", value=f"{SAMPLE_APP_URL}/checkout.html"),
            Action(type="expect_text", target="#checkout-total", value="$198.00"),
        ],
        expected="Checkout total equals $198.00 for quantity 2",
    )

    result = TestResult(
        id="result-1234",
        session_id=session_id,
        tc_id=tc_id,
        status="FAILED",
        reason="Confirmed bug: consistent failure",
        first_run_outcome="failed",
        recheck_outcome="failed",
        duration_ms=450.0,
        failure_message="AssertionError: Expected text '$198.00' not found in '$99.00' at selector '#checkout-total'",
        explanation="The application calculates unit price once and ignores item quantity when quantity is 2 or more.",
    )

    # Create dummy screenshot and evidence
    target_dir = settings.STORAGE_DIR / session_id / tc_id
    target_dir.mkdir(parents=True, exist_ok=True)
    screenshot_path = target_dir / "failure.png"
    screenshot_path.write_bytes(b"dummy_png_bytes_for_testing")

    evidence = EvidenceData(
        session_id=session_id,
        tc_id=tc_id,
        screenshot_path=str(screenshot_path),
        console_logs=[ConsoleEntry(type="warning", text="Cart badge warning", location="app.js:45")],
        network_errors=[NetworkEntry(method="GET", url=f"{SAMPLE_APP_URL}/api/config", status=200)],
        final_url=f"{SAMPLE_APP_URL}/checkout.html",
        page_title="ShopEasy - Checkout",
        failure_message=result.failure_message,
    )
    evidence.save(settings.STORAGE_DIR)

    reporter = Reporter()
    bug_report = reporter.generate_report(
        session_id=session_id,
        tc=tc,
        result=result,
        app_url=SAMPLE_APP_URL,
        planner_source="fallback",
        browser_name="Chromium",
        index=1,
    )

    assert bug_report is not None
    assert bug_report.bug_code.startswith("BUG-")
    assert bug_report.severity == "HIGH"  # functional -> HIGH
    assert bug_report.status == "CONFIRMED"
    assert bug_report.report_path is not None

    # Verify generated HTML file on disk
    html_file = Path(bug_report.report_path)
    assert html_file.exists()
    html_content = html_file.read_text(encoding="utf-8")

    # Verify all required spec fields appear in HTML
    assert bug_report.bug_code in html_content
    assert "Checkout total calculation bug" in html_content
    assert "Severity: HIGH" in html_content
    assert "CONFIRMED" in html_content
    assert "Checkout total equals $198.00" in html_content
    assert "Reproduction Steps" in html_content
    assert "Navigate to" in html_content
    assert "Click" in html_content and "#add-p1" in html_content
    assert "failure.png" in html_content
    assert "Cart badge warning" in html_content
    assert "Chromium" in html_content
    assert "Generated by QA Agent. Verify before filing." in html_content


def test_reporter_html_escaping_prevents_xss():
    """Verify that Jinja2 autoescaping prevents malicious HTML/script injection."""
    session_id = "m4_xss_test_session"
    tc_id = "TC-XSS-01"

    malicious_title = "<script>alert('xss_attack')</script> Injection Test"
    malicious_expected = "<img src=x onerror=alert(1)> Expected"

    tc = TestCase(
        id=tc_id,
        title=malicious_title,
        category="validation",
        steps=[
            Action(type="fill", target="<input>", value="<b>bold_payload</b>"),
        ],
        expected=malicious_expected,
    )

    result = TestResult(
        id="result-xss",
        session_id=session_id,
        tc_id=tc_id,
        status="FAILED",
        reason="Confirmed failure",
        first_run_outcome="failed",
        recheck_outcome="failed",
        duration_ms=100.0,
        failure_message="<script>evil()</script>",
    )

    reporter = Reporter()
    bug_report = reporter.generate_report(
        session_id=session_id,
        tc=tc,
        result=result,
        app_url=SAMPLE_APP_URL,
    )

    assert bug_report is not None
    html_content = Path(bug_report.report_path).read_text(encoding="utf-8")

    # Unescaped raw script tags must NOT appear
    assert "<script>alert('xss_attack')</script>" not in html_content
    assert "<img src=x onerror=alert(1)>" not in html_content

    # Escaped safe HTML entities must appear instead
    assert "&lt;script&gt;" in html_content
    assert "&lt;/script&gt;" in html_content
    assert "&lt;img" in html_content
    assert "&lt;b&gt;bold_payload&lt;/b&gt;" in html_content


def test_reporter_handles_missing_evidence_gracefully():
    """Verify that reporter does not crash when evidence or screenshots are missing."""
    session_id = "m4_missing_evidence_session"
    tc_id = "TC-NO-EV"

    tc = TestCase(
        id=tc_id,
        title="Missing Evidence Test",
        category="validation",
        steps=[Action(type="goto", value=f"{SAMPLE_APP_URL}/login.html")],
        expected="Should render report even with zero evidence files",
    )

    result = TestResult(
        id="result-no-ev",
        session_id=session_id,
        tc_id=tc_id,
        status="FAILED",
        reason="Confirmed failure",
        first_run_outcome="failed",
        recheck_outcome="failed",
        duration_ms=50.0,
        failure_message="Unexpected failure without files",
    )

    reporter = Reporter()
    bug = reporter.generate_report(session_id, tc, result, app_url=SAMPLE_APP_URL)

    assert bug is not None
    html_content = Path(bug.report_path).read_text(encoding="utf-8")
    assert "Screenshot not available" in html_content
    assert "No console errors captured" in html_content
    assert "No network errors captured" in html_content


def test_no_report_for_passed_or_needs_review():
    """Verify that bug reports are never generated for PASSED or NEEDS_REVIEW tests."""
    reporter = Reporter()

    tc = TestCase(
        id="TC-PASS",
        title="Pass",
        category="functional",
        steps=[],
        expected="Pass",
    )

    pass_result = TestResult(
        id="r1",
        session_id="s1",
        tc_id="TC-PASS",
        status="PASSED",
        reason="First run passed",
        first_run_outcome="passed",
    )
    assert reporter.generate_report("s1", tc, pass_result, SAMPLE_APP_URL) is None

    review_result = TestResult(
        id="r2",
        session_id="s1",
        tc_id="TC-PASS",
        status="NEEDS_REVIEW",
        reason="Flaky test",
        first_run_outcome="failed",
        recheck_outcome="passed",
    )
    assert reporter.generate_report("s1", tc, review_result, SAMPLE_APP_URL) is None


# --- 4. End-to-End Live Recheck and Bug Report Generation ---

def test_live_consistent_failure_generates_bug_report():
    """Execute live consistent failure on sample app (BUG-01) and verify FAILED status & HTML report."""
    session_id = "m4_live_e2e_session"

    # Define test triggering BUG-01: valid email with wrong password
    # With SAMPLE_BUGS=on, this will consistently fail to show "Invalid email or password"
    tc = TestCase(
        id="TC-LIVE-01",
        title="Verify wrong password shows error message",
        category="validation",
        steps=[
            Action(type="goto", value=f"{SAMPLE_APP_URL}/login.html"),
            Action(type="fill", target="#email", value="test@demo.com"),
            Action(type="fill", target="#password", value="WrongPass123"),
            Action(type="click", target="#login-button"),
            # Because BUG-01 is ON, login succeeds and redirects to index.html instead of showing error
            Action(type="expect_text", target="#login-message", value="Invalid email or password"),
        ],
        expected="Shows error 'Invalid email or password' and stays on login page",
    )

    plan = TestPlan(
        source="fallback",
        branch="instruction",
        tests=[tc],
    )

    executor = TestExecutor()
    # 1. First run
    first_outcomes = executor.run_session(session_id, plan)
    assert len(first_outcomes) == 1
    assert first_outcomes[0].outcome == "failed"

    # 2. Verifier: runs recheck in fresh browser context
    verifier = Verifier(executor=executor)
    verified_results = verifier.verify_session(session_id, plan, first_outcomes, app_url=SAMPLE_APP_URL)

    assert len(verified_results) == 1
    res = verified_results[0]
    assert res.status == "FAILED"
    assert "Confirmed bug" in res.reason
    assert res.first_run_outcome == "failed"
    assert res.recheck_outcome == "failed"

    # 3. Reporter: generates HTML bug report
    reporter = Reporter()
    bug_reports = reporter.generate_reports(
        session_id=session_id,
        plan=plan,
        results=verified_results,
        app_url=SAMPLE_APP_URL,
        planner_source="fallback",
    )

    assert len(bug_reports) == 1
    report = bug_reports[0]
    assert report.bug_code.startswith("BUG-")
    assert report.severity == "LOW"  # validation category -> LOW
    assert report.status == "CONFIRMED"

    # Verify report HTML exists and contains expected evidence
    html_path = Path(report.report_path)
    assert html_path.exists()
    content = html_path.read_text(encoding="utf-8")
    assert "Verify wrong password shows error message" in content
    assert "Invalid email or password" in content
    assert "Generated by QA Agent. Verify before filing." in content
