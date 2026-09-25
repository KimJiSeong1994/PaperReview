"""
Google Scholar 검색 클라이언트 (Enhanced)
웹 스크래핑을 통한 Google Scholar 검색

강화된 기능:
- 다중 쿼리 전략
- 제목 정확 매칭
- 쿼리 최적화
- 결과 병합 및 중복 제거
"""

import requests
from bs4 import BeautifulSoup
from src.collector.paper.rate_limiter import RateLimiter
from typing import List, Dict, Any, Optional
import time
import re
import urllib.parse
import os
import random
import pickle
import threading
from pathlib import Path
from src.utils.logger import log_search_operation, logger

def _get_free_proxy(timeout: int = 5, *, deadline=None, stop_event=None) -> Optional[str]:
    """Bound proxy discovery and validation synchronously in the owning worker."""
    deadline = min(deadline or float('inf'), time.monotonic() + timeout)
    try:
        if time.monotonic() >= deadline or (stop_event is not None and stop_event.is_set()):
            return None
        response = requests.get('https://www.sslproxies.org/', timeout=max(0.01, deadline - time.monotonic()))
        response.raise_for_status()
        rows = BeautifulSoup(response.text, 'html.parser').select('#list tbody tr')[:2]
        for row in rows:
            if time.monotonic() >= deadline or (stop_event is not None and stop_event.is_set()):
                break
            cells = row.find_all('td')
            if len(cells) < 7 or cells[6].get_text(strip=True).lower() != 'yes':
                continue
            proxy = 'http://' + cells[0].get_text(strip=True) + ':' + cells[1].get_text(strip=True)
            try:
                check = requests.get('https://www.google.com', proxies={'https': proxy}, timeout=min(2, deadline - time.monotonic()))
                check.raise_for_status()
                return proxy
            except requests.RequestException:
                continue
    except requests.RequestException as error:
        logger.debug('Proxy discovery failed: %s', error)
    return None

