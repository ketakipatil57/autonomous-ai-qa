"""Unit tests for evaluator page-and-trigger bug matching."""

from eval.run_evaluation import (
    match_report_to_bug,
    regression_outcomes_by_id,
    result_page,
)


def test_evaluation_match_requires_page_and_trigger_keywords():
    bug_report = {
        "title": "Wrong password is accepted",
        "expected": "Invalid email or password",
        "actual": "The login was accepted",
    }
    result_detail = {
        "title": "Verify wrong password is rejected",
        "expected": "Shows an error and stays on login page",
        "steps": [
            {"type": "goto", "value": "http://127.0.0.1:3000/login.html"},
            {"type": "fill", "target": "#password", "value": "WrongPassword123"},
        ],
    }
    planted_bug = {
        "id": "BUG-01",
        "page": "/login.html",
        "trigger": "Enter valid email with any wrong password",
    }

    match = match_report_to_bug(bug_report, result_detail, planted_bug)
    assert match is not None
    assert "wrong" in match["matched_trigger_keywords"]
    assert "password" in match["matched_trigger_keywords"]


def test_evaluation_match_rejects_wrong_page_or_weak_keyword_overlap():
    bug_report = {"title": "Authentication response mismatch"}
    result_detail = {
        "title": "Password validation",
        "steps": [{"type": "goto", "value": "http://127.0.0.1:3000/checkout.html"}],
    }
    planted_bug = {
        "id": "BUG-01",
        "page": "/login.html",
        "trigger": "Enter valid email with any wrong password",
    }

    assert match_report_to_bug(bug_report, result_detail, planted_bug) is None

    result_detail["steps"][0]["value"] = "http://127.0.0.1:3000/login.html"
    assert match_report_to_bug(bug_report, result_detail, planted_bug) is None


def test_result_page_uses_last_navigation():
    detail = {
        "steps": [
            {"type": "goto", "value": "http://127.0.0.1:3000/index.html"},
            {"type": "goto", "value": "http://127.0.0.1:3000/checkout.html"},
        ]
    }

    assert result_page(detail) == "/checkout.html"


def test_checkout_total_report_does_not_match_empty_cart_bug():
    bug_report = {"title": "Checkout total for quantity two"}
    result_detail = {
        "title": "Checkout total calculates for quantity 2",
        "expected": "Total equals $198.00",
        "steps": [
            {"type": "goto", "value": "http://127.0.0.1:3000/index.html"},
            {"type": "click", "target": "#add-p1"},
            {"type": "click", "target": "#add-p1"},
            {"type": "goto", "value": "http://127.0.0.1:3000/checkout.html"},
        ],
    }
    empty_cart_bug = {
        "id": "BUG-03",
        "page": "/checkout.html",
        "trigger": "Open checkout with empty cart, click Place order",
    }

    assert match_report_to_bug(bug_report, result_detail, empty_cart_bug) is None


def test_wrong_password_trigger_does_not_match_successful_login():
    result_detail = {
        "title": "Verify successful login with valid credentials",
        "expected": "Redirect to the products page",
        "steps": [
            {"type": "goto", "value": "http://127.0.0.1:3000/login.html"},
            {"type": "fill", "target": "#email", "value": "test@demo.com"},
            {"type": "fill", "target": "#password", "value": "Test@123"},
        ],
    }
    planted_bug = {
        "id": "BUG-01",
        "page": "/login.html",
        "trigger": "Enter test@demo.com with any wrong password",
    }

    assert match_report_to_bug({}, result_detail, planted_bug) is None


def test_checkout_quantity_trigger_uses_repeated_product_action():
    result_detail = {
        "title": "Checkout total calculates for quantity of 2",
        "expected": "Total equals $198.00",
        "steps": [
            {"type": "goto", "value": "http://127.0.0.1:3000/index.html"},
            {"type": "click", "target": "#add-p1"},
            {"type": "click", "target": "#add-p1"},
            {"type": "goto", "value": "http://127.0.0.1:3000/checkout.html"},
        ],
    }
    planted_bug = {
        "id": "BUG-02",
        "page": "/checkout.html",
        "trigger": "Add the same product twice, check total",
    }

    match = match_report_to_bug({}, result_detail, planted_bug)
    assert match is not None
    assert "twice" in match["matched_trigger_keywords"]


def test_evaluation_repeatability_keys_duplicate_titles_by_saved_id():
    first_saved_id = "saved-regression-test-1"
    second_saved_id = "saved-regression-test-2"
    shared_title = "Duplicate title"
    first_steps = [{"type": "goto", "value": "http://localhost:3000/index.html"}]
    second_steps = [{"type": "goto", "value": "http://localhost:3000/checkout.html"}]
    saved_tests = [
        {
            "id": first_saved_id,
            "tc_code": "TC-01",
            "title": shared_title,
            "category": "functional",
            "expected": "Show the products page",
            "steps": first_steps,
            "created_at": "2026-01-01T00:00:00",
        },
        {
            "id": second_saved_id,
            "tc_code": "TC-02",
            "title": shared_title,
            "category": "functional",
            "expected": "Show checkout",
            "steps": second_steps,
            "created_at": "2026-01-02T00:00:00",
        },
    ]
    results = [
        {
            "id": "result-2",
            "tc_code": "TC-02",
            "title": shared_title,
            "category": "functional",
            "status": "FAILED",
            "first_run_outcome": "failed",
            "recheck_outcome": "failed",
            "reason": "confirmed",
            "failure_message": "Expected checkout",
        },
        {
            "id": "result-1",
            "tc_code": "TC-01",
            "title": shared_title,
            "category": "functional",
            "status": "PASSED",
            "first_run_outcome": "passed",
            "recheck_outcome": None,
            "reason": "passed",
            "failure_message": None,
        },
    ]
    details = {
        "result-1": {"expected": "Show the products page", "steps": first_steps},
        "result-2": {"expected": "Show checkout", "steps": second_steps},
    }

    outcomes = regression_outcomes_by_id(saved_tests, results, details)

    assert outcomes[first_saved_id]["status"] == "PASSED"
    assert outcomes[second_saved_id]["status"] == "FAILED"
    assert len(outcomes) == 2


def test_empty_login_trigger_matches_email_and_password_fields():
    result_detail = {
        "title": "Verify empty email and password submission shows required error",
        "steps": [
            {"type": "goto", "value": "http://127.0.0.1:3000/login.html"},
            {"type": "click", "target": "#login-button"},
        ],
    }
    planted_bug = {
        "id": "BUG-04",
        "page": "/login.html",
        "trigger": "Submit login with empty fields",
    }

    match = match_report_to_bug({}, result_detail, planted_bug)
    assert match is not None
    assert match["matched_trigger_keywords"] == ["empty", "field"]
