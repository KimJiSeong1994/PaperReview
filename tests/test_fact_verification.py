"""
Fact Verification 단위 테스트

LLM 호출 없이 데이터 모델, 리포트 파싱, 프롬프트 생성, EvidenceLinker 등을 검증한다.
"""
import sys
from pathlib import Path

import pytest

# Ensure project root is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.DeepAgent.tools.fact_verification import (
    Claim,
    ClaimEvidence,
    ClaimExtractor,
    ClaimType,
    Evidence,
    EvidenceLinker,
    CrossRefValidator,
    CrossReference,
    ConsensusReport,
    ClaimRelation,
    ConsensusLevel,
    MatchType,
    VerificationResult,
    VerificationStatus,
    CLAIM_TYPE_CONFIDENCE,
    SECTION_KEYWORDS,
)


# ==================== Fixtures ====================

SAMPLE_REPORT = """# Comprehensive Literature Review and Analysis Report

**Review Date**: February 17, 2026
**Number of Papers Analyzed**: 2

====================================================================================================

## Executive Summary

This comprehensive literature review provides an in-depth analysis of 2 papers.

## Research Landscape Overview

### Temporal Distribution
- **2024**: 2 paper(s)

====================================================================================================

## Detailed Paper-by-Paper Analysis

----------------------------------------------------------------------------------------------------

### Paper 1: Attention Is All You Need

**Citation**: Vaswani, et al. (2024). *Attention Is All You Need*. NeurIPS.
**arXiv**: 1706.03762

#### Abstract Summary
We propose a new simple network architecture, the Transformer.

#### Methodology & Technical Approach
**Primary Methods Employed:**
- **Deep Learning**: The paper employs deep neural network architectures

#### Key Contributions
The paper makes the following significant contributions to the field:

**1.** Proposes the Transformer architecture based entirely on attention mechanisms

**2.** Achieves 28.4 BLEU on the WMT 2014 English-to-German translation task

**3.** Demonstrates that self-attention can replace recurrence and convolutions

#### Experimental Results & Evaluation
The paper presents comprehensive experimental validation, including:
- Rigorous comparison with state-of-the-art baselines
- Ablation studies to validate design choices

#### Critical Analysis
**Strengths:**
- Comprehensive analysis coverage
**Limitations & Areas for Future Research:**
- Extending to additional domains or datasets

#### Reproducibility Assessment
**Reproducibility Score**: 4.2/5.0
- Code Availability: Provided
- Dataset Access: Public

----------------------------------------------------------------------------------------------------

### Paper 2: BERT: Pre-training of Deep Bidirectional Transformers

**Citation**: Devlin, et al. (2024). *BERT*. ACL.

#### Abstract Summary
We introduce BERT, a new language representation model.

#### Methodology & Technical Approach
**Primary Methods Employed:**
- **Nlp**: Natural language processing methods are applied

#### Key Contributions
**1.** Introduces bidirectional pre-training for language representations

**2.** Achieves state-of-the-art results on 11 NLP benchmarks

#### Experimental Results & Evaluation
The paper achieves 93.2% accuracy on SQuAD v2.0, outperforming previous models by 3.2%.

#### Reproducibility Assessment
**Reproducibility Score**: 3.8/5.0
- Code Availability: Provided
- Dataset Access: Public

====================================================================================================

## Cross-Paper Synthesis & Comparative Analysis

### Thematic Connections
Both papers advance the state of the art in NLP.
"""


def _make_claim(
    claim_id: str = "claim_001",
    text: str = "achieves 93.2% accuracy",
    claim_type: ClaimType = ClaimType.STATISTICAL,
    paper_id: str = "paper_1",
    section: str = "Paper 1",
) -> Claim:
    return Claim(
        id=claim_id,
        text=text,
        claim_type=claim_type,
        source_paper_id=paper_id,
        report_section=section,
        confidence_required=CLAIM_TYPE_CONFIDENCE.get(claim_type, 0.7),
    )


def _make_evidence(
    evidence_id: str = "ev_001",
    claim_id: str = "claim_001",
    paper_id: str = "paper_1",
    text: str = "Our model achieves 93.2% accuracy on SQuAD.",
    match_type: MatchType = MatchType.DIRECT_QUOTE,
    similarity: float = 0.95,
    status: VerificationStatus = VerificationStatus.VERIFIED,
) -> Evidence:
    return Evidence(
        id=evidence_id,
        claim_id=claim_id,
        paper_id=paper_id,
        text=text,
        chunk_id="chunk_12",
        chunk_index=12,
        estimated_section="Results",
        match_type=match_type,
        similarity_score=similarity,
        verification_status=status,
    )


# ==================== Claim Tests ====================

class TestClaimSerialization:
    def test_claim_to_dict(self):
        claim = _make_claim()
        d = claim.to_dict()

        assert d["id"] == "claim_001"
        assert d["text"] == "achieves 93.2% accuracy"
        assert d["claim_type"] == "statistical"
        assert d["source_paper_id"] == "paper_1"
        assert d["confidence_required"] == 0.9

    def test_claim_from_dict(self):
        original = _make_claim()
        restored = Claim.from_dict(original.to_dict())

        assert restored.id == original.id
        assert restored.text == original.text
        assert restored.claim_type == original.claim_type
        assert restored.source_paper_id == original.source_paper_id
        assert restored.confidence_required == original.confidence_required

    def test_claim_roundtrip(self):
        for ct in ClaimType:
            claim = _make_claim(claim_type=ct)
            restored = Claim.from_dict(claim.to_dict())
            assert restored.claim_type == ct


# ==================== Evidence Tests ====================

