"""Verification script for Milestone 1: Sample App and Planted Bugs.

Tests the sample application using Playwright in headless Chromium:
1. Valid login behavior.
2. Each of the 5 planted bugs when SAMPLE_BUGS=on (reproducible).
3. Each of the 5 planted bugs when SAMPLE_BUGS=off (absent / fixed).
"""

from __future__ import annotations

import os
import sys
import time
from playwright.sync_api import sync_playwright, Page, expect

BASE_URL = os.environ.get("APP_URL", "http://localhost:3000")


def reset_page_state(page: Page) -> None:
    """Clear localStorage and sessionStorage to reset cart and auth."""
    page.evaluate("() => { localStorage.clear(); sessionStorage.clear(); }")


def test_valid_login(page: Page, bugs_mode: str) -> bool:
    """Verify that a valid user can log in successfully regardless of bug mode."""
    page.goto(f"{BASE_URL}/login.html?bugs={bugs_mode}")
    reset_page_state(page)
    page.reload()

    page.fill("#email", "test@demo.com")
    page.fill("#password", "Test@123")
    page.click("#login-button")

    # Should show success message and redirect
    msg = page.locator("#login-message")
    expect(msg).to_contain_text("Login successful")
    page.wait_for_url("**/index.html*", timeout=5000)
    return True


def test_bug_01(page: Page, bugs_mode: str) -> dict[str, any]:
    """BUG-01: Login accepts a wrong password for the valid email."""
    page.goto(f"{BASE_URL}/login.html?bugs={bugs_mode}")
    reset_page_state(page)
    page.reload()

    page.fill("#email", "test@demo.com")
    page.fill("#password", "WrongPassword999!")
    page.click("#login-button")

    if bugs_mode == "on":
        # Bug ON: accepts wrong password and redirects to index.html
        msg = page.locator("#login-message")
        expect(msg).to_contain_text("Login successful")
        page.wait_for_url("**/index.html*", timeout=5000)
        return {
            "bug_id": "BUG-01",
            "mode": "on",
            "passed": True,
            "observation": "Wrong password was accepted and user was redirected to index.html (bug reproduced)"
        }
    else:
        # Bug OFF: rejected with 'Invalid email or password', stays on login.html
        time.sleep(0.3)
        msg = page.locator("#login-message")
        expect(msg).to_be_visible()
        expect(msg).to_have_text("Invalid email or password")
        assert "login.html" in page.url
        return {
            "bug_id": "BUG-01",
            "mode": "off",
            "passed": True,
            "observation": "Wrong password was rejected with 'Invalid email or password' (correct behavior)"
        }


def test_bug_02(page: Page, bugs_mode: str) -> dict[str, any]:
    """BUG-02: Checkout total is wrong when quantity is 2 or more."""
    page.goto(f"{BASE_URL}/index.html?bugs={bugs_mode}")
    reset_page_state(page)
    page.reload()

    # Add Headphones ($99.00) twice
    page.click("#add-p1")
    page.click("#add-p1")

    # Navigate to checkout
    page.goto(f"{BASE_URL}/checkout.html?bugs={bugs_mode}")
    total_text = page.locator("#checkout-total").inner_text().strip()

    if bugs_mode == "on":
        # Bug ON: total only counts base price once ($99.00 instead of $198.00)
        assert total_text == "$99.00", f"Expected $99.00 when bug is ON, got {total_text}"
        return {
            "bug_id": "BUG-02",
            "mode": "on",
            "passed": True,
            "observation": f"Checkout total is {total_text} instead of $198.00 for quantity 2 (bug reproduced)"
        }
    else:
        # Bug OFF: total equals 2 * $99.00 = $198.00
        assert total_text == "$198.00", f"Expected $198.00 when bug is OFF, got {total_text}"
        return {
            "bug_id": "BUG-02",
            "mode": "off",
            "passed": True,
            "observation": f"Checkout total is {total_text} reflecting price * quantity (correct behavior)"
        }


def test_bug_03(page: Page, bugs_mode: str) -> dict[str, any]:
    """BUG-03: Checkout allows placing an order with an empty cart."""
    page.goto(f"{BASE_URL}/checkout.html?bugs={bugs_mode}")
    reset_page_state(page)
    page.reload()

    page.click("#place-order-btn")
    msg = page.locator("#order-message")
    expect(msg).to_be_visible()
    msg_text = msg.inner_text().strip()

    if bugs_mode == "on":
        # Bug ON: allows placing order
        assert "Order placed" in msg_text, f"Expected 'Order placed', got '{msg_text}'"
        return {
            "bug_id": "BUG-03",
            "mode": "on",
            "passed": True,
            "observation": f"Empty cart order succeeded with '{msg_text}' (bug reproduced)"
        }
    else:
        # Bug OFF: shows error 'Your cart is empty'
        assert "Your cart is empty" in msg_text, f"Expected 'Your cart is empty', got '{msg_text}'"
        return {
            "bug_id": "BUG-03",
            "mode": "off",
            "passed": True,
            "observation": f"Empty cart order blocked with '{msg_text}' (correct behavior)"
        }


