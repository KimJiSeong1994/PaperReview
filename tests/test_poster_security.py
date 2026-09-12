"""Poster backend security regression contracts."""

from __future__ import annotations

import hashlib
import re

from app.DeepAgent.agents.poster_agent import PosterGenerationAgent
from app.DeepAgent.agents.poster_composition_agent import PosterCompositionAgent
from app.DeepAgent.poster.sanitizer import sanitize_css, sanitize_poster_markup

# Every stylesheet below carries this declaration so each case can assert both
# halves of the contract: the dangerous part is gone AND the stylesheet is still
# there. Asserting only the first misses over-blocking, which cost the poster its
# whole <style> block; asserting only the second misses the security boundary.
_CANARY = "color:#123456"
_STYLE_BODY_RE = re.compile(r"<style>(.*)</style>", re.DOTALL)


def _sanitized_stylesheet(css: str) -> str:
    """Return what the poster sanitizer left inside <style>."""
    sanitized = sanitize_poster_markup(f"<style>{css}</style>")
    body = _STYLE_BODY_RE.search(sanitized)
    assert body is not None, "the <style> element itself has to survive"
    return body.group(1)


def test_static_svg_and_data_image_sources_survive_poster_sanitization() -> None:
    html = (
        '<svg viewBox="0 0 160 90"><rect width="160" height="90"/></svg>'
        '<img src="data:image/png;base64,AAAA" alt="safe">'
    )

    sanitized = PosterGenerationAgent._sanitize_external_images(html)

    assert "<svg" in sanitized
    assert 'viewbox="0 0 160 90"' in sanitized.lower()
    assert "<rect" in sanitized
    assert 'src="data:image/png;base64,AAAA"' in sanitized


def test_external_image_src_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup('<img src="https://example.com/logo.png" alt="x">')

    assert "https://example.com/logo.png" not in sanitized


def test_relative_image_src_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup('<img src="/private/logo.png" alt="x">')

    assert "/private/logo.png" not in sanitized


def test_external_anchor_href_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup('<a href="https://example.com">paper</a>')

    assert "https://example.com" not in sanitized


def test_relative_anchor_href_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup('<a href="../secret">paper</a>')

    assert "../secret" not in sanitized


def test_body_background_external_url_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup('<body background="https://evil.example/bg.png">safe</body>')

    assert "evil.example" not in sanitized
    assert "background=" not in sanitized


def test_table_background_protocol_relative_url_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup('<table background="//evil.example/bg.png"><tr><td>safe</td></tr></table>')

    assert "evil.example" not in sanitized
    assert "background=" not in sanitized


def test_table_cell_background_relative_url_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup('<table><tr><td background="../bg.png">safe</td></tr></table>')

    assert "../bg.png" not in sanitized
    assert "background=" not in sanitized


def test_svg_use_references_are_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        '<svg viewBox="0 0 10 10"><use href="#shape"></use></svg>'
    )

    assert "<use" not in sanitized
    assert 'href="#shape"' not in sanitized


def test_svg_image_references_are_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        '<svg viewBox="0 0 10 10"><image href="figure.png"></image></svg>'
    )

    assert "<image" not in sanitized
    assert "figure.png" not in sanitized


def test_svg_foreign_object_is_dropped_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        '<svg viewBox="0 0 10 10"><foreignObject><div>html</div></foreignObject></svg>'
    )

    assert "foreignObject" not in sanitized
    assert "<div" not in sanitized


def test_svg_animation_is_dropped_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        '<svg viewBox="0 0 10 10"><animate attributeName="x"></animate></svg>'
    )

    assert "<animate" not in sanitized


def test_svg_set_animation_is_dropped_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        '<svg viewBox="0 0 10 10"><set attributeName="href" to="javascript:alert(1)"></set></svg>'
    )

    assert "<set" not in sanitized


def test_raster_data_image_survives_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup('<img src="data:image/png;base64,AAAA" alt="safe">')

    assert 'src="data:image/png;base64,AAAA"' in sanitized