class TestEvidenceSerialization:
    def test_evidence_to_dict(self):
        ev = _make_evidence()
        d = ev.to_dict()

        assert d["id"] == "ev_001"
        assert d["claim_id"] == "claim_001"
        assert d["match_type"] == "direct_quote"
        assert d["similarity_score"] == 0.95
        assert d["verification_status"] == "verified"
        assert d["chunk_id"] == "chunk_12"
        assert d["estimated_section"] == "Results"

    def test_evidence_from_dict(self):
        original = _make_evidence()
        restored = Evidence.from_dict(original.to_dict())

        assert restored.id == original.id
        assert restored.match_type == original.match_type
        assert restored.verification_status == original.verification_status
        assert restored.similarity_score == original.similarity_score

    def test_evidence_defaults(self):
        ev = Evidence(id="ev", claim_id="c", paper_id="p", text="t")
        assert ev.match_type == MatchType.NOT_FOUND
        assert ev.verification_status == VerificationStatus.UNVERIFIED
        assert ev.similarity_score == 0.0
        assert ev.chunk_index == -1


# ==================== ClaimEvidence Tests ====================

class TestClaimEvidence:
    def test_best_evidence_returns_highest_similarity(self):
        claim = _make_claim()
        ev1 = _make_evidence(evidence_id="ev_1", similarity=0.7)
        ev2 = _make_evidence(evidence_id="ev_2", similarity=0.95)
        ev3 = _make_evidence(evidence_id="ev_3", similarity=0.8)

        ce = ClaimEvidence(claim=claim, evidences=[ev1, ev2, ev3])
        best = ce.best_evidence()

        assert best is not None
        assert best.id == "ev_2"
        assert best.similarity_score == 0.95

    def test_best_evidence_empty(self):
        claim = _make_claim()
        ce = ClaimEvidence(claim=claim, evidences=[])
        assert ce.best_evidence() is None

    def test_roundtrip(self):
        claim = _make_claim()
        ev = _make_evidence()
        ce = ClaimEvidence(claim=claim, evidences=[ev])

        restored = ClaimEvidence.from_dict(ce.to_dict())
        assert restored.claim.id == claim.id
        assert len(restored.evidences) == 1
        assert restored.evidences[0].id == ev.id


# ==================== VerificationResult Tests ====================

class TestVerificationResult:
    def test_statistics_basic(self):
        claims = [
            _make_claim("c1", claim_type=ClaimType.STATISTICAL),
            _make_claim("c2", claim_type=ClaimType.METHODOLOGICAL),
            _make_claim("c3", claim_type=ClaimType.INTERPRETIVE),
        ]

        ce1 = ClaimEvidence(
            claim=claims[0],
            evidences=[_make_evidence("e1", "c1", status=VerificationStatus.VERIFIED)],
        )
        ce2 = ClaimEvidence(
            claim=claims[1],
            evidences=[_make_evidence("e2", "c2", status=VerificationStatus.UNVERIFIED)],
        )

        result = VerificationResult(claims=claims, claim_evidences=[ce1, ce2])
        stats = result.statistics

        assert stats["total_claims"] == 3
        assert stats["verifiable_claims"] == 2
        assert stats["interpretive_claims"] == 1
        assert stats["verified"] == 1
        assert stats["unverified"] == 1
        assert stats["verification_rate"] == 0.5

    def test_statistics_all_verified(self):
        claims = [
            _make_claim("c1", claim_type=ClaimType.FACTUAL),
            _make_claim("c2", claim_type=ClaimType.FACTUAL),
        ]
        ces = [
            ClaimEvidence(
                claim=c,
                evidences=[_make_evidence(f"e{i}", c.id, status=VerificationStatus.VERIFIED)],
            )
            for i, c in enumerate(claims)
        ]

        result = VerificationResult(claims=claims, claim_evidences=ces)
        assert result.statistics["verification_rate"] == 1.0

    def test_statistics_empty(self):
        result = VerificationResult()
        stats = result.statistics
        assert stats["total_claims"] == 0
        assert stats["verifiable_claims"] == 0
        assert stats["verification_rate"] == 0.0

    def test_by_type_counts(self):
        claims = [
            _make_claim("c1", claim_type=ClaimType.STATISTICAL),
            _make_claim("c2", claim_type=ClaimType.STATISTICAL),
            _make_claim("c3", claim_type=ClaimType.COMPARATIVE),
        ]
        result = VerificationResult(claims=claims)
        by_type = result.statistics["by_type"]

        assert by_type["statistical"] == 2
        assert by_type["comparative"] == 1
        assert by_type["methodological"] == 0

    def test_roundtrip(self):
        claim = _make_claim()
        ev = _make_evidence()
        ce = ClaimEvidence(claim=claim, evidences=[ev])
        result = VerificationResult(claims=[claim], claim_evidences=[ce])

        restored = VerificationResult.from_dict(result.to_dict())
        assert restored.total_claims == 1
        assert len(restored.claim_evidences) == 1
        assert restored.claim_evidences[0].claim.id == claim.id


# ==================== ClaimExtractor Tests ====================

class TestParseReportSections:
    def setup_method(self):
        self.extractor = ClaimExtractor.__new__(ClaimExtractor)
        self.extractor.model = "gpt-4o-mini"
        self.extractor.client = None
        self.extractor.api_key = None

    def test_parses_two_papers(self):
        sections = self.extractor._parse_report_sections(SAMPLE_REPORT)

        assert len(sections) == 2
        assert sections[0]["paper_index"] == 0
        assert sections[0]["paper_title"] == "Attention Is All You Need"
        assert sections[1]["paper_index"] == 1
        assert "BERT" in sections[1]["paper_title"]

    def test_section_text_not_empty(self):
        sections = self.extractor._parse_report_sections(SAMPLE_REPORT)

        for section in sections:
            assert len(section["text"]) > 0

    def test_excludes_cross_paper_section(self):
        sections = self.extractor._parse_report_sections(SAMPLE_REPORT)

        for section in sections:
            assert "Cross-Paper Synthesis" not in section["text"]

    def test_section_name_format(self):
        sections = self.extractor._parse_report_sections(SAMPLE_REPORT)

        assert sections[0]["section_name"] == "Paper 1"
        assert sections[1]["section_name"] == "Paper 2"

    def test_empty_report(self):
        sections = self.extractor._parse_report_sections("")
        assert sections == []

    def test_report_without_papers(self):
        report = "# Report\n\nNo papers analyzed.\n"
        sections = self.extractor._parse_report_sections(report)
        assert sections == []


