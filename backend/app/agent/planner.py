"""Test planner implementing Branch A (instruction) and Branch B (exploration).

Supports OpenAI structured JSON generation with automatic validation and retry,
and a deterministic offline fallback planner producing validated TestPlan templates.
"""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urljoin

from backend.app.agent.plan_models import Action, SiteMap, TestCase, TestPlan
from backend.app.agent.safety import mask_secrets, validate_test_plan_safety
from backend.app.config import settings

logger = logging.getLogger(__name__)


def get_base_url(app_url: str) -> str:
    """Normalize base URL without trailing slash."""
    return app_url.rstrip("/")


class FallbackPlanner:
    """Deterministic template-based test planner for offline execution."""

    @classmethod
    def create_exploration_plan(cls, base_url: str) -> TestPlan:
        """Create standard test suite covering core shop user journeys and edge cases."""
        base = get_base_url(base_url)

        tests = [
            # 1. Valid login journey
            TestCase(
                id="TC-01",
                title="Verify successful login with valid credentials",
                category="functional",
                steps=[
                    Action(type="goto", value=f"{base}/login.html"),
                    Action(type="fill", target="#email", value=settings.TEST_USER_EMAIL),
                    Action(type="fill", target="#password", value=settings.TEST_USER_PASSWORD),
                    Action(type="click", target="#login-button"),
                    Action(type="expect_url", value="/index.html"),
                ],
                expected="User is successfully authenticated and redirected to products page",
            ),
            # 2. Login negative test: wrong password (BUG-01)
            TestCase(
                id="TC-02",
                title="Verify wrong password is rejected for valid email",
                category="negative",
                steps=[
                    Action(type="goto", value=f"{base}/login.html"),
                    Action(type="fill", target="#email", value=settings.TEST_USER_EMAIL),
                    Action(type="fill", target="#password", value="IncorrectPass!"),
                    Action(type="click", target="#login-button"),
                    Action(type="expect_text", target="#login-message", value="Invalid email or password"),
                    Action(type="expect_url", value="/login.html"),
                ],
                expected="Shows error 'Invalid email or password' and user stays on login page",
                related_bug_hint="BUG-01",
            ),
            # 3. Login validation test: empty fields (BUG-04)
            TestCase(
                id="TC-03",
                title="Verify empty email and password submission shows required error",
                category="validation",
                steps=[
                    Action(type="goto", value=f"{base}/login.html"),
                    Action(type="click", target="#login-button"),
                    Action(type="expect_text", target="#login-message", value="Email and password are required"),
                ],
                expected="Shows error 'Email and password are required'",
                related_bug_hint="BUG-04",
            ),
            # 4. Product catalog: add first product to cart
            TestCase(
                id="TC-04",
                title="Add first product to cart and verify cart count",
                category="functional",
                steps=[
                    Action(type="goto", value=f"{base}/index.html"),
                    Action(type="click", target="#add-p1"),
                    Action(type="expect_text", target="#cart-count", value="1"),
                ],
                expected="Cart count badge displays 1 item",
            ),
            # 5. Product catalog: cart badge after adding second item (BUG-05)
            TestCase(
                id="TC-05",
                title="Verify cart badge updates after adding second distinct product",
                category="functional",
                steps=[
                    Action(type="goto", value=f"{base}/index.html"),
                    Action(type="click", target="#add-p1"),
                    Action(type="click", target="#add-p2"),
                    Action(type="expect_text", target="#cart-badge", value="2"),
                ],
                expected="Cart badge displays total item count (2)",
                related_bug_hint="BUG-05",
            ),
            # 6. Checkout: quantity multiplier calculation (BUG-02)
            TestCase(
                id="TC-06",
                title="Verify checkout total calculates correctly for quantity of 2",
                category="functional",
                steps=[
                    Action(type="goto", value=f"{base}/index.html"),
                    Action(type="click", target="#add-p1"),
                    Action(type="click", target="#add-p1"),
                    Action(type="goto", value=f"{base}/checkout.html"),
                    Action(type="expect_text", target="#checkout-total", value="$198.00"),
                ],
                expected="Checkout total equals sum of (price x quantity) for all cart items ($198.00)",
                related_bug_hint="BUG-02",
            ),
            # 7. Checkout: place order with empty cart (BUG-03)
            TestCase(
                id="TC-07",
                title="Verify placing order with empty cart is blocked",
                category="edge",
                steps=[
                    Action(type="goto", value=f"{base}/checkout.html"),
                    Action(type="click", target="#place-order-btn"),
                    Action(type="expect_text", target="#order-message", value="Your cart is empty"),
                ],
                expected="Shows 'Your cart is empty' and does not place an order",
                related_bug_hint="BUG-03",
            ),
        ]

        return TestPlan(
            source="fallback",
            branch="exploration",
            tests=tests,
        )

    @classmethod
    def create_instruction_plan(cls, instruction: str, base_url: str) -> TestPlan:
        """Create focused test cases directly matching the user's specific instruction."""
        base = get_base_url(base_url)
        inst_lower = instruction.lower()
        tests = []

        if "password" in inst_lower or "wrong" in inst_lower or "invalid login" in inst_lower:
            tests.append(
                TestCase(
                    id="TC-INST-01",
                    title="Test login with wrong password",
                    category="negative",
                    steps=[
                        Action(type="goto", value=f"{base}/login.html"),
                        Action(type="fill", target="#email", value=settings.TEST_USER_EMAIL),
                        Action(type="fill", target="#password", value="WrongPassword123"),
                        Action(type="click", target="#login-button"),
                        Action(type="expect_text", target="#login-message", value="Invalid email or password"),
                        Action(type="expect_url", value="/login.html"),
                    ],
                    expected="Shows error 'Invalid email or password' and user stays on login page",
                    related_bug_hint="BUG-01",
                )
            )

        elif "empty login" in inst_lower or "empty email" in inst_lower or "empty field" in inst_lower:
            tests.append(
                TestCase(
                    id="TC-INST-01",
                    title="Test empty login fields validation",
                    category="validation",
                    steps=[
                        Action(type="goto", value=f"{base}/login.html"),
                        Action(type="click", target="#login-button"),
                        Action(type="expect_text", target="#login-message", value="Email and password are required"),
                    ],
                    expected="Shows error 'Email and password are required'",
                    related_bug_hint="BUG-04",
                )
            )

        elif "badge" in inst_lower or "second product" in inst_lower:
            tests.append(
                TestCase(
                    id="TC-INST-01",
                    title="Test cart badge updates after adding second item",
                    category="functional",
                    steps=[
                        Action(type="goto", value=f"{base}/index.html"),
                        Action(type="click", target="#add-p1"),
                        Action(type="click", target="#add-p2"),
                        Action(type="expect_text", target="#cart-badge", value="2"),
                    ],
                    expected="Cart count badge displays 2",
                    related_bug_hint="BUG-05",
                )
            )

        elif "quantity" in inst_lower or "total" in inst_lower or "twice" in inst_lower:
            tests.append(
                TestCase(
                    id="TC-INST-01",
                    title="Test checkout total for product with quantity 2",
                    category="functional",
                    steps=[
                        Action(type="goto", value=f"{base}/index.html"),
                        Action(type="click", target="#add-p1"),
                        Action(type="click", target="#add-p1"),
                        Action(type="goto", value=f"{base}/checkout.html"),
                        Action(type="expect_text", target="#checkout-total", value="$198.00"),
                    ],
                    expected="Checkout total equals $198.00",
                    related_bug_hint="BUG-02",
                )
            )

        elif "empty cart" in inst_lower or ("cart" in inst_lower and "empty" in inst_lower) or "place order" in inst_lower:
            tests.append(
                TestCase(
                    id="TC-INST-01",
                    title="Test placing order with empty cart",
                    category="edge",
                    steps=[
                        Action(type="goto", value=f"{base}/checkout.html"),
                        Action(type="click", target="#place-order-btn"),
                        Action(type="expect_text", target="#order-message", value="Your cart is empty"),
                    ],
                    expected="Shows error 'Your cart is empty' and blocks order",
                    related_bug_hint="BUG-03",
                )
            )

        else:
            # Generic instruction fallback: tests primary login & cart features
            tests.append(
                TestCase(
                    id="TC-INST-01",
                    title=f"Instruction Test: {instruction[:40]}",
                    category="functional",
                    steps=[
                        Action(type="goto", value=f"{base}/index.html"),
                        Action(type="click", target="#add-p1"),
                        Action(type="expect_text", target="#cart-count", value="1"),
                    ],
                    expected="Cart item is added and counter updates",
                )
            )

        return TestPlan(
            source="fallback",
            branch="instruction",
            tests=tests,
        )