def test_safe_static_svg_shape_survives_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        '<svg viewBox="0 0 10 10"><rect width="10" height="10"></rect></svg>'
    )

    assert "<svg" in sanitized
    assert "<rect" in sanitized


def test_svg_presentation_attr_external_url_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        '<svg viewBox="0 0 10 10"><rect fill="url(https://evil.example/g.svg#g)"></rect></svg>'
    )

    assert "https://evil.example" not in sanitized
    assert "url(" not in sanitized


def test_svg_presentation_attr_protocol_relative_url_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        '<svg viewBox="0 0 10 10"><rect stroke="url(//evil.example/g.svg#g)"></rect></svg>'
    )

    assert "//evil.example" not in sanitized
    assert "url(" not in sanitized


def test_svg_presentation_attr_relative_url_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        '<svg viewBox="0 0 10 10"><rect filter="url(../filters.svg#blur)"></rect></svg>'
    )

    assert "../filters.svg" not in sanitized
    assert "url(" not in sanitized


def test_svg_presentation_attr_local_fragment_url_survives_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        '<svg viewBox="0 0 10 10">'
        '<defs><linearGradient id="gradient"></linearGradient></defs>'
        '<rect fill="url(#gradient)"></rect>'
        "</svg>"
    )

    assert 'fill="url(#gradient)"' in sanitized
    assert "<lineargradient" in sanitized.lower()


def test_javascript_image_protocol_is_removed_from_generated_poster_html() -> None:
    html = '<img src="javascript:alert(1)" alt="x">'

    sanitized = PosterGenerationAgent._sanitize_external_images(html)

    assert "javascript:" not in sanitized


def test_event_handler_attributes_are_removed_from_generated_poster_html() -> None:
    html = '<section onclick="alert(1)">safe text</section>'

    sanitized = PosterGenerationAgent._sanitize_external_images(html)

    assert "onclick=" not in sanitized


def test_style_url_payloads_are_removed_from_generated_poster_html() -> None:
    html = '<div style="background-image:url(javascript:alert(1))">safe text</div>'

    sanitized = PosterGenerationAgent._sanitize_external_images(html)

    assert "javascript:" not in sanitized


def test_style_block_escaped_url_function_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        r"<style>.poster{background:u\72l(https://evil.example/bg.png);}</style>"
    )

    assert "evil.example" not in sanitized
    assert r"u\72l" not in sanitized


def test_style_attribute_escaped_url_function_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        r'<div style="background:u\72l(https://evil.example/bg.png)">safe</div>'
    )

    assert "evil.example" not in sanitized
    assert r"u\72l" not in sanitized


def test_style_block_image_set_external_url_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        '<style>.poster{background-image:image-set("https://evil.example/bg.png" 1x);}</style>'
    )

    assert "evil.example" not in sanitized
    assert "image-set" not in sanitized.lower()


def test_style_attribute_webkit_image_set_external_url_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        '<div style="background-image:-webkit-image-set(\'https://evil.example/bg.png\' 1x)">safe</div>'
    )

    assert "evil.example" not in sanitized
    assert "image-set" not in sanitized.lower()


def test_style_mixed_case_whitespace_url_is_removed_by_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        '<style>.poster{background: U R L ( https://evil.example/bg.png );}</style>'
    )

    assert "evil.example" not in sanitized
    assert "U R L" not in sanitized


def test_ordinary_grid_color_and_font_css_survives_strict_poster_sanitizer() -> None:
    sanitized = sanitize_poster_markup(
        "<style>"
        ".poster{display:grid;grid-template-columns:1fr 1fr;color:#123456;"
        "font-family:Inter,Arial,sans-serif;gap:12px;}"
        "</style>"
    )

    assert "display:grid" in sanitized
    assert "grid-template-columns:1fr 1fr" in sanitized
    assert "color:#123456" in sanitized
    assert "font-family:Inter,Arial,sans-serif" in sanitized