class TestBuildExtractionPrompt:
    def setup_method(self):
        self.extractor = ClaimExtractor.__new__(ClaimExtractor)
        self.extractor.model = "gpt-4o-mini"
        self.extractor.client = None
        self.extractor.api_key = None

    def test_includes_paper_title(self):
        prompt = self.extractor._build_extraction_prompt(
            "Some review text.", "My Paper Title"
        )
        assert "My Paper Title" in prompt

    def test_includes_section_text(self):
        prompt = self.extractor._build_extraction_prompt(
            "The model achieves 95% accuracy.", "Paper A"
        )
        assert "95% accuracy" in prompt

    def test_truncates_long_sections(self):
        long_text = "A" * 10000
        prompt = self.extractor._build_extraction_prompt(long_text, "Paper B")
        assert "[truncated]" in prompt
        assert len(prompt) < 10000

    def test_includes_json_format_instruction(self):
        prompt = self.extractor._build_extraction_prompt("text", "title")
        assert '"claims"' in prompt
        assert '"type"' in prompt


class TestClaimTypeConfidence:
    def test_statistical_highest(self):
        assert CLAIM_TYPE_CONFIDENCE[ClaimType.STATISTICAL] == 0.9

    def test_interpretive_zero(self):
        assert CLAIM_TYPE_CONFIDENCE[ClaimType.INTERPRETIVE] == 0.0

    def test_all_types_covered(self):
        for ct in ClaimType:
            assert ct in CLAIM_TYPE_CONFIDENCE


class TestHeuristicExtraction:
    def setup_method(self):
        self.extractor = ClaimExtractor.__new__(ClaimExtractor)
        self.extractor.model = "gpt-4o-mini"
        self.extractor.client = None
        self.extractor.api_key = None

    def test_extracts_statistical_claims(self):
        text = "The model achieves 93.2% accuracy on the benchmark. It also scores 0.85 F1."
        claims = self.extractor._extract_claims_heuristic(text, "paper_1", "Results")

        stat_claims = [c for c in claims if c.claim_type == ClaimType.STATISTICAL]
        assert len(stat_claims) >= 1

    def test_extracts_comparative_claims(self):
        text = "Our approach outperforms BERT by a significant margin on all tasks."
        claims = self.extractor._extract_claims_heuristic(text, "paper_1", "Results")

        comp_claims = [c for c in claims if c.claim_type == ClaimType.COMPARATIVE]
        assert len(comp_claims) >= 1

    def test_unique_ids(self):
        text = "Model A achieves 90% accuracy. Model B achieves 95% accuracy."
        claims = self.extractor._extract_claims_heuristic(text, "p1", "Results")

        ids = [c.id for c in claims]
        assert len(ids) == len(set(ids))


# ==================== EvidenceLinker Tests ====================

SAMPLE_PAPER = {
    "title": "Attention Is All You Need",
    "arxiv_id": "1706.03762",
    "authors": ["Vaswani", "Shazeer"],
    "year": 2017,
    "abstract": "We propose a new simple network architecture, the Transformer, "
                "based solely on attention mechanisms.",
    "full_text": (
        "Abstract. We propose a new simple network architecture, the Transformer, "
        "based solely on attention mechanisms, dispensing with recurrence and convolutions entirely. "
        "Experiments on two machine translation tasks show these models to be superior in quality. "
        "1 Introduction. The dominant sequence transduction models are based on complex recurrent "
        "or convolutional neural networks. We propose the Transformer, a model architecture eschewing "
        "recurrence and instead relying entirely on an attention mechanism. "
        "3 Model Architecture. The Transformer follows an encoder-decoder structure using stacked "
        "self-attention and point-wise fully connected layers. "
        "4 Experiments. On the WMT 2014 English-to-German translation task, the big transformer model "
        "outperforms the best previously reported models including ensembles by more than 2.0 BLEU, "
        "establishing a new state-of-the-art BLEU score of 28.4. "
        "On the WMT 2014 English-to-French translation task, our model achieves 41.0 BLEU, "
        "outperforming all of the previously published single models. "
        "5 Conclusion. In this work, we presented the Transformer, the first sequence transduction "
        "model based entirely on attention. We plan to extend the Transformer to other tasks."
    ),
}


def _make_linker() -> EvidenceLinker:
    """LLM 없이 동작하는 EvidenceLinker 인스턴스 생성"""
    linker = EvidenceLinker.__new__(EvidenceLinker)
    linker.model = "gpt-4o-mini"
    linker.client = None
    linker.api_key = None
    return linker


