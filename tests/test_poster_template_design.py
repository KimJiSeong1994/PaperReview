"""Academic poster template design regression contracts."""

from __future__ import annotations

import re

from app.DeepAgent.agents.poster_composition_agent import PosterCompositionAgent
from app.DeepAgent.agents.poster_content_agent import ExtractedContent
from app.DeepAgent.agents.poster_critic_agent import PosterCriticAgent
from app.DeepAgent.agents.poster_agent import PosterGenerationAgent
from app.DeepAgent.agents.poster_layout_agent import LayoutType, PosterLayoutAgent
from app.DeepAgent.agents.poster_visual_agent import PosterVisualAgent
from app.DeepAgent.config.style_manager import StyleManager


LONG_REVIEW_TITLE = (
    "검색-증강 그래프 추론과 Verifier-Guided Multi-Agent Planning for "
    "Long-Horizon Scientific Literature Synthesis Under Noisy Evidence"
)


def _content_fixture() -> ExtractedContent:
    papers = [
        {
            "title": "GraphRAG for Scientific Claim Retrieval",
            "methodology": (
                "A heterogeneous citation graph links claims, experiments, and "
                "datasets before retrieval re-ranks evidence by path support."
            ),
            "contributions": "Introduces graph-aware retrieval for verifiable survey writing.",
            "results": "Improves answer attribution by 18.4 points on 420 benchmark questions.",
            "limitations": "Evaluation is limited to English-language benchmark questions.",
        },
        {
            "title": "Verifier-Guided Multi-Agent Planning",
            "methodology": (
                "Planner, executor, and verifier roles coordinate through explicit "
                "state transitions and artifact checks."
            ),
            "contributions": "Reduces unsupported synthesis in long-horizon agent workflows.",
            "results": "Cuts invalid citations from 14.2% to 3.1% across 96 review tasks.",
            "limitations": "The review-task sample is smaller than the retrieval benchmark.",
        },
        {
            "title": "Table-Preserving Evidence Compression",
            "methodology": (
                "Structured tables are carried as typed evidence objects, then rendered "
                "after summarization to avoid lossy markdown flattening."
            ),
            "contributions": "Keeps comparative evidence auditable in poster summaries.",
            "results": "Preserves 97% of table cells in ablation reports.",
            "limitations": "Complex merged-cell tables remain under-tested.",
        },
    ]
    return ExtractedContent(
        title=LONG_REVIEW_TITLE,
        subtitle="A three-paper systematic review poster template stress test",
        abstract=(
            "Abstract: We compare retrieval, planning, and evidence compression methods "
            "for scientific literature synthesis with concrete accuracy, latency, and "
            "citation quality measurements."
        ),
        motivation=(
            "Background: conference posters need a clear thesis, compact evidence, "
            "and print-safe visuals without relying on remote assets."
        ),
        contributions=[
            "Unifies three papers around verifiable evidence flow.",
            "Separates claims, methods, and quantitative results.",
            "Preserves figure captions and tables as first-class evidence.",
        ],
        methodology=(
            "Methodology: extract claims, retrieve graph neighborhoods, plan synthesis, "
            "verify citations, and export print-ready HTML."
        ),
        paper_titles=[paper["title"] for paper in papers],
        key_findings=[
            "Thesis: graph-grounded evidence plus verifier roles improves literature synthesis reliability.",
            "Evaluation shows 18.4-point attribution gains and 3.1% invalid citation rates.",
            "Table-preserving rendering keeps comparison evidence inspectable.",
        ],
        comparison_data={},
        conclusion=(
            "Conclusion: evidence-aware poster design should show the thesis first, "
            "then method-specific panels, quantitative results, and auditable references."
        ),
        keywords=["GraphRAG", "Verifier", "Evidence", "Poster", "Print CSS"],
        statistics={"num_papers": 3, "num_figures": 4, "num_tables": 1},
        required_visualizations=["pipeline_diagram", "comparison_table"],
        content_analysis={"domain": "scientific_literature_review"},
        figures=[
            {
                "paper_title": "GraphRAG for Scientific Claim Retrieval",
                "image_base64": "AAAA",
                "mime_type": "image/png",
                "caption": "Figure 1. Claim graph neighborhood used for evidence retrieval.",
            }
        ],
        paper_analyses=papers,
        comparison_tables=[
            "| Paper | Metric | Result |\n"
            "| --- | --- | --- |\n"
            "| GraphRAG | Attribution | +18.4 points |\n"
            "| Verifier Planning | Invalid citations | 3.1% |\n"
            "| Evidence Compression | Table cells preserved | 97% |"
        ],
        visualization_data={"quantitative": {"attribution_gain": "18.4 points"}},
        references=[
            "GraphRAG for Scientific Claim Retrieval, 2025.",
            "Verifier-Guided Multi-Agent Planning, 2025.",
        ],
    )


