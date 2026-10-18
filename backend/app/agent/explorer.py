"""Website explorer for Branch B using Playwright sync API.

Crawls the application starting from app_url using breadth-first search (BFS),
extracting links, buttons, inputs, forms, and headings to produce a SiteMap.
"""

from __future__ import annotations

import json
from collections import deque
from pathlib import Path
from urllib.parse import urljoin, urlparse
from playwright.sync_api import sync_playwright

from backend.app.agent.plan_models import (
    PageButton,
    PageData,
    PageForm,
    PageInput,
    SiteMap,
)
from backend.app.agent.safety import validate_url
from backend.app.config import settings


def normalize_url(url: str) -> str:
    """Strip URL fragments and trailing slashes for deduplication."""
    parsed = urlparse(url)
    clean_path = parsed.path.rstrip("/")
    if not clean_path:
        clean_path = "/"
    return f"{parsed.scheme}://{parsed.netloc}{clean_path}"


def extract_page_data(page) -> PageData:
    """Extract metadata, interactive elements, forms, and headings from current page."""
    current_url = page.url
    title = page.title()

    # 1. Collect all same-origin links
    parsed_base = urlparse(current_url)
    raw_links = page.eval_on_selector_all("a[href]", "elements => elements.map(e => e.getAttribute('href'))")
    links = []
    for href in raw_links:
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue
        absolute_url = urljoin(current_url, href)
        parsed_target = urlparse(absolute_url)
        # Keep same-origin links only
        if parsed_target.netloc == parsed_base.netloc:
            clean = normalize_url(absolute_url)
            if clean not in links:
                links.append(clean)

    # 2. Collect buttons
    raw_buttons = page.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll('button, input[type="button"], input[type="submit"], .btn'));
        return btns.map(b => ({
            text: (b.innerText || b.value || '').trim(),
            id: b.id || null,
            type: b.type || 'button',
            selector: b.id ? '#' + b.id : (b.className ? '.' + b.className.split(' ')[0] : null)
        }));
    }""")
    buttons = [PageButton(**b) for b in raw_buttons if b.get("text") or b.get("id")]

    # 3. Collect inputs
    raw_inputs = page.evaluate("""() => {
        const inputs = Array.from(document.querySelectorAll('input:not([type="hidden"]):not([type="submit"]):not([type="button"]), textarea, select'));
        return inputs.map(i => {
            let labelText = null;
            if (i.id) {
                const lbl = document.querySelector(`label[for="${i.id}"]`);
                if (lbl) labelText = lbl.innerText.trim();
            }
            if (!labelText && i.closest('label')) {
                labelText = i.closest('label').innerText.trim();
            }
            return {
                type: i.type || 'text',
                name: i.name || null,
                id: i.id || null,
                placeholder: i.placeholder || null,
                label: labelText
            };
        });
    }""")
    inputs = [PageInput(**inp) for inp in raw_inputs]

    # 4. Collect forms
    raw_forms = page.evaluate("""() => {
        const forms = Array.from(document.querySelectorAll('form'));
        return forms.map(f => {
            const submitBtn = f.querySelector('button[type="submit"], input[type="submit"]');
            return {
                id: f.id || null,
                action: f.action || null,
                method: (f.method || 'GET').toUpperCase(),
                submit_button: submitBtn ? (submitBtn.id ? '#' + submitBtn.id : (submitBtn.innerText || submitBtn.value || '').trim()) : null,
                inputs: []
            };
        });
    }""")
    forms = [PageForm(**frm) for frm in raw_forms]

    # 5. Collect visible headings
    raw_headings = page.eval_on_selector_all(
        "h1, h2, h3",
        "elements => elements.map(e => e.innerText.trim()).filter(t => t.length > 0)"
    )

    return PageData(
        url=current_url,
        title=title,
        links=links,
        buttons=buttons,
        inputs=inputs,
        forms=forms,
        headings=raw_headings,
    )


class SiteExplorer:
    """Breadth-first crawler collecting site metadata for test generation."""

    def __init__(self, headless: bool = True):
        self.headless = headless

    def explore(
        self,
        app_url: str,
        max_pages: int = 10,
        max_depth: int = 2,
        save_debug_dir: Path | str | None = None,
    ) -> SiteMap:
        """Perform breadth-first exploration up to max_pages and max_depth."""
        # Safety check on starting URL
        validate_url(app_url)

        queue: deque[tuple[str, int]] = deque([(app_url, 0)])
        visited: set[str] = set()
        pages: list[PageData] = []
        base_origin = urlparse(app_url).netloc

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.headless)
            context = browser.new_context()
            page = context.new_page()
            page.set_default_timeout(settings.TEST_TIMEOUT_SECONDS * 1000)

            while queue and len(pages) < max_pages:
                current_url, depth = queue.popleft()
                normalized = normalize_url(current_url)

                if normalized in visited:
                    continue

                visited.add(normalized)

                try:
                    # Enforce domain allowlist and same-origin check
                    validate_url(current_url)
                    if urlparse(current_url).netloc != base_origin:
                        continue

                    page.goto(current_url, wait_until="domcontentloaded")
                    page_data = extract_page_data(page)
                    pages.append(page_data)

                    # Enqueue next links if within depth limit
                    if depth < max_depth:
                        for next_link in page_data.links:
                            if normalize_url(next_link) not in visited:
                                queue.append((next_link, depth + 1))

                except Exception as e:
                    # Log and continue exploration on individual page errors
                    continue

            context.close()
            browser.close()

        site_map = SiteMap(
            app_url=app_url,
            pages=pages,
            explored_count=len(pages),
        )

        # Save debug JSON in storage if directory provided or default storage
        debug_dir = Path(save_debug_dir or settings.STORAGE_DIR)
        debug_dir.mkdir(parents=True, exist_ok=True)
        debug_file = debug_dir / "sitemap.json"
        try:
            with open(debug_file, "w", encoding="utf-8") as f:
                f.write(site_map.model_dump_json(indent=2))
        except Exception:
            pass

        return site_map