class TestEvidenceLinkerChunking:
    def setup_method(self):
        self.linker = _make_linker()

    def test_chunk_paper_text_basic(self):
        chunks = self.linker._chunk_paper_text(SAMPLE_PAPER)
        assert len(chunks) > 0
        for chunk in chunks:
            assert "text" in chunk
            assert "paper_id" in chunk
            assert "chunk_index" in chunk
            assert "chunk_id" in chunk
            assert len(chunk["text"]) > 0

    def test_chunk_indices_sequential(self):
        chunks = self.linker._chunk_paper_text(SAMPLE_PAPER)
        for i, chunk in enumerate(chunks):
            assert chunk["chunk_index"] == i

    def test_chunk_paper_no_text(self):
        paper = {"title": "Empty", "abstract": "", "full_text": ""}
        chunks = self.linker._chunk_paper_text(paper)
        assert chunks == []

    def test_chunk_uses_abstract_fallback(self):
        paper = {"title": "Abstract Only", "abstract": "This is the abstract text."}
        chunks = self.linker._chunk_paper_text(paper)
        assert len(chunks) == 1
        assert "abstract text" in chunks[0]["text"]

    def test_get_paper_chunks_standalone(self):
        chunks = self.linker._get_paper_chunks(SAMPLE_PAPER, kg_storage=None)
        assert len(chunks) > 0


class TestEvidenceLinkerExactMatch:
    def setup_method(self):
        self.linker = _make_linker()
        self.chunks = self.linker._chunk_paper_text(SAMPLE_PAPER)

    def test_exact_match_number(self):
        claim = _make_claim(
            text="achieves a BLEU score of 28.4",
            claim_type=ClaimType.STATISTICAL,
            paper_id="1706.03762",
        )
        evidences = self.linker._exact_match(claim, self.chunks, SAMPLE_PAPER)

        assert len(evidences) >= 1
        assert evidences[0].verification_status == VerificationStatus.VERIFIED
        assert evidences[0].match_type == MatchType.DIRECT_QUOTE
        assert evidences[0].similarity_score == 1.0

    def test_exact_match_multiple_numbers(self):
        claim = _make_claim(
            text="achieves 41.0 BLEU on English-to-French",
            claim_type=ClaimType.STATISTICAL,
            paper_id="1706.03762",
        )
        evidences = self.linker._exact_match(claim, self.chunks, SAMPLE_PAPER)
        assert len(evidences) >= 1

    def test_exact_match_no_numbers(self):
        claim = _make_claim(
            text="proposes the Transformer architecture",
            claim_type=ClaimType.METHODOLOGICAL,
            paper_id="1706.03762",
        )
        evidences = self.linker._exact_match(claim, self.chunks, SAMPLE_PAPER)
        assert evidences == []

    def test_exact_match_wrong_number(self):
        claim = _make_claim(
            text="achieves 99.9% accuracy",
            claim_type=ClaimType.STATISTICAL,
            paper_id="1706.03762",
        )
        evidences = self.linker._exact_match(claim, self.chunks, SAMPLE_PAPER)
        assert evidences == []


class TestEvidenceLinkerSectionEstimation:
    def test_abstract_detection(self):
        text = "In this paper, we propose a novel approach to the problem."
        section = EvidenceLinker._estimate_section(text)
        assert section == "Abstract"

    def test_experiment_detection(self):
        text = "The accuracy on the benchmark dataset is 95%. Ablation results confirm."
        section = EvidenceLinker._estimate_section(text)
        assert section == "Experiments"

    def test_method_detection(self):
        text = "Our proposed architecture consists of an encoder-decoder framework."
        section = EvidenceLinker._estimate_section(text)
        assert section == "Method"

    def test_conclusion_detection(self):
        text = "In conclusion, we have shown that our contribution advances the state of the art."
        section = EvidenceLinker._estimate_section(text)
        assert section == "Conclusion"

    def test_unknown_text(self):
        text = "xyzzy foobar."
        section = EvidenceLinker._estimate_section(text)
        assert section == "Unknown"


class TestEvidenceLinkerPaperIdMatching:
    def test_exact_match(self):
        assert EvidenceLinker._paper_id_matches("paper_a", "paper_a") is True

    def test_substring_match(self):
        assert EvidenceLinker._paper_id_matches("attention", "attention_is_all_you_need") is True

    def test_reverse_substring(self):
        assert EvidenceLinker._paper_id_matches("attention_is_all_you_need", "attention") is True

    def test_no_match(self):
        assert EvidenceLinker._paper_id_matches("paper_a", "paper_b") is False

    def test_empty_ids(self):
        assert EvidenceLinker._paper_id_matches("", "paper_a") is False
        assert EvidenceLinker._paper_id_matches("paper_a", "") is False

    def test_case_insensitive(self):
        assert EvidenceLinker._paper_id_matches("Paper_A", "paper_a") is True

    def test_short_substring_rejected(self):
        # IDs shorter than 4 chars should not match as substring
        assert EvidenceLinker._paper_id_matches("ab", "xyzab") is False
        assert EvidenceLinker._paper_id_matches("abc", "xyzabc") is False

    def test_four_char_substring_accepted(self):
        assert EvidenceLinker._paper_id_matches("bert", "bert_large_model") is True


class TestEvidenceLinkerHeuristicVerify:
    def setup_method(self):
        self.linker = _make_linker()

    def _make_ev(self, score: float) -> Evidence:
        return Evidence(
            id="ev_test",
            claim_id="c_test",
            paper_id="p_test",
            text="some evidence",
            similarity_score=score,
        )

    def test_high_score_verified(self):
        claim = _make_claim()
        ev = self.linker._heuristic_verify(claim, self._make_ev(0.9))
        assert ev.verification_status == VerificationStatus.VERIFIED
        assert ev.match_type == MatchType.DIRECT_QUOTE

    def test_medium_score_partially(self):
        claim = _make_claim()
        ev = self.linker._heuristic_verify(claim, self._make_ev(0.75))
        assert ev.verification_status == VerificationStatus.PARTIALLY_VERIFIED
        assert ev.match_type == MatchType.PARAPHRASE

    def test_low_medium_inferred(self):
        claim = _make_claim()
        ev = self.linker._heuristic_verify(claim, self._make_ev(0.55))
        assert ev.verification_status == VerificationStatus.PARTIALLY_VERIFIED
        assert ev.match_type == MatchType.INFERRED

    def test_low_score_unverified(self):
        claim = _make_claim()
        ev = self.linker._heuristic_verify(claim, self._make_ev(0.3))
        assert ev.verification_status == VerificationStatus.UNVERIFIED
        assert ev.match_type == MatchType.NOT_FOUND


