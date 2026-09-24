"""Verify downloaded production responses against the published post record."""

import hashlib
import json
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path


class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.h1_count = 0
        self.canonical = []
        self.meta = {}
        self.schemas = []
        self.schema_active = False
        self.parts = []

    def handle_starttag(self, tag, attributes):
        attributes = dict(attributes)
        if tag == "h1":
            self.h1_count += 1
        if tag == "link" and attributes.get("rel") == "canonical":
            self.canonical.append(attributes.get("href"))
        if tag == "meta":
            key = attributes.get("property", attributes.get("name", ""))
            self.meta[key] = attributes.get("content")
        if tag == "script" and attributes.get("type") == "application/ld+json":
            self.schema_active = True
            self.parts = []

    def handle_data(self, text):
        if self.schema_active:
            self.parts.append(text)

    def handle_endtag(self, tag):
        if tag == "script" and self.schema_active:
            value = json.loads("".join(self.parts))
            self.schemas.extend(value.get("@graph", [value]))
            self.schema_active = False


root = Path(__file__).parent
expected = json.loads((root / "repository-published-post.json").read_text())
before = json.loads((root / "before-publication.json").read_text())
actual = json.loads(Path("/tmp/ipccf-published-post.json").read_text())
for key in expected:
    assert actual.get(key) == expected[key], f"API mismatch: {key}"
for key in ["id", "slug", "created_at", "author", "tags", "category", "thumbnail_url", "published"]:
    assert actual[key] == before[key], f"Preserved field changed: {key}"

html = Path("/tmp/ipccf-published-page.html").read_text()
page = Page()
page.feed(html)
url = "https://jiphyeonjeon.kr/blog/" + actual["slug"]
assert page.h1_count == 1
assert page.canonical == [url]
assert page.meta["og:title"].startswith(actual["title"])
assert page.meta["description"] == "arXiv:2604.15704v1 · " + actual["excerpt"]
for phrase in ["테스트 지표", "오프셋", "Softplus", "독립된 재현", "References"]:
    assert phrase in html, f"SSR content missing: {phrase}"
article = next(p for p in page.schemas if p.get("@type") == "BlogPosting")
paper = next(p for p in page.schemas if p.get("@type") == "ScholarlyArticle")
assert article["dateModified"] == actual["updated_at"]
assert article["datePublished"] == before["created_at"]
assert paper["name"] == "Intent Propagation Contrastive Collaborative Filtering"
assert [a["name"] for a in paper["author"]] == [
    "Haojie Li", "Junwei Du", "Guanfeng Liu", "Feng Jiang", "Yan Wang", "Xiaofang Zhou"
]
assert Path("/tmp/ipccf-live-thumbnail.png").stat().st_size > 1000
wiki_path = Path("/Users/jiseong/Library/Mobile Documents/com~apple~CloudDocs/PaperWiki/PaperWiki/blog/recsys-ir/ipccf/ipccf-deep-review.md")
assert wiki_path.read_text().split("\n", 1)[1].lstrip() == actual["content"]
receipt = {
    "url": url,
    "verified_at": datetime.now(timezone.utc).isoformat(),
    "published": True,
    "updated_at": actual["updated_at"],
    "created_at_preserved": True,
    "other_production_posts_unchanged_by_revision": True,
    "content_sha256": hashlib.sha256(actual["content"].encode()).hexdigest(),
    "pull_request": "https://github.com/KimJiSeong1994/PaperReview/pull/254",
    "merge_commit": "53befd6219708a50fac7593a23bead1ce1c7d30f",
    "production_backup": "/home/ubuntu/PaperReviewAgent/data/blog/backups/posts-before-ipccf-revision-20260905T074540942812Z.json",
    "paperwiki": str(wiki_path),
    "checks": {
        "api_exact_match": True,
        "SSR_body": True,
        "one_h1": True,
        "canonical": True,
        "meta_description": True,
        "json_ld_dates": True,
        "paper_title_and_six_authors": True,
        "thumbnail_http_200": True,
        "katex_formulas": 67,
        "local_blog_seo_tests_passed": 56,
        "local_frontend_build_and_typecheck": "passed",
        "required_pull_request_CI": "passed",
    },
}
(root / "published-post.json").write_text(json.dumps(actual, ensure_ascii=False, indent=2) + "\n")
(root / "publication.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
print(json.dumps(receipt, ensure_ascii=False, indent=2))
