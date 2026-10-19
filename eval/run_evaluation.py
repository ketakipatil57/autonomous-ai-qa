"""Run the Autonomous QA agent against the sample app and report measured results."""

from __future__ import annotations

import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
SESSION_TIMEOUT_SECONDS = 360
POLL_INTERVAL_SECONDS = 1
STOP_WORDS = {
    "add", "after", "all", "and", "any", "cart", "check", "click",
    "com", "demo", "does", "email", "enter", "for", "from", "with", "when",
    "open", "place", "product", "products", "checkout", "login", "page",
    "shows", "show", "submit", "that", "the", "this", "two", "user", "valid",
    "test",
}


def http_request(
    url: str,
    method: str = "GET",
    payload: dict[str, Any] | None = None,
    timeout: float = 10,
) -> Any:
    """Send a JSON HTTP request and return its decoded JSON response."""
    body = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if body is not None else {}
    request = Request(url, data=body, headers=headers, method=method)
    try:
        with urlopen(request, timeout=timeout) as response:
            content = response.read()
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{method} {url} failed: {exc.reason}") from exc
    return json.loads(content) if content else None


def wait_for_service(
    url: str,
    process: subprocess.Popen[bytes] | None,
    service_name: str,
    timeout_seconds: int = 45,
) -> None:
    """Wait until a local service responds, failing with its process status if it exits."""
    deadline = time.monotonic() + timeout_seconds
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise RuntimeError(f"{service_name} exited during startup with code {process.returncode}")
        try:
            http_request(url, timeout=2)
            return
        except (RuntimeError, json.JSONDecodeError) as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"{service_name} did not become ready: {last_error}")