class TestEvidenceLinkerGetPaperIdVariants:
    def setup_method(self):
        self.linker = _make_linker()

    def test_with_arxiv_id(self):
        variants = self.linker._get_paper_id_variants(SAMPLE_PAPER)
        assert "1706.03762" in variants

    def test_with_title(self):
        variants = self.linker._get_paper_id_variants(SAMPLE_PAPER)
        title_id = "attention_is_all_you_need"
        assert title_id in variants

    def test_empty_paper(self):
        variants = self.linker._get_paper_id_variants({})
        assert len(variants) == 0


# ==================== Phase C: CrossRefValidator Tests ====================

# ─── Data Model Serialization ───

class TestCrossReferenceSerialization:
    def test_to_dict(self):
        claim_a = _make_claim("ca", text="Transformer uses attention", paper_id="paper_1")
        claim_b = _make_claim("cb", text="BERT uses bidirectional attention", paper_id="paper_2")
        xref = CrossReference(
            id="xref_001",
            claim_a=claim_a,
            claim_b=claim_b,
            relation=ClaimRelation.SUPPORTS,
            topic="attention mechanism",
            explanation="Both discuss attention.",
            confidence=0.8,
        )
        d = xref.to_dict()

        assert d["id"] == "xref_001"
        assert d["relation"] == "supports"
        assert d["topic"] == "attention mechanism"
        assert d["confidence"] == 0.8
        assert d["claim_a"]["id"] == "ca"
        assert d["claim_b"]["id"] == "cb"

    def test_from_dict(self):
        claim_a = _make_claim("ca", paper_id="p1")
        claim_b = _make_claim("cb", paper_id="p2")
        original = CrossReference(
            id="xref_002",
            claim_a=claim_a,
            claim_b=claim_b,
            relation=ClaimRelation.CONTRADICTS,
            topic="performance",
            explanation="Conflicting results.",
            confidence=0.7,
        )
        restored = CrossReference.from_dict(original.to_dict())

        assert restored.id == original.id
        assert restored.relation == ClaimRelation.CONTRADICTS
        assert restored.topic == "performance"
        assert restored.claim_a.id == "ca"
        assert restored.claim_b.id == "cb"

    def test_roundtrip_all_relations(self):
        for rel in ClaimRelation:
            xref = CrossReference(
                id=f"xref_{rel.value}",
                claim_a=_make_claim("a", paper_id="p1"),
                claim_b=_make_claim("b", paper_id="p2"),
                relation=rel,
            )
            restored = CrossReference.from_dict(xref.to_dict())
            assert restored.relation == rel


class TestConsensusReportSerialization:
    def test_to_dict(self):
        claims = [
            _make_claim("c1", paper_id="p1"),
            _make_claim("c2", paper_id="p2"),
        ]
        xref = CrossReference(
            id="xr1",
            claim_a=claims[0],
            claim_b=claims[1],
            relation=ClaimRelation.SUPPORTS,
        )
        report = ConsensusReport(
            topic="transformer",
            claims=claims,
            cross_references=[xref],
            consensus_level=ConsensusLevel.STRONG,
            supporting_count=1,
            contradicting_count=0,
            summary="Strong agreement.",
        )
        d = report.to_dict()

        assert d["topic"] == "transformer"
        assert d["consensus_level"] == "strong"
        assert d["supporting_count"] == 1
        assert d["contradicting_count"] == 0
        assert len(d["claims"]) == 2
        assert len(d["cross_references"]) == 1

    def test_from_dict(self):
        original = ConsensusReport(
            topic="data",
            consensus_level=ConsensusLevel.DIVIDED,
            supporting_count=1,
            contradicting_count=3,
            summary="Divided findings.",
        )
        restored = ConsensusReport.from_dict(original.to_dict())

        assert restored.topic == "data"
        assert restored.consensus_level == ConsensusLevel.DIVIDED
        assert restored.supporting_count == 1
        assert restored.contradicting_count == 3

    def test_roundtrip_all_levels(self):
        for level in ConsensusLevel:
            report = ConsensusReport(
                topic="test",
                consensus_level=level,
            )
            restored = ConsensusReport.from_dict(report.to_dict())
            assert restored.consensus_level == level


# ─── CrossRefValidator Helper: make validator without LLM ───

def _make_validator() -> CrossRefValidator:
    """LLM 없이 동작하는 CrossRefValidator 인스턴스 생성"""
    validator = CrossRefValidator.__new__(CrossRefValidator)
    validator.model = "gpt-4o-mini"
    validator.client = None
    validator.api_key = None
    return validator


# ─── Topic Grouping ───

