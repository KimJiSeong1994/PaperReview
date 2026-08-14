"""Poster backend security regression contracts."""

from __future__ import annotations

from app.DeepAgent.agents.poster_agent import PosterGenerationAgent
from app.DeepAgent.agents.poster_composition_agent import PosterCompositionAgent
from app.DeepAgent.poster.sanitizer import sanitize_poster_markup


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
