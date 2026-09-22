"""
Bibliography consistency across published blog posts (``data/blog/posts.json``).

A review's reference list is a factual claim about who wrote the cited work, and
a wrong one is invisible: it renders, it reads correctly, and no build step
looks at it. Two defects have reached production this way.

* A truncated author list closed with ``& Surname`` instead of ``et al.``,
  so ten names were presented as the whole list. Counting authors cannot catch
  this on its own -- the corpus has 32 genuine ten-author entries -- but the
  same work cited in another post with a longer list can.
* The same work listed twice in one post as the same kind of record. A preprint
  paired with its version of record is deliberate -- these reviews cite the
  published record and list the arXiv copy they actually read -- so a pair counts
  only when both entries are preprints, or neither is.

Both are checked here against the corpus itself rather than against an external
source, so the checks stay mechanical and need no network.

There is no allowlist: every conflict the corpus had was a real truncation and
was corrected against the arXiv record. A new entry here means a new defect.
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


def _title_key(title: str) -> str:
    # APA puts the venue after the title as ". In <Proceedings...>". Same work,
    # one entry naming the venue and one not, must still key alike.
    title = re.split(r"\.\s+In\s", title)[0]
    return re.sub(r"[^a-z0-9]", "", title.lower())[:55]


def _references() -> list[tuple[str, str, bool, int, str]]:
    """(slug, title_key, is_preprint, author_count, author_text) per reference."""
    posts = json.loads(POSTS_FILE.read_text(encoding="utf-8"))["posts"]
    out = []
    for post in posts:
        if not post.get("published"):
            continue
        # Easy and detailed views are separate bibliographies of one review.
        # Check duplicates within each view and author consistency across both.
        bodies = [(post["slug"], post["content"])]
        if post.get("deep_content"):
            bodies.append((post["slug"] + "?view=deep", post["deep_content"]))
        for view_slug, body in bodies:
            for line in body.split("\n"):
                match = REFERENCE.match(line.strip())
                if not match:
                    continue
                authors = " ".join(match.group(1).split())
                count = len(AUTHOR.findall(authors))
                if count:
                    out.append(
                        (
                            view_slug,
                            _title_key(match.group(3)),
                            "arxiv:" in line.lower(),
                            count,
                            authors,
                        )
                    )
    return out


def test_the_parser_still_finds_the_bibliographies() -> None:
    """A regex that silently stops matching would make every check below vacuous."""
    refs = _references()
    assert len(refs) > 400, f"only {len(refs)} references parsed - has the format changed?"
    assert len({slug for slug, _, _, _, _ in refs}) > 50


def test_one_work_is_not_listed_twice_as_the_same_kind_of_record() -> None:
    """A preprint listed alongside its version of record is deliberate, not a repeat."""
    seen: dict[tuple[str, str, bool], int] = defaultdict(int)
    for slug, key, is_preprint, _, _ in _references():
        seen[(slug, key, is_preprint)] += 1
    duplicates = {
        (slug, key, "preprint" if is_preprint else "published")
        for (slug, key, is_preprint), n in seen.items()
        if n > 1
    }
    assert not duplicates, (
        f"one post lists the same work twice as the same kind of record: {sorted(duplicates)}"
    )


def test_a_work_cited_in_several_posts_keeps_one_author_list() -> None:
    by_work: dict[str, set[tuple[str, int]]] = defaultdict(set)
    for slug, key, _, count, authors in _references():
        if any(mark in authors for mark in ABBREVIATED):
            continue  # says it is abbreviated; a shorter list is expected
        by_work[key].add((slug, count))

    conflicts = {
        key: sorted(entries)
        for key, entries in by_work.items()
        if len({count for _, count in entries}) > 1
    }
    assert not conflicts, (
        "the same work carries different author counts across posts, and neither "
        f"side is marked abbreviated - one list is truncated: {conflicts}"
    )