class TestTopicGrouping:
    def setup_method(self):
        self.validator = _make_validator()

    def test_keyword_grouping_basic(self):
        claims = [
            _make_claim("c1", text="The transformer model uses multi-head attention", paper_id="p1"),
            _make_claim("c2", text="Attention mechanism improves translation quality", paper_id="p2"),
            _make_claim("c3", text="The dataset contains 1M training examples", paper_id="p1"),
        ]
        groups = self.validator._group_by_keywords(claims)

        # "attention mechanism" 토픽에 c1, c2가 있어야 함
        assert "attention mechanism" in groups
        attention_ids = {c.id for c in groups["attention mechanism"]}
        assert "c1" in attention_ids
        assert "c2" in attention_ids

    def test_keyword_grouping_no_match_goes_general(self):
        claims = [
            _make_claim("c1", text="This is a random unrelated statement", paper_id="p1"),
        ]
        groups = self.validator._group_by_keywords(claims)

        assert "General" in groups
        assert len(groups["General"]) == 1

    def test_group_by_topic_fallback_to_keywords(self):
        claims = [
            _make_claim("c1", text="BERT achieves state-of-the-art", paper_id="p1"),
        ]
        # kg_storage=None → keywords fallback
        groups = self.validator._group_by_topic(claims, kg_storage=None)

        assert "bert" in groups
        assert len(groups["bert"]) == 1

    def test_extract_topic_keywords(self):
        text = "The transformer architecture with self-supervised pre-training achieves high accuracy"
        topics = CrossRefValidator._extract_topic_keywords(text)

        assert "transformer" in topics
        assert "self-supervised learning" in topics
        assert "pre-training" in topics
        assert "performance" in topics  # "accuracy" maps to "performance"

    def test_extract_topic_keywords_empty(self):
        topics = CrossRefValidator._extract_topic_keywords("nothing relevant here xyz")
        assert topics == []

    def test_claim_assigned_to_max_two_topics(self):
        claims = [
            _make_claim(
                "c1",
                text="Transformer with attention and convolution and reinforcement and BERT and GPT",
                paper_id="p1",
            ),
        ]
        groups = self.validator._group_by_keywords(claims)

        # 하나의 claim이 최대 2개 토픽에 배정
        claim_topic_count = sum(
            1 for topic_claims in groups.values()
            if any(c.id == "c1" for c in topic_claims)
        )
        assert claim_topic_count <= 2


# ─── Cross-Paper Pair Generation ───

class TestCrossPaperPairs:
    def test_basic_pairs(self):
        claims = [
            _make_claim("c1", paper_id="p1"),
            _make_claim("c2", paper_id="p2"),
            _make_claim("c3", paper_id="p1"),
        ]
        pairs = CrossRefValidator._get_cross_paper_pairs(claims)

        # c1-c2 (다른 논문), c2-c3 (다른 논문) → 2쌍
        # c1-c3 (같은 논문) → 제외
        assert len(pairs) == 2
        for a, b in pairs:
            assert a.source_paper_id != b.source_paper_id

    def test_same_paper_no_pairs(self):
        claims = [
            _make_claim("c1", paper_id="p1"),
            _make_claim("c2", paper_id="p1"),
        ]
        pairs = CrossRefValidator._get_cross_paper_pairs(claims)
        assert pairs == []

    def test_three_papers(self):
        claims = [
            _make_claim("c1", paper_id="p1"),
            _make_claim("c2", paper_id="p2"),
            _make_claim("c3", paper_id="p3"),
        ]
        pairs = CrossRefValidator._get_cross_paper_pairs(claims)
        # C(3,2) = 3, 모두 다른 논문
        assert len(pairs) == 3

    def test_empty_claims(self):
        pairs = CrossRefValidator._get_cross_paper_pairs([])
        assert pairs == []

    def test_single_claim(self):
        pairs = CrossRefValidator._get_cross_paper_pairs([_make_claim("c1")])
        assert pairs == []


# ─── Heuristic Comparison ───

class TestHeuristicComparison:
    def setup_method(self):
        self.validator = _make_validator()

    def test_contradiction_detected(self):
        claim_a = _make_claim("ca", text="Our model outperforms all baselines", paper_id="p1")
        claim_b = _make_claim("cb", text="The baseline model underperforms on this task", paper_id="p2")
        ref = self.validator._compare_claims_heuristic(claim_a, claim_b, "performance")

        assert ref.relation == ClaimRelation.CONTRADICTS
        assert ref.confidence >= 0.5
        assert ref.topic == "performance"

    def test_high_overlap_supports(self):
        claim_a = _make_claim(
            "ca",
            text="The attention mechanism achieves strong results on translation tasks",
            paper_id="p1",
        )
        claim_b = _make_claim(
            "cb",
            text="The attention mechanism shows strong results on machine translation tasks",
            paper_id="p2",
        )
        ref = self.validator._compare_claims_heuristic(claim_a, claim_b, "attention")

        assert ref.relation == ClaimRelation.SUPPORTS
        assert ref.confidence >= 0.4

    def test_low_overlap_independent(self):
        claim_a = _make_claim(
            "ca", text="We use convolutional neural networks for image classification", paper_id="p1"
        )
        claim_b = _make_claim(
            "cb", text="The dataset is publicly available on GitHub", paper_id="p2"
        )
        ref = self.validator._compare_claims_heuristic(claim_a, claim_b, "general")

        assert ref.relation == ClaimRelation.INDEPENDENT

    def test_extends_with_different_numbers(self):
        claim_a = _make_claim(
            "ca",
            text="The model achieves 93.2 accuracy on the benchmark dataset evaluation",
            paper_id="p1",
        )
        claim_b = _make_claim(
            "cb",
            text="Our model achieves 95.1 accuracy on the benchmark dataset evaluation",
            paper_id="p2",
        )
        ref = self.validator._compare_claims_heuristic(claim_a, claim_b, "performance")

        # 높은 overlap + 다른 수치 → EXTENDS
        assert ref.relation == ClaimRelation.EXTENDS

    def test_cross_reference_has_valid_id(self):
        claim_a = _make_claim("ca", paper_id="p1")
        claim_b = _make_claim("cb", paper_id="p2")
        ref = self.validator._compare_claims_heuristic(claim_a, claim_b, "topic")

        assert ref.id.startswith("xref_")
        assert len(ref.id) > 5

    def test_explanation_not_empty(self):
        claim_a = _make_claim("ca", paper_id="p1")
        claim_b = _make_claim("cb", paper_id="p2")
        ref = self.validator._compare_claims_heuristic(claim_a, claim_b, "topic")

        assert len(ref.explanation) > 0


