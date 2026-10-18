"""Shared Playwright runner library used by generated pytest test cases.

Provides PlaywrightTestSession context manager that attaches console & network listeners,
translates standard test actions, and automatically captures evidence on failure.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from playwright.sync_api import sync_playwright, Playwright, Browser, BrowserContext, Page

from backend.app.agent.evidence import ConsoleEntry, NetworkEntry, EvidenceData
from backend.app.config import settings


class PlaywrightTestSession:
    """Context manager executing test actions with active evidence listeners."""

    def __init__(
        self,
        session_id: str,
        tc_id: str,
        storage_dir: Path | str | None = None,
        timeout_seconds: int | None = None,
        headless: bool = True,
    ):
        self.session_id = session_id
        self.tc_id = tc_id
        self.storage_dir = Path(storage_dir or settings.STORAGE_DIR).resolve()
        self.timeout_seconds = timeout_seconds or settings.TEST_TIMEOUT_SECONDS
        self.headless = headless

        self._playwright: Playwright | None = None
        self._browser: Browser | None = None
        self._context: BrowserContext | None = None
        self.page: Page | None = None

        self.console_logs: list[ConsoleEntry] = []
        self.network_errors: list[NetworkEntry] = []

    def __enter__(self) -> PlaywrightTestSession:
        self._playwright = sync_playwright().start()
        self._browser = self._playwright.chromium.launch(headless=self.headless)
        self._context = self._browser.new_context()
        self.page = self._context.new_page()
        self.page.set_default_timeout(self.timeout_seconds * 1000)

        # 1. Capture browser console messages (error and warning)
        def _on_console(msg: Any) -> None:
            if msg.type in ("error", "warning"):
                loc = f"{msg.location.get('url', '')}:{msg.location.get('lineNumber', '')}" if msg.location else None
                self.console_logs.append(
                    ConsoleEntry(type=msg.type, text=msg.text, location=loc)
                )

        # 2. Capture failed network requests
        def _on_request_failed(request: Any) -> None:
            self.network_errors.append(
                NetworkEntry(
                    method=request.method,
                    url=request.url,
                    status=None,
                    failure=request.failure or "Request failed",
                )
            )

        # 3. Capture responses with status >= 400
        def _on_response(response: Any) -> None:
            if response.status >= 400:
                self.network_errors.append(
                    NetworkEntry(
                        method=response.request.method,
                        url=response.url,
                        status=response.status,
                        failure=None,
                    )
                )

        self.page.on("console", _on_console)
        self.page.on("requestfailed", _on_request_failed)
        self.page.on("response", _on_response)

        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        if exc_type is not None:
            # Capture failure evidence
            target_dir = self.storage_dir / self.session_id / self.tc_id
            target_dir.mkdir(parents=True, exist_ok=True)
            screenshot_path = target_dir / "failure.png"

            final_url = None
            page_title = None

            if self.page:
                try:
                    final_url = self.page.url
                    page_title = self.page.title()
                    self.page.screenshot(path=str(screenshot_path), full_page=True)
                except Exception:
                    screenshot_path = None

            failure_msg = str(exc_val) if exc_val else f"{exc_type.__name__}"

            evidence = EvidenceData(
                session_id=self.session_id,
                tc_id=self.tc_id,
                screenshot_path=str(screenshot_path) if screenshot_path and screenshot_path.exists() else None,
                console_logs=self.console_logs,
                network_errors=self.network_errors,
                final_url=final_url,
                page_title=page_title,
                failure_message=failure_msg,
            )
            evidence.save(self.storage_dir)

        # Clean up browser resources
        try:
            if self._context:
                self._context.close()
        except Exception:
            pass
        try:
            if self._browser:
                self._browser.close()
        except Exception:
            pass
        try:
            if self._playwright:
                self._playwright.stop()
        except Exception:
            pass

        # Return False to re-raise exception for pytest
        return False

    # Action implementations
    def goto(self, url: str) -> None:
        """Navigate to target URL."""
        assert self.page is not None
        self.page.goto(url)

    def fill(self, target: str, value: str | None) -> None:
        """Fill input field with value."""
        assert self.page is not None
        self.page.fill(target, value or "")

    def click(self, target: str) -> None:
        """Click element matching selector."""
        assert self.page is not None
        self.page.click(target)

    def expect_text(self, target: str, expected_text: str) -> None:
        """Assert target element contains expected text."""
        assert self.page is not None
        locator = self.page.locator(target)
        actual_text = locator.inner_text()
        assert expected_text in actual_text, (
            f"Expected text '{expected_text}' not found in '{actual_text}' at selector '{target}'"
        )

    def expect_url(self, expected_url: str) -> None:
        """Assert current page URL contains expected URL."""
        assert self.page is not None
        current_url = self.page.url
        assert expected_url in current_url, (
            f"Expected URL '{expected_url}' not found in current URL '{current_url}'"
        )

    def expect_visible(self, target: str) -> None:
        """Assert target element is visible."""
        assert self.page is not None
        locator = self.page.locator(target)
        assert locator.is_visible(), f"Expected element '{target}' to be visible, but it was not"

    def expect_not_visible(self, target: str) -> None:
        """Assert target element is not visible."""
        assert self.page is not None
        locator = self.page.locator(target)
        assert not locator.is_visible(), f"Expected element '{target}' to be not visible, but it was"

    def expect_count_text(self, target: str, expected_count: str | int) -> None:
        """Assert target element text matches expected count string."""
        assert self.page is not None
        locator = self.page.locator(target)
        actual = locator.inner_text().strip()
        expected = str(expected_count).strip()
        assert actual == expected, (
            f"Expected count text '{expected}', got '{actual}' at selector '{target}'"
        )
