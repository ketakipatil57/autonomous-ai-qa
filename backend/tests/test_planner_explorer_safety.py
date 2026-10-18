"""Milestone 3 acceptance tests: Explorer, AI Planner, and Safety.

Verifies:
1. Safety module: domain allowlist, destructive action blocking, step limits, secret masking.
2. Explorer module: BFS crawling of sample app at http://localhost:3000, metadata extraction, SiteMap creation.
3. Branch A: Instruction-based test planning (fallback and LLM integration paths).
4. Branch B: Exploration-based test planning (fallback and LLM integration paths).
5. OpenAI SDK integration, Pydantic schema validation, retry mechanism, and graceful fallback.
6. Failure explanation generation.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest

from backend.app.agent.explorer import SiteExplorer
from backend.app.agent.plan_models import Action, PageData, SiteMap, TestCase, TestPlan
from backend.app.agent.planner import AIPlanner, FallbackPlanner
from backend.app.agent.safety import (
    SafetyError,
    check_destructive_action,
    is_host_allowed,
    mask_secrets,
    validate_test_case_safety,
    validate_test_plan_safety,
    validate_url,
)
from backend.app.config import settings

SAMPLE_APP_URL = "http://localhost:3000"


# --- 1. Safety Module Tests ---

def test_safety_domain_allowlist():
    """Verify that only localhost and 127.0.0.1 are allowed by default."""
    assert is_host_allowed("http://localhost:3000/index.html") is True
    assert is_host_allowed("http://127.0.0.1:3000/checkout.html") is True
    assert is_host_allowed("localhost") is True

    # External unauthorized domains must be blocked
    assert is_host_allowed("https://evil-site.com") is False
    assert is_host_allowed("http://google.com") is False

    # validate_url must raise SafetyError on external domains
    with pytest.raises(SafetyError) as exc:
        validate_url("https://malicious.org/api")
    assert "blocked" in str(exc.value)


def test_safety_destructive_actions():
    """Verify that destructive words (delete, remove, unsubscribe) are blocked."""
    # Forbidden target
    bad_action_1 = Action(type="click", target="#delete-account-btn")
    with pytest.raises(SafetyError) as exc:
        check_destructive_action(bad_action_1)
    assert "Destructive action blocked" in str(exc.value)

    # Forbidden value
    bad_action_2 = Action(type="fill", target="#reason", value="Please unsubscribe me")
    with pytest.raises(SafetyError) as exc:
        check_destructive_action(bad_action_2)
    assert "Destructive action blocked" in str(exc.value)

    # Allowed safe actions
    safe_action = Action(type="click", target="#place-order-btn")
    check_destructive_action(safe_action)  # Should not raise


def test_safety_credential_masking():
    """Verify that test user credentials and API keys are masked in text."""
    raw_text = f"Logged in user test@demo.com with password {settings.TEST_USER_PASSWORD}."
    masked = mask_secrets(raw_text)
    assert settings.TEST_USER_PASSWORD not in masked
    assert "***MASKED_PASSWORD***" in masked


# --- 2. Explorer Module Tests ---

def test_explorer_bfs_crawling():
    """Verify BFS crawler discovers pages and extracts links, buttons, inputs, and forms."""
    explorer = SiteExplorer(headless=True)
    site_map = explorer.explore(
        app_url=SAMPLE_APP_URL,
        max_pages=5,
        max_depth=2,
    )

    assert isinstance(site_map, SiteMap)
    assert site_map.explored_count >= 3, f"Expected at least 3 pages, got {site_map.explored_count}"

    discovered_urls = [p.url for p in site_map.pages]
    assert any("index.html" in u for u in discovered_urls)
    assert any("login.html" in u for u in discovered_urls)
    assert any("checkout.html" in u for u in discovered_urls)

    # Verify element extraction on login page
    login_page = next((p for p in site_map.pages if "login.html" in p.url), None)
    assert login_page is not None
    assert any(i.id == "email" for i in login_page.inputs)
    assert any(i.id == "password" for i in login_page.inputs)
    assert any(b.id == "login-button" or "Login" in b.text for b in login_page.buttons)


# --- 3. Branch A: Instruction-Based Planning Tests ---

def test_planner_branch_a_instruction_offline():
    """Verify Branch A returns focused test cases matching specific user instructions without API key."""
    planner = AIPlanner(api_key=None)

    # Instruction 1: Wrong password login
    plan_login = planner.plan_from_instruction(
        instruction="Test login with a wrong password",
        app_url=SAMPLE_APP_URL,
    )
    assert plan_login.source == "fallback"
    assert plan_login.branch == "instruction"
    assert len(plan_login.tests) == 1
    assert "wrong password" in plan_login.tests[0].title.lower()

    # Instruction 2: Empty cart checkout
    plan_cart = planner.plan_from_instruction(
        instruction="Test checkout when cart is empty",
        app_url=SAMPLE_APP_URL,
    )
    assert plan_cart.branch == "instruction"
    assert len(plan_cart.tests) == 1
    assert "empty cart" in plan_cart.tests[0].title.lower()


# --- 4. Branch B: Exploration-Based Planning Tests ---

def test_planner_branch_b_exploration_offline():
    """Verify Branch B generates a full valid suite from SiteMap without API key."""
    explorer = SiteExplorer(headless=True)
    site_map = explorer.explore(app_url=SAMPLE_APP_URL, max_pages=3, max_depth=1)

    planner = AIPlanner(api_key=None)
    plan = planner.plan_from_exploration(site_map)

    assert plan.source == "fallback"
    assert plan.branch == "exploration"
    assert len(plan.tests) <= settings.MAX_TESTS_PER_RUN
    assert len(plan.tests) >= 5

    # Verify all test cases pass validation
    for tc in plan.tests:
        assert len(tc.steps) <= settings.MAX_STEPS_PER_TEST
        assert tc.id.startswith("TC-")


# --- 5. OpenAI Integration, Validation Retry & Graceful Fallback ---

def test_planner_openai_mock_success():
    """Verify that valid OpenAI responses are parsed and marked with source='openai'."""
    planner = AIPlanner(api_key="sk-mock-key-for-testing", model="gpt-4o-mini")

    mock_llm_payload = {
        "source": "openai",
        "branch": "instruction",
        "tests": [
            {
                "id": "TC-01",
                "title": "LLM Generated Test",
                "category": "functional",
                "steps": [
                    {"type": "goto", "value": f"{SAMPLE_APP_URL}/index.html"},
                    {"type": "click", "target": "#add-p1"},
                    {"type": "expect_text", "target": "#cart-count", "value": "1"},
                ],
                "expected": "Cart count is 1",
            }
        ],
    }

    with patch.object(planner, "_call_llm_for_plan", return_value=mock_llm_payload):
        plan = planner.plan_from_instruction("Test adding headphones", app_url=SAMPLE_APP_URL)
        assert plan.source == "openai"
        assert plan.branch == "instruction"
        assert len(plan.tests) == 1
        assert plan.tests[0].id == "TC-01"


def test_planner_openai_failure_falls_back():
    """Verify that if OpenAI API fails or throws an exception, it seamlessly falls back to FallbackPlanner."""
    planner = AIPlanner(api_key="sk-mock-key", model="gpt-4o-mini")

    with patch.object(planner, "_call_llm_for_plan", return_value=None):
        plan = planner.plan_from_instruction("Test login with a wrong password", app_url=SAMPLE_APP_URL)
        assert plan.source == "fallback"
        assert plan.branch == "instruction"
        assert len(plan.tests) >= 1


def test_explain_failure_fallback():
    """Verify plain-English explanation generation in offline mode."""
    planner = AIPlanner(api_key=None)
    explanation = planner.explain_failure(
        tc_title="Login wrong password",
        expected="Shows error message",
        failure_message="AssertionError: Expected text 'Invalid' not found in ''",
        final_url=f"{SAMPLE_APP_URL}/login.html",
    )
    assert isinstance(explanation, str)
    assert len(explanation) > 10
    assert "differed" in explanation or "failed" in explanation


def test_repo_isolation_no_planted_bugs_in_backend():
    """Verify repository isolation: backend/app/ must never import or read planted_bugs.json (Section 11 & 14)."""
    app_dir = settings.BASE_DIR / "backend" / "app"
    for py_file in app_dir.rglob("*.py"):
        content = py_file.read_text(encoding="utf-8")
        assert "planted_bugs" not in content, f"Forbidden reference to planted_bugs found in {py_file}"

