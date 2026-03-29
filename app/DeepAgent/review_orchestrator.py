import logging
logger = logging.getLogger(__name__)

"""
Review Orchestrator
N명의 연구원이 병렬로 논문을 분석하고, 지도교수가 검증하는 오케스트레이션
"""
import sys
import os
import threading
from typing import List, Dict, Any, Optional
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

# 경로 추가

from app.DeepAgent.workspace_manager import WorkspaceManager
from app.DeepAgent.tools.paper_loader import load_and_prepare_papers
from app.DeepAgent.tools.report_generator import generate_markdown_report, generate_html_report
from app.DeepAgent.subagents.researcher_agent import analyze_paper_deep
from app.DeepAgent.subagents.advisor_agent import validate_and_synthesize
from app.DeepAgent.tools.fact_verification import (
    ClaimExtractor, EvidenceLinker, CrossRefValidator, VerificationResult,
)

_workspace_write_lock = threading.Lock()


class ReviewOrchestrator:
    """
    논문 리뷰 오케스트레이터

    역할:
    1. 선택된 논문 로드
    2. N명의 연구원 에이전트에게 병렬 분석 위임
    3. 지도교수 에이전트에게 검증 요청
    4. 최종 리포트 생성
    """

    def __init__(
        self,
        max_workers: Optional[int] = None,
        workspace: Optional[WorkspaceManager] = None
    ):
        """
        Args:
            max_workers: 병렬 실행할 최대 워커 수 (None이면 논문 수만큼)
            workspace: Workspace Manager (None이면 자동 생성)
        """
        self.workspace = workspace or WorkspaceManager()
        self.max_workers = max_workers

        logger.info("[INFO] Review Orchestrator initialized")
        logger.info(f"   Session: {self.workspace.session_id}")
        logger.info(f"   Workspace: {self.workspace.session_path}")

    def review_papers(
        self,
        paper_ids: List[str],
        verbose: bool = True
    ) -> Dict[str, Any]:
        """
        논문 리뷰 프로세스 실행

        Args:
            paper_ids: 리뷰할 논문 ID 리스트
            verbose: 상세 로그 출력 여부

        Returns:
            리뷰 결과
        """
        if verbose:
            logger.info("\n" + "="*80)
            logger.info("[INFO] Starting Deep Paper Review Process")
            logger.info("="*80 + "\n")

        # Step 1: 논문 로드
        papers = self._load_papers(paper_ids, verbose)

        if not papers:
            return {"error": "No papers loaded", "status": "failed"}

        # Step 2: 병렬 분석
        analyses = self._parallel_analysis(papers, verbose)

        # Step 3: 검증 및 종합
        validation = self._validate_and_synthesize(analyses, papers, verbose)

        # Step 3.5: 사실 검증
        verification = self._verify_facts(papers, analyses, validation, verbose)

        # Step 4: 최종 리포트 생성
        report = self._generate_report(papers, analyses, validation, verbose, verification)

        # Step 5: 결과 저장
        self._save_results(papers, analyses, validation, report, verbose, verification)

        if verbose:
            logger.info("\n" + "="*80)
            logger.info("[OK] Deep Paper Review Completed!")
            logger.info("="*80 + "\n")

        return {
            "status": "completed",
            "session_id": self.workspace.session_id,
            "papers_reviewed": len(papers),
            "analyses": analyses,
            "validation": validation,
            "verification": verification,
            "report": report,
            "workspace_path": str(self.workspace.session_path)
        }

    def _load_papers(self, paper_ids: List[str], verbose: bool) -> List[Dict[str, Any]]:
        """논문 로드"""
        if verbose:
            logger.info("[Step 1] Loading Papers...")
            logger.info("-" * 80)

        papers = load_and_prepare_papers(paper_ids)

        # Workspace에 저장
        self.workspace.save_selected_papers(papers)
        self.workspace.log(f"Loaded {len(papers)} papers")

        if verbose:
            logger.info(f"[OK] Loaded {len(papers)} papers\n")

        return papers

    def _parallel_analysis(
        self,
        papers: List[Dict[str, Any]],
        verbose: bool
    ) -> List[Dict[str, Any]]:
        """
        병렬 논문 분석
        N명의 연구원이 동시에 각자의 논문을 분석
        """
        if verbose:
            logger.info("[Step 2] Parallel Analysis by Researchers...")
            logger.info("-" * 80)
            logger.info(f"Spawning {len(papers)} researcher agents (parallel execution)")

        start_time = datetime.now()

        # 워커 수 결정
        max_workers = self.max_workers or min(len(papers), os.cpu_count() or 4)

        analyses = []

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            # 각 논문에 대해 분석 작업 제출
            future_to_paper = {
                executor.submit(self._analyze_single_paper, i, paper): (i, paper)
                for i, paper in enumerate(papers, 1)
            }

            # 완료된 작업 수집
            for future in as_completed(future_to_paper):
                researcher_id, paper = future_to_paper[future]
                try:
                    analysis = future.result()
                    analyses.append(analysis)

                    if verbose:
                        logger.info(f"  [v] Researcher {researcher_id} completed analysis")

                except Exception as e:
                    logger.error(f"  [x] Researcher {researcher_id} failed: {e}")
                    self.workspace.log(f"Analysis failed for paper {researcher_id}: {e}", "ERROR")

        # 논문 순서대로 정렬 (완료 순서와 무관하게)
        analyses.sort(key=lambda a: papers.index(
            next(p for p in papers if (p.get('id') or p.get('arxiv_id')) == a.get('paper_id'))
        ))

        elapsed = (datetime.now() - start_time).total_seconds()

        if verbose:
            logger.info(f"\n[OK] Parallel analysis completed in {elapsed:.1f}s")
            logger.info(f"   Average time per paper: {elapsed/len(papers):.1f}s\n")

        return analyses

    def _analyze_single_paper(
        self,
        researcher_id: int,
        paper: Dict[str, Any]
    ) -> Dict[str, Any]:
        """단일 논문 분석 (개별 연구원)"""
        # 연구원 ID
        rid = f"researcher_{researcher_id}"

        # 논문 분석
        analysis = analyze_paper_deep(paper)

        # Workspace에 저장 (thread-safe)
        with _workspace_write_lock:
            self.workspace.save_researcher_analysis(
                researcher_id=rid,
                paper_id=analysis.get("paper_id", "unknown"),
                analysis=analysis
            )

        self.workspace.log(f"Researcher {researcher_id} completed analysis of paper {analysis.get('paper_id')}")

        return analysis

    def _validate_and_synthesize(
        self,
        analyses: List[Dict[str, Any]],
        papers: List[Dict[str, Any]],
        verbose: bool
    ) -> Dict[str, Any]:
        """지도교수에 의한 검증 및 종합"""
        if verbose:
            logger.info("[Step 3] Validation & Synthesis by Advisor...")
            logger.info("-" * 80)

        start_time = datetime.now()

        # 지도교수 검증
        validation = validate_and_synthesize(analyses, papers)

        # Workspace에 저장
        self.workspace.save_advisor_validation(validation)
        self.workspace.log("Advisor validation completed")

        elapsed = (datetime.now() - start_time).total_seconds()

        if verbose:
            summary = validation.get("summary", {})
            logger.info(f"  [v] Validated {summary.get('total_papers', 0)} analyses")
            logger.info(f"  [v] Approved: {summary.get('approved', 0)}")
            logger.info(f"  [v] Needs Revision: {summary.get('needs_revision', 0)}")
            logger.info(f"\n[OK] Validation completed in {elapsed:.1f}s\n")

        return validation

    def _verify_facts(
        self,
        papers: List[Dict[str, Any]],
        analyses: List[Dict[str, Any]],
        validation: Dict[str, Any],
        verbose: bool,
    ) -> Dict[str, Any]:
        """
        Step 3.5: 사실 검증 파이프라인

        1. 초안 리포트에서 Claim 추출
        2. 원문 논문과 Evidence 연결
        3. 논문 간 교차 검증 및 합의도 분석
        """
        if verbose:
            logger.info("[Step 3.5] Fact Verification...")
            logger.info("-" * 80)

        start_time = datetime.now()

        try:
            # 초안 리포트 생성 (Claim 추출용)
            synthesis = validation.get("cross_paper_synthesis", {})
            draft_report = generate_markdown_report(papers, analyses, validation, synthesis)

            # 1. Claim 추출
            extractor = ClaimExtractor()
            claims = extractor.extract_claims_sync(draft_report, papers, analyses)

            if verbose:
                logger.info(f"  [v] Extracted {len(claims)} claims from report")

            # 2. Evidence 연결
            linker = EvidenceLinker()
            claim_evidences = linker.find_all_evidence_sync(claims, papers)

            verification_result = VerificationResult(
                claims=claims,
                claim_evidences=claim_evidences,
            )
            stats = verification_result.statistics

            if verbose:
                logger.info(f"  [v] Evidence linked: {stats['verified']} verified, "
                      f"{stats['unverified']} unverified out of {stats['verifiable_claims']}")

            # 3. 교차 검증 (2개 이상 논문일 때만)
            cross_refs = []
            consensus = []
            if len(papers) >= 2:
                validator = CrossRefValidator()
                cross_refs = validator.detect_conflicts_sync(claims)
                consensus = validator.build_consensus_sync(claims, cross_refs)

                if verbose:
                    conflicts = sum(1 for r in cross_refs if r.relation.value == "contradicts")
                    logger.info(f"  [v] Cross-validation: {len(cross_refs)} comparisons, {conflicts} conflicts")

            # Workspace에 저장
            self.workspace.save_verification_claims(
                [c.to_dict() for c in claims]
            )
            if cross_refs:
                self.workspace.save_cross_references(
                    [xref.to_dict() for xref in cross_refs],
                    [cons.to_dict() for cons in consensus],
                )

            self.workspace.log("Fact verification completed")

            elapsed = (datetime.now() - start_time).total_seconds()

            if verbose:
                rate = stats['verification_rate'] * 100
                logger.info(f"\n[OK] Fact verification completed in {elapsed:.1f}s")
                logger.info(f"   Verification rate: {rate:.1f}%\n")

            return {
                "claims": [c.to_dict() for c in claims],
                "claim_evidences": [ce.to_dict() for ce in claim_evidences],
                "cross_references": [xref.to_dict() for xref in cross_refs],
                "consensus": [cons.to_dict() for cons in consensus],
                "statistics": stats,
            }

        except Exception as e:
            if verbose:
                logger.error(f"  [!] Fact verification failed: {e}")
            self.workspace.log(f"Fact verification failed: {e}", "WARNING")
            return {"claims": [], "claim_evidences": [], "cross_references": [],
                    "consensus": [], "statistics": {}}

    def _generate_report(
        self,
        papers: List[Dict[str, Any]],
        analyses: List[Dict[str, Any]],
        validation: Dict[str, Any],
        verbose: bool,
        verification: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, str]:
        """최종 리포트 생성"""
        if verbose:
            logger.info("[Step 4] Generating Final Report...")
            logger.info("-" * 80)

        # Synthesis 데이터 추출
        synthesis = validation.get("cross_paper_synthesis", {})

        # Markdown 리포트
        markdown_report = generate_markdown_report(
            papers, analyses, validation, synthesis, verification=verification
        )

        # HTML 리포트
        html_report = generate_html_report(
            papers, analyses, validation, synthesis, verification=verification
        )

        if verbose:
            logger.info(f"  [v] Markdown report generated ({len(markdown_report)} chars)")
            logger.info(f"  [v] HTML report generated ({len(html_report)} chars)")
            logger.info("\n[OK] Report generation completed\n")

        return {
            "markdown": markdown_report,
            "html": html_report
        }

    def _save_results(
        self,
        papers: List[Dict[str, Any]],
        analyses: List[Dict[str, Any]],
        validation: Dict[str, Any],
        report: Dict[str, str],
        verbose: bool,
        verification: Optional[Dict[str, Any]] = None,
    ):
        """결과 저장"""
        if verbose:
            logger.info("[Step 5] Saving Results...")
            logger.info("-" * 80)

        # Markdown 리포트 저장
        md_path = self.workspace.save_final_report(
            report["markdown"],
            format="markdown"
        )

        # HTML 리포트 저장
        html_path = self.workspace.save_final_report(
            report["html"],
            format="html"
        )

        # JSON 결과 저장
        json_result = {
            "papers": papers,
            "analyses": analyses,
            "validation": validation,
            "verification": verification or {},
            "session_id": self.workspace.session_id,
            "completed_at": datetime.now().isoformat()
        }
        json_path = self.workspace.save_final_report(
            json_result,
            format="json"
        )

        # 상태 업데이트
        self.workspace.update_status("completed")

        if verbose:
            logger.info(f"  [v] Markdown report: {md_path}")
            logger.info(f"  [v] HTML report: {html_path}")
            logger.info(f"  [v] JSON results: {json_path}")
            logger.info("\n[OK] All results saved\n")


# ==================== Standalone Functions ====================

def review_selected_papers(
    paper_ids: List[str],
    max_workers: Optional[int] = None,
    verbose: bool = True
) -> Dict[str, Any]:
    """
    선택된 논문들을 리뷰 (원스톱 함수)

    Args:
        paper_ids: 논문 ID 리스트
        max_workers: 병렬 실행 워커 수
        verbose: 상세 로그 출력

    Returns:
        리뷰 결과
    """
    orchestrator = ReviewOrchestrator(max_workers=max_workers)
    return orchestrator.review_papers(paper_ids, verbose=verbose)