def test_script_tags_are_removed_from_generated_poster_html() -> None:
    html = "<main>safe<script>alert(1)</script></main>"

    sanitized = PosterGenerationAgent._sanitize_external_images(html)

    assert "<script" not in sanitized
    assert "alert(1)" not in sanitized


def test_malicious_autofigure_svg_is_inert_when_injected_by_composition() -> None:
    agent = PosterCompositionAgent()

    html = agent.inject_figures_by_composition(
        "<section><!-- EMBED_SVG_0 --></section>",
        composition=None,  # type: ignore[arg-type]
        autofigure_svgs=[
            {
                "paper_title": "Paper",
                "svg_content": (
                    '<svg viewBox="0 0 120 80" onload="alert(1)">'
                    '<script>alert(2)</script><rect width="120" height="80"/></svg>'
                ),
            }
        ],
        figures=[],
    )

    assert "onload=" not in html
    assert "<script" not in html
    assert '<svg viewBox="0 0 120 80"' in html
    assert "<rect" in html


def test_static_data_image_is_injected_by_composition() -> None:
    agent = PosterCompositionAgent()

    html = agent.inject_figures_by_composition(
        "<section><!-- EMBED_FIGURE_0 --></section>",
        composition=None,  # type: ignore[arg-type]
        autofigure_svgs=[],
        figures=[
            {
                "image_base64": "AAAA",
                "mime_type": "image/png",
                "caption": "Safe figure",
            }
        ],
    )

    assert 'src="data:image/png;base64,AAAA"' in html


def test_markdown_list_items_escape_html_payloads() -> None:
    html = PosterCompositionAgent()._text_to_html(
        "- <img src=x onerror=alert(1)> model result"
    )

    assert "<img" not in html
    assert "&lt;img" in html


def test_markdown_table_cells_escape_html_payloads() -> None:
    html = PosterCompositionAgent()._markdown_table_to_html(
        "| Paper | Result |\n"
        "| --- | --- |\n"
        "| A | <svg onload=alert(1)></svg> |\n"
    )

    assert "<svg" not in html
    assert "&lt;svg" in html


def test_agent_supplied_quality_keys_outside_the_allowlist_never_reach_the_response() -> None:
    """F4: quality is deny-by-default, like provenance."""
    from app.DeepAgent.poster.service import PosterApplicationService

    scored_html = "<main>safe</main>"
    result = PosterApplicationService()._normalize_result(
        {
            "success": True,
            "poster_html": scored_html,
            "quality": {
                "validation_score": 0.9,
                "scored_sha256": hashlib.sha256(scored_html.encode("utf-8")).hexdigest(),
                "evaluator": "rule_based",
                "leaked_path": "/tmp/private/workspace/report.md",
            },
        },
        generation_id="poster_test",
        session_id="session-1",
        timings={"total_ms": 1.0},
        provenance={"route": "direct"},
    )

    assert "leaked_path" not in result["quality"]
    assert "/tmp/private" not in str(result["quality"])
    # 필터가 해시 비교를 앞지르면 안 된다: 바이트가 그대로면 점수는 살아남는다.
    assert result["quality"]["validation_score"] == 0.9


def test_local_fragment_urls_survive_a_style_block() -> None:
    """SVG paint, mask and clip references have no network capability at all.

    The attribute path already keeps url(#gradient); a stylesheet saying the same
    thing has to be judged the same way.
    """
    kept = _sanitized_stylesheet(
        f".node{{fill:url(#gradient);mask:url(#m);clip-path:url(#c);{_CANARY}}}"
    )

    assert "fill:url(#gradient)" in kept
    assert "mask:url(#m)" in kept
    assert "clip-path:url(#c)" in kept
    assert _CANARY in kept


def test_inline_raster_data_url_survives_a_style_block() -> None:
    kept = _sanitized_stylesheet(
        f".node{{background:url(data:image/png;base64,AAAA);{_CANARY}}}"
    )

    assert "url(data:image/png;base64,AAAA)" in kept
    assert _CANARY in kept


