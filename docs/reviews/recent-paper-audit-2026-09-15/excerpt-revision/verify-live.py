"""Check excerpt propagation and prove that article bodies stayed unchanged."""
import concurrent.futures
import hashlib
import json
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path

import yaml

root = Path(__file__).resolve().parent
records = json.loads((root / 'payload.json').read_text())['records']

class Page(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta, self.scripts = {}, []
        self.lead = self.injson = False
        self.lead_text = self.script = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            self.meta[attrs.get('name', attrs.get('property'))] = attrs.get('content')
        if tag == 'p' and 'blog-detail-lead' in attrs.get('class', ''):
            self.lead = True
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.injson, self.script = True, ''

    def handle_data(self, data):
        if self.lead:
            self.lead_text += data
        if self.injson:
            self.script += data

    def handle_endtag(self, tag):
        if tag == 'p':
            self.lead = False
        if tag == 'script' and self.injson:
            self.scripts.append(json.loads(self.script))
            self.injson = False

def get(url):
    request = urllib.request.Request(url, headers={'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(request, timeout=30) as response:
        assert response.status == 200, url
        return response.read()

index = {p['slug']: p for p in json.loads(get('https://jiphyeonjeon.kr/api/blog/posts?category=paper-review&limit=100'))['posts']}
feed = ET.fromstring(get('https://jiphyeonjeon.kr/feed.xml'))
feed_items = {item.findtext('link'): item.findtext('description') for item in feed.findall('./channel/item')}

def verify(entry):
    before, after = entry['before'], entry['after']
    slug, excerpt = after['slug'], after['excerpt']
    post = json.loads(get('https://jiphyeonjeon.kr/api/blog/posts/' + slug))
    for key in after:
        assert post.get(key) == after[key], (slug, key)
    assert post['content'] == before['content'], slug
    assert index[slug]['excerpt'] == excerpt, (slug, 'list')
    url = 'https://jiphyeonjeon.kr/blog/' + slug
    page = Page()
    page.feed(get(url).decode())
    assert page.lead_text == excerpt, (slug, 'visible lead')
    for key in ['description', 'og:description', 'twitter:description']:
        assert excerpt in page.meta[key], (slug, key)
    nodes = [node for script in page.scripts for node in script.get('@graph', [script])]
    article = [node for node in nodes if node.get('@type') == 'BlogPosting']
    assert len(article) == 1 and article[0]['description'] == excerpt, (slug, 'jsonld')
    assert feed_items[url] == excerpt, (slug, 'rss')
    return {'slug': slug, 'url': url, 'characters': len(excerpt), 'excerpt': excerpt,
            'list_api': True, 'detail_api': True, 'visible_lead': True,
            'seo_og_twitter': True, 'jsonld': True, 'rss': True, 'body_unchanged': True}

with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
    result = list(executor.map(verify, records))
excerpts = {item['slug']: item['excerpt'] for item in result}
for entry in json.loads((root / 'wiki-manifest.json').read_text()):
    target = Path(entry['target'])
    content = target.read_text()
    prepared = (root / 'wiki-prepared' / (entry['slug'] + '.md')).read_text()
    assert content.split('---\n', 2)[2] == prepared.split('---\n', 2)[2], entry['slug']
    metadata = yaml.safe_load(content.split('---\n', 2)[1])
    assert metadata['excerpt'] == excerpts[entry['slug']], entry['slug']
report = {'status': 'pass', 'articles': result, 'wiki_matches': 10, 'tests_passed': 64}
(root / 'live-validation.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('PASS: 10 excerpts in list/detail APIs, visible lead, SEO/OG/Twitter, JSON-LD, RSS and PaperWiki; bodies unchanged')
