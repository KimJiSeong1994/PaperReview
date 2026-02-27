"""
Workspace Manager for Deep Agent System
파일 시스템 기반 컨텍스트 및 메모리 관리
"""
import os
import json
import re
import uuid
from datetime import datetime
from typing import Dict, List, Any, Optional
from pathlib import Path


class WorkspaceManager:
    """
    Deep Agent의 작업 공간 및 메모리 관리자
    
    역할:
    1. 세션별 작업 공간 생성
    2. 중간 결과 저장 (연구원 분석 결과)
    3. 컨텍스트 로드 (에이전트 간 공유)
    4. 최종 리포트 저장
    """
    
    def __init__(self, base_path: str = "data/workspace"):
        """
        Args:
            base_path: 작업 공간 루트 경로
        """
        self.base_path = Path(base_path)
        self.session_id = self._generate_session_id()
        self.session_path = self.base_path / self.session_id
        
        # 세션 디렉토리 생성
        self._create_session_workspace()
    
    def _generate_session_id(self) -> str:
        """고유 세션 ID 생성"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        unique_id = str(uuid.uuid4())[:8]
        return f"review_{timestamp}_{unique_id}"
    
    def _create_session_workspace(self):
        """세션 작업 공간 생성"""
        # 디렉토리 구조
        dirs = [
            self.session_path,
            self.session_path / "analyses",      # 연구원 분석 결과
            self.session_path / "validations",   # 지도교수 검증 결과
            self.session_path / "verifications", # 사실 검증 결과
            self.session_path / "plans",         # Todo 계획
            self.session_path / "reports",       # 최종 리포트
            self.session_path / "logs",          # 로그
        ]
        
        for dir_path in dirs:
            dir_path.mkdir(parents=True, exist_ok=True)
        
        # 세션 메타데이터 저장
        metadata = {
            "session_id": self.session_id,
            "created_at": datetime.now().isoformat(),
            "status": "initialized"
        }
        self.save_metadata(metadata)
    
    @staticmethod
    def _sanitize_id(identifier: str) -> str:
        """Sanitize identifier to prevent path traversal."""
        sanitized = re.sub(r'[^a-zA-Z0-9_\-]', '_', str(identifier))
        if not sanitized:
            sanitized = "unknown"
        return sanitized

    def _validate_path(self, path: Path) -> Path:
        """Ensure path is within workspace."""
        resolved = path.resolve()
        if not str(resolved).startswith(str(self.base_path.resolve())):
            raise ValueError(f"Path traversal detected: {path}")
        return resolved

    # ==================== Paper Management ====================
    
    def save_selected_papers(self, papers: List[Dict[str, Any]]) -> str:
        """
        선택된 논문 정보 저장
        
        Args:
            papers: 논문 정보 리스트
            
        Returns:
            저장된 파일 경로
        """
        file_path = self.session_path / "selected_papers.json"
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump({
                "papers": papers,
                "count": len(papers),
                "saved_at": datetime.now().isoformat()
            }, f, indent=2, ensure_ascii=False)
        
        return str(file_path)
    
    def load_selected_papers(self) -> List[Dict[str, Any]]:
        """선택된 논문 로드"""
        file_path = self.session_path / "selected_papers.json"
        
        if not file_path.exists():
            return []
        
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("papers", [])
    
    # ==================== Analysis Results ====================
    
    def save_researcher_analysis(
        self,
        researcher_id: str,
        paper_id: str,
        analysis: Dict[str, Any]
    ) -> str:
        """
        연구원의 논문 분석 결과 저장

        Args:
            researcher_id: 연구원 ID
            paper_id: 논문 ID
            analysis: 분석 결과

        Returns:
            저장된 파일 경로
        """
        safe_researcher_id = self._sanitize_id(researcher_id)
        safe_paper_id = self._sanitize_id(paper_id)
        file_name = f"{safe_researcher_id}_paper_{safe_paper_id}.json"
        file_path = self._validate_path(self.session_path / "analyses" / file_name)

        result = {
            "researcher_id": researcher_id,
            "paper_id": paper_id,
            "analysis": analysis,
            "analyzed_at": datetime.now().isoformat()
        }

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        return str(file_path)
    
    def load_researcher_analysis(
        self,
        researcher_id: str,
        paper_id: str
    ) -> Optional[Dict[str, Any]]:
        """특정 연구원의 분석 결과 로드"""
        safe_researcher_id = self._sanitize_id(researcher_id)
        safe_paper_id = self._sanitize_id(paper_id)
        file_name = f"{safe_researcher_id}_paper_{safe_paper_id}.json"
        file_path = self._validate_path(self.session_path / "analyses" / file_name)

        if not file_path.exists():
            return None

        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def load_all_analyses(self) -> List[Dict[str, Any]]:
        """모든 연구원의 분석 결과 로드"""
        analyses_dir = self.session_path / "analyses"
        analyses = []
        
        for file_path in analyses_dir.glob("*.json"):
            with open(file_path, 'r', encoding='utf-8') as f:
                analyses.append(json.load(f))
        
        return analyses
    
    # ==================== Validation Results ====================
    
    def save_advisor_validation(
        self, 
        validation: Dict[str, Any]
    ) -> str:
        """
        지도교수의 검증 결과 저장
        
        Args:
            validation: 검증 결과
            
        Returns:
            저장된 파일 경로
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"validation_{timestamp}.json"
        file_path = self.session_path / "validations" / file_name
        
        result = {
            "validation": validation,
            "validated_at": datetime.now().isoformat()
        }
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)
        
        return str(file_path)
    
    def load_latest_validation(self) -> Optional[Dict[str, Any]]:
        """최신 검증 결과 로드"""
        validations_dir = self.session_path / "validations"
        
        validation_files = sorted(
            validations_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        
        if not validation_files:
            return None
        
        with open(validation_files[0], 'r', encoding='utf-8') as f:
            return json.load(f)
    
    # ==================== Fact Verification ====================

    def save_verification_claims(
        self,
        claims: List[Dict[str, Any]]
    ) -> str:
        """
        사실 검증 주장(Claims) 저장

        Args:
            claims: Claim 데이터 리스트 (to_dict() 변환 후)

        Returns:
            저장된 파일 경로
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"claims_{timestamp}.json"
        file_path = self.session_path / "verifications" / file_name

        result = {
            "claims": claims,
            "count": len(claims),
            "saved_at": datetime.now().isoformat()
        }

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        return str(file_path)

    def load_verification_claims(self) -> Optional[List[Dict[str, Any]]]:
        """최신 검증 주장 로드"""
        verifications_dir = self.session_path / "verifications"

        claim_files = sorted(
            verifications_dir.glob("claims_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        if not claim_files:
            return None

        with open(claim_files[0], 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("claims", [])

    # ==================== Cross-Reference ====================

    def save_cross_references(
        self,
        cross_refs: List[Dict[str, Any]],
        consensus: Optional[List[Dict[str, Any]]] = None,
    ) -> str:
        """
        교차 검증 결과 저장

        Args:
            cross_refs: CrossReference 데이터 리스트 (to_dict() 변환 후)
            consensus: ConsensusReport 데이터 리스트 (선택)

        Returns:
            저장된 파일 경로
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"crossrefs_{timestamp}.json"
        file_path = self.session_path / "verifications" / file_name

        result = {
            "cross_references": cross_refs,
            "consensus": consensus or [],
            "count": len(cross_refs),
            "saved_at": datetime.now().isoformat(),
        }

        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(result, f, indent=2, ensure_ascii=False)

        return str(file_path)

    def load_cross_references(self) -> Optional[Dict[str, Any]]:
        """최신 교차 검증 결과 로드"""
        verifications_dir = self.session_path / "verifications"

        xref_files = sorted(
            verifications_dir.glob("crossrefs_*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )

        if not xref_files:
            return None

        with open(xref_files[0], 'r', encoding='utf-8') as f:
            return json.load(f)

    # ==================== Plans & Todos ====================
    
    def save_plan(self, plan: Dict[str, Any]) -> str:
        """작업 계획 저장"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_name = f"plan_{timestamp}.json"
        file_path = self.session_path / "plans" / file_name
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(plan, f, indent=2, ensure_ascii=False)
        
        return str(file_path)
    
    def load_latest_plan(self) -> Optional[Dict[str, Any]]:
        """최신 계획 로드"""
        plans_dir = self.session_path / "plans"
        
        plan_files = sorted(
            plans_dir.glob("*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )
        
        if not plan_files:
            return None
        
        with open(plan_files[0], 'r', encoding='utf-8') as f:
            return json.load(f)
    
    # ==================== Final Report ====================
    
    def save_final_report(
        self, 
        report: str, 
        format: str = "markdown"
    ) -> str:
        """
        최종 리뷰 리포트 저장
        
        Args:
            report: 리포트 내용
            format: 파일 형식 (markdown, html, pdf)
            
        Returns:
            저장된 파일 경로
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        extensions = {
            "markdown": "md",
            "html": "html",
            "pdf": "pdf",
            "json": "json"
        }
        
        ext = extensions.get(format, "txt")
        file_name = f"final_review_{timestamp}.{ext}"
        file_path = self.session_path / "reports" / file_name
        
        # JSON인 경우 구조화된 데이터로 저장
        if format == "json" and isinstance(report, dict):
            with open(file_path, 'w', encoding='utf-8') as f:
                json.dump(report, f, indent=2, ensure_ascii=False)
        else:
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(report)
        
        return str(file_path)
    
    # ==================== Metadata ====================
    
    def save_metadata(self, metadata: Dict[str, Any]):
        """세션 메타데이터 저장"""
        file_path = self.session_path / "metadata.json"
        
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)
    
    def load_metadata(self) -> Dict[str, Any]:
        """세션 메타데이터 로드"""
        file_path = self.session_path / "metadata.json"
        
        if not file_path.exists():
            return {}
        
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    
    def update_status(self, status: str):
        """세션 상태 업데이트"""
        metadata = self.load_metadata()
        metadata["status"] = status
        metadata["updated_at"] = datetime.now().isoformat()
        self.save_metadata(metadata)
    
    # ==================== Logs ====================
    
    def log(self, message: str, level: str = "INFO"):
        """작업 로그 저장"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_entry = f"[{timestamp}] [{level}] {message}\n"
        
        log_file = self.session_path / "logs" / "session.log"
        
        with open(log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    
    # ==================== Cleanup ====================
    
    def get_session_summary(self) -> Dict[str, Any]:
        """세션 요약 정보"""
        metadata = self.load_metadata()
        analyses = self.load_all_analyses()
        
        return {
            "session_id": self.session_id,
            "session_path": str(self.session_path),
            "status": metadata.get("status", "unknown"),
            "created_at": metadata.get("created_at"),
            "paper_count": len(self.load_selected_papers()),
            "analysis_count": len(analyses),
            "has_validation": self.load_latest_validation() is not None,
            "has_verification": self.load_verification_claims() is not None,
            "has_cross_references": self.load_cross_references() is not None,
            "has_final_report": len(list((self.session_path / "reports").glob("*.md"))) > 0
        }
    
    def __repr__(self) -> str:
        return f"<WorkspaceManager session={self.session_id}>"

