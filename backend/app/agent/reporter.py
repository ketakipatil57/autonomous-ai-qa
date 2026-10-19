"""Bug report generator rendering evidence-backed HTML reports from Jinja2 templates.

Renders bug_report.html.j2 into storage/<session>/<tc>/bug_report.html for every confirmed
FAILED test, including reproduction steps, expected vs actual behavior, and evidence artifacts.
"""

from __future__ import annotations

import datetime
from pathlib import Path
from typing import Any
from jinja2 import Environment, FileSystemLoader, select_autoescape

from backend.app.agent.evidence import EvidenceData
from backend.app.agent.plan_models import Action, BugReport, SeverityType, TestCase, TestPlan, TestResult
from backend.app.config import settings

DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "templates"


def severity_from_category(category: str) -> SeverityType:
    """Guess bug severity based on test category (Section 6.9)."""
    cat = (category or "").lower()
    if cat == "validation":
        return "LOW"
    elif cat == "functional":
        return "HIGH"
    elif cat in ("edge", "negative"):
        return "MEDIUM"
    return "MEDIUM"


def action_to_plain_english(action: Action) -> str:
    """Format browser Action into plain-English reproduction instruction."""
    t = action.type
    target = action.target or ""
    val = action.value or ""

    if t == "goto":
        return f"Navigate to {val}"
    elif t == "fill":
        return f"Enter '{val}' into input field '{target}'"
    elif t == "click":
        return f"Click '{target}'"
    elif t == "expect_text":
        return f"Verify that element '{target}' displays text '{val}'"
    elif t == "expect_url":
        return f"Verify that page URL contains '{val}'"
    elif t == "expect_visible":
        return f"Verify that element '{target}' is visible"
    elif t == "expect_not_visible":
        return f"Verify that element '{target}' is not visible"
    elif t == "expect_count_text":
        return f"Verify that element '{target}' displays count '{val}'"
    else:
        return f"Perform {t} on '{target}' with value '{val}'"


class Reporter:
    """Renders HTML bug reports and structured BugReport records for confirmed failures."""

    def __init__(
        self,
        template_dir: Path | str | None = None,
        storage_root: Path | str | None = None,
    ):
        self.template_dir = Path(template_dir or DEFAULT_TEMPLATE_DIR).resolve()
        self.storage_root = Path(storage_root or settings.STORAGE_DIR).resolve()

        # Initialize Jinja2 with autoescaping enabled for HTML/XML/J2
        self.jinja_env = Environment(
            loader=FileSystemLoader(str(self.template_dir)),
            autoescape=select_autoescape(["html", "xml", "j2"]),
        )

    def generate_report(
        self,
        session_id: str,
        tc: TestCase,
        result: TestResult,
        app_url: str,
        planner_source: str = "fallback",
        browser_name: str = "Chromium",
        index: int = 1,
    ) -> BugReport | None:
        """Render bug report for a single FAILED test result."""
        # Only confirmed FAILED tests get bug reports (Section 6.8 & 6.9)
        if result.status != "FAILED":
            return None

        short_session = session_id[:8] if len(session_id) >= 8 else session_id
        bug_code = f"BUG-{short_session}-{index}"
        severity = severity_from_category(tc.category)

        # Plain-English reproduction steps
        repro_steps = [action_to_plain_english(step) for step in tc.steps]

        # Evidence collection and fallback handling
        evidence_data = EvidenceData.load(session_id, tc.id, self.storage_root)
        tc_storage = self.storage_root / session_id / tc.id
        screenshot_file = tc_storage / "failure.png"

        screenshot_rel_url = "failure.png" if screenshot_file.exists() else None

        console_errors = []
        network_errors = []
        if evidence_data:
            console_errors = [c.model_dump() for c in evidence_data.console_logs]
            network_errors = [n.model_dump() for n in evidence_data.network_errors]

        actual_behaviour = (
            result.explanation
            or result.failure_message
            or "Observed application behaviour diverged from expected requirement."
        )

        now_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

        bug = BugReport(
            id=f"{session_id}-{tc.id}-bug",
            session_id=session_id,
            tc_id=tc.id,
            test_result_id=result.id,
            bug_code=bug_code,
            title=tc.title,
            severity=severity,
            reproduction_steps=repro_steps,
            expected=tc.expected,
            actual=actual_behaviour,
            status="CONFIRMED",
            environment={
                "app_url": app_url,
                "browser": browser_name,
                "planner_source": planner_source,
                "timestamp": now_str,
            },
            evidence={
                "screenshot_url": screenshot_rel_url,
                "console_errors": console_errors,
                "network_errors": network_errors,
                "failure_message": result.failure_message or "",
            },
            report_path=None,
            created_at=now_str,
        )

        # Render HTML template
        template = self.jinja_env.get_template("bug_report.html.j2")
        rendered_html = template.render(bug=bug)

        # Write to storage/<session>/<tc>/bug_report.html
        tc_storage.mkdir(parents=True, exist_ok=True)
        report_file = tc_storage / "bug_report.html"
        with open(report_file, "w", encoding="utf-8") as f:
            f.write(rendered_html)

        bug.report_path = str(report_file)
        result.report_path = str(report_file)

        return bug

    def generate_reports(
        self,
        session_id: str,
        plan: TestPlan,
        results: list[TestResult],
        app_url: str,
        planner_source: str = "fallback",
        browser_name: str = "Chromium",
        bug_index_offset: int = 0,
    ) -> list[BugReport]:
        """Generate bug reports for all confirmed FAILED results in a test session."""
        tc_map = {tc.id: tc for tc in plan.tests}
        reports: list[BugReport] = []
        bug_index = bug_index_offset + 1

        for res in results:
            if res.status == "FAILED":
                tc = tc_map.get(res.tc_id)
                if tc:
                    report = self.generate_report(
                        session_id=session_id,
                        tc=tc,
                        result=res,
                        app_url=app_url,
                        planner_source=planner_source,
                        browser_name=browser_name,
                        index=bug_index,
                    )
                    if report:
                        reports.append(report)
                        bug_index += 1

        return reports

    def get_rendered_report_html(self, session_id: str, tc_id: str) -> str | None:
        """Read rendered bug report HTML from disk if it exists."""
        report_file = self.storage_root / session_id / tc_id / "bug_report.html"
        if not report_file.exists():
            return None
        with open(report_file, "r", encoding="utf-8") as f:
            return f.read()