class GoogleScholarSearcher:
    """Google Scholar 검색 클라이언트 (Enhanced)"""

    # Class-level: throttling is per-upstream, not per-instance. Jitter is kept
    # — Scholar blocks clients that request on a metronome.
    _rate_limiter = RateLimiter(2.0, jitter=(1.5, 2.5))

    def __init__(self):
        self.base_url = "https://scholar.google.com"
        # 다양한 User-Agent 로테이션
        self.user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        ]
        self.headers = {
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0',
        }
        self.session = requests.Session()
        # 랜덤 User-Agent 선택
        self.headers['User-Agent'] = random.choice(self.user_agents)
        self.session.headers.update(self.headers)

        # 재시도 설정 (속도 우선 — 403 차단 시 빠르게 포기)
        self.max_retries = 1
        self.retry_delay_base = 2.0

        # 스레드 안전성을 위한 상태 잠금
        self._state_lock = threading.Lock()

        # 프록시 설정 (lazy init - 첫 요청 시 설정)
        self._proxy = None
        self._proxy_initialized = False
        self._proxy_failures = 0

        # CAPTCHA 처리 설정
        self.enable_manual_captcha = True  # 수동 CAPTCHA 해결 활성화
        self.cookies_file = Path(os.path.dirname(__file__)) / '.google_scholar_cookies.pkl'
        self._load_cookies()

        # Circuit breaker 설정
        self._consecutive_failures = 0
        self._disabled_until = 0  # Scholar 재활성화 시각 (timestamp)
        self._circuit_breaker_threshold = 8  # 연속 실패 횟수 임계값 (5→8)
        self._circuit_breaker_cooldown = 300  # 비활성화 시간 (2분→5분)

    def _ensure_proxy(self, *, deadline=None, stop_event=None):
        """첫 요청 시 프록시 설정 (lazy init)"""
        with self._state_lock:
            if self._proxy_initialized:
                return
            self._proxy_initialized = True
        self._try_set_proxy(deadline=deadline, stop_event=stop_event)

    def _try_set_proxy(self, *, deadline=None, stop_event=None):
        """무료 프록시 획득 및 설정"""
        proxy_url = _get_free_proxy(deadline=deadline, stop_event=stop_event)
        if proxy_url:
            self._proxy = {"http": proxy_url, "https": proxy_url}
            self.session.proxies.update(self._proxy)
            logger.info(f"Google Scholar proxy configured: {proxy_url}")
        else:
            self._proxy = None
            self.session.proxies.clear()
            logger.info("Google Scholar running without proxy")

    def _rotate_proxy(self):
        """프록시 실패 시 새 프록시로 교체"""
        with self._state_lock:
            self._proxy_failures += 1
            logger.info("Rotating to new proxy after failure...")
            self._proxy_failures = 0
        self._try_set_proxy()

    def _load_cookies(self):
        """저장된 쿠키 로드"""
        if self.cookies_file.exists():
            try:
                with open(self.cookies_file, 'rb') as f:
                    cookies = pickle.load(f)
                    for cookie in cookies:
                        self.session.cookies.set(cookie['name'], cookie['value'], domain=cookie.get('domain'))
                logger.info("Google Scholar cookies loaded successfully")
            except Exception as e:
                logger.warning(f"Failed to load cookies: {e}")

    def _save_cookies(self):
        """현재 세션의 쿠키 저장"""
        try:
            cookies = []
            for cookie in self.session.cookies:
                cookies.append({
                    'name': cookie.name,
                    'value': cookie.value,
                    'domain': cookie.domain,
                    'path': cookie.path
                })
            with open(self.cookies_file, 'wb') as f:
                pickle.dump(cookies, f)
            logger.info("Google Scholar cookies saved successfully")
        except Exception as e:
            logger.warning(f"Failed to save cookies: {e}")

    def _rate_limit(self):
        """Rate limiting을 위한 요청 간 딜레이 (랜덤 추가)"""
        self._rate_limiter.wait()

    def _is_available(self) -> bool:
        """Circuit breaker: Google Scholar 사용 가능 여부 확인"""
        with self._state_lock:
            if self._consecutive_failures >= self._circuit_breaker_threshold:
                now = time.time()
                if now < self._disabled_until:
                    remaining = int(self._disabled_until - now)
                    logger.warning(f"Google Scholar temporarily disabled ({remaining}s remaining)")
                    return False
                else:
                    logger.info("Google Scholar circuit breaker reset - retrying")
                    self._consecutive_failures = 0
            return True

    def is_circuit_open(self) -> bool:
        """Report circuit-breaker state without mutating it.

        ``_is_available`` resets the failure counter once the cooldown lapses,
        so callers that only want to *observe* the breaker must not use it.
        """
        with self._state_lock:
            return (
                self._consecutive_failures >= self._circuit_breaker_threshold
                and time.time() < self._disabled_until
            )

    def _record_success(self):
        """검색 성공 시 실패 카운터 초기화"""
        with self._state_lock:
            self._consecutive_failures = 0

    def _record_failure(self):
        """검색 실패 시 카운터 증가 및 circuit breaker 활성화"""
        with self._state_lock:
            self._consecutive_failures += 1
            if self._consecutive_failures >= self._circuit_breaker_threshold:
                self._disabled_until = time.time() + self._circuit_breaker_cooldown
                logger.error(
                    f"Google Scholar disabled for {self._circuit_breaker_cooldown}s "
                    f"after {self._consecutive_failures} consecutive failures"
                )

    def _request_with_backoff(self, url: str, params: dict, *, deadline=None, stop_event=None) -> requests.Response:
        deadline = deadline if deadline is not None else time.monotonic() + 30
        def check():
            remaining = deadline - time.monotonic()
            if remaining <= 0 or (stop_event is not None and stop_event.is_set()):
                raise TimeoutError('Scholar request budget exhausted')
            return remaining
        check()
        self._ensure_proxy(deadline=deadline, stop_event=stop_event)
        for attempt in range(max(1, self.max_retries)):
            check()
            self._rate_limit()
            remaining = check()
            try:
                response = self.session.get(url, params=params, timeout=min(10, remaining))
                response.raise_for_status()
                return response
            except requests.RequestException:
                if attempt + 1 >= max(1, self.max_retries):
                    raise
                delay = min(self.retry_delay_base * (2 ** attempt), check())
                if stop_event is not None:
                    stop_event.wait(delay)
                else:
                    time.sleep(delay)
        raise RuntimeError('Scholar retry budget exhausted')

    def _is_captcha_response(self, response) -> bool:
        """응답이 CAPTCHA인지 확인"""
        if response.status_code == 429:
            return True
        if 'sorry/index' in response.url or '/sorry/' in str(response.url):
            return True
        if response.text and ('captcha' in response.text.lower() or 'unusual traffic' in response.text.lower()):
            return True
        return False

    def _solve_captcha_manually(self, url: str) -> bool:
        """브라우저를 열어 사용자가 수동으로 CAPTCHA 해결"""
        try:
            from selenium import webdriver
            from selenium.webdriver.chrome.service import Service
            from selenium.webdriver.chrome.options import Options
            from webdriver_manager.chrome import ChromeDriverManager
            from selenium.webdriver.support.ui import WebDriverWait

            logger.info("=" * 60)
            logger.info("CAPTCHA DETECTED - Opening browser for manual verification")
            logger.info("=" * 60)
            logger.info("\n" + "=" * 60)
            logger.info("🔒 Google Scholar CAPTCHA 감지!")
            logger.info("브라우저가 자동으로 열립니다. CAPTCHA를 해결해주세요.")
            logger.info("해결 후 브라우저를 닫으면 자동으로 검색이 계속됩니다.")
            logger.info("=" * 60 + "\n")

            # Chrome 옵션 설정
            chrome_options = Options()
            chrome_options.add_argument('--disable-blink-features=AutomationControlled')
            chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
            chrome_options.add_experimental_option('useAutomationExtension', False)

            # WebDriver 초기화
            driver = webdriver.Chrome(
                service=Service(ChromeDriverManager().install()),
                options=chrome_options
            )

            try:
                # CAPTCHA 페이지로 이동
                driver.get(url)

                logger.info("Waiting for CAPTCHA to be solved...")
                logger.info("⏳ CAPTCHA 해결을 기다리는 중... (최대 5분)")

                # CAPTCHA가 해결되고 정상 페이지로 이동할 때까지 대기 (최대 5분)
                # 또는 사용자가 수동으로 scholar 페이지로 이동할 때까지
                WebDriverWait(driver, 300).until(
                    lambda d: ('scholar.google.com' in d.current_url and 'sorry' not in d.current_url.lower()) or
                              (d.current_url.startswith('https://scholar.google.com/scholar'))
                )

                # 추가 대기 (쿠키가 완전히 설정되도록)
                time.sleep(3)

                logger.info("✅ CAPTCHA solved successfully!")
                logger.info("✅ CAPTCHA 해결 완료!")
                logger.info("🔄 쿠키를 저장하고 세션을 업데이트하는 중...")

                # 추가로 Google Scholar 메인 페이지 방문 (쿠키 확인)
                try:
                    driver.get("https://scholar.google.com")
                    time.sleep(2)
                except Exception as e:
                    logger.warning("Unexpected error navigating to Scholar main page: %s", e)

                # 쿠키 가져오기
                selenium_cookies = driver.get_cookies()
                logger.info(f"Retrieved {len(selenium_cookies)} cookies from browser")

                # requests 세션에 쿠키 적용
                logger.info(f"Transferring {len(selenium_cookies)} cookies to session...")
                cookie_count = 0
                for cookie in selenium_cookies:
                    try:
                        self.session.cookies.set(
                            cookie['name'],
                            cookie['value'],
                            domain=cookie.get('domain', '.google.com'),
                            path=cookie.get('path', '/'),
                            secure=cookie.get('secure', False)
                        )
                        cookie_count += 1
                    except Exception as e:
                        logger.warning(f"Failed to set cookie {cookie.get('name')}: {e}")

                logger.info(f"Successfully transferred {cookie_count}/{len(selenium_cookies)} cookies")

                # 쿠키 저장
                self._save_cookies()

                logger.info("Cookies saved to file and session updated")

                # 헤더도 업데이트 (브라우저처럼)
                self.headers['User-Agent'] = driver.execute_script("return navigator.userAgent")
                self.session.headers.update(self.headers)
                logger.info(f"Updated User-Agent: {self.headers['User-Agent'][:50]}...")

                driver.quit()
                return True

            except Exception as e:
                logger.error(f"Error during CAPTCHA solving: {e}")
                driver.quit()
                return False

        except ImportError:
            logger.error("Selenium not installed. Install with: pip install selenium webdriver-manager")
            logger.info("Continuing without manual CAPTCHA solving...")
            return False
        except Exception as e:
            logger.error(f"Failed to open browser for CAPTCHA: {e}")
            return False

    def _extract_keywords(self, query: str) -> List[str]:
        """쿼리에서 핵심 키워드 추출"""
        stopwords = {'the', 'a', 'an', 'and', 'or', 'but', 'in', 'on', 'at', 'to', 'for',
                     'of', 'with', 'by', 'from', 'is', 'are', 'was', 'were', 'be', 'been',
                     'as', 'it', 'its', 'this', 'that', 'these', 'those', 'can', 'will',
                     'using', 'based', 'via', 'through', 'into', 'over', 'under'}

        # 소문자로 변환하고 특수문자 제거
        query_clean = re.sub(r'[^\w\s\-]', ' ', query.lower())
        words = query_clean.split()
        keywords = [w for w in words if w not in stopwords and len(w) > 2]
        return keywords

    def _build_optimized_query(self, query: str, search_type: str = "default") -> str:
        """최적화된 검색 쿼리 생성"""
        if search_type == "exact":
            # 정확한 구문 검색
            return f'"{query}"'

        elif search_type == "title":
            # 제목에서 검색
            return f'allintitle: {query}'

        elif search_type == "keywords":
            # 키워드 기반 검색
            keywords = self._extract_keywords(query)
            if keywords:
                return " ".join(keywords[:5])  # 상위 5개 키워드
            return query

        else:  # default
            return query

    @log_search_operation("Google Scholar")
    def search(self, query: str, max_results: int = 10, sort_by: str = "relevance", *, deadline=None, stop_event=None, attempts=None) -> List[Dict[str, Any]]:
        """Finite HTML retrieval; interactive CAPTCHA and scholarly retries are not request-safe."""
        deadline = deadline if deadline is not None else time.monotonic() + 30
        if not self._is_available():
            if attempts is not None:
                attempts.append({'query': query, 'status': 'circuit_open'})
            return []
        receipt = {'query': query, 'status': 'dispatched'}
        if attempts is not None:
            attempts.append(receipt)
        try:
            response = self._request_with_backoff(self.base_url + '/scholar', {'q': query, 'hl': 'en', 'as_sdt': '0,5', **({'scisbd': '1'} if sort_by == 'date' else {})}, deadline=deadline, stop_event=stop_event)
            if self._is_captcha_response(response):
                raise requests.HTTPError('Scholar CAPTCHA requires independent manual recovery')
            papers = self._parse_search_results(response.text, max_results)
            self._record_success()
            receipt['status'] = 'searched' if papers else 'searched_empty'
            return papers
        except Exception as error:
            receipt['status'] = 'timeout' if isinstance(error, (TimeoutError, requests.Timeout)) else 'error'
            self._record_failure()
            if attempts is None:
                raise
            return []

    @log_search_operation("Google Scholar Enhanced")
    def enhanced_search(self, query: str, max_results: int = 10, *, deadline=None, stop_event=None, attempts=None) -> List[Dict[str, Any]]:
        from src.utils.paper_utils import generate_result_key
        deadline = deadline if deadline is not None else time.monotonic() + 30
        papers, seen = [], set()
        for strategy in ('keywords', 'title'):
            if time.monotonic() >= deadline or (stop_event is not None and stop_event.is_set()):
                if attempts is not None:
                    attempts.append({'query': query, 'status': 'timeout'})
                break
            for paper in self.search(self._build_optimized_query(query, strategy), max_results, deadline=deadline, stop_event=stop_event, attempts=attempts):
                key = generate_result_key(paper)
                if key not in seen:
                    seen.add(key)
                    papers.append(paper)
            if len(papers) >= max_results:
                break
        return papers[:max_results]

    @log_search_operation("Google Scholar Title")
    def search_by_title(self, title: str, max_results: int = 5, *, deadline=None, stop_event=None, attempts=None) -> List[Dict[str, Any]]:
        return self.search(f'allintitle: "{title}"', max_results, deadline=deadline, stop_event=stop_event, attempts=attempts)

    def search_by_author(self, author: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        저자별 논문 검색

        Args:
            author: 저자 이름
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        query = f'author:"{author}"'
        return self.search(query, max_results)

    def search_by_year(self, query: str, year: int, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        특정 연도 논문 검색

        Args:
            query: 검색 쿼리
            year: 연도
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        query_with_year = f'{query} after:{year} before:{year+1}'
        return self.search(query_with_year, max_results)

    def get_cited_by(self, paper_url: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        특정 논문을 인용한 논문들 가져오기

        Args:
            paper_url: 논문 URL
            max_results: 최대 결과 수

        Returns:
            인용 논문 리스트
        """
        try:
            # Cited by 링크 찾기
            self._rate_limit()  # Rate limiting 추가
            response = self.session.get(paper_url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Cited by 링크 찾기
            cited_by_link = soup.find('a', string=re.compile(r'Cited by'))
            if not cited_by_link:
                return []

            cited_by_url = urllib.parse.urljoin(self.base_url, cited_by_link.get('href', ''))

            # Cited by 페이지 접근
            self._rate_limit()  # Rate limiting 추가
            cited_response = self.session.get(cited_by_url, timeout=15)
            cited_response.raise_for_status()

            return self._parse_search_results(cited_response.text, max_results)

        except Exception as e:
            logger.error(f"인용 논문 가져오기 오류: {e}")
            return []

    def get_related_articles(self, paper_url: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """
        관련 논문 가져오기

        Args:
            paper_url: 논문 URL
            max_results: 최대 결과 수

        Returns:
            관련 논문 리스트
        """
        try:
            # Related articles 링크 찾기
            self._rate_limit()  # Rate limiting 추가
            response = self.session.get(paper_url, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # Related articles 링크 찾기
            related_link = soup.find('a', string=re.compile(r'Related articles'))
            if not related_link:
                return []

            related_url = urllib.parse.urljoin(self.base_url, related_link.get('href', ''))

            # Related articles 페이지 접근
            self._rate_limit()  # Rate limiting 추가
            related_response = self.session.get(related_url, timeout=15)
            related_response.raise_for_status()

            return self._parse_search_results(related_response.text, max_results)

        except Exception as e:
            logger.error(f"관련 논문 가져오기 오류: {e}")
            return []

    def _parse_search_results(self, html_content: str, max_results: int) -> List[Dict[str, Any]]:
        """검색 결과 HTML 파싱"""
        try:
            soup = BeautifulSoup(html_content, 'html.parser')
            papers = []

            # 검색 결과 요소 찾기
            result_elements = soup.find_all('div', class_='gs_ri')

            for element in result_elements[:max_results]:
                paper_info = self._extract_paper_from_element(element)
                if paper_info:
                    papers.append(paper_info)

            return papers

        except Exception as e:
            logger.error(f"검색 결과 파싱 오류: {e}")
            return []

    def _search_via_scholarly(self, query: str, max_results: int = 10) -> List[Dict[str, Any]]:
        """scholarly 라이브러리를 통한 대체 검색 (HTML 스크래핑 실패 시 fallback)"""
        try:
            from scholarly import scholarly as scholarly_lib

            search_results = scholarly_lib.search_pubs(query)
            papers = []

            for _ in range(max_results):
                try:
                    result = next(search_results)
                    bib = result.get('bib', {})

                    # Extract DOI from bib or URL
                    doi = bib.get('doi', '')
                    pub_url = result.get('pub_url', '')
                    eprint_url = result.get('eprint_url', '')
                    if not doi and pub_url:
                        doi_match = re.search(r'doi\.org/(10\.\S+)', pub_url)
                        if doi_match:
                            doi = doi_match.group(1)

                    # Extract arxiv_id from URL or eprint_url
                    arxiv_id = ''
                    for candidate_url in [eprint_url, pub_url]:
                        if candidate_url:
                            arxiv_match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})', candidate_url)
                            if arxiv_match:
                                arxiv_id = arxiv_match.group(1)
                                break

                    paper = {
                        "title": bib.get('title', ''),
                        "authors": bib.get('author', []),
                        "abstract": bib.get('abstract', ''),
                        "url": pub_url or eprint_url,
                        "pdf_url": eprint_url,
                        "journal": bib.get('venue', ''),
                        "year": str(bib.get('pub_year', '')),
                        "citations": result.get('num_citations', 0),
                        "doi": doi,
                        "arxiv_id": arxiv_id,
                        "source": "Google Scholar",
                    }

                    if paper['title']:
                        papers.append(paper)

                except StopIteration:
                    break
                except Exception as e:
                    logger.debug("scholarly result parse error: %s", e)
                    continue

            return papers

        except ImportError:
            logger.warning("scholarly library not available for fallback")
            return []
        except Exception as e:
            logger.warning("scholarly fallback search failed: %s", e)
            return []

    def _extract_paper_from_element(self, element) -> Optional[Dict[str, Any]]:
        """HTML 요소에서 논문 정보 추출"""
        try:
            # 제목 추출
            title_elem = element.find('h3', class_='gs_rt')
            title = ""
            url = ""
            if title_elem:
                title_link = title_elem.find('a')
                if title_link:
                    title = title_link.get_text(separator=' ', strip=True)
                    url = title_link.get('href', '')
                else:
                    title = title_elem.get_text(separator=' ', strip=True)

            # 저자 및 출판 정보 추출
            authors_elem = element.find('div', class_='gs_a')
            authors = []
            journal = ""
            year = ""
            if authors_elem:
                authors_text = authors_elem.get_text(separator=' ')
                # 저자 파싱 (일반적으로 첫 번째 부분이 저자)
                parts = authors_text.split(' - ')
                if parts:
                    authors_part = parts[0]
                    authors = [author.strip() for author in authors_part.split(',')]

                    # 출판 정보에서 저널과 연도 추출
                    if len(parts) > 1:
                        journal_part = parts[1]
                        # 연도 추출
                        year_match = re.search(r'\b(19|20)\d{2}\b', journal_part)
                        if year_match:
                            year = year_match.group()
                        journal = journal_part

            # 초록 추출
            abstract_elem = element.find('div', class_='gs_rs')
            abstract = abstract_elem.get_text(separator=' ', strip=True) if abstract_elem else ""

            # 인용 수 추출
            citations_elem = element.find('a', string=re.compile(r'Cited by'))
            citations = 0
            if citations_elem:
                citations_text = citations_elem.get_text()
                citations_match = re.search(r'(\d+)', citations_text)
                if citations_match:
                    citations = int(citations_match.group(1))

            # PDF 링크 추출
            pdf_link = element.find('a', string='[PDF]')
            pdf_url = pdf_link.get('href', '') if pdf_link else ""

            # DOI 추출 (초록에서)
            doi = ""
            doi_match = re.search(r'doi\.org/([^\s]+)', abstract)
            if doi_match:
                doi = doi_match.group(1)

            # arXiv ID 추출 (URL 또는 PDF 링크에서)
            arxiv_id = ""
            for candidate_url in [pdf_url, url]:
                if candidate_url:
                    arxiv_match = re.search(r'arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})', candidate_url)
                    if arxiv_match:
                        arxiv_id = arxiv_match.group(1)
                        break

            return {
                "title": title,
                "authors": authors,
                "abstract": abstract,
                "url": url,
                "pdf_url": pdf_url,
                "journal": journal,
                "year": year,
                "citations": citations,
                "doi": doi,
                "arxiv_id": arxiv_id,
                "source": "Google Scholar"
            }

        except Exception as e:
            logger.error(f"논문 정보 추출 오류: {e}")
            return None

    def search_with_filters(self, query: str, year_start: int = None, year_end: int = None,
                          author: str = None, max_results: int = 10, *, deadline=None, stop_event=None, attempts=None) -> List[Dict[str, Any]]:
        """
        필터를 적용한 검색

        Args:
            query: 검색 쿼리
            year_start: 시작 연도
            year_end: 종료 연도
            author: 저자
            max_results: 최대 결과 수

        Returns:
            논문 정보 리스트
        """
        try:
            # 검색 쿼리 구성
            search_query = query

            if author:
                search_query += f' author:"{author}"'

            if year_start and year_end:
                search_query += f' after:{year_start-1} before:{year_end+1}'
            elif year_start:
                search_query += f' after:{year_start-1}'
            elif year_end:
                search_query += f' before:{year_end+1}'

            return self.search(search_query, max_results, deadline=deadline, stop_event=stop_event, attempts=attempts)

        except Exception as e:
            logger.error(f"필터 검색 중 오류 발생: {e}")
            raise

    def get_author_profile(self, author_name: str) -> Optional[Dict[str, Any]]:
        """
        저자 프로필 정보 가져오기

        Args:
            author_name: 저자 이름

        Returns:
            저자 프로필 정보
        """
        try:
            # 저자 검색
            search_url = f"{self.base_url}/citations"
            params = {
                'mauthors': author_name,
                'hl': 'en'
            }

            self._rate_limit()  # Rate limiting 추가
            response = self.session.get(search_url, params=params, timeout=15)
            response.raise_for_status()

            soup = BeautifulSoup(response.text, 'html.parser')

            # 저자 프로필 정보 추출
            profile_elem = soup.find('div', class_='gsc_vcd')
            if not profile_elem:
                return None

            # 저자 이름
            name_elem = profile_elem.find('h3', class_='gsc_oai_name')
            name = name_elem.get_text(strip=True) if name_elem else author_name

            # 소속
            affiliation_elem = profile_elem.find('div', class_='gsc_oai_aff')
            affiliation = affiliation_elem.get_text(strip=True) if affiliation_elem else ""

            # 연구 분야
            interests_elem = profile_elem.find('div', class_='gsc_oai_int')
            interests = []
            if interests_elem:
                interests = [interest.strip() for interest in interests_elem.get_text().split(',')]

            # 인용 통계
            stats_elem = profile_elem.find('table', class_='gsc_rsb_st')
            citations = 0
            h_index = 0
            i10_index = 0

            if stats_elem:
                rows = stats_elem.find_all('tr')
                for row in rows:
                    cells = row.find_all('td')
                    if len(cells) >= 2:
                        label = cells[0].get_text(strip=True)
                        value = cells[1].get_text(strip=True)

                        if 'Citations' in label:
                            citations = int(re.sub(r'[^\d]', '', value)) if re.search(r'\d', value) else 0
                        elif 'h-index' in label:
                            h_index = int(re.sub(r'[^\d]', '', value)) if re.search(r'\d', value) else 0
                        elif 'i10-index' in label:
                            i10_index = int(re.sub(r'[^\d]', '', value)) if re.search(r'\d', value) else 0

            return {
                "name": name,
                "affiliation": affiliation,
                "interests": interests,
                "total_citations": citations,
                "h_index": h_index,
                "i10_index": i10_index,
                "source": "Google Scholar"
            }

        except Exception as e:
            logger.error(f"저자 프로필 가져오기 오류: {e}")
            return None
