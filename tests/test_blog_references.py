"""
Bibliography consistency across published blog posts (``data/blog/posts.json``).

A review's reference list is a factual claim about who wrote the cited work, and
a wrong one is invisible: it renders, it reads correctly, and no build step
looks at it. Two defects have reached production this way.

* A truncated author list closed with ``& Surname`` instead of ``et al.``,
  so ten names were presented as the whole list. Counting authors cannot catch
  this on its own -- the corpus has 32 genuine ten-author entries -- but the
  same work cited in another post with a longer list can.
* The same work listed twice in one post, once as an arXiv preprint and once as
  the published version, presented as two separate references.

Both are checked here against the corpus itself rather than against an external
source, so the checks stay mechanical and need no network.

``KNOWN_CONFLICTS`` and ``KNOWN_DUPLICATES`` are the defects that already exist.
They are frozen so new drift fails while the backlog stays visible -- entries
should be removed as the underlying bibliographies are corrected, not added to.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import Path

POSTS_FILE = Path(__file__).resolve().parents[1] / "data" / "blog" / "posts.json"

# "Surname, A. B., ... (2026). Title" -- the APA shape every post's list uses.
REFERENCE = re.compile(
    r"^([A-ZÀ-Ý][^()]{10,400}?)\s*\(((?:19|20)\d\d)[a-z]?\)\.\s*\*?([^*(\[]{6,200})"
)
AUTHOR = re.compile(r"[A-ZÀ-Ý][\w'’\-]+,\s*(?:[A-ZÀ-Ý]\.\s*)+(?:[A-ZÀ-Ý]\.)?")

# An author list that says it is incomplete is not evidence of a conflict:
# APA's ellipsis form and "et al." are both deliberate abbreviations.
ABBREVIATED = ("et al.", "…", ". . .", "...")

# Same work, different author counts, neither side abbreviated -- one is wrong.
KNOWN_CONFLICTS = {
    "fromlocaltoglobalagraphragapproachtoqueryfocusedsummari",  # Edge et al., 8 vs 10
    "ragvsgraphragasystematicevaluationandkeyinsights",  # Han et al., 9 vs 12
    "reflexionlanguageagentswithverbalreinforcementlearning",  # Shinn et al., 5 vs 6
    "searchr1trainingllmstoreasonandleveragesearchengineswit",  # Jin et al., 6 vs 8
}

# One work, two entries in the same post (preprint and published version).
KNOWN_DUPLICATES = {
    ("hipporag-neurobiologically-inspired-long-term-memory", "hipporagneurobiologicallyinspiredlongtermmemoryforlarge"),
    ("intent-propagation-contrastive-collaborative-filtering", "intentpropagationcontrastivecollaborativefiltering"),
    ("rag-vs-graphrag-systematic-evaluation", "ragvsgraphragasystematicevaluationandkeyinsights"),
}


def _title_key(title: str) -> str:
    # APA puts the venue after the title as ". In <Proceedings...>". Same work,
    # one entry naming the venue and one not, must still key alike.
    title = re.split(r"\.\s+In\s", title)[0]
    return re.sub(r"[^a-z0-9]", "", title.lower())[:55]


def _references() -> list[tuple[str, str, int, str]]:
    """(slug, title_key, author_count, author_text) for every parsed reference."""
    posts = json.loads(POSTS_FILE.read_text(encoding="utf-8"))["posts"]
    out = []
    for post in posts:
        if not post.get("published"):
            continue
        for line in post["content"].split("\n"):
            match = REFERENCE.match(line.strip())
            if not match:
                continue
            authors = " ".join(match.group(1).split())
            count = len(AUTHOR.findall(authors))
            if count:
                out.append((post["slug"], _title_key(match.group(3)), count, authors))
    return out


def test_the_parser_still_finds_the_bibliographies() -> None:
    """A regex that silently stops matching would make every check below vacuous."""
    refs = _references()
    assert len(refs) > 400, f"only {len(refs)} references parsed - has the format changed?"
    assert len({slug for slug, _, _, _ in refs}) > 50


def test_one_work_is_not_listed_twice_in_the_same_post() -> None:
    seen: dict[tuple[str, str], int] = defaultdict(int)
    for slug, key, _, _ in _references():
        seen[(slug, key)] += 1
    duplicates = {pair for pair, n in seen.items() if n > 1} - KNOWN_DUPLICATES
    assert not duplicates, (
        "the same work is listed more than once in one post "
        f"(preprint and published version are one reference): {sorted(duplicates)}"
    )


def test_a_work_cited_in_several_posts_keeps_one_author_list() -> None:
    by_work: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for slug, key, count, authors in _references():
        if any(mark in authors for mark in ABBREVIATED):
            continue  # says it is abbreviated; a shorter list is expected
        by_work[key].add((slug, count))

    conflicts = {
        key: sorted(entries)
        for key, entries in by_work.items()
        if len({count for _, count in entries}) > 1 and key not in KNOWN_CONFLICTS
    }
    assert not conflicts, (
        "the same work carries different author counts across posts, and neither "
        f"side is marked abbreviated - one list is truncated: {conflicts}"
    )
