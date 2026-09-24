import pytest

from src.search_eval.query_analysis_reward import (
    mixed_gate_score,
    strict_mixed_gate_accepts,
)
from src.search_eval.skillopt_contract import ValidationError


def test_mixed_uses_exact_point_eight_weight_and_invalid_soft_zero_semantics():
    assert mixed_gate_score(hard=1.0, soft=0.5) == 0.6
    assert mixed_gate_score(hard=0.0, soft=0.0) == 0.0
    with pytest.raises(ValidationError):
        mixed_gate_score(hard=0.0, soft=float("inf"))


def test_strict_improvement_has_no_epsilon_and_tie_rejects():
    assert not strict_mixed_gate_accepts(
        candidate_hard=1,
        candidate_soft=0.1234567890124,
        current_hard=1,
        current_soft=0.1234567890124,
    )
    assert strict_mixed_gate_accepts(
        candidate_hard=1,
        candidate_soft=0.123456789014,
        current_hard=1,
        current_soft=0.123456789012,
    )