def test_the_word_url_inside_a_css_comment_costs_nothing() -> None:
    kept = _sanitized_stylesheet(f"/* no external url(s) allowed */.node{{{_CANARY}}}")

    assert "no external url(s) allowed" in kept
    assert _CANARY in kept


def test_a_url_inside_a_css_string_literal_costs_nothing() -> None:
    """Text inside a string is not a url token to the browser either."""
    kept = _sanitized_stylesheet(f".node{{content:'url(';{_CANARY}}}")

    assert "content:'url('" in kept
    assert _CANARY in kept


def test_scroll_behavior_is_not_mistaken_for_the_behavior_property() -> None:
    """behavior: attaches script; scroll-behavior: is ordinary layout."""
    kept = _sanitized_stylesheet(f".node{{scroll-behavior:smooth;{_CANARY}}}")

    assert "scroll-behavior:smooth" in kept
    assert _CANARY in kept


def test_page_sizing_survives_a_stylesheet_that_paints_with_a_gradient() -> None:
    """The product bug: one url(#grad) used to cost the poster its @page rule,
    and with it the A3 geometry the PDF export is held to."""
    kept = _sanitized_stylesheet(
        f"@page{{size:A3 landscape;margin:0}}.node{{fill:url(#grad);{_CANARY}}}"
    )

    assert "@page{size:A3 landscape;margin:0}" in kept
    assert "fill:url(#grad)" in kept
    assert _CANARY in kept


def test_network_urls_are_removed_without_dropping_the_stylesheet() -> None:
    for target in (
        "http://evil.example/b.png",
        "https://evil.example/b.png",
        "//evil.example/b.png",
        "/abs/b.png",
        "../rel/b.png",
        "file:///etc/passwd",
        # An SVG document can carry script, so it stays out of the raster allowance.
        "data:image/svg+xml;base64,AAAA",
    ):
        kept = _sanitized_stylesheet(f".node{{background:url({target});{_CANARY}}}")

        assert target not in kept, target
        assert "url(" not in kept, target
        assert _CANARY in kept, target


def test_import_rules_are_removed_without_dropping_the_stylesheet() -> None:
    for rule in (
        "@import url(http://evil.example/x.css);",
        '@import "http://evil.example/x.css";',
        "@import url(http://evil.example/x.css) screen;",
    ):
        kept = _sanitized_stylesheet(f"{rule}.node{{{_CANARY}}}")

        assert "evil.example" not in kept, rule
        assert "@import" not in kept, rule
        assert _CANARY in kept, rule


def test_image_set_is_removed_without_dropping_the_stylesheet() -> None:
    for call in (
        'image-set("http://evil.example/b.png" 1x)',
        "-webkit-image-set('http://evil.example/b.png' 1x)",
    ):
        kept = _sanitized_stylesheet(f".node{{background-image:{call};{_CANARY}}}")

        assert "evil.example" not in kept, call
        assert "image-set" not in kept.lower(), call
        assert _CANARY in kept, call


def test_active_content_declarations_are_removed_without_dropping_the_stylesheet() -> None:
    for declaration in (
        "width:expression(alert(1))",
        # A local fragment is not safe here: an XBL binding runs script.
        "-moz-binding:url(#evil)",
        "behavior:url(#default#time2)",
    ):
        kept = _sanitized_stylesheet(f".node{{{declaration};{_CANARY}}}")

        assert "expression(" not in kept.lower(), declaration
        assert "-moz-binding" not in kept.lower(), declaration
        assert "behavior" not in kept.lower(), declaration
        assert "url(" not in kept, declaration
        assert _CANARY in kept, declaration