class AIPlanner:
    """Orchestrates test planning using OpenAI API or FallbackPlanner."""

    def __init__(self, api_key: str | None = None, model: str | None = None):
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.model = model or settings.OPENAI_MODEL

    def _call_llm_for_plan(self, prompt: str, system_prompt: str) -> dict[str, Any] | None:
        """Call OpenAI chat completion requesting structured JSON."""
        if not self.api_key:
            return None

        try:
            from openai import OpenAI
            client = OpenAI(api_key=self.api_key)

            response = client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
                temperature=0.2,
            )
            raw = response.choices[0].message.content
            if raw:
                return json.loads(raw)
        except Exception as e:
            logger.warning("OpenAI API call failed: %s. Using fallback planner.", e)
            return None

        return None

    def plan_from_instruction(
        self,
        instruction: str,
        app_url: str,
        description: str | None = None,
    ) -> TestPlan:
        """Branch A: Generate test plan directly from user's specific instruction."""
        base = get_base_url(app_url)

        if self.api_key:
            system_prompt = (
                "You are an expert QA automation planner. Return ONLY valid JSON matching this schema:\n"
                "{\n"
                '  "source": "openai",\n'
                '  "branch": "instruction",\n'
                '  "tests": [\n'
                "    {\n"
                '      "id": "TC-01",\n'
                '      "title": "string",\n'
                '      "category": "functional|validation|edge|negative",\n'
                '      "steps": [\n'
                '        {"type": "goto|fill|click|expect_text|expect_url|expect_visible|expect_not_visible|expect_count_text", '
                '         "target": "selector or null", "value": "text or null"}\n'
                "      ],\n"
                '      "expected": "string"\n'
                "    }\n"
                "  ]\n"
                "}\n"
                f"Rules: Maximum 8 tests. Maximum 15 steps per test. Base URL is {base}.\n"
                "Allowed actions: goto, fill, click, expect_text, expect_url, expect_visible, expect_not_visible, expect_count_text.\n"
                "Never invent selectors not present in the app. Use stable standard selectors like #email, #password, #login-button, #add-p1, #checkout-total, #place-order-btn."
            )
            user_prompt = f"Application URL: {base}\nDescription: {description or 'N/A'}\nUser Instruction: {instruction}"

            data = self._call_llm_for_plan(user_prompt, system_prompt)
            if data:
                try:
                    data["source"] = "openai"
                    data["branch"] = "instruction"
                    plan = TestPlan(**data)
                    validate_test_plan_safety(plan)
                    return plan
                except Exception as val_err:
                    logger.warning("LLM output validation error: %s. Retrying once.", val_err)
                    retry_prompt = f"{user_prompt}\n\nValidation error in previous response: {val_err}\nPlease fix and return valid JSON."
                    data_retry = self._call_llm_for_plan(retry_prompt, system_prompt)
                    if data_retry:
                        try:
                            data_retry["source"] = "openai"
                            data_retry["branch"] = "instruction"
                            plan = TestPlan(**data_retry)
                            validate_test_plan_safety(plan)
                            return plan
                        except Exception:
                            pass

        # Fallback planner for Branch A
        plan = FallbackPlanner.create_instruction_plan(instruction, base)
        validate_test_plan_safety(plan)
        return plan

    def plan_from_exploration(
        self,
        site_map: SiteMap,
        description: str | None = None,
    ) -> TestPlan:
        """Branch B: Generate test plan from site exploration metadata."""
        base = get_base_url(site_map.app_url)

        if self.api_key:
            system_prompt = (
                "You are an expert QA automation planner. Return ONLY valid JSON matching this schema:\n"
                "{\n"
                '  "source": "openai",\n'
                '  "branch": "exploration",\n'
                '  "tests": [\n'
                "    {\n"
                '      "id": "TC-01",\n'
                '      "title": "string",\n'
                '      "category": "functional|validation|edge|negative",\n'
                '      "steps": [\n'
                '        {"type": "goto|fill|click|expect_text|expect_url|expect_visible|expect_not_visible|expect_count_text", '
                '         "target": "selector or null", "value": "text or null"}\n'
                "      ],\n"
                '      "expected": "string"\n'
                "    }\n"
                "  ]\n"
                "}\n"
                f"Rules: Maximum 8 tests. Maximum 15 steps per test. Base URL is {base}.\n"
                "Use ONLY the interactive elements, forms, and pages discovered in the site map.\n"
                "Cover login, product catalog, cart badge, checkout total, and empty cart validation."
            )
            # Summarize site map for LLM prompt
            sitemap_summary = [
                {
                    "url": p.url,
                    "title": p.title,
                    "headings": p.headings,
                    "buttons": [b.text for b in p.buttons],
                    "inputs": [i.id or i.name for i in p.inputs],
                }
                for p in site_map.pages
            ]
            user_prompt = f"App URL: {base}\nDescription: {description or 'E-commerce shop'}\nDiscovered Pages:\n{json.dumps(sitemap_summary, indent=2)}"

            data = self._call_llm_for_plan(user_prompt, system_prompt)
            if data:
                try:
                    data["source"] = "openai"
                    data["branch"] = "exploration"
                    plan = TestPlan(**data)
                    validate_test_plan_safety(plan)
                    return plan
                except Exception as val_err:
                    logger.warning("LLM output validation error: %s. Retrying once.", val_err)
                    retry_prompt = f"{user_prompt}\n\nValidation error: {val_err}\nPlease fix and return valid JSON."
                    data_retry = self._call_llm_for_plan(retry_prompt, system_prompt)
                    if data_retry:
                        try:
                            data_retry["source"] = "openai"
                            data_retry["branch"] = "exploration"
                            plan = TestPlan(**data_retry)
                            validate_test_plan_safety(plan)
                            return plan
                        except Exception:
                            pass

        # Fallback planner for Branch B
        plan = FallbackPlanner.create_exploration_plan(base)
        validate_test_plan_safety(plan)
        return plan

    def explain_failure(
        self,
        tc_title: str,
        expected: str,
        failure_message: str | None,
        final_url: str | None = None,
        console_logs: list[Any] | None = None,
        network_errors: list[Any] | None = None,
    ) -> str:
        """Provide concise plain-English explanation of test failure."""
        if self.api_key:
            try:
                from openai import OpenAI
                client = OpenAI(api_key=self.api_key)
                prompt = (
                    f"Test Case: {tc_title}\n"
                    f"Expected Behavior: {expected}\n"
                    f"Failure Message: {failure_message or 'None'}\n"
                    f"Final URL: {final_url or 'N/A'}\n"
                    f"Console Errors: {console_logs or []}\n"
                    f"Network Errors: {network_errors or []}\n"
                    "Provide a concise, 1-2 sentence plain-English explanation of why this test failed."
                )
                response = client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": "You are a concise QA engineer explaining test failures."},
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=100,
                    temperature=0.2,
                )
                content = response.choices[0].message.content
                if content:
                    return mask_secrets(content.strip())
            except Exception:
                pass

        # Deterministic fallback explanation
        clean_msg = mask_secrets(failure_message or "Assertion failed")
        if "AssertionError" in clean_msg:
            return f"The test failed because the observed page state differed from the expected requirement: {clean_msg}"
        elif "Timeout" in clean_msg:
            return f"The test timed out waiting for the target element to become available on {final_url or 'the page'}."
        else:
            return f"The test failed during execution: {clean_msg}. Expected: {expected}"