def start_sample_app() -> tuple[subprocess.Popen[bytes], str]:
    """Start an isolated sample app so evaluation cannot alter a user's running app."""
    port = allocate_port()
    sample_app_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["SAMPLE_BUGS"] = "on"
    process = subprocess.Popen(
        [
            sys.executable,
            str(ROOT_DIR / "sample_app" / "server.py"),
            "--port",
            str(port),
        ],
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_for_service(f"{sample_app_url}/api/config", process, "Sample app")
    except Exception:
        terminate_process(process)
        raise
    return process, sample_app_url


def set_sample_bug_mode(sample_app_url: str, enabled: bool) -> None:
    """Set the sample app mode using its existing runtime toggle endpoint."""
    config = http_request(
        f"{sample_app_url}/api/toggle-bugs",
        method="POST",
        payload={"sample_bugs": "on" if enabled else "off"},
    )
    expected = "on" if enabled else "off"
    if config.get("sample_bugs") != expected:
        raise RuntimeError(f"Sample app did not switch to SAMPLE_BUGS={expected}.")


def allocate_port() -> int:
    """Select an unused local TCP port for the isolated evaluation API."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def start_backend(runtime_dir: Path) -> tuple[subprocess.Popen[bytes], str]:
    """Launch an isolated FastAPI backend using a temporary SQLite database."""
    port = allocate_port()
    api_base = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["DATABASE_URL"] = f"sqlite:///{(runtime_dir / 'evaluation.db').as_posix()}"
    env["STORAGE_DIR"] = str(runtime_dir / "storage")
    env["GENERATED_TESTS_DIR"] = str(runtime_dir / "generated_tests")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "backend.app.main:app",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
        ],
        cwd=ROOT_DIR,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_for_service(f"{api_base}/health", process, "Evaluation API")
    except Exception:
        terminate_process(process)
        raise
    return process, api_base


def wait_for_session(api_base: str, session_id: str) -> dict[str, Any]:
    """Poll an API session until its background pipeline reaches a terminal state."""
    deadline = time.monotonic() + SESSION_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        session = http_request(f"{api_base}/api/sessions/{session_id}")
        if session["status"] in ("COMPLETED", "FAILED_TO_RUN"):
            return session
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Session {session_id} did not finish within {SESSION_TIMEOUT_SECONDS}s.")


def run_session(
    api_base: str,
    sample_app_url: str,
    instruction: str | None,
    label: str,
    bugs_enabled: bool,
) -> dict[str, Any]:
    """Start one full API-backed run and collect its results and bug reports."""
    payload: dict[str, Any] = {"app_url": sample_app_url}
    if instruction:
        payload["instruction"] = instruction
    session = http_request(f"{api_base}/api/sessions", method="POST", payload=payload)
    http_request(f"{api_base}/api/sessions/{session['id']}/start", method="POST")
    finished = wait_for_session(api_base, session["id"])
    results = http_request(f"{api_base}/api/sessions/{session['id']}/results")
    bugs = http_request(f"{api_base}/api/bugs?session_id={session['id']}")
    result_details = {
        result["id"]: http_request(f"{api_base}/api/results/{result['id']}")
        for result in results
    }
    return {
        "label": label,
        "bugs_enabled": bugs_enabled,
        "session_id": session["id"],
        "branch": finished["branch"],
        "planner_source": finished["planner_source"],
        "status": finished["status"],
        "counts": finished.get("counts", {}),
        "results": results,
        "result_details": result_details,
        "bugs": bugs,
    }


def branch_a_instruction(planted_bug: dict[str, Any]) -> str:
    """Translate each ground-truth trigger into a focused fallback-planner instruction."""
    page = planted_bug["page"]
    trigger = planted_bug["trigger"].lower()
    if page.endswith("/login.html") and "wrong password" in trigger:
        return "Test login with a wrong password"
    if page.endswith("/login.html") and "empty" in trigger:
        return "Test empty login fields"
    if page.endswith("/checkout.html") and "empty" in trigger:
        return "Test checkout with an empty cart and place order"
    if page.endswith("/checkout.html"):
        return "Test checkout total when the same product is added twice"
    if page.endswith("/index.html"):
        return "Test cart badge after adding a second product"
    raise ValueError(
        f"No Branch A instruction mapping exists for planted page {page!r}."
    )


def normalize_tokens(text: str) -> set[str]:
    """Extract comparable trigger and result keywords."""
    tokens = re.findall(r"[a-z0-9]+", text.lower())
    normalized = set()
    for token in tokens:
        keyword = token.rstrip("s")
        if len(keyword) >= 3 and keyword not in STOP_WORDS and not keyword.isdigit():
            normalized.add("different" if keyword == "distinct" else keyword)
    return normalized


def result_page(detail: dict[str, Any]) -> str | None:
    """Return the final page visited by the test case's goto actions."""
    page = None
    for step in detail.get("steps", []):
        if step.get("type") == "goto" and step.get("value"):
            page = urlparse(step["value"]).path
    return page


def match_report_to_bug(
    bug_report: dict[str, Any],
    result_detail: dict[str, Any],
    planted_bug: dict[str, Any],
) -> dict[str, Any] | None:
    """Match a confirmed report only when its page and trigger keywords overlap."""
    page = result_page(result_detail)
    if page != planted_bug["page"]:
        return None

    evidence_text = " ".join(
        [
            bug_report.get("title", ""),
            bug_report.get("expected") or "",
            bug_report.get("actual") or "",
            result_detail.get("title", ""),
            result_detail.get("expected") or "",
            result_detail.get("reason", ""),
            result_detail.get("failure_message") or "",
            " ".join(step.get("target") or "" for step in result_detail.get("steps", [])),
            " ".join(step.get("value") or "" for step in result_detail.get("steps", [])),
        ]
    )
    add_product_targets = [
        step.get("target") or ""
        for step in result_detail.get("steps", [])
        if step.get("type") == "click"
        and (step.get("target") or "").startswith("#add-")
    ]
    add_product_counts = Counter(add_product_targets)
    if any(count > 1 for count in add_product_counts.values()):
        evidence_text += " same product twice"
    if len(add_product_counts) > 1:
        evidence_text += " different products"
    evidence_words = set(re.findall(r"[a-z0-9]+", evidence_text.lower()))
    if {"email", "password"}.issubset(evidence_words):
        evidence_text += " fields"

    trigger_keywords = normalize_tokens(planted_bug["trigger"])
    matched_keywords = sorted(trigger_keywords & normalize_tokens(evidence_text))
    required_matches = min(2, len(trigger_keywords))
    if len(matched_keywords) < required_matches:
        return None

    return {
        "bug_id": planted_bug["id"],
        "page": page,
        "matched_trigger_keywords": matched_keywords,
    }


def collect_matches(
    runs: list[dict[str, Any]],
    planted_bugs: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Classify all reported bugs and return detected matches and false reports."""
    matches: list[dict[str, Any]] = []
    false_reports: list[dict[str, Any]] = []
    for run in runs:
        bug_by_result = {bug["test_result_id"]: bug for bug in run["bugs"]}
        used_bug_ids: set[str] = set()
        for result_id, detail in run["result_details"].items():
            bug_report = bug_by_result.get(result_id)
            if not bug_report:
                continue
            candidates = [
                match
                for planted_bug in planted_bugs
                if planted_bug["id"] not in used_bug_ids
                for match in [match_report_to_bug(bug_report, detail, planted_bug)]
                if match is not None
            ]
            if candidates:
                best_match = max(
                    candidates,
                    key=lambda candidate: len(candidate["matched_trigger_keywords"]),
                )
                used_bug_ids.add(best_match["bug_id"])
                matches.append(
                    {
                        "run": run["label"],
                        "reported_bug_code": bug_report["bug_code"],
                        "reported_title": bug_report["title"],
                        **best_match,
                    }
                )
            else:
                false_reports.append(
                    {
                        "run": run["label"],
                        "reported_bug_code": bug_report["bug_code"],
                        "reported_title": bug_report["title"],
                        "page": result_page(detail),
                    }
                )
    return matches, false_reports


def run_regression_suite(api_base: str, label: str) -> dict[str, Any]:
    """Launch a regression rerun and key outcomes by saved regression-test ID."""
    saved_tests = http_request(f"{api_base}/api/regression")
    session = http_request(f"{api_base}/api/regression/run", method="POST")
    finished = wait_for_session(api_base, session["id"])
    results = http_request(f"{api_base}/api/sessions/{session['id']}/results")
    result_details = {
        result["id"]: http_request(f"{api_base}/api/results/{result['id']}")
        for result in results
    }
    outcomes = regression_outcomes_by_id(saved_tests, results, result_details)
    return {
        "label": label,
        "session_id": session["id"],
        "status": finished["status"],
        "planner_source": finished["planner_source"],
        "outcomes": outcomes,
    }


def regression_outcomes_by_id(
    saved_tests: list[dict[str, Any]],
    results: list[dict[str, Any]],
    result_details: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Correlate rerun outcomes to saved IDs using each test's definition."""

    def signature(test: dict[str, Any], detail: dict[str, Any]) -> str:
        return json.dumps(
            {
                "tc_code": test.get("tc_code"),
                "category": test.get("category"),
                "expected": detail.get("expected", test.get("expected")),
                "steps": detail.get("steps", test.get("steps", [])),
            },
            sort_keys=True,
        )

    saved_by_signature: dict[str, list[str]] = {}
    for saved_test in sorted(
        saved_tests,
        key=lambda item: (item.get("created_at", ""), item["id"]),
    ):
        saved_by_signature.setdefault(
            signature(saved_test, saved_test), []
        ).append(saved_test["id"])

    outcomes: dict[str, dict[str, Any]] = {}
    for result in results:
        detail = result_details[result["id"]]
        key = signature(result, detail)
        candidates = saved_by_signature.get(key, [])
        if not candidates:
            raise RuntimeError(
                "Could not match regression result to a saved test by code and definition: "
                f"{result.get('tc_code')!r}"
            )
        outcomes[candidates.pop(0)] = {
            "status": result["status"],
            "first_run_outcome": result["first_run_outcome"],
            "recheck_outcome": result["recheck_outcome"],
            "reason": result["reason"],
            "failure_message": result["failure_message"],
        }
    missing_ids = {
        saved_test["id"]
        for saved_test in saved_tests
        if saved_test["id"] not in outcomes
    }
    if missing_ids:
        raise RuntimeError(
            "Regression run omitted saved test outcomes: "
            + ", ".join(sorted(missing_ids))
        )
    return outcomes


def print_summary(report: dict[str, Any]) -> None:
    """Print a compact table of the actual measured metrics."""
    rows = [
        ("Bug detection rate", report["bug_detection_rate"]),
        ("False-report ratio", report["false_report_ratio"]),
        ("Repeatability", report["repeatability"]),
        ("Control reports", report["control_false_report_count"]),
    ]
    width = max(len(label) for label, _ in rows)
    print("\nEvaluation summary")
    print(f"+-{'-' * width}-+----------------+")
    print(f"| {'Metric'.ljust(width)} | {'Measured value'.ljust(14)} |")
    print(f"+-{'-' * width}-+----------------+")
    for label, value in rows:
        display = f"{value:.2%}" if isinstance(value, float) else str(value)
        print(f"| {label.ljust(width)} | {display.ljust(14)} |")
    print(f"+-{'-' * width}-+----------------+")


def terminate_process(process: subprocess.Popen[bytes] | None) -> None:
    """Stop a child process started by the evaluator."""
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def main() -> int:
    ground_truth_path = ROOT_DIR / "sample_app" / "planted_bugs.json"
    with ground_truth_path.open("r", encoding="utf-8") as file:
        planted_bugs = json.load(file)["bugs"]

    sample_process: subprocess.Popen[bytes] | None = None
    backend_process: subprocess.Popen[bytes] | None = None
    with tempfile.TemporaryDirectory(prefix="qa-agent-evaluation-") as temp_dir:
        try:
            sample_process, sample_app_url = start_sample_app()
            backend_process, api_base = start_backend(Path(temp_dir))

            set_sample_bug_mode(sample_app_url, True)
            bug_on_runs: list[dict[str, Any]] = []
            branch_bugs_on = run_session(
                api_base, sample_app_url, None, "bugs_on_branch_b", True
            )
            bug_on_runs.append(branch_bugs_on)
            for planted_bug in planted_bugs:
                branch_a_run = run_session(
                    api_base,
                    sample_app_url,
                    branch_a_instruction(planted_bug),
                    f"bugs_on_branch_a_{planted_bug['id']}",
                    True,
                )
                bug_on_runs.append(branch_a_run)

            set_sample_bug_mode(sample_app_url, False)
            control_runs = [
                run_session(
                    api_base, sample_app_url, None, "bugs_off_branch_b", False
                )
            ]
            for planted_bug in planted_bugs:
                control_runs.append(
                    run_session(
                        api_base,
                        sample_app_url,
                        branch_a_instruction(planted_bug),
                        f"bugs_off_branch_a_{planted_bug['id']}",
                        False,
                    )
                )

            # Keep the app unchanged while comparing two consecutive suite reruns.
            regression_runs = [
                run_regression_suite(api_base, "regression_run_1"),
                run_regression_suite(api_base, "regression_run_2"),
            ]
            regression_outcomes = [run["outcomes"] for run in regression_runs]
            outcome_keys = set(regression_outcomes[0]) | set(regression_outcomes[1])
            identical = sum(
                1
                for key in outcome_keys
                if regression_outcomes[0].get(key, {}).get("status")
                == regression_outcomes[1].get(key, {}).get("status")
            )
            repeatability = identical / len(outcome_keys) if outcome_keys else None

            bug_matches, bug_on_false_reports = collect_matches(bug_on_runs, planted_bugs)
            control_reports = [
                {
                    "run": run["label"],
                    "reported_bug_code": bug["bug_code"],
                    "reported_title": bug["title"],
                    "page": result_page(
                        run["result_details"].get(bug["test_result_id"], {})
                    ),
                }
                for run in control_runs
                for bug in run["bugs"]
            ]
            all_report_count = (
                sum(len(run["bugs"]) for run in bug_on_runs)
                + len(control_reports)
            )
            false_report_count = len(bug_on_false_reports) + len(control_reports)
            detected_bug_ids = {match["bug_id"] for match in bug_matches}

            report = {
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "sample_app_url": sample_app_url,
                "evaluation_modes": {
                    "bugs_on": ["Branch B", "one Branch A run per planted bug area"],
                    "bugs_off_control": ["Branch B", "one Branch A run per planted bug area"],
                },
                "bug_detection_rate": (
                    len(detected_bug_ids) / len(planted_bugs) if planted_bugs else 0.0
                ),
                "false_report_ratio": (
                    false_report_count / all_report_count if all_report_count else 0.0
                ),
                "repeatability": repeatability,
                "repeatability_identical_tests": identical,
                "repeatability_total_tests": len(outcome_keys),
                "planner_source": {
                    run["label"]: run["planner_source"]
                    for run in bug_on_runs + control_runs + regression_runs
                },
                "detected_bugs": bug_matches,
                "missed_bugs": [
                    bug for bug in planted_bugs if bug["id"] not in detected_bug_ids
                ],
                "false_reports": bug_on_false_reports + control_reports,
                "control_false_report_count": len(control_reports),
                "control_false_reports": control_reports,
                "control_zero_bugs_reported": len(control_reports) == 0,
                "runs": bug_on_runs + control_runs,
                "regression_runs": regression_runs,
                "matching_method": (
                    "A report matches one planted bug only when the test's final goto "
                    "path equals the planted page and at least two significant trigger "
                    "keywords appear in its report/result text or test steps. Repeated "
                    "or distinct product-add actions supply their corresponding qualifier. Each "
                    "planted bug can match at most once per run."
                ),
            }

            results_dir = ROOT_DIR / "eval" / "results"
            results_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            output_file = results_dir / f"{timestamp}.json"
            output_file.write_text(json.dumps(report, indent=2), encoding="utf-8")
            print_summary(report)
            print(f"\nResults written to {output_file}")
            print("\nRaw JSON:")
            print(json.dumps(report, indent=2))
            return 0
        finally:
            terminate_process(backend_process)
            terminate_process(sample_process)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"Evaluation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
