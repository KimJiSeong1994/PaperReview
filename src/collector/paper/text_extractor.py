import io
import logging
import re
import sys
import os
import PyPDF2
import pdfplumber

import requests
from bs4 import BeautifulSoup
from typing import Dict, Any, Optional

from src.utils.logger import log_data_processing

logger = logging.getLogger(__name__)

class TextExtractor:
    def __init__(self, use_scihub: bool = True):
        self.headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}
        self.session = requests.Session()
        self.session.headers.update(self.headers)
        self.use_scihub = use_scihub

    def close(self):
        """Close the HTTP session."""
        self.session.close()

    def __del__(self):
        self.session.close()
        self.scihub_mirrors = [
            'https://sci-hub.se',
            'https://sci-hub.st',
            'https://sci-hub.ru'
        ]

    @log_data_processing("Text Extraction")
    def extract_full_text(self, paper: Dict[str, Any]) -> Optional[str]:
        if paper.get('full_text'):
            return paper['full_text']

        # 추출 시도 순서: arXiv PDF → Sci-Hub → Semantic Scholar → Abstract
        for extractor in [
            lambda: self._extract_from_arxiv_pdf(paper) if 'arXiv' in paper.get('source', '') else None,
            lambda: self._extract_from_scihub(paper) if self.use_scihub and (paper.get('doi') or paper.get('url')) else None,
            lambda: self._extract_from_semantic_scholar(paper) if (paper.get('connected_papers_id') or 'Semantic Scholar' in paper.get('source', '')) else None
        ]:
            text = extractor()
            if text:
                return text

        return paper.get('abstract', '')

    def _extract_from_arxiv_pdf(self, paper: Dict[str, Any]) -> Optional[str]:
        try:
            pdf_url = paper.get('pdf_url') or (f"https://arxiv.org/pdf/{paper['arxiv_id'].split('v')[0]}.pdf" if paper.get('arxiv_id') else None)
            if not pdf_url:
                return None
            pdf_file = io.BytesIO(self.session.get(pdf_url, timeout=30).content)

            try:
                with pdfplumber.open(pdf_file) as pdf:
                    full_text = '\n\n'.join([page.extract_text() for page in pdf.pages if page.extract_text()])
                    return full_text if full_text.strip() else None

            except Exception as e:
                logger.debug("pdfplumber failed for arXiv PDF, trying PyPDF2: %s", e)
                pdf_file.seek(0)
                return self._extract_with_pypdf2(pdf_file)

        except Exception as e:
            logger.warning("arXiv PDF extraction failed: %s", e)
            return None

    def _extract_with_pypdf2(self, pdf_file: io.BytesIO) -> Optional[str]:
        try:
            reader = PyPDF2.PdfReader(pdf_file)
            full_text = '\n\n'.join([page.extract_text() for page in reader.pages if page.extract_text()])
            return full_text if full_text.strip() else None

        except Exception as e:
            logger.debug("PyPDF2 extraction failed: %s", e)
            return None

    def _extract_from_scihub(self, paper: Dict[str, Any]) -> Optional[str]:
        try:
            identifier = paper.get('doi') or paper.get('url')
            if not identifier:
                return None

            for mirror in self.scihub_mirrors:
                try:
                    response = self.session.get(f"{mirror}/{identifier}", timeout=15, allow_redirects=True)
                    if response.status_code != 200:
                        continue

                    soup = BeautifulSoup(response.text, 'html.parser')

                    # PDF URL 찾기 (iframe > embed > button 순서)
                    pdf_url = (soup.find('iframe', {'id': 'pdf'}) or soup.find('embed', {'type': 'application/pdf'}))
                    pdf_url = pdf_url.get('src') if pdf_url else None

                    if not pdf_url:
                        save_button = soup.find('button', {'onclick': True})
                        if save_button and 'location.href' in save_button.get('onclick', ''):
                            match = re.search(r"location\.href='([^']+)'", save_button.get('onclick', ''))
                            pdf_url = match.group(1) if match else None

                    if pdf_url:
                        pdf_url = ('https:' + pdf_url) if pdf_url.startswith('//') else (mirror + pdf_url if pdf_url.startswith('/') else pdf_url)
                        pdf_file = io.BytesIO(self.session.get(pdf_url, timeout=30).content)

                        try:
                            with pdfplumber.open(pdf_file) as pdf:
                                full_text = '\n\n'.join([page.extract_text() for page in pdf.pages if page.extract_text()])
                                return full_text if full_text.strip() else None

                        except Exception as e:
                            logger.debug("pdfplumber failed for SciHub PDF, trying PyPDF2: %s", e)
                            pdf_file.seek(0)
                            return self._extract_with_pypdf2(pdf_file)

                except Exception as e:
                    logger.debug("SciHub mirror %s failed: %s", mirror, e)
                    continue

            return None

        except Exception as e:
            logger.warning("SciHub extraction failed: %s", e)
            return None

    def _extract_from_semantic_scholar(self, paper: Dict[str, Any]) -> Optional[str]:
        try:
            paper_id = (paper['connected_papers_id'][3:] if paper.get('connected_papers_id', '').startswith('ss_') else paper.get('paper_id'))
            if not paper_id:
                return None

            response = self.session.get(
                f"https://api.semanticscholar.org/graph/v1/paper/{paper_id}",
                params={'fields': 'abstract'},
                timeout=10
            )
            response.raise_for_status()
            return response.json().get('abstract', None)

        except Exception as e:
            logger.warning("Semantic Scholar text extraction failed: %s", e)
            return None

    def extract_batch(self, papers: list, max_papers: int = None) -> Dict[str, Any]:
        papers_to_process = papers[:max_papers] if max_papers else papers
        results = {'total': 0, 'success': 0, 'failed': 0, 'already_exists': 0}

        for i, paper in enumerate(papers_to_process):
            logger.info(f"  [{i+1}/{len(papers_to_process)}] {paper.get('title', 'Unknown')[:50]}...")

            if paper.get('full_text'):
                results['already_exists'] += 1
                logger.info("    ✓ 본문 이미 존재")
                continue

            results['total'] += 1
            full_text = self.extract_full_text(paper)

            if full_text and len(full_text.strip()) > 100:
                paper['full_text'] = full_text
                paper['full_text_length'] = len(full_text)
                results['success'] += 1
                source_info = (" (arXiv PDF)" if 'arXiv' in paper.get('source', '') else " (Sci-Hub)" if self.use_scihub and (paper.get('doi') or paper.get('url')) else "")
                logger.info(f"    ✓ 본문 추출 완료 ({len(full_text):,}자){source_info}")

            else:
                results['failed'] += 1
                if paper.get('abstract'):
                    paper['full_text'] = paper['abstract']
                    paper['full_text_length'] = len(paper['abstract'])
                    logger.info(f"    ○ PDF 없음 - Abstract 사용 ({len(paper['abstract'])}자)")

                else:
                    logger.error("    ✗ 본문 추출 실패")

        return results