def test_bug_04(page: Page, bugs_mode: str) -> dict[str, any]:
    """BUG-04: Empty email on login does not show the required message."""
    page.goto(f"{BASE_URL}/login.html?bugs={bugs_mode}")
    reset_page_state(page)
    page.reload()

    # Leave fields empty and submit
    page.click("#login-button")
    msg = page.locator("#login-message")

    if bugs_mode == "on":
        # Bug ON: validation message is not displayed
        is_visible = msg.is_visible()
        msg_text = msg.inner_text().strip()
        assert not is_visible or msg_text == "", f"Expected no message when bug is ON, got '{msg_text}'"
        return {
            "bug_id": "BUG-04",
            "mode": "on",
            "passed": True,
            "observation": "No validation message shown for empty login submission (bug reproduced)"
        }
    else:
        # Bug OFF: shows 'Email and password are required'
        expect(msg).to_be_visible()
        msg_text = msg.inner_text().strip()
        assert "Email and password are required" in msg_text, f"Expected 'Email and password are required', got '{msg_text}'"
        return {
            "bug_id": "BUG-04",
            "mode": "off",
            "passed": True,
            "observation": f"Validation message '{msg_text}' displayed (correct behavior)"
        }


def test_bug_05(page: Page, bugs_mode: str) -> dict[str, any]:
    """BUG-05: Cart count badge does not update after adding a second item."""
    page.goto(f"{BASE_URL}/index.html?bugs={bugs_mode}")
    reset_page_state(page)
    page.reload()

    # Add first distinct product (Headphones)
    page.click("#add-p1")
    badge_1 = page.locator("#cart-badge").inner_text().strip()
    assert badge_1 == "1", f"Expected badge '1' after first item, got '{badge_1}'"

    # Add second distinct product (Keyboard)
    page.click("#add-p2")
    badge_2 = page.locator("#cart-badge").inner_text().strip()

    if bugs_mode == "on":
        # Bug ON: badge fails to update and stays at 1
        assert badge_2 == "1", f"Expected badge to remain '1' when bug is ON, got '{badge_2}'"
        return {
            "bug_id": "BUG-05",
            "mode": "on",
            "passed": True,
            "observation": f"Cart badge remained at {badge_2} after adding second distinct product (bug reproduced)"
        }
    else:
        # Bug OFF: badge updates to 2
        assert badge_2 == "2", f"Expected badge to update to '2' when bug is OFF, got '{badge_2}'"
        return {
            "bug_id": "BUG-05",
            "mode": "off",
            "passed": True,
            "observation": f"Cart badge correctly updated to {badge_2} (correct behavior)"
        }


def run_all_checks() -> bool:
    """Run all checks across both bug modes."""
    print("=" * 70)
    print("Milestone 1 Verification: Sample App & Planted Bugs")
    print(f"Target URL: {BASE_URL}")
    print("=" * 70)

    results = []
    all_ok = True

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        print("\n--- Testing Happy Path: Valid Login ---")
        try:
            test_valid_login(page, bugs_mode="off")
            print("  [PASS] Valid login (test@demo.com / Test@123) successfully redirects")
        except Exception as e:
            print(f"  [FAIL] Valid login failed: {e}")
            all_ok = False

        print("\n--- Testing SAMPLE_BUGS=on (All 5 bugs must reproduce) ---")
        for test_fn in (test_bug_01, test_bug_02, test_bug_03, test_bug_04, test_bug_05):
            try:
                res = test_fn(page, bugs_mode="on")
                results.append(res)
                print(f"  [CONFIRMED] {res['bug_id']}: {res['observation']}")
            except Exception as e:
                print(f"  [FAILED TO REPRODUCE] {test_fn.__name__}: {e}")
                all_ok = False

        print("\n--- Testing SAMPLE_BUGS=off (All 5 bugs must be fixed/absent) ---")
        for test_fn in (test_bug_01, test_bug_02, test_bug_03, test_bug_04, test_bug_05):
            try:
                res = test_fn(page, bugs_mode="off")
                results.append(res)
                print(f"  [FIXED] {res['bug_id']}: {res['observation']}")
            except Exception as e:
                print(f"  [BUG STILL PRESENT] {test_fn.__name__}: {e}")
                all_ok = False

        context.close()
        browser.close()

    print("\n" + "=" * 70)
    print(f"Verification Summary: {'ALL PASSED' if all_ok else 'SOME CHECKS FAILED'}")
    print("=" * 70)
    return all_ok


if __name__ == "__main__":
    success = run_all_checks()
    sys.exit(0 if success else 1)
