import math
import os
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import networkx as nx
import plotly.graph_objects as go
import streamlit as st
from dotenv import load_dotenv

# Ensure project modules are importable (mirrors main.py path setup)
PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT / "src"))
sys.path.append(str(PROJECT_ROOT / "app" / "SearchAgent"))

from search_agent import SearchAgent  # pylint: disable=wrong-import-position

load_dotenv()


def init_agent() -> SearchAgent:
    """Create or reuse a SearchAgent stored in Streamlit session state."""
    if "search_agent" not in st.session_state:
        st.session_state.search_agent = SearchAgent(
            openai_api_key=os.getenv("OPENAI_API_KEY")
        )
    return st.session_state.search_agent


def render_sidebar(agent: SearchAgent) -> Dict[str, Any]:
    """Render sidebar controls and return the configured search filters."""
    st.sidebar.title("검색 설정")
    st.sidebar.caption("소스를 선택하고 검색 옵션을 조정하세요.")

    query = st.sidebar.text_input("검색 키워드", help="쉼표로 구분해 여러 키워드를 입력할 수 있습니다.")
    max_results = st.sidebar.slider("소스당 최대 결과 수", min_value=5, max_value=100, value=20, step=5)

    st.sidebar.subheader("검색 소스")
    sources = {
        "arxiv": st.sidebar.checkbox("arXiv", value=True),
        "connected_papers": st.sidebar.checkbox("Connected Papers", value=True),
        "google_scholar": st.sidebar.checkbox("Google Scholar", value=True),
    }

    st.sidebar.subheader("고급 필터")
    sort_by = st.sidebar.selectbox("정렬 기준", ["relevance", "date"])
    year_start, year_end = st.sidebar.slider(
        "연도 범위",
        min_value=1990,
        max_value=2025,
        value=(2015, 2025),
        help="Google Scholar 검색에만 적용됩니다.",
    )
    author = st.sidebar.text_input("저자 필터 (Google Scholar)")
    arxiv_category = st.sidebar.text_input("arXiv 카테고리 (예: cs.LG)")

    st.sidebar.markdown("---")
    with st.sidebar.expander("저장 데이터"):
        st.metric("저장된 논문 수", agent.get_saved_papers_count())
        if st.button("저장 데이터 초기화", type="secondary"):
            if agent.clear_saved_papers():
                st.success("저장된 논문을 초기화했습니다.")
            else:
                st.error("저장 데이터 초기화에 실패했습니다.")

    filters = {
        "query": query,
        "max_results": max_results,
        "sources": [src for src, enabled in sources.items() if enabled],
        "sort_by": sort_by,
        "year_start": year_start,
        "year_end": year_end,
        "author": author.strip() or None,
        "category": arxiv_category.strip() or None,
    }
    return filters


def format_paper_summary(paper: Dict[str, Any]) -> str:
    """Return a concise summary string for a paper."""
    authors = ", ".join(paper.get("authors", [])[:4])
    year = paper.get("year") or paper.get("published")
    journal = paper.get("journal") or paper.get("publication", "")
    summary_parts = [part for part in [authors, journal, year] if part]
    return " · ".join(summary_parts)