def _autofigures_fixture() -> list[dict[str, str]]:
    return [
        {
            "paper_title": "Overall Methodology Pipeline",
            "svg_content": (
                '<svg viewBox="0 0 240 120" role="img" aria-label="pipeline">'
                '<title>Overall synthesis pipeline</title>'
                '<rect x="10" y="30" width="60" height="40"></rect>'
                '<text x="20" y="55">Claims</text>'
                '<path d="M75 50 L110 50"></path>'
                '<rect x="115" y="30" width="90" height="40"></rect>'
                '<text x="125" y="55">Verifier</text>'
                "</svg>"
            ),
        },
        {
            "paper_title": "Verifier-Guided Multi-Agent Planning",
            "svg_content": (
                '<svg viewBox="0 0 180 90" role="img" aria-label="agent roles">'
                '<circle cx="45" cy="45" r="25"></circle>'
                '<circle cx="135" cy="45" r="25"></circle>'
                '<text x="25" y="48">Plan</text><text x="112" y="48">Verify</text>'
                "</svg>"
            ),
        },
        {
            "paper_title": "Table-Preserving Evidence Compression",
            "svg_content": (
                '<svg viewBox="0 0 180 90" role="img" aria-label="table evidence">'
                '<rect x="20" y="20" width="140" height="50"></rect>'
                '<line x1="20" y1="45" x2="160" y2="45"></line>'
                '<line x1="90" y1="20" x2="90" y2="70"></line>'
                "</svg>"
            ),
        },
    ]


def _render_html() -> str:
    content = _content_fixture()
    agent = PosterCompositionAgent()
    composition = agent.design(
        content,
        autofigure_svgs=_autofigures_fixture(),
        figures=content.figures or [],
    )
    return agent.render_html(
        composition,
        autofigure_svgs=_autofigures_fixture(),
        figures=content.figures or [],
        content=content,
    )


def _canonical_polished_html() -> str:
    body_text = " ".join(
        [
            "Abstract methodology results findings contribution evidence thesis benchmark evaluation.",
            "The poster reports 18.4 accuracy gain, 3.1 f1 citation error, and 97 accuracy table preservation.",
        ]
        * 8
    )
    return f"""<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{LONG_REVIEW_TITLE}</title>
<style>
@page {{ size: A3 landscape; margin: 8mm; }}
:root {{ --ink:#111827; --paper:#ffffff; --line:#d1d5db; --blue:#1d4ed8; }}
body {{ margin:0; font-family:Arial, sans-serif; background:var(--paper); color:var(--ink); }}
.poster {{ aspect-ratio:4 / 3; display:grid; grid-template-columns:repeat(12,minmax(0,1fr)); gap:12px; }}
.poster-header {{ grid-column:1 / -1; }}
.poster-title.title-long.title-ko {{ overflow-wrap:anywhere; }}
.evidence-meta {{ display:flex; gap:12px; }}
.thesis-strip {{ grid-column:1 / -1; border-left:6px solid #059669; }}
.overview-section {{ grid-column:span 4; }}
.papers-section {{ grid-column:span 8; }}
.comparison-section {{ grid-column:span 8; }}
.findings-section {{ grid-column:span 4; }}
.conclusion-section {{ grid-column:1 / -1; }}
.paper-card {{ break-inside:avoid; border:1px solid var(--line); }}
figure {{ break-inside:avoid; margin:8px 0; }}
figcaption {{ font-size:.75rem; }}
table {{ width:100%; border-collapse:collapse; break-inside:avoid; }}
th, td {{ border:1px solid var(--line); padding:4px; }}
@media (max-width: 1199px) {{ .poster {{ grid-template-columns:repeat(8,minmax(0,1fr)); }} }}
@media (max-width: 760px) {{ .poster {{ grid-template-columns:1fr; aspect-ratio:auto; }} }}
@media print {{ * {{ -webkit-print-color-adjust:exact; print-color-adjust:exact; }} section,article,figure,table {{ break-inside:avoid; }} }}
</style>
</head>
<body>
<main class="poster">
<header class="poster-header">
<h1 class="poster-title title-ko title-en title-long">{LONG_REVIEW_TITLE}</h1>
<div class="evidence-meta"><span>3 papers</span><span>2 figures</span><span>1 table</span></div>
</header>
<aside class="thesis-strip">Thesis: verifier-guided graph evidence improves synthesis reliability.</aside>
<section class="overview-section panel panel--overview"><h2>Abstract</h2><p>{body_text}</p>
<figure><svg viewBox="0 0 10 10"><rect width="10" height="10"></rect></svg><figcaption>Evidence pipeline diagram.</figcaption></figure></section>
<section class="papers-section panel panel--paper-card"><article class="paper-card"><h3>GraphRAG</h3><p>Methodology and results with 18.4% improvement.</p></article></section>
<section class="comparison-section panel panel--comparison"><h2>Results</h2><table><thead><tr><th>Metric</th><th>Result</th></tr></thead><tbody><tr><td>Invalid citations</td><td>3.1%</td></tr></tbody></table></section>
<section class="findings-section panel panel--findings"><h2>Findings</h2><p>Contribution and benchmark evidence.</p></section>
<section class="conclusion-section panel panel--conclusion"><h2>Conclusion</h2><p>Conclusion links claims to evidence.</p></section>
</main>
</body>
</html>"""