# ─── Consensus Computation ───

class TestConsensusComputation:
    def test_strong_consensus(self):
        claims = [_make_claim("c1", paper_id="p1"), _make_claim("c2", paper_id="p2")]
        refs = [
            CrossReference(
                id="xr1", claim_a=claims[0], claim_b=claims[1],
                relation=ClaimRelation.SUPPORTS, confidence=0.8,
            ),
        ]
        report = CrossRefValidator._compute_consensus("attention", claims, refs)

        assert report.consensus_level == ConsensusLevel.STRONG
        assert report.supporting_count == 1
        assert report.contradicting_count == 0
        assert "Strong consensus" in report.summary

    def test_moderate_consensus(self):
        claims = [
            _make_claim("c1", paper_id="p1"),
            _make_claim("c2", paper_id="p2"),
            _make_claim("c3", paper_id="p3"),
            _make_claim("c4", paper_id="p4"),
        ]
        refs = [
            CrossReference(
                id="xr1", claim_a=claims[0], claim_b=claims[1],
                relation=ClaimRelation.SUPPORTS,
            ),
            CrossReference(
                id="xr2", claim_a=claims[0], claim_b=claims[2],
                relation=ClaimRelation.SUPPORTS,
            ),
            CrossReference(
                id="xr3", claim_a=claims[0], claim_b=claims[3],
                relation=ClaimRelation.SUPPORTS,
            ),
            CrossReference(
                id="xr4", claim_a=claims[1], claim_b=claims[2],
                relation=ClaimRelation.CONTRADICTS,
            ),
        ]
        # 3 supporting, 1 contradicting → supporting > contradicting * 2 (3 > 2) → MODERATE
        report = CrossRefValidator._compute_consensus("perf", claims, refs)

        assert report.consensus_level == ConsensusLevel.MODERATE

    def test_weak_consensus(self):
        claims = [
            _make_claim("c1", paper_id="p1"),
            _make_claim("c2", paper_id="p2"),
            _make_claim("c3", paper_id="p3"),
        ]
        refs = [
            CrossReference(
                id="xr1", claim_a=claims[0], claim_b=claims[1],
                relation=ClaimRelation.SUPPORTS,
            ),
            CrossReference(
                id="xr2", claim_a=claims[0], claim_b=claims[2],
                relation=ClaimRelation.SUPPORTS,
            ),
            CrossReference(
                id="xr3", claim_a=claims[1], claim_b=claims[2],
                relation=ClaimRelation.CONTRADICTS,
            ),
        ]
        # 2 supporting, 1 contradicting → supporting > contradicting (2>1)
        # but NOT supporting > contradicting * 2 (2 !> 2) → WEAK
        report = CrossRefValidator._compute_consensus("topic", claims, refs)

        assert report.consensus_level == ConsensusLevel.WEAK

    def test_divided_consensus(self):
        claims = [_make_claim("c1", paper_id="p1"), _make_claim("c2", paper_id="p2")]
        refs = [
            CrossReference(
                id="xr1", claim_a=claims[0], claim_b=claims[1],
                relation=ClaimRelation.CONTRADICTS,
            ),
            CrossReference(
                id="xr2", claim_a=claims[0], claim_b=claims[1],
                relation=ClaimRelation.CONTRADICTS,
            ),
        ]
        report = CrossRefValidator._compute_consensus("topic", claims, refs)

        assert report.consensus_level == ConsensusLevel.DIVIDED
        assert report.contradicting_count == 2
        assert "Divided" in report.summary

    def test_no_cross_refs_weak(self):
        claims = [_make_claim("c1", paper_id="p1")]
        report = CrossRefValidator._compute_consensus("topic", claims, [])

        assert report.consensus_level == ConsensusLevel.WEAK
        assert "Insufficient" in report.summary

    def test_only_independent_refs_weak(self):
        claims = [_make_claim("c1", paper_id="p1"), _make_claim("c2", paper_id="p2")]
        refs = [
            CrossReference(
                id="xr1", claim_a=claims[0], claim_b=claims[1],
                relation=ClaimRelation.INDEPENDENT,
            ),
        ]
        # INDEPENDENT is not counted in total_meaningful → WEAK
        report = CrossRefValidator._compute_consensus("topic", claims, refs)

        assert report.consensus_level == ConsensusLevel.WEAK

    def test_extending_counts_as_agreeing(self):
        claims = [_make_claim("c1", paper_id="p1"), _make_claim("c2", paper_id="p2")]
        refs = [
            CrossReference(
                id="xr1", claim_a=claims[0], claim_b=claims[1],
                relation=ClaimRelation.EXTENDS,
            ),
        ]
        # EXTENDS counts toward agreeing: agreeing=1, contradicting=0 → STRONG
        report = CrossRefValidator._compute_consensus("topic", claims, refs)

        assert report.consensus_level == ConsensusLevel.STRONG

    def test_extending_plus_supporting_moderate(self):
        claims = [
            _make_claim("c1", paper_id="p1"),
            _make_claim("c2", paper_id="p2"),
            _make_claim("c3", paper_id="p3"),
        ]
        refs = [
            CrossReference(
                id="xr1", claim_a=claims[0], claim_b=claims[1],
                relation=ClaimRelation.SUPPORTS,
            ),
            CrossReference(
                id="xr2", claim_a=claims[0], claim_b=claims[2],
                relation=ClaimRelation.EXTENDS,
            ),
            CrossReference(
                id="xr3", claim_a=claims[1], claim_b=claims[2],
                relation=ClaimRelation.CONTRADICTS,
            ),
        ]
        # agreeing = 1 supporting + 1 extending = 2, contradicting = 1
        # agreeing(2) > contradicting(1)*2(2)? No → WEAK
        # agreeing(2) > contradicting(1)? Yes → WEAK
        report = CrossRefValidator._compute_consensus("perf", claims, refs)

        assert report.consensus_level == ConsensusLevel.WEAK


