import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.evidence import load_facts
from qhapaq_finance.evidence_quality import evaluate_quality
from qhapaq_finance.model_requirements import (
    ModelProfileError,
    RequirementStatus,
    evaluate_capital_cost_stage_readiness,
    evaluate_model_readiness,
    load_model_profile,
)

ROOT = Path(__file__).parents[1]
PROFILE = ROOT / "data/model_profiles/fcff-research-v1.json"


def _report(issuer: str = "qcom"):
    quality_path = ROOT / "data/research" / issuer / "evidence-quality-profile.json"
    quality = evaluate_quality(quality_path, ROOT)
    facts = load_facts(
        ROOT / "data/research" / issuer / "financial-evidence.json",
        ROOT,
        as_of=date.fromisoformat("2026-09-08"),
    )
    return evaluate_model_readiness(load_model_profile(PROFILE), facts, quality), facts, quality


def test_fcff_profile_is_versioned_and_qcom_nvda_are_complete() -> None:
    profile = load_model_profile(PROFILE)
    assert profile.version == "1" and profile.profile_id == "fcff-research"
    assert not any(name in PROFILE.read_text(encoding="utf-8") for name in ("QCOM", "NVDA", "AAPL"))
    for issuer in ("qcom", "nvda"):
        report, _, _ = _report(issuer)
        assert report.model_ready
        assert any(item.derivation_id == "ttm_reconstruction" for item in report.requirements)


def test_malformed_and_duplicate_profiles_fail(tmp_path: Path) -> None:
    broken = tmp_path / "broken.json"
    broken.write_text("{}", encoding="utf-8")
    with pytest.raises(ModelProfileError):
        load_model_profile(broken)
    raw = json.loads(PROFILE.read_text(encoding="utf-8"))
    raw["requirements"].append(raw["requirements"][0])
    broken.write_text(json.dumps(raw), encoding="utf-8")
    with pytest.raises(ModelProfileError, match="duplicate"):
        load_model_profile(broken)


def test_missing_unit_period_quality_and_undeclared_derivation_fail_closed(tmp_path: Path) -> None:
    report, facts, quality = _report()
    assert all(item.status is RequirementStatus.SATISFIED for item in report.requirements)
    missing = dict(facts)
    del missing["cash_q3fy26"]
    result = evaluate_model_readiness(load_model_profile(PROFILE), missing, quality)
    assert (
        next(item for item in result.requirements if item.requirement_id == "cash").status
        is RequirementStatus.MISSING
    )
    bad_unit = dict(facts)
    bad_unit["cash_q3fy26"] = replace(bad_unit["cash_q3fy26"], unit="shares")
    result = evaluate_model_readiness(load_model_profile(PROFILE), bad_unit, quality)
    assert (
        next(item for item in result.requirements if item.requirement_id == "cash").status
        is RequirementStatus.INVALID
    )
    bad_period = dict(facts)
    bad_period["cash_q3fy26"] = replace(
        bad_period["cash_q3fy26"],
        period_kind=__import__(
            "qhapaq_finance.evidence", fromlist=["PeriodKind"]
        ).PeriodKind.DURATION,
        period_start=date(2026, 1, 1),
    )
    result = evaluate_model_readiness(load_model_profile(PROFILE), bad_period, quality)
    assert (
        next(item for item in result.requirements if item.requirement_id == "cash").status
        is RequirementStatus.INVALID
    )
    failed_quality = replace(quality, missing_required_facts=("x",))
    result = evaluate_model_readiness(load_model_profile(PROFILE), facts, failed_quality)
    assert not result.model_ready
    assert all(
        item.status is RequirementStatus.QUALITY_BLOCKED
        or item.status is RequirementStatus.OPTIONAL_UNAVAILABLE
        for item in result.requirements
    )
    raw = json.loads(PROFILE.read_text(encoding="utf-8"))
    raw["requirements"][0]["allowed_derivations"] = []
    alternate = tmp_path / "profile.json"
    alternate.write_text(json.dumps(raw), encoding="utf-8")
    result = evaluate_model_readiness(load_model_profile(alternate), facts, quality)
    assert (
        next(item for item in result.requirements if item.requirement_id == "revenue_ttm").status
        is RequirementStatus.INVALID
    )


def test_readiness_serialization_is_deterministic_and_input_sensitive() -> None:
    first, facts, quality = _report()
    second = evaluate_model_readiness(load_model_profile(PROFILE), facts, quality)
    assert first.to_dict() == second.to_dict() and first.content_identity == second.content_identity
    changed = dict(facts)
    changed["cash_q3fy26"] = replace(changed["cash_q3fy26"], value=999.0)
    assert (
        evaluate_model_readiness(load_model_profile(PROFILE), changed, quality).content_identity
        != first.content_identity
    )


def test_capital_cost_dependency_is_a_separate_valuation_stage() -> None:
    profile = load_model_profile(PROFILE)
    assert profile.capital_cost_requirement is not None
    blocked = evaluate_capital_cost_stage_readiness(profile, None)
    assert not blocked.ready
    report, _, _ = _report()
    assert report.model_ready  # FCFF financial completeness remains independently valid.
