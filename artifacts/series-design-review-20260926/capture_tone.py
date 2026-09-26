"""Capture the deployed home/search, blog index, post and series surfaces for a tone comparison."""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

OUT = Path(__file__).resolve().parent / "tone"
OUT.mkdir(exist_ok=True)
BASE = "https://jiphyeonjeon.kr"
PAGES = {
    "home": "/",
    "blog": "/blog",
    "post": "/blog/deepwalk-online-learning-social-representations-review-2026",
    "series": "/blog/series/gnn",
    "tags": "/blog/tags",
}


def main() -> None:
    receipt = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        for theme in ("light", "dark"):
            for name, (w, h) in {"mobile": (390, 844), "desktop": (1280, 900)}.items():
                context = browser.new_context(viewport={"width": w, "height": h}, color_scheme=theme)
                page = context.new_page()
                for key, path in PAGES.items():
                    page.goto(BASE + path, wait_until="networkidle")
                    page.evaluate("t => document.documentElement.setAttribute('data-theme', t)", theme)
                    page.wait_for_timeout(400)
                    page.screenshot(path=str(OUT / f"{key}-{name}-{theme}.png"))
                    if key in ("home", "series") and name == "desktop":
                        page.screenshot(path=str(OUT / f"{key}-{name}-{theme}-full.png"), full_page=True)
                    tokens = page.evaluate(
                        """() => {
                          const cs = el => el ? getComputedStyle(el) : null;
                          const pick = (sel, props) => { const s = cs(document.querySelector(sel)); return s ? Object.fromEntries(props.map(p => [p, s[p]])) : null; };
                          return {
                            bodyBg: cs(document.body).backgroundColor,
                            font: cs(document.body).fontFamily,
                            h1: pick('h1', ['fontSize','fontWeight','letterSpacing','color']),
                            button: pick('button, a.blog-series-start-cta, .search-btn, .blog-detail-pdf-link', ['borderRadius','backgroundColor','color','fontSize','fontWeight','padding']),
                            card: pick('.blog-rail-card, .home-card, .blog-series-start, .geo-decision, .result-card', ['borderRadius','backgroundColor','borderColor','boxShadow','padding']),
                            radii: [...new Set([...document.querySelectorAll('*')].map(e => getComputedStyle(e).borderRadius).filter(r => r && r !== '0px'))].slice(0, 12),
                          };
                        }"""
                    )
                    receipt.append({"page": key, "viewport": name, "theme": theme, **tokens})
                context.close()
        browser.close()
    (OUT / "tone-receipt.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"captures": len(receipt)}))


if __name__ == "__main__":
    main()