def inject_connected_theme():
    """Inject custom CSS to emulate a tri-pane research graph UI."""
    st.markdown(
        """
        <style>
            @import url('https://fonts.googleapis.com/css2?family=Roboto:wght@300;400;500;700&display=swap');
            html, body, [class*="css"]  {
                font-family: 'Roboto', sans-serif;
                background: #f3f4f7;
            }
            .connected-wrapper {
                background: #ffffff;
                border-radius: 16px;
                padding: 20px 24px;
                box-shadow: 0 20px 45px rgba(15, 23, 42, 0.08);
            }
            .pane-title {
                text-transform: uppercase;
                font-size: 0.85rem;
                letter-spacing: 0.08em;
                color: #7d889f;
                margin-bottom: 8px;
                font-weight: 500;
            }
            .paper-card .stButton>button {
                width: 100%;
                background: transparent;
                border: none;
                text-align: left;
                padding: 12px 14px;
                border-radius: 10px;
                color: #0f172a;
                box-shadow: inset 0 0 0 1px rgba(148, 163, 184, 0.4);
            }
            .paper-card .stButton>button:hover {
                box-shadow: inset 0 0 0 2px #4f46e5;
                background: rgba(79, 70, 229, 0.05);
            }
            .paper-card.selected .stButton>button {
                box-shadow: inset 0 0 0 2px #7c3aed;
                background: rgba(124, 58, 237, 0.08);
            }
            .origin-pill {
                background: linear-gradient(135deg, #8b5cf6, #ec4899);
                color: white;
                font-weight: 600;
                border-radius: 999px;
                padding: 4px 12px;
                font-size: 0.75rem;
                display: inline-block;
                margin-bottom: 6px;
            }
            .paper-meta {
                font-size: 0.82rem;
                color: #6b7280;
            }
            .detail-card {
                background: #ffffff;
                border-radius: 18px;
                padding: 24px;
                border: 1px solid rgba(15, 23, 42, 0.06);
                box-shadow: 0 15px 40px rgba(15, 23, 42, 0.08);
            }
            .detail-card h2 {
                font-size: 1.2rem;
                margin-bottom: 6px;
                color: #111;
            }
            .detail-card .detail-meta {
                font-size: 0.9rem;
                color: #6b7280;
                margin-bottom: 14px;
            }
            .detail-actions .stButton>button {
                width: 100%;
                margin-top: 8px;
                background: #f4f4ff;
                border: none;
                color: #4c1d95;
            }
            .detail-actions .stButton>button:hover {
                background: #ddd6fe;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def flatten_results(results: Dict[str, List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
    """Merge multi-source results into a single ordered list."""
    flattened: List[Dict[str, Any]] = []

    for source, papers in results.items():
        for idx, paper in enumerate(papers):
            title = paper.get("title") or f"{source}-{idx}"
            doc_id = f"{source}-{idx}-{abs(hash(title))}"
            flattened.append(
                {
                    **paper,
                    "title": title,
                    "doc_id": doc_id,
                    "source": source,
                    "citations": paper.get("citations", 0) or 0,
                    "year": paper.get("year")
                    or paper.get("published")
                    or paper.get("publication_year"),
                }
            )

    flattened.sort(key=lambda item: item.get("citations", 0), reverse=True)
    return flattened


TITLE_TOKENIZER = re.compile(r"[A-Za-z0-9]+" )


def _title_tokens(paper: Dict[str, Any]) -> List[str]:
    title = paper.get("title", "")
    return [token for token in TITLE_TOKENIZER.findall(title.lower()) if len(token) > 2]


def build_similarity_graph(papers: List[Dict[str, Any]]) -> nx.Graph:
    graph = nx.Graph()
    if not papers:
        return graph

    token_cache = {paper["doc_id"]: set(_title_tokens(paper)) for paper in papers}
    for paper in papers:
        graph.add_node(
            paper["doc_id"],
            weight=max(paper.get("citations", 1), 1),
            year=paper.get("year"),
            title=paper["title"],
        )

    for idx, paper in enumerate(papers):
        for jdx in range(idx + 1, len(papers)):
            other = papers[jdx]
            base_tokens = token_cache[paper["doc_id"]]
            other_tokens = token_cache[other["doc_id"]]
            if not base_tokens or not other_tokens:
                continue

            overlap = len(base_tokens & other_tokens)
            union = len(base_tokens | other_tokens)
            score = overlap / union if union else 0

            if score >= 0.12:
                graph.add_edge(
                    paper["doc_id"],
                    other["doc_id"],
                    weight=round(score, 3),
                )

    # Ensure graph stays connected by linking sequential items if isolated
    nodes = list(graph.nodes())
    for idx in range(len(nodes) - 1):
        if not graph.has_edge(nodes[idx], nodes[idx + 1]):
            graph.add_edge(nodes[idx], nodes[idx + 1], weight=0.05)

    return graph


def build_graph_figure(
    papers: List[Dict[str, Any]], selected_id: str
) -> Optional[go.Figure]:
    if not papers:
        return None

    graph = build_similarity_graph(papers)
    if not graph.nodes:
        return None

    layout = nx.spring_layout(graph, seed=42, k=0.55)

    edge_x: List[float] = []
    edge_y: List[float] = []
    for start, end in graph.edges():
        x0, y0 = layout[start]
        x1, y1 = layout[end]
        edge_x.extend([x0, x1, None])
        edge_y.extend([y0, y1, None])

    edge_trace = go.Scatter(
        x=edge_x,
        y=edge_y,
        line=dict(width=1, color="rgba(148, 163, 184, 0.35)"),
        hoverinfo="none",
        mode="lines",
    )

    years = [graph.nodes[node].get("year") for node in graph.nodes()]
    min_year = min((year for year in years if year), default=2011)
    max_year = max((year for year in years if year), default=2024)
    range_year = max(max_year - min_year, 1)

    node_x: List[float] = []
    node_y: List[float] = []
    node_color: List[str] = []
    node_size: List[float] = []
    node_text: List[str] = []
    node_outline: List[str] = []

    for node_id in graph.nodes():
        x, y = layout[node_id]
        node_x.append(x)
        node_y.append(y)
        year = graph.nodes[node_id].get("year") or min_year
        relative = (year - min_year) / range_year
        base_green = int(150 + relative * 70)
        color = f"rgba(60, {base_green}, 150, 0.95)"
        if node_id == selected_id:
            color = "rgba(157, 23, 77, 1)"
        node_color.append(color)

        weight = graph.nodes[node_id].get("weight", 1)
        size = 14 + 6 * math.log10(weight + 1)
        node_outline.append("#ffffff" if node_id != selected_id else "#fdf2f8")
        node_size.append(size)
        node_text.append(graph.nodes[node_id].get("title", ""))

    node_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode="markers",
        hoverinfo="text",
        marker=dict(
            showscale=False,
            color=node_color,
            size=node_size,
            line=dict(width=3, color=node_outline),
        ),
        hovertemplate="%{text}<extra></extra>",
        text=node_text,
    )

    label_trace = go.Scatter(
        x=node_x,
        y=node_y,
        mode="text",
        text=node_text,
        textposition="top center",
        textfont=dict(size=12, color="rgba(55, 65, 81, 0.92)"),
        hoverinfo="none",
    )

    figure = go.Figure(data=[edge_trace, node_trace, label_trace])
    figure.update_layout(
        showlegend=False,
        hovermode="closest",
        margin=dict(l=0, r=0, t=30, b=10),
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        template="plotly_white",
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        height=640,
    )
    return figure


def render_paper_card(paper: Dict[str, Any], is_selected: bool, is_origin=False):
    meta = format_paper_summary(paper)
    classes = "paper-card"
    if is_selected:
        classes += " selected"

    with st.container():
        if is_origin:
            st.markdown('<div class="origin-pill">Origin Paper</div>', unsafe_allow_html=True)
        with st.container():
            st.markdown(
                f'<div class="{classes}">',
                unsafe_allow_html=True,
            )
            if st.button(
                f"{paper['title']}\n{meta}",
                key=f"select-{paper['doc_id']}",
                use_container_width=True,
            ):
                st.session_state["selected_paper_id"] = paper["doc_id"]
            st.markdown("</div>", unsafe_allow_html=True)


def render_detail_panel(paper: Dict[str, Any]):
    if not paper:
        st.info("논문이 선택되지 않았습니다.")
        return

    authors = ", ".join(paper.get("authors", [])[:5]) or "Unknown authors"
    st.markdown('<div class="detail-card">', unsafe_allow_html=True)
    st.markdown(f"<h2>{paper.get('title')}</h2>", unsafe_allow_html=True)
    st.markdown(
        f'<div class="detail-meta">{authors} · {paper.get("year", "N/A")} · {paper.get("source", "").title()}</div>',
        unsafe_allow_html=True,
    )
    st.write(paper.get("abstract") or "초록 정보가 없습니다.")

    st.markdown("---")
    st.metric(label="Citations", value=paper.get("citations", 0))

    with st.container():
        col1, col2, col3 = st.columns(3)
        if paper.get("url") or paper.get("paper_url"):
            col1.link_button("원문 열기", paper.get("url") or paper.get("paper_url"))
        if paper.get("pdf_url"):
            col2.link_button("PDF", paper["pdf_url"])
        if paper.get("doi"):
            doi_url = f"https://doi.org/{paper['doi']}"
            col3.link_button("DOI", doi_url)

    st.markdown("</div>", unsafe_allow_html=True)


def render_connected_interface(
    results: Dict[str, List[Dict[str, Any]]],
    query: str,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    if not results:
        st.info("검색 결과가 없습니다. 키워드를 입력한 뒤 검색을 실행하세요.")
        return [], None

    inject_connected_theme()
    papers = flatten_results(results)
    if not papers:
        st.warning("표시할 논문이 없습니다.")
        return [], None

    selected_id = st.session_state.get("selected_paper_id", papers[0]["doc_id"])
    if selected_id not in {paper["doc_id"] for paper in papers}:
        selected_id = papers[0]["doc_id"]
        st.session_state["selected_paper_id"] = selected_id

    selected_paper = next(
        (paper for paper in papers if paper["doc_id"] == selected_id), papers[0]
    )

    st.markdown(
        f"""
        <div class="connected-wrapper">
            <div style="display:flex; justify-content:space-between; align-items:center;">
                <div>
                    <h2 style="margin-bottom:2px;">{query or "Paper graph"}</h2>
                    <p style="color:#6b7280; margin:0;">시각 그래프를 통해 연관 논문을 탐색해보세요.</p>
                </div>
                <div style="font-size:0.9rem; color:#6366f1;">총 {len(papers)}편</div>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_left, col_center, col_right = st.columns([1.6, 2.6, 1.6], gap="medium")

    with col_left:
        st.markdown('<div class="pane-title">Prior & Related Works</div>', unsafe_allow_html=True)
        render_paper_card(papers[0], is_selected=papers[0]["doc_id"] == selected_id, is_origin=True)
        for paper in papers[1:]:
            render_paper_card(paper, is_selected=paper["doc_id"] == selected_id)

    with col_center:
        st.markdown('<div class="pane-title">Graph view</div>', unsafe_allow_html=True)
        figure = build_graph_figure(papers, selected_id)
        if figure:
            st.plotly_chart(figure, use_container_width=True)
        else:
            st.info("그래프를 생성할 수 없습니다. 검색 결과를 다시 확인해주세요.")

    with col_right:
        st.markdown('<div class="pane-title">Details</div>', unsafe_allow_html=True)
        render_detail_panel(selected_paper)

    return papers, selected_paper


def main():
    st.set_page_config(page_title="Paper Review Agent", layout="wide")
    st.title("📚 Paper Graph Explorer")
    st.caption("Connected Papers 스타일의 인터랙티브 논문 그래프")

    agent = init_agent()
    filters = render_sidebar(agent)

    st.markdown("### 🔍 검색")
    st.write("키워드를 입력하고 아래 버튼을 눌러 검색을 실행하세요.")

    search_triggered = st.button("검색 실행", type="primary", use_container_width=True)

    if search_triggered:
        if not filters["query"]:
            st.warning("검색 키워드를 입력해 주세요.")
            return

        with st.spinner("검색 중입니다..."):
            results = agent.search_with_filters(
                filters["query"],
                {k: v for k, v in filters.items() if k != "query"},
            )
            st.session_state["latest_results"] = results
    results = st.session_state.get("latest_results", {})

    papers, selected_paper = render_connected_interface(results, filters["query"])

    if results and papers:
        st.markdown("---")
        st.subheader("📥 결과 저장")
        save_col, export_col = st.columns(2)

        if save_col.button("플랫폼 DB에 저장", use_container_width=True):
            save_info = agent.save_papers(results, filters["query"])
            if save_info.get("success"):
                st.success(
                    f"새로 저장: {save_info['new_papers']}개 / 중복: {save_info['duplicates']}개"
                )
            else:
                st.error(f"저장 실패: {save_info.get('error')}")

        if export_col.button("JSON으로 내보내기", use_container_width=True):
            filename = agent.export_results(results)
            if filename:
                with open(filename, "rb") as file_obj:
                    st.download_button(
                        label="다운로드 시작",
                        data=file_obj,
                        file_name=filename,
                        mime="application/json",
                    )
            else:
                st.error("JSON 내보내기에 실패했습니다.")

    st.markdown("---")
    st.subheader("🕓 검색 기록")
    history = agent.get_search_history()
    if history:
        st.table(history[::-1])
    else:
        st.info("검색 기록이 없습니다.")


if __name__ == "__main__":
    main()