# ==================== Cross-ref Pair Cap Tests ====================

class TestCrossPaperPairsCap:
    def test_max_pairs_limits_output(self):
        # Create claims from many different papers to generate many cross-paper pairs
        claims = [_make_claim(f"c{i}", paper_id=f"p{i}") for i in range(20)]
        # Without cap: C(20,2) = 190 pairs, all cross-paper
        pairs = CrossRefValidator._get_cross_paper_pairs(claims, max_pairs=10)
        assert len(pairs) == 10

    def test_default_max_pairs_50(self):
        claims = [_make_claim(f"c{i}", paper_id=f"p{i}") for i in range(15)]
        # C(15,2) = 105 > 50
        pairs = CrossRefValidator._get_cross_paper_pairs(claims)
        assert len(pairs) == 50

    def test_fewer_than_cap(self):
        claims = [
            _make_claim("c1", paper_id="p1"),
            _make_claim("c2", paper_id="p2"),
        ]
        pairs = CrossRefValidator._get_cross_paper_pairs(claims, max_pairs=50)
        assert len(pairs) == 1


# ==================== Prompt Injection Sanitization Tests ====================

class TestPromptSanitization:
    def test_sanitize_escapes_braces(self):
        text = "Use {injection} here"
        result = ClaimExtractor._sanitize_for_prompt(text)
        assert result == "Use {{injection}} here"

    def test_sanitize_no_braces(self):
        text = "Normal text without braces"
        result = ClaimExtractor._sanitize_for_prompt(text)
        assert result == text

    def test_extraction_prompt_has_xml_delimiters(self):
        extractor = ClaimExtractor.__new__(ClaimExtractor)
        extractor.model = "gpt-4o-mini"
        extractor.client = None
        extractor.api_key = None

        prompt = extractor._build_extraction_prompt("Section text", "Paper Title")
        assert "<paper_title>" in prompt
        assert "</paper_title>" in prompt
        assert "<review_section>" in prompt
        assert "</review_section>" in prompt

    def test_extraction_prompt_sanitizes_braces(self):
        extractor = ClaimExtractor.__new__(ClaimExtractor)
        extractor.model = "gpt-4o-mini"
        extractor.client = None
        extractor.api_key = None

        prompt = extractor._build_extraction_prompt("text with {braces}", "Title {test}")
        # Braces in user content should be escaped (doubled)
        assert "{{braces}}" in prompt
        assert "{{test}}" in prompt


# ==================== Evidence Truncation Tests ====================

class TestEvidenceTruncation:
    def setup_method(self):
        self.linker = _make_linker()

    def test_short_text_no_truncation(self):
        claim = _make_claim(
            text="achieves a BLEU score of 28.4",
            claim_type=ClaimType.STATISTICAL,
            paper_id="1706.03762",
        )
        chunks = [{"text": "Short text about 28.4 BLEU score", "paper_id": "1706.03762",
                    "chunk_index": 0, "chunk_id": "c0"}]
        evidences = self.linker._exact_match(claim, chunks, SAMPLE_PAPER)
        if evidences:
            assert "[truncated]" not in evidences[0].text

    def test_long_text_gets_truncated_marker(self):
        claim = _make_claim(
            text="achieves a BLEU score of 28.4",
            claim_type=ClaimType.STATISTICAL,
            paper_id="1706.03762",
        )
        long_text = "The model achieves 28.4 BLEU score. " + "x" * 1000
        chunks = [{"text": long_text, "paper_id": "1706.03762",
                    "chunk_index": 0, "chunk_id": "c0"}]
        evidences = self.linker._exact_match(claim, chunks, SAMPLE_PAPER)
        if evidences:
            assert "[truncated]" in evidences[0].text
            assert len(evidences[0].text) <= 812  # 800 + len(" [truncated]")


# ==================== Chunk Overlap Tests ====================

class TestChunkOverlap:
    def setup_method(self):
        self.linker = _make_linker()

    def test_default_overlap_is_200(self):
        import inspect
        sig = inspect.signature(self.linker._chunk_paper_text)
        assert sig.parameters["overlap"].default == 200

    def test_chunks_overlap_content(self):
        # Create a paper with enough text that overlapping chunks are generated
        long_text = " ".join(f"word{i}" for i in range(500))
        paper = {"title": "Long Paper", "full_text": long_text}
        chunks = self.linker._chunk_paper_text(paper, chunk_size=200, overlap=50)

        if len(chunks) >= 2:
            # Second chunk should contain some text from end of first chunk
            first_end = chunks[0]["text"][-50:]
            assert any(word in chunks[1]["text"] for word in first_end.split())


# ==================== Section Keywords Tests ====================

class TestExpandedSectionKeywords:
    def test_method_includes_new_keywords(self):
        for kw in ["pipeline", "training", "loss function"]:
            assert kw in SECTION_KEYWORDS["Method"]

    def test_experiments_includes_new_keywords(self):
        for kw in ["precision", "recall", "sota", "metric"]:
            assert kw in SECTION_KEYWORDS["Experiments"]

    def test_new_keywords_detected(self):
        text = "The training pipeline uses a custom loss function for optimization."
        section = EvidenceLinker._estimate_section(text)
        assert section == "Method"

    def test_sota_detected_as_experiments(self):
        text = "Our method achieves sota results with high precision and recall metrics."
        section = EvidenceLinker._estimate_section(text)
        assert section == "Experiments"