def test_render_html_returns_self_contained_markup_after_sanitization() -> None:
    html = _render_html()
    html_lower = html.lower()

    assert "<script" not in html_lower
    assert "<link" not in html_lower
    assert "http://" not in html_lower
    assert "https://" not in html_lower
    assert "fonts.googleapis.com" not in html_lower
    assert "cdn.jsdelivr.net" not in html_lower
    assert "@import" not in html_lower


def test_render_html_includes_a3_landscape_print_contract() -> None:
    html = _render_html()
    compact = re.sub(r"\s+", " ", html.lower())

    assert "@page" in compact
    assert "a3" in compact
    assert "landscape" in compact
    assert "width: 396mm" in compact
    assert "height: 297mm" in compact
    assert "@media print" in compact
    assert "print-color-adjust: exact" in compact
    assert "break-inside: avoid" in compact


def test_render_html_includes_twelve_column_responsive_grid_contract() -> None:
    html = _render_html()
    compact = re.sub(r"\s+", "", html.lower())

    assert "aspect-ratio:4/3" in compact
    assert "grid-template-columns:repeat(12,minmax(0,1fr))" in compact
    assert ".paper-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr))" in compact
    assert "@media(max-width:1199px)" in compact
    assert "@media(max-width:760px)" in compact


def test_editorial_pattern_maps_to_nonempty_legacy_sections_on_twelve_column_grid() -> None:
    plan = PosterLayoutAgent().plan(_content_fixture())

    assert plan.layout_type is LayoutType.THREE_COLUMN
    assert plan.columns == 3
    assert plan.grid_template == "repeat(12, minmax(0, 1fr))"
    assert plan.sections


def test_legacy_assembly_keeps_limitations_and_safe_provenance() -> None:
    content = _content_fixture()
    agent = object.__new__(PosterGenerationAgent)
    agent.style_manager = None

    html = agent._assemble_poster(content, layout=None, section_htmls={})

    assert "Status synthesized" in html
    assert "3 source papers" in html
    assert "English-language benchmark questions" in html
    assert "Provenance &amp; References" in html
    assert "AI & Graph Learning Conference" not in html


def test_legacy_assembly_default_style_does_not_clip_screen_content() -> None:
    content = _content_fixture()
    agent = object.__new__(PosterGenerationAgent)
    agent.style_manager = StyleManager()
    agent.theme = "default"

    html = agent._assemble_poster(content, layout=None, section_htmls={})
    screen_poster_rule = re.search(
        r"\.poster-container\s*\{([^}]*)\}", html, re.DOTALL
    )

    assert screen_poster_rule is not None
    assert "overflow: hidden" not in screen_poster_rule.group(1)
    assert "@media (max-width: 1199px)" in html
    assert "@media (max-width: 760px)" in html


def test_visual_helpers_do_not_fabricate_placeholder_diagrams_or_metrics() -> None:
    visual = PosterVisualAgent()

    assert visual.generate_architecture_svg() == ""
    assert visual.generate_algorithm_svg() == ""
    assert visual.generate_bar_chart({}) == ""
    assert visual.generate_pipeline_diagram([]) == ""
    assert visual.generate_timeline([]) == ""


def test_render_html_marks_long_multilingual_title_with_title_classes() -> None:
    html = _render_html()

    assert LONG_REVIEW_TITLE in html
    assert re.search(r"<h1[^>]+class=\"[^\"]*poster-title", html)
    assert re.search(r"<h1[^>]+class=\"[^\"]*title-ko", html)
    assert re.search(r"<h1[^>]+class=\"[^\"]*title-long", html)