def test_escaped_and_spaced_url_functions_are_removed_without_dropping_the_stylesheet() -> None:
    for value in (
        r"u\72l(http://evil.example/b.png)",
        r"\75rl(http://evil.example/b.png)",
        "U R L ( http://evil.example/b.png )",
    ):
        kept = _sanitized_stylesheet(f".node{{background:{value};{_CANARY}}}")

        assert "evil.example" not in kept, value
        # The escape must not survive either: the browser would decode it back
        # into the very fetch the check just removed.
        assert "\\" not in kept, value
        assert _CANARY in kept, value


def test_a_url_token_synthesized_by_removal_is_removed_too() -> None:
    """Dropping the @import splices ``ur`` onto ``l(`` and makes a live url()."""
    kept = _sanitized_stylesheet(
        f".node{{background:ur@import a;l(http://evil.example/b.png);{_CANARY}}}"
    )

    assert "evil.example" not in kept
    assert "url(" not in kept
    assert _CANARY in kept


def test_css_that_keeps_resynthesizing_url_tokens_loses_its_stylesheet() -> None:
    """Fail-closed: input that will not converge is dropped whole, not shipped."""
    nested = "ur" * 6 + "@import a;" + "l(x)" * 5 + "l(http://evil.example)"

    assert _sanitized_stylesheet(f".node{{{_CANARY};background:{nested}}}") == ""


def test_sanitized_css_is_a_fixpoint_of_the_sanitizer() -> None:
    """What was inspected is what is returned.

    Sanitizing the output again must change nothing -- otherwise some escape or
    splice survived the check and the browser could still decode it into a fetch.
    """
    for css in (
        f".node{{fill:url(#gradient);{_CANARY}}}",
        f".node{{background:url(http://evil.example/b.png);{_CANARY}}}",
        r".node{background:u\72l(http://evil.example/b.png)}",
        f".node{{content:'url(';{_CANARY}}}",
        f"@import url(http://evil.example/x.css);.node{{{_CANARY}}}",
        f".node{{background:ur@import a;l(http://evil.example/b.png);{_CANARY}}}",
    ):
        once = sanitize_css(css)

        assert sanitize_css(once) == once, css


def test_a_self_closing_style_tag_cannot_smuggle_css_past_the_sanitizer() -> None:
    """HTMLParser sends <style/> to handle_startendtag without entering CDATA
    mode. Emitting a lone <style> there would leave every following byte as a
    live stylesheet the sanitizer never read -- and a trailing real <style>
    block closes it, so the poster still renders while the fetch happens.
    """
    sanitized = sanitize_poster_markup(
        "<style/>"
        "@import url(http://evil.example/x.css);"
        "body{background:url(http://evil.example/b.png)}"
        # CSS ignores <!-- and -->, so an unsanitized comment is a declaration
        # too once a dangling <style> has opened a stylesheet around it.
        "<!-- *{background:url(http://evil.example/c.png)} -->"
        "<style>.real{color:#123456}</style>"
    )

    assert "<style></style>" in sanitized
    # Nothing may be left open: the browser reads on to the next </style>.
    assert sanitized.count("<style>") == sanitized.count("</style>")
    assert ".real{color:#123456}" in sanitized


def test_a_self_closing_title_tag_cannot_swallow_the_rest_of_the_poster() -> None:
    """<title> is RCDATA, so a dangling one turns the whole poster into its text."""
    sanitized = sanitize_poster_markup('<title/><h1 id="t">Poster</h1>')

    assert "<title></title>" in sanitized
    assert '<h1 id="t">Poster</h1>' in sanitized


def test_self_closing_svg_shapes_still_render() -> None:
    """Closing the element must not cost the shapes a poster is drawn with."""
    sanitized = sanitize_poster_markup(
        '<svg viewBox="0 0 10 10"><rect width="10" height="10"/><circle r="2"/></svg>'
    )

    assert "<rect width=\"10\" height=\"10\"></rect>" in sanitized
    assert '<circle r="2"></circle>' in sanitized
    # Void elements must not grow a closing tag.
    assert "</img>" not in sanitize_poster_markup('<img src="data:image/png;base64,AAAA"/>')
