"""Capture the deployed series pages and neighbouring brand surfaces for design review."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent
BASE = "https://jiphyeonjeon.kr"
PAGES = {
    "series-gnn": "/blog/series/gnn",
    "series-graphrag": "/blog/series/graphrag",
    "series-build": "/blog/series/jiphyeonjeon-build",
    "blog-index": "/blog",
    "post": "/blog/deepwalk-online-learning-social-representations-review-2026",
}
VIEWPORTS = {"mobile": (390, 844), "desktop": (1280, 900)}


def main() -> None:
    receipt = {"base": BASE, "captures": []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for theme in ("light", "dark"):
            for name, (width, height) in VIEWPORTS.items():
                context = browser.new_context(viewport={"width": width, "height": height}, color_scheme=theme)
                page = context.new_page()
                for key, path in PAGES.items():
                    page.goto(BASE + path, wait_until="networkidle")
                    page.evaluate("theme => document.documentElement.setAttribute('data-theme', theme)", theme)
                    page.wait_for_timeout(400)
                    fold = OUT / f"{key}-{name}-{theme}-fold.png"
                    page.screenshot(path=str(fold))
                    full = OUT / f"{key}-{name}-{theme}-full.png"
                    page.screenshot(path=str(full), full_page=True)
                    metrics = page.evaluate(
                        """() => {
                          const cs = el => el ? getComputedStyle(el) : null;
                          const h1 = cs(document.querySelector('h1'));
                          const body = cs(document.querySelector('p'));
                          return {
                            height: document.documentElement.scrollHeight,
                            h1: h1 && { size: h1.fontSize, weight: h1.fontWeight, family: h1.fontFamily },
                            body: body && { size: body.fontSize, lineHeight: body.lineHeight, family: body.fontFamily },
                            headings: [...document.querySelectorAll('h2,h3')].slice(0, 12).map(e => ({ tag: e.tagName, text: e.textContent.trim().slice(0, 40), size: getComputedStyle(e).fontSize })),
                          };
                        }"""
                    )
                    receipt["captures"].append({"page": key, "viewport": name, "theme": theme, "fold": fold.name, "full": full.name, **metrics})
                context.close()
        browser.close()
    (OUT / "capture-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"captures": len(receipt["captures"])}))


if __name__ == "__main__":
    main()
