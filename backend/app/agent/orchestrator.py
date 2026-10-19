"""Agent pipeline orchestrator coordinating exploration, planning, execution, verification, reporting, and persistence."""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from backend.app.agent.evidence import EvidenceData
from backend.app.agent.executor import TestExecutor
from backend.app.agent.explorer import SiteExplorer
from backend.app.agent.planner import AIPlanner
from backend.app.agent.plan_models import Action, TestCase, TestPlan, TestResult
from backend.app.agent.reporter import Reporter
from backend.app.agent.safety import validate_test_plan_safety, validate_url
from backend.app.agent.verifier import Verifier
from backend.app.config import settings
from backend.app.db import SessionLocal
from backend.app.models import (
    BugReportModel,
    EvidenceModel,
    RegressionTestModel,
    TestCaseModel,
    TestResultModel,
    TestSession,
)

logger = logging.getLogger(__name__)


class PipelineOrchestrator:
    """Executes the complete Autonomous QA testing pipeline for a given session."""

    def __init__(
        self,
        executor: Optional[TestExecutor] = None,
        explorer: Optional[SiteExplorer] = None,
        planner: Optional[AIPlanner] = None,
        verifier: Optional[Verifier] = None,
        reporter: Optional[Reporter] = None,
    ):
        self.executor = executor or TestExecutor()
        self.explorer = explorer or SiteExplorer()
        self.planner = planner or AIPlanner()
        self.verifier = verifier or Verifier(executor=self.executor, planner=self.planner)
        self.reporter = reporter or Reporter()

    def run_pipeline(
        self,
        session_id: str,
        custom_plan: Optional[TestPlan | list[TestPlan]] = None,
    ) -> None:
        """Run the end-to-end pipeline synchronously in the current thread."""
        db = SessionLocal()
        try:
            session = db.query(TestSession).filter(TestSession.id == session_id).first()
            if not session:
                logger.error("Session %s not found in database", session_id)
                return

            # Update status to RUNNING
            session.status = "RUNNING"
            db.commit()

            plans: list[TestPlan]
            if custom_plan:
                plans = custom_plan if isinstance(custom_plan, list) else [custom_plan]
                if not plans:
                    raise ValueError("A custom regression run must contain at least one plan")
                for batch_plan in plans:
                    validate_test_plan_safety(batch_plan)
                session.stage = "planning"
                session.current_step = "Loaded custom regression test plan"
                session.planner_source = plans[0].source
                db.commit()
            else:
                # Validate starting URL
                validate_url(session.app_url)

                # Branch A vs Branch B
                if session.instruction and session.instruction.strip():
                    # Branch A: direct instruction
                    session.stage = "planning"
                    session.current_step = "Generating test cases from user instruction (Branch A)..."
                    db.commit()

                    plan = self.planner.plan_from_instruction(
                        instruction=session.instruction.strip(),
                        app_url=session.app_url,
                        description=session.description,
                    )
                else:
                    # Branch B: exploration first
                    session.stage = "exploring"
                    session.current_step = "Exploring application pages with Playwright (Branch B)..."
                    db.commit()

                    site_map = self.explorer.explore(
                        app_url=session.app_url,
                        max_pages=10,
                        max_depth=2,
                        save_debug_dir=settings.STORAGE_DIR,
                    )

                    session.stage = "planning"
                    session.current_step = f"Generating test plan from {len(site_map.pages)} discovered pages..."
                    db.commit()

                    plan = self.planner.plan_from_exploration(
                        site_map=site_map,
                        description=session.description,
                    )

                validate_test_plan_safety(plan)
                plans = [plan]

            # Persist test cases
            all_test_cases = [tc for batch_plan in plans for tc in batch_plan.tests]
            session.planner_source = plans[0].source
            session.tests_total = len(all_test_cases)
            session.tests_done = 0
            tc_model_map: dict[str, TestCaseModel] = {}
            regression_models_by_id: dict[str, RegressionTestModel] = {}

            if custom_plan:
                regression_ids = [tc.id for tc in all_test_cases]
                regression_models_by_id = {
                    regression.id: regression
                    for regression in db.query(RegressionTestModel)
                    .filter(RegressionTestModel.id.in_(regression_ids))
                    .all()
                }
                missing_regression_ids = set(regression_ids) - regression_models_by_id.keys()
                if missing_regression_ids:
                    raise ValueError(
                        "Saved regression tests no longer exist: "
                        + ", ".join(sorted(missing_regression_ids))
                    )

            # Clear any previously registered test cases for this session
            db.query(TestCaseModel).filter(TestCaseModel.session_id == session_id).delete()
            db.commit()

            for tc in all_test_cases:
                regression_model = regression_models_by_id.get(tc.id)
                tc_model = TestCaseModel(
                    id=str(uuid.uuid4()),
                    session_id=session_id,
                    tc_code=regression_model.tc_code if regression_model else tc.id,
                    title=tc.title,
                    category=tc.category,
                    steps_json=json.dumps([s.model_dump() for s in tc.steps]),
                    expected=tc.expected,
                    related_bug_hint=tc.related_bug_hint,
                )
                db.add(tc_model)
                tc_model_map[tc.id] = tc_model

            db.commit()

            # Stage: Executing
            session.stage = "executing"
            session.current_step = f"Executing test suite ({len(all_test_cases)} tests) with Playwright..."
            db.commit()

            # Stage: Rechecking & Verification
            session.stage = "rechecking"
            db.commit()

            verified_results: list[TestResult] = []
            batch_results: list[tuple[TestPlan, list[TestResult]]] = []
            for batch_index, batch_plan in enumerate(plans, start=1):
                session.stage = "executing"
                session.current_step = (
                    f"Executing test batch {batch_index} of {len(plans)} "
                    f"({len(batch_plan.tests)} tests)..."
                )
                db.commit()
                first_run_outcomes = self.executor.run_session(session_id, batch_plan)

                session.stage = "rechecking"
                session.current_step = (
                    f"Verifying test batch {batch_index} of {len(plans)}..."
                )
                session.tests_done = min(
                    len(all_test_cases),
                    session.tests_done + len(first_run_outcomes),
                )
                db.commit()
                batch_verified_results = self.verifier.verify_session(
                    session_id=session_id,
                    plan=batch_plan,
                    first_run_outcomes=first_run_outcomes,
                    app_url=session.app_url,
                )
                verified_results.extend(batch_verified_results)
                batch_results.append((batch_plan, batch_verified_results))

            # Stage: Reporting
            session.stage = "reporting"
            session.current_step = "Generating evidence-backed HTML bug reports..."
            db.commit()

            reports = []
            bug_index_offset = 0
            for batch_plan, results in batch_results:
                batch_reports = self.reporter.generate_reports(
                    session_id=session_id,
                    plan=batch_plan,
                    results=results,
                    app_url=session.app_url,
                    planner_source=batch_plan.source,
                    bug_index_offset=bug_index_offset,
                )
                reports.extend(batch_reports)
                bug_index_offset += len(batch_reports)

            # Persist Results, Evidence, and Bug Reports
            result_model_map: dict[str, TestResultModel] = {}
            for r in verified_results:
                tc_model = tc_model_map.get(r.tc_id)
                tc_fk_id = tc_model.id if tc_model else str(uuid.uuid4())

                res_model = TestResultModel(
                    id=r.id,
                    session_id=session_id,
                    test_case_id=tc_fk_id,
                    status=r.status,
                    reason=r.reason,
                    first_run_outcome=r.first_run_outcome,
                    recheck_outcome=r.recheck_outcome,
                    duration_ms=r.duration_ms,
                    failure_message=r.failure_message,
                    explanation=r.explanation,
                    screenshot_path=r.screenshot_path,
                    evidence_path=r.evidence_path,
                    report_path=r.report_path,
                )
                db.add(res_model)
                result_model_map[r.tc_id] = res_model

                # Persist Evidence
                evidence_data = EvidenceData.load(session_id, r.tc_id, settings.STORAGE_DIR)
                if evidence_data:
                    if evidence_data.screenshot_path:
                        db.add(
                            EvidenceModel(
                                id=str(uuid.uuid4()),
                                test_result_id=res_model.id,
                                type="screenshot",
                                path_or_json=evidence_data.screenshot_path,
                            )
                        )
                    if evidence_data.console_logs:
                        db.add(
                            EvidenceModel(
                                id=str(uuid.uuid4()),
                                test_result_id=res_model.id,
                                type="console",
                                path_or_json=json.dumps([c.model_dump() for c in evidence_data.console_logs]),
                            )
                        )
                    if evidence_data.network_errors:
                        db.add(
                            EvidenceModel(
                                id=str(uuid.uuid4()),
                                test_result_id=res_model.id,
                                type="network",
                                path_or_json=json.dumps([n.model_dump() for n in evidence_data.network_errors]),
                            )
                        )
                    if evidence_data.failure_message:
                        db.add(
                            EvidenceModel(
                                id=str(uuid.uuid4()),
                                test_result_id=res_model.id,
                                type="pytest",
                                path_or_json=evidence_data.failure_message,
                            )
                        )

            db.commit()

            # Persist Bug Reports
            for bug in reports:
                res_model = result_model_map.get(bug.tc_id)
                res_fk_id = res_model.id if res_model else str(uuid.uuid4())

                bug_model = BugReportModel(
                    id=str(uuid.uuid4()),
                    session_id=session_id,
                    test_result_id=res_fk_id,
                    bug_code=bug.bug_code,
                    title=bug.title,
                    severity=bug.severity,
                    reproduction_steps_json=json.dumps(bug.reproduction_steps),
                    expected=bug.expected,
                    actual=bug.actual,
                    report_path=bug.report_path or "",
                )
                db.add(bug_model)

            db.commit()

            # Save first-run PASSED tests as regression tests (Section 9)
            result_by_tc = {r.tc_id: r for r in verified_results}
            if custom_plan:
                for tc in all_test_cases:
                    res = result_by_tc.get(tc.id)
                    regression_model = regression_models_by_id[tc.id]
                    if res:
                        regression_model.last_run_at = datetime.now(timezone.utc)
                        regression_model.last_status = res.status
                        regression_model.run_count += 1
            else:
                updated_regression_ids: set[str] = set()
                for tc in all_test_cases:
                    res = result_by_tc.get(tc.id)
                    if res and (res.first_run_outcome == "passed" or res.status == "PASSED"):
                        tc_model = tc_model_map.get(tc.id)
                        tc_fk_id = tc_model.id if tc_model else str(uuid.uuid4())

                        steps_json = json.dumps([s.model_dump() for s in tc.steps])
                        # A test's code and definition identify it; titles are
                        # descriptive and may legitimately be duplicated.
                        candidates = (
                            db.query(RegressionTestModel)
                            .filter(
                                RegressionTestModel.tc_code == tc.id,
                                RegressionTestModel.category == tc.category,
                                RegressionTestModel.steps_json == steps_json,
                                RegressionTestModel.expected == tc.expected,
                            )
                            .order_by(
                                RegressionTestModel.created_at.asc(),
                                RegressionTestModel.id.asc(),
                            )
                            .all()
                        )
                        existing = next(
                            (
                                candidate
                                for candidate in candidates
                                if candidate.id not in updated_regression_ids
                            ),
                            None,
                        )
                        if existing:
                            existing.last_run_at = datetime.now(timezone.utc)
                            existing.last_status = "PASSED"
                            existing.run_count += 1
                            updated_regression_ids.add(existing.id)
                        else:
                            reg_model = RegressionTestModel(
                                id=str(uuid.uuid4()),
                                source_session_id=session_id,
                                test_case_id=tc_fk_id,
                                tc_code=tc.id,
                                title=tc.title,
                                category=tc.category,
                                steps_json=steps_json,
                                expected=tc.expected,
                                last_run_at=datetime.now(timezone.utc),
                                last_status="PASSED",
                                run_count=1,
                            )
                            db.add(reg_model)

            db.commit()

            # Finalize Session Counts & Status
            passed_cnt = sum(1 for r in verified_results if r.status == "PASSED")
            failed_cnt = sum(1 for r in verified_results if r.status == "FAILED")
            needs_review_cnt = sum(1 for r in verified_results if r.status == "NEEDS_REVIEW")

            session.total_count = len(verified_results)
            session.passed_count = passed_cnt
            session.failed_count = failed_cnt
            session.needs_review_count = needs_review_cnt
            session.tests_done = len(verified_results)
            session.stage = "done"
            session.current_step = (
                f"Execution finished: {passed_cnt} passed, {failed_cnt} failed, {needs_review_cnt} needs review"
            )
            session.status = "COMPLETED"
            session.completed_at = datetime.now(timezone.utc)
            db.commit()

        except Exception as e:
            logger.exception("Pipeline failed for session %s: %s", session_id, e)
            try:
                session = db.query(TestSession).filter(TestSession.id == session_id).first()
                if session:
                    session.status = "FAILED_TO_RUN"
                    session.stage = "failed"
                    session.current_step = f"Pipeline execution failed: {e}"
                    session.completed_at = datetime.now(timezone.utc)
                    db.commit()
            except Exception:
                pass
        finally:
            db.close()