def test_render_html_exposes_real_evidence_meta_counts_and_thesis_strip() -> None:
    html = _render_html()
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).lower()

    assert 'class="evidence-meta"' in html
    assert 'class="thesis-strip"' in html
    assert "3 papers" in text or "3편" in text
    assert "4 figures" in text or "4개 figure" in text or "4 figures" in html.lower()
    assert "graph-grounded evidence plus verifier roles" in text
    assert "status synthesized" in text
    assert "3 source papers" in text
    assert re.search(r"generated \d{4}-\d{2}-\d{2}", text)


def test_render_html_keeps_limitations_visible_without_css_clipping() -> None:
    html = _render_html()

    assert "**한계**" not in html
    assert "<strong>한계</strong>" in html
    assert "English-language benchmark questions" in html
    assert "-webkit-line-clamp" not in html
    assert "overflow: hidden" not in re.search(
        r"\.paper-card p\s*\{([^}]*)\}", html, re.DOTALL
    ).group(1)


def test_render_html_uses_source_derived_metric_labels_and_target_values() -> None:
    html = _render_html()
    compact = re.sub(r"\s+", " ", html).lower()

    assert "answer attribution" in compact
    assert "invalid citations" in compact
    assert "table cells preserved" in compact
    assert ">18.4 points</strong>" in compact
    assert ">3.1%</strong>" in compact
    assert ">97%</strong>" in compact
    assert "<span>key result</span>" not in compact


def test_render_html_preserves_comparison_table_from_fixture() -> None:
    html = _render_html()

    assert "<table" in html
    assert "<th>Paper</th>" in html
    assert "<td>GraphRAG</td>" in html
    assert "<td>+18.4 points</td>" in html
    assert "<td>97%</td>" in html


def test_render_html_wraps_every_visual_in_semantic_figure_with_caption() -> None:
    html = _render_html()
    visual_count = len(re.findall(r"<(?:svg|img)\b", html, re.IGNORECASE))
    figure_count = len(re.findall(r"<figure\b", html, re.IGNORECASE))
    figcaption_count = len(re.findall(r"<figcaption\b", html, re.IGNORECASE))

    assert visual_count >= 2
    assert figure_count >= visual_count
    assert figcaption_count >= visual_count


def test_render_html_uses_role_based_panel_classes() -> None:
    html = _render_html()

    assert re.search(r'class="[^"]*\boverview-section\b', html)
    assert re.search(r'class="[^"]*\bpapers-section\b', html)
    assert re.search(r'class="[^"]*\bcomparison-section\b', html)
    assert re.search(r'class="[^"]*\bfindings-section\b', html)
    assert re.search(r'class="[^"]*\bconclusion-section\b', html)


def test_rendered_template_does_not_use_generic_paper_placeholders() -> None:
    html = _render_html()
    result = PosterCriticAgent().critique(html)

    assert "Paper 1" not in html
    assert not any(
        "Generic template placeholders remain" in issue
        for issue in result.structural_issues
    )


def test_missing_paper_title_uses_honest_evidence_source_label() -> None:
    content = _content_fixture()
    content.paper_analyses[0]["title"] = ""
    agent = PosterCompositionAgent()
    composition = agent.design(content, autofigure_svgs=[], figures=[])
    html = agent.render_html(composition, content=content)

    assert "Untitled evidence source" in html
    assert "Paper 1" not in html


def test_critic_accepts_polished_self_contained_canonical_html() -> None:
    result = PosterCriticAgent().critique(_canonical_polished_html())

    assert result.structural_issues == []
    assert result.suggestions == "No changes needed."
    assert result.metrics["self_contained"] == 1.0


def test_critic_flags_external_cdn_dependencies() -> None:
    html = _canonical_polished_html().replace(
        "</head>",
        '<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/example.css"></head>',
    )

    result = PosterCriticAgent().critique(html)

    assert any("External font/CDN/asset dependencies" in issue for issue in result.structural_issues)


def test_critic_flags_generic_metric_placeholders() -> None:
    html = _canonical_polished_html().replace(
        "18.4 accuracy gain",
        "Metric A attribution gains",
    )

    result = PosterCriticAgent().critique(html)

    assert any("Generic template placeholders remain" in issue for issue in result.structural_issues)


def test_critic_flags_missing_print_css_contract() -> None:
    html = re.sub(r"@page\s*\{[^}]*\}", "", _canonical_polished_html())
    html = re.sub(r"@media print\s*\{[^}]*\}", "", html)

    result = PosterCriticAgent().critique(html)

    assert any("Missing @page" in issue for issue in result.structural_issues)
    assert any("Missing @media print" in issue for issue in result.structural_issues)
