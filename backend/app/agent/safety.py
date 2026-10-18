"""Safety and security enforcement module.

Implements domain allowlist, action/step limits, destructive action blocking,
and secret credential masking according to Section 8 of the specification.
"""

from __future__ import annotations

import logging
import re
from urllib.parse import urlparse

from backend.app.agent.plan_models import Action, TestCase, TestPlan
from backend.app.config import settings

logger = logging.getLogger(__name__)

DESTRUCTIVE_WORDS = ("delete", "remove", "unsubscribe")


class SafetyError(Exception):
    """Raised when an operation violates security or safety guardrails."""
    pass


def get_allowed_hosts() -> list[str]:
    """Return configured allowed hostnames in lowercase."""
    return [h.strip().lower() for h in settings.ALLOWED_HOSTS if h.strip()]


def is_host_allowed(url_or_host: str, allowed_hosts: list[str] | None = None) -> bool:
    """Check if the target URL or host belongs to the domain allowlist."""
    if not url_or_host:
        return False

    hosts = [h.strip().lower() for h in (allowed_hosts or get_allowed_hosts())]

    # Handle URLs with or without scheme
    raw = url_or_host.strip()
    if not raw.startswith(("http://", "https://")):
        raw = "http://" + raw

    try:
        parsed = urlparse(raw)
        hostname = (parsed.hostname or "").lower()
    except Exception:
        return False

    if not hostname:
        return False

    return hostname in hosts


def validate_url(url: str, allowed_hosts: list[str] | None = None) -> str:
    """Validate that target URL belongs to domain allowlist, or raise SafetyError."""
    if not is_host_allowed(url, allowed_hosts):
        allowed = allowed_hosts or get_allowed_hosts()
        raise SafetyError(f"Access to URL '{url}' is blocked. Allowed hosts: {allowed}")
    return url


def check_destructive_action(action: Action) -> None:
    """Inspect action target and value, blocking any containing destructive terms."""
    fields_to_check = [action.target or "", action.value or ""]

    for field in fields_to_check:
        lower_field = field.lower()
        for word in DESTRUCTIVE_WORDS:
            # Check for word presence
            pattern = rf"\b{re.escape(word)}\b"
            if re.search(pattern, lower_field) or word in lower_field:
                msg = f"Destructive action blocked: Term '{word}' detected in action (target='{action.target}', value='{action.value}')"
                logger.warning(msg)
                raise SafetyError(msg)


def validate_test_case_safety(tc: TestCase) -> None:
    """Validate safety rules for an individual TestCase."""
    if len(tc.steps) > settings.MAX_STEPS_PER_TEST:
        raise SafetyError(
            f"Test case '{tc.id}' exceeds step limit of {settings.MAX_STEPS_PER_TEST} (has {len(tc.steps)} steps)"
        )

    for action in tc.steps:
        # If action is goto, check URL allowlist
        if action.type == "goto" and action.value:
            validate_url(action.value)
        check_destructive_action(action)


def validate_test_plan_safety(plan: TestPlan) -> None:
    """Validate safety rules for the full TestPlan."""
    if len(plan.tests) > settings.MAX_TESTS_PER_RUN:
        raise SafetyError(
            f"Test plan exceeds limit of {settings.MAX_TESTS_PER_RUN} tests (has {len(plan.tests)} tests)"
        )

    for tc in plan.tests:
        validate_test_case_safety(tc)


def mask_secrets(text: str) -> str:
    """Mask test credentials and API keys in logs and reports."""
    if not text:
        return text

    masked = text
    # Mask user password
    if settings.TEST_USER_PASSWORD:
        masked = masked.replace(settings.TEST_USER_PASSWORD, "***MASKED_PASSWORD***")

    # Mask OpenAI API key
    if settings.OPENAI_API_KEY:
        masked = masked.replace(settings.OPENAI_API_KEY, "***MASKED_API_KEY***")

    return masked
