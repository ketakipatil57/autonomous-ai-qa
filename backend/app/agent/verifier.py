"""Verifier implementing Section 6.8 status-transition and recheck logic.

Rules:
1. First run passed -> PASSED.
2. First run failed/error -> Recheck fresh browser context:
   - Passed on recheck -> NEEDS_REVIEW (flaky).
   - Failed with SAME normalized message -> FAILED (confirmed bug).
   - Failed with DIFFERENT message or error -> NEEDS_REVIEW.
3. Setup/connection error -> NEEDS_REVIEW with reason "environment".
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any

from backend.app.agent.executor import TestExecutor
from backend.app.agent.plan_models import TestCase, TestOutcome, TestPlan, TestResult
from backend.app.agent.planner import AIPlanner
from backend.app.config import settings

ENV_ERROR_PATTERNS = (
    "connection refused",
    "err_connection_refused",
    "err_name_not_resolved",
    "failed to connect",
    "server unreachable",
    "unreachable",
    "cannot connect",
    "err_connection_reset",
    "target closed",
)


def normalize_failure_message(msg: str | None) -> str:
    """Normalize failure message by masking timings, random IDs, hex pointers, and UUIDs."""
    if not msg:
        return ""

    text = str(msg).strip()

    # 1. Mask memory / hex addresses (e.g. 0x000001ADE5517870)
    text = re.sub(r"0x[0-9a-fA-F]+", "<HEX>", text)

    # 2. Mask UUIDs
    text = re.sub(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}", "<UUID>", text)

    # 3. Mask durations and timings (e.g. 20000ms, 20.0s, 0.45s)
    text = re.sub(r"\b\d+(\.\d+)?\s*(ms|seconds|second|sec|s)\b", "<TIME>", text, flags=re.IGNORECASE)

    # 4. Mask attempt / retry counters (e.g. attempt 1, try 2, retry #1)
    text = re.sub(r"\b(attempt|try|run|retry)\s*#?\d+\b", "<ATTEMPT>", text, flags=re.IGNORECASE)

    # 5. Mask random digit sequences of 5+ digits
    text = re.sub(r"\b\d{5,}\b", "<ID>", text)

    # 6. Collapse whitespace and lowercase
    text = " ".join(text.split()).lower()
    return text


def is_environment_error(failure_message: str | None) -> bool:
    """Check if the failure is caused by an environment or setup error."""
    if not failure_message:
        return False
    msg_lower = failure_message.lower()
    return any(p in msg_lower for p in ENV_ERROR_PATTERNS)


def are_failure_messages_same(msg1: str | None, msg2: str | None) -> bool:
    """Compare two failure messages after normalization."""
    return normalize_failure_message(msg1) == normalize_failure_message(msg2)


class Verifier:
    """Evaluates test outcomes, executes fresh-context rechecks, and classifies status."""

    def __init__(
        self,
        executor: TestExecutor | None = None,
        planner: AIPlanner | None = None,
        storage_root: Path | str | None = None,
    ):
        self.executor = executor or TestExecutor(storage_root=storage_root)
        self.planner = planner or AIPlanner()
        self.storage_root = Path(storage_root or settings.STORAGE_DIR).resolve()

    def verify_test_case(
        self,
        session_id: str,
        tc: TestCase,
        first_outcome: TestOutcome,
        app_url: str | None = None,
    ) -> TestResult:
        """Verify an individual test case following Section 6.8 rules."""
        result_id = str(uuid.uuid4())
        tc_storage = self.storage_root / session_id / tc.id
        screenshot_file = tc_storage / "failure.png"
        evidence_file = tc_storage / "evidence.json"

        # Rule 1: First run passed
        if first_outcome.outcome == "passed":
            return TestResult(
                id=result_id,
                session_id=session_id,
                tc_id=tc.id,
                status="PASSED",
                reason="First run passed",
                first_run_outcome="passed",
                recheck_outcome=None,
                duration_ms=first_outcome.duration_ms,
                failure_message=None,
                explanation=None,
                screenshot_path=None,
                evidence_path=None,
            )

        # Rule 3: Setup or environment error
        if is_environment_error(first_outcome.failure_message):
            explanation = None
            if self.planner:
                explanation = self.planner.explain_failure(
                    tc_title=tc.title,
                    expected=tc.expected,
                    failure_message=first_outcome.failure_message,
                    final_url=app_url,
                )

            return TestResult(
                id=result_id,
                session_id=session_id,
                tc_id=tc.id,
                status="NEEDS_REVIEW",
                reason="environment",
                first_run_outcome=first_outcome.outcome,
                recheck_outcome=None,
                duration_ms=first_outcome.duration_ms,
                failure_message=first_outcome.failure_message,
                explanation=explanation,
                screenshot_path=str(screenshot_file) if screenshot_file.exists() else None,
                evidence_path=str(evidence_file) if evidence_file.exists() else None,
            )

        # Rule 2: Recheck with fresh browser context
        recheck_outcome = self.executor.run_single_test_case(session_id, tc)

        # Case 2a: Passed on recheck -> flaky test
        if recheck_outcome.outcome == "passed":
            status = "NEEDS_REVIEW"
            reason = "Flaky test: failed on first run but passed on recheck"
        # Case 2b: Failed again -> compare failure messages
        elif recheck_outcome.outcome == "failed":
            if are_failure_messages_same(first_outcome.failure_message, recheck_outcome.failure_message):
                status = "FAILED"
                reason = "Confirmed bug: consistent failure on first run and recheck"
            else:
                status = "NEEDS_REVIEW"
                reason = "Inconsistent failure: failed with different message on recheck"
        # Case 2c: Error on recheck (crash, timeout, etc.)
        else:
            status = "NEEDS_REVIEW"
            reason = "Inconsistent failure: recheck encountered execution error"

        # Generate plain-English explanation for failures & needs review
        explanation = None
        if self.planner:
            explanation = self.planner.explain_failure(
                tc_title=tc.title,
                expected=tc.expected,
                failure_message=first_outcome.failure_message,
                final_url=app_url,
            )

        total_duration = round(first_outcome.duration_ms + recheck_outcome.duration_ms, 2)

        return TestResult(
            id=result_id,
            session_id=session_id,
            tc_id=tc.id,
            status=status,
            reason=reason,
            first_run_outcome=first_outcome.outcome,
            recheck_outcome=recheck_outcome.outcome,
            duration_ms=total_duration,
            failure_message=first_outcome.failure_message or recheck_outcome.failure_message,
            explanation=explanation,
            screenshot_path=str(screenshot_file) if screenshot_file.exists() else None,
            evidence_path=str(evidence_file) if evidence_file.exists() else None,
        )

    def verify_session(
        self,
        session_id: str,
        plan: TestPlan,
        first_run_outcomes: list[TestOutcome],
        app_url: str | None = None,
    ) -> list[TestResult]:
        """Verify all test cases in a session and determine final statuses."""
        results: list[TestResult] = []
        outcome_map = {o.tc_id: o for o in first_run_outcomes}

        for tc in plan.tests:
            outcome = outcome_map.get(tc.id)
            if not outcome:
                # Missing outcome treated as error
                outcome = TestOutcome(
                    tc_id=tc.id,
                    outcome="error",
                    duration_ms=0.0,
                    failure_message="No execution outcome recorded",
                )

            res = self.verify_test_case(session_id, tc, outcome, app_url=app_url)
            results.append(res)

        return results
