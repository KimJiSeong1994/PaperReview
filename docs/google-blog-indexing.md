# Google blog indexing: readiness is not inclusion

## What the deployment verifies

The public article document must return HTTP 200, a full selected easy/deep body,
its intended canonical, and one managed `seo-json-ld` block. The inert
`blog-bootstrap` JSON contains public `PostDetail` fields only and both reading
bodies. React initializes from that same post and revalidates with an 8-second
per-attempt limit and at most one transient retry. Network errors preserve the
readable post; definitive 404/410 clears the post, bootstrap, and old article
structured data.

A healthy HTTP response, sitemap entry, live URL test, or IndexNow HTTP 200/202
is **not** evidence that Google indexed the URL. IndexNow receipts are update
notifications for its participating engines. No Google status is inferred from
them. The current separate-deep-indexing policy remains opt-in; ordinary deep
views point to their base canonical, and EvoOntology is the current exception.

## Reproducible read-only checks

Run from a machine with public network access:

```sh
curl --fail --silent --show-error --head https://jiphyeonjeon.kr/blog/evo-ontology
curl --fail --silent --show-error https://jiphyeonjeon.kr/robots.txt
```

Inspect the actual bootstrap and canonical without changing server state:

```sh
python3 - <<'PY'
import json
from html.parser import HTMLParser
from urllib.request import urlopen

class Inspector(HTMLParser):
    canonical = None
    active = False
    raw = ''
    count = 0
    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonical = attrs.get('href')
        if tag == 'script' and attrs.get('id') == 'blog-bootstrap':
            self.active = True
            self.count += 1
    def handle_data(self, value):
        if self.active:
            self.raw += value
    def handle_endtag(self, tag):
        if tag == 'script':
            self.active = False

for suffix in ('', '?view=deep'):
    url = 'https://jiphyeonjeon.kr/blog/evo-ontology' + suffix
    with urlopen(url, timeout=15) as response:
        parser = Inspector()
        parser.feed(response.read().decode())
        payload = json.loads(parser.raw)
        assert parser.count == 1 and payload['version'] == 1
        assert payload['route']['slug'] == payload['post']['slug'] == 'evo-ontology'
        assert payload['post']['published'] is True
        print({'url': url, 'status': response.status, 'canonical': parser.canonical,
               'easy_chars': len(payload['post']['content']),
               'deep_chars': len(payload['post']['deep_content'] or '')})
PY
```

On the deployed host, readiness also checks the revision loaded by the running
process and its process ID against the expected Git SHA and systemd MainPID.
These values are captured by the application process; the health endpoint does
not reread the mutable checkout on every request. The service remains a single
Uvicorn worker. See [release operations](frontend-release-operations.md).

## Search Console evidence to record

Use **URL Inspection's Google indexed-data view**, separately from “Test live
URL”. For each intended canonical record:

| Field | What it establishes |
| --- | --- |
| Page indexing status and exclusion reason | Indexed, discovered but not crawled, crawled but not indexed, duplicate, redirect, or technical exclusion |
| Last crawl and fetch result | What Google fetched and when; compare against actual deployment completion, not just edited file timestamps |
| User-declared and Google-selected canonical | Whether Google follows the intended base/deep policy or selected another representative |
| Crawled/rendered HTML and resource failures | Whether the unique article text survived rendering or became a loading/error page |
| Actual query and impressions | Distinguishes index absence from ranking/serving for a particular search |

For a normal `?view=deep` alternate, Google selecting the base URL can be expected.
For a self-canonical EvoOntology deep URL, compare both views' indexed data;
self-canonical and sitemap inclusion are signals, not a guarantee of separation.
If Search Console data is unavailable, label Google indexing **unknown**.
Do not label a page “indexed” merely because a public technical probe passed.

## Intentional operational limits

- Public post responses are `Cache-Control: no-store` so a retraction does not
  depend on a shared HTML cache expiry. Static content-hashed assets remain
  cacheable and are retained across promotion and rollback.
- Both Markdown bodies are duplicated into the bootstrap to keep reading
  switches usable during API failures. Measure compressed payload growth for
  large posts. The current 89-article / 178-view audit measured a maximum
  bootstrap of 32,084 gzip bytes and a full document of 91,419 gzip bytes; the review budget is 128 KiB gzip for the bootstrap and 512 KiB
  gzip for a complete article document. Revisit unusually large articles rather
  than silently adding a long-lived HTML cache.
- Optional cross-encoder warmup runs on a supervised daemon thread after
  required startup. Its model loader already serializes concurrent lazy loads.
  Python cannot force-cancel that thread; process exit may stop optional loading,
  while required analytics and search-worker drains still run on shutdown.
  The first search can still wait for a cold ranking model.
- A managed single-worker restart still has a brief interruption. This change
  does not claim zero downtime or duplicate background work through extra workers.

## Official references

- [Google URL Inspection](https://support.google.com/webmasters/answer/9012289)
- [Page indexing report](https://support.google.com/webmasters/answer/7440203)
- [Google canonical troubleshooting](https://developers.google.com/search/docs/crawling-indexing/canonicalization-troubleshooting)
- [Google JavaScript SEO](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics)
- [IndexNow participation](https://www.indexnow.org/searchengines.json)
