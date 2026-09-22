from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from qhapaq_finance.financial_canonicalization import (
    FactContext,
    FinancialCanonicalizer,
    IssuerProfile,
    MetricSpec,
    PeriodKind,
    ProfileKind,
    ResolutionStatus,
)
from qhapaq_finance.sec_filing_xbrl import (
    FilingArtifact,
    FilingNativeXbrlError,
    VerifiedFilingArtifacts,
    parse_filing_native_evidence,
)

FIXTURE = Path(__file__).parent / "fixtures/sec_filing_xbrl/valid"
REVENUE_SPEC = MetricSpec(
    "revenue",
    "us-gaap",
    "RevenueFromContractWithCustomerExcludingAssessedTax",
    (),
    "USD",
    PeriodKind.DURATION,
)
PROFILE = IssuerProfile(ProfileKind.OPERATING_COMPANY, "fixture")


def _filing(*, contradictory: bool = False) -> VerifiedFilingArtifacts:
    names = ["instance.xml", "acme.xsd", "acme_pre.xml", "acme_lab.xml"]
    names.append("acme_contradictory_cal.xml" if contradictory else "acme_cal.xml")
    artifacts = tuple(
        FilingArtifact(path, hashlib.sha256(path.read_bytes()).hexdigest())
        for path in (FIXTURE / name for name in names)
    )
    return VerifiedFilingArtifacts(
        accession="0000000123-26-000001",
        form="10-K",
        filing_date=date(2026, 2, 1),
        report_date=date(2025, 12, 31),
        fiscal_year=2025,
        fiscal_period="FY",
        cik="0000000123",
        artifacts=artifacts,
    )


def test_bridge_emits_standard_raw_fact_with_verified_lineage() -> None:
    evidence = parse_filing_native_evidence((_filing(),))
    fact = next(item for item in evidence.raw_facts if item.fact_id == "standard")

    assert (fact.taxonomy, fact.concept, fact.value, fact.unit) == (
        "us-gaap",
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        100.0,
        "USD",
    )
    assert fact.start == date(2025, 1, 1)
    assert fact.end == date(2025, 12, 31)
    assert fact.source_identity in evidence.source_identities


def test_structural_extension_is_accepted_but_label_only_extension_is_not() -> None:
    evidence = parse_filing_native_evidence((_filing(),))
    context = FactContext(
        date(2025, 12, 31),
        fiscal_year=2025,
        fiscal_period="FY",
        semantic_extensions=evidence.semantic_extensions,
    )
    custom = next(item for item in evidence.raw_facts if item.fact_id == "extension")
    label_only = next(item for item in evidence.raw_facts if item.fact_id == "label-only")

    accepted = FinancialCanonicalizer().resolve(PROFILE, context, REVENUE_SPEC, (custom,))
    rejected = FinancialCanonicalizer().resolve(PROFILE, context, REVENUE_SPEC, (label_only,))

    assert accepted.decision.status is ResolutionStatus.RESOLVED
    assert rejected.decision.status is ResolutionStatus.MISSING
    assert ("acme", "LabelOnlyRevenue") not in evidence.semantic_extensions


def test_contradictory_presentation_and_calculation_relationships_fail_closed() -> None:
    with pytest.raises(FilingNativeXbrlError, match="contradictory structural relationships"):
        parse_filing_native_evidence((_filing(contradictory=True),))


def test_unit_and_dimension_mismatches_cannot_authorize_extension() -> None:
    evidence = parse_filing_native_evidence((_filing(),))
    context = FactContext(
        date(2025, 12, 31),
        fiscal_year=2025,
        fiscal_period="FY",
        semantic_extensions=evidence.semantic_extensions,
    )
    dimensional = next(
        item for item in evidence.raw_facts if item.fact_id == "extension-dimensional"
    )
    euro = next(item for item in evidence.raw_facts if item.fact_id == "extension-eur")

    assert dimensional.dimensions == ("acme:RegionAxis=acme:NorthMember",)
    assert (
        FinancialCanonicalizer()
        .resolve(PROFILE, context, REVENUE_SPEC, (dimensional,))
        .decision.status
        is ResolutionStatus.MISSING
    )
    assert (
        FinancialCanonicalizer().resolve(PROFILE, context, REVENUE_SPEC, (euro,)).decision.status
        is ResolutionStatus.MISSING
    )


def test_bridge_rejects_checksum_or_source_identity_mismatch() -> None:
    filing = _filing()
    corrupted = FilingArtifact(filing.artifacts[0].path, "0" * 64)
    invalid = VerifiedFilingArtifacts(
        **{**filing.__dict__, "artifacts": (corrupted, *filing.artifacts[1:])}
    )

    with pytest.raises(FilingNativeXbrlError, match="checksum"):
        parse_filing_native_evidence((invalid,))


def _changed_filing(tmp_path: Path, name: str, old: str, new: str) -> VerifiedFilingArtifacts:
    filing = _filing()
    artifacts = []
    for artifact in filing.artifacts:
        if artifact.path.name == name:
            text = artifact.path.read_text()
            assert old in text
            path = tmp_path / name
            path.write_text(text.replace(old, new))
            artifact = FilingArtifact(path, hashlib.sha256(path.read_bytes()).hexdigest())
        artifacts.append(artifact)
    return replace(filing, artifacts=tuple(artifacts))


def test_standard_native_fact_repairs_missing_canonical_observation() -> None:
    context = FactContext(date(2025, 12, 31), fiscal_year=2025, fiscal_period="FY")
    canonicalizer = FinancialCanonicalizer()
    assert canonicalizer.resolve(PROFILE, context, REVENUE_SPEC, ()).decision.status is (
        ResolutionStatus.MISSING
    )
    evidence = parse_filing_native_evidence((_filing(),))
    fact = next(item for item in evidence.raw_facts if item.fact_id == "standard")
    result = canonicalizer.resolve(PROFILE, context, REVENUE_SPEC, (fact,))
    assert result.decision.status is ResolutionStatus.RESOLVED
    assert result.normalized_value == 100.0
    assert (fact.accession, fact.filing_form, fact.filing_date) == (
        "0000000123-26-000001",
        "10-K",
        date(2026, 2, 1),
    )


def test_typed_dimensions_are_preserved_and_cannot_repair_consolidated_gap(
    tmp_path: Path,
) -> None:
    filing = _changed_filing(
        tmp_path,
        "instance.xml",
        '<xbrldi:explicitMember dimension="acme:RegionAxis">'
        "acme:NorthMember</xbrldi:explicitMember>",
        '<xbrldi:typedMember dimension="acme:RegionAxis">'
        "<acme:RegionDomain>North</acme:RegionDomain></xbrldi:typedMember>",
    )
    evidence = parse_filing_native_evidence((filing,))
    fact = next(item for item in evidence.raw_facts if item.fact_id == "extension-dimensional")
    assert fact.dimensions and "North" in fact.dimensions[0]
    assert not fact.consolidated
    result = FinancialCanonicalizer().resolve(
        PROFILE,
        FactContext(date(2025, 12, 31), semantic_extensions=evidence.semantic_extensions),
        REVENUE_SPEC,
        (fact,),
    )
    assert result.decision.status is ResolutionStatus.MISSING


@pytest.mark.parametrize(
    "old,new",
    [
        ("<startDate>2025-01-01</startDate>", "<startDate>2026-01-01</startDate>"),
        ("<period><startDate>", "<period><instant>2025-12-31</instant><startDate>"),
        ('scheme="http://www.sec.gov/CIK"', 'scheme="http://example.com/untrusted"'),
    ],
)
def test_invalid_contexts_fail_closed(tmp_path: Path, old: str, new: str) -> None:
    filing = _changed_filing(tmp_path, "instance.xml", old, new)
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


def test_units_resolve_namespace_uris_not_prefix_spelling(tmp_path: Path) -> None:
    filing = _changed_filing(tmp_path, "instance.xml", "iso4217", "currency")
    # Only change the prefix, leaving the namespace URI itself intact.
    # The replacement above also changed the URI; correct it in the local artifact.
    artifact = filing.artifacts[0]
    artifact.path.write_text(
        artifact.path.read_text().replace(
            "http://www.xbrl.org/2003/currency", "http://www.xbrl.org/2003/iso4217"
        )
    )
    filing = replace(
        filing,
        artifacts=(
            replace(artifact, sha256=hashlib.sha256(artifact.path.read_bytes()).hexdigest()),
            *filing.artifacts[1:],
        ),
    )
    evidence = parse_filing_native_evidence((filing,))
    assert next(f for f in evidence.raw_facts if f.fact_id == "standard").unit == "USD"


def test_spoofed_currency_namespace_cannot_be_usd(tmp_path: Path) -> None:
    filing = _changed_filing(
        tmp_path, "instance.xml", "http://www.xbrl.org/2003/iso4217", "http://example.com/fake"
    )
    evidence = parse_filing_native_evidence((filing,))
    fact = next(f for f in evidence.raw_facts if f.fact_id == "standard")
    assert fact.unit != "USD"


@pytest.mark.parametrize(
    "old,new",
    [
        ('weight="1"', ""),
        ('weight="1"', 'weight="-1"'),
        ('xlink:role="statement"', 'xlink:role="other-statement"'),
        ('weight="1"', 'weight="1" use="prohibited"'),
        ('xlink:to="child"', 'xlink:to="missing"'),
    ],
)
def test_incomplete_or_incompatible_structural_evidence_fails_closed(
    tmp_path: Path,
    old: str,
    new: str,
) -> None:
    filing = _changed_filing(tmp_path, "acme_cal.xml", old, new)
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


def test_equivalent_structural_evidence_across_filings_retains_lineage(tmp_path: Path) -> None:
    second = _changed_filing(tmp_path, "instance.xml", ">100<", ">101<")
    second = replace(second, accession="0000000123-26-000002")
    evidence = parse_filing_native_evidence((_filing(), second))
    assert len(evidence.raw_facts) == 10
    assert len(evidence.source_identities) == 6
    assert ("acme", "CustomRevenue") in evidence.semantic_extensions


def test_compound_unit_does_not_prevent_standard_fact_recovery(tmp_path: Path) -> None:
    filing = _changed_filing(
        tmp_path,
        "instance.xml",
        "</xbrl>",
        '<unit id="per-share"><divide><unitNumerator><measure>iso4217:USD</measure>'
        "</unitNumerator><unitDenominator><measure>xbrli:shares</measure>"
        "</unitDenominator></divide></unit>"
        '<us-gaap:EarningsPerShareBasic contextRef="annual" unitRef="per-share">2.5'
        "</us-gaap:EarningsPerShareBasic></xbrl>",
    )
    evidence = parse_filing_native_evidence((filing,))
    assert next(f for f in evidence.raw_facts if f.fact_id == "standard").value == 100
    assert next(f for f in evidence.raw_facts if f.concept == "EarningsPerShareBasic").unit == (
        "USD/shares"
    )


def test_scoped_unit_namespace_is_resolved_at_measure(tmp_path: Path) -> None:
    filing = _changed_filing(
        tmp_path,
        "instance.xml",
        "<measure>iso4217:USD</measure>",
        '<measure xmlns:iso4217="http://example.com/fake">iso4217:USD</measure>',
    )
    evidence = parse_filing_native_evidence((filing,))
    assert next(f for f in evidence.raw_facts if f.fact_id == "standard").unit != "USD"
    assert next(f for f in evidence.raw_facts if f.fact_id == "extension-eur").unit == "EUR"


def test_issuer_concepts_resolve_by_namespace_and_schema_id(tmp_path: Path) -> None:
    filing = _filing()
    artifacts = []
    for artifact in filing.artifacts:
        content = artifact.path.read_text()
        if artifact.path.name == "instance.xml":
            content = content.replace("xmlns:acme=", "xmlns:issuer=").replace("acme:", "issuer:")
        elif artifact.path.suffix == ".xsd":
            content = content.replace('id="acme_CustomRevenue"', 'id="custom-revenue-id"')
        else:
            content = content.replace("#acme_CustomRevenue", "#custom-revenue-id")
        path = tmp_path / artifact.path.name
        path.write_text(content)
        artifacts.append(FilingArtifact(path, hashlib.sha256(path.read_bytes()).hexdigest()))
    evidence = parse_filing_native_evidence((replace(filing, artifacts=tuple(artifacts)),))
    fact = next(f for f in evidence.raw_facts if f.fact_id == "extension")
    result = FinancialCanonicalizer().resolve(
        PROFILE,
        FactContext(date(2025, 12, 31), semantic_extensions=evidence.semantic_extensions),
        REVENUE_SPEC,
        (fact,),
    )
    assert result.decision.status is ResolutionStatus.RESOLVED


@pytest.mark.parametrize(
    "old,new",
    [
        (
            "</entity>",
            "<segment><acme:UnknownScenario>segment</acme:UnknownScenario></segment></entity>",
        ),
        ('<xbrldi:explicitMember dimension="acme:RegionAxis">', "<xbrldi:explicitMember>"),
    ],
)
def test_unrepresentable_context_qualifiers_fail_closed(
    tmp_path: Path,
    old: str,
    new: str,
) -> None:
    filing = _changed_filing(tmp_path, "instance.xml", old, new)
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


def test_schema_period_mismatch_is_not_marked_compatible(tmp_path: Path) -> None:
    filing = _changed_filing(tmp_path, "acme.xsd", 'periodType="duration"', 'periodType="instant"')
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


@pytest.mark.parametrize("value", ["NaN", "INF", "-INF", "1e1000"])
def test_non_finite_facts_fail_closed(tmp_path: Path, value: str) -> None:
    filing = _changed_filing(tmp_path, "instance.xml", ">100<", f">{value}<")
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


@pytest.mark.parametrize(
    "changes",
    [
        {"accession": "invalid"},
        {"fiscal_period": "Q5"},
        {"fiscal_period": "Q1"},
        {"filing_date": date(2024, 1, 1)},
        {"fiscal_year": 0},
    ],
)
def test_invalid_filing_identity_fails_closed(changes: dict[str, object]) -> None:
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((replace(_filing(), **changes),))


def test_instance_dei_identity_must_agree_with_verified_metadata(tmp_path: Path) -> None:
    filing = _changed_filing(
        tmp_path,
        "instance.xml",
        "</xbrl>",
        '<dei:DocumentFiscalYearFocus xmlns:dei="http://xbrl.sec.gov/dei/2025" '
        'contextRef="annual">2024</dei:DocumentFiscalYearFocus></xbrl>',
    )
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


def test_schema_imports_and_linkbase_urls_never_access_network(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import socket

    def no_network(*args: object, **kwargs: object) -> None:
        raise AssertionError("filing-native parsing attempted network I/O")

    monkeypatch.setattr(socket, "socket", no_network)
    filing = _changed_filing(
        tmp_path,
        "acme.xsd",
        "</xs:schema>",
        '<xs:import namespace="http://fasb.org/us-gaap/2025" '
        'schemaLocation="https://example.invalid/us-gaap.xsd"/></xs:schema>',
    )
    evidence = parse_filing_native_evidence((filing,))
    assert next(f for f in evidence.raw_facts if f.fact_id == "standard").value == 100


def _inline_filing() -> VerifiedFilingArtifacts:
    path = FIXTURE / "primary.htm"
    return replace(
        _filing(), artifacts=(FilingArtifact(path, hashlib.sha256(path.read_bytes()).hexdigest()),)
    )


def test_inline_primary_recovers_scaled_signed_facts_without_extracted_instance() -> None:
    evidence = parse_filing_native_evidence((_inline_filing(),))
    revenue, loss = evidence.raw_facts
    assert (revenue.taxonomy, revenue.value, revenue.unit) == ("us-gaap", 1234500.0, "USD")
    assert (loss.concept, loss.value) == ("OperatingIncomeLoss", -12000.0)
    assert revenue.source_identity in evidence.source_identities
    assert revenue.start == date(2025, 1, 1)


def test_inline_primary_supplements_facts_missing_from_extracted_instance() -> None:
    filing = _filing()
    evidence = parse_filing_native_evidence(
        (replace(filing, artifacts=(*filing.artifacts, *_inline_filing().artifacts)),)
    )
    assert next(f for f in evidence.raw_facts if f.concept == "OperatingIncomeLoss").value == -12000
    # Both reported revenues survive; the bridge must not choose the convenient value.
    revenues = [f.value for f in evidence.raw_facts if f.concept == REVENUE_SPEC.standard_concept]
    assert set(revenues) == {100.0, 1234500.0}


@pytest.mark.parametrize(
    "old,new",
    [
        ('format="ixt:num-dot-decimal"', 'format="ixt:unknown-transform"'),
        ('sign="-"', 'sign="+"'),
        ('scale="3"', 'scale="1.5"'),
    ],
)
def test_unsupported_inline_transforms_fail_closed(tmp_path: Path, old: str, new: str) -> None:
    artifact = _inline_filing().artifacts[0]
    path = tmp_path / "primary.htm"
    path.write_text(artifact.path.read_text().replace(old, new))
    filing = replace(
        _inline_filing(),
        artifacts=(FilingArtifact(path, hashlib.sha256(path.read_bytes()).hexdigest()),),
    )
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


def test_standard_namespace_cannot_be_spoofed_by_prefix_or_substring(tmp_path: Path) -> None:
    filing = _changed_filing(
        tmp_path, "instance.xml", "http://fasb.org/us-gaap/2025", "http://example.com/us-gaap/2025"
    )
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


def test_missing_numeric_unit_and_unresolved_context_fail_closed(tmp_path: Path) -> None:
    filing = _changed_filing(tmp_path, "instance.xml", 'unitRef="usd"', "")
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


def test_xml_entities_are_not_accepted_as_filing_evidence(tmp_path: Path) -> None:
    filing = _changed_filing(
        tmp_path,
        "instance.xml",
        "<xbrl xmlns=",
        '<!DOCTYPE xbrl [<!ENTITY hundred "100">]><xbrl xmlns=',
    )
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


def test_instance_namespace_cannot_define_currency_units(tmp_path: Path) -> None:
    filing = _changed_filing(tmp_path, "instance.xml", "iso4217:USD", "xbrli:USD")
    evidence = parse_filing_native_evidence((filing,))
    assert next(f for f in evidence.raw_facts if f.fact_id == "standard").unit != "USD"


def test_duplicate_schema_definitions_fail_closed(tmp_path: Path) -> None:
    filing = _changed_filing(
        tmp_path,
        "acme.xsd",
        "</xs:schema>",
        '<xs:element name="CustomRevenue" id="duplicate" type="xbrli:sharesItemType" '
        'xbrli:periodType="duration"/></xs:schema>',
    )
    with pytest.raises(FilingNativeXbrlError, match="schema"):
        parse_filing_native_evidence((filing,))


def test_duplicate_locator_labels_fail_closed(tmp_path: Path) -> None:
    filing = _changed_filing(
        tmp_path,
        "acme_cal.xml",
        "<link:calculationArc",
        '<link:loc xlink:label="child" xlink:href="acme.xsd#acme_LabelOnlyRevenue"/>'
        "<link:calculationArc",
    )
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


def test_semantic_authorization_cannot_leak_into_a_label_only_filing() -> None:
    second = replace(_filing(), accession="0000000123-26-000002")
    second = replace(
        second,
        artifacts=tuple(
            artifact for artifact in second.artifacts if artifact.path.name != "acme_cal.xml"
        ),
    )
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((_filing(), second))


def test_scale_applied_before_float_conversion(tmp_path: Path) -> None:
    filing = _changed_filing(
        tmp_path, "instance.xml", 'decimals="0">100', 'decimals="0" scale="-400">1e400'
    )
    evidence = parse_filing_native_evidence((filing,))
    assert next(f for f in evidence.raw_facts if f.fact_id == "standard").value == 1.0


def test_nonzero_underflow_cannot_become_zero_evidence(tmp_path: Path) -> None:
    filing = _changed_filing(tmp_path, "instance.xml", ">100<", ">1e-400<")
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


def test_untrusted_linkbase_namespace_cannot_authorize_extensions(tmp_path: Path) -> None:
    filing = _changed_filing(
        tmp_path,
        "acme_cal.xml",
        "<link:calculationLink",
        '<link:calculationLink xmlns:link="http://example.com/fake"',
    )
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


def test_inline_excluded_text_is_not_part_of_numeric_value(tmp_path: Path) -> None:
    artifact = _inline_filing().artifacts[0]
    path = tmp_path / "primary.htm"
    path.write_text(
        artifact.path.read_text().replace(
            ">12</ix:nonFraction>", ">1<ix:exclude>9</ix:exclude>2</ix:nonFraction>"
        )
    )
    filing = replace(
        _inline_filing(),
        artifacts=(FilingArtifact(path, hashlib.sha256(path.read_bytes()).hexdigest()),),
    )
    evidence = parse_filing_native_evidence((filing,))
    assert next(f for f in evidence.raw_facts if f.fact_id == "inline-loss").value == -12000


def test_extension_prefix_rebinding_cannot_reuse_another_schema(tmp_path: Path) -> None:
    filing = _changed_filing(
        tmp_path,
        "instance.xml",
        '<acme:CustomRevenue id="extension"',
        '<acme:CustomRevenue xmlns:acme="http://example.com/other-issuer" id="extension"',
    )
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


def test_remote_locator_filename_cannot_impersonate_standard_taxonomy(tmp_path: Path) -> None:
    filing = _changed_filing(
        tmp_path,
        "acme_cal.xml",
        'xlink:href="us-gaap.xsd#',
        'xlink:href="https://example.com/us-gaap.xsd#',
    )
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((filing,))


def test_period_incompatible_calculation_cannot_authorize_extension(tmp_path: Path) -> None:
    filing = _filing()
    artifacts = []
    for artifact in filing.artifacts:
        content = artifact.path.read_text()
        if artifact.path.name in {"acme_pre.xml", "acme_cal.xml"}:
            content = content.replace(
                "RevenueFromContractWithCustomerExcludingAssessedTax", "Assets"
            )
        path = tmp_path / artifact.path.name
        path.write_text(content)
        artifacts.append(FilingArtifact(path, hashlib.sha256(path.read_bytes()).hexdigest()))
    with pytest.raises(FilingNativeXbrlError):
        parse_filing_native_evidence((replace(filing, artifacts=tuple(artifacts)),))


# --- Task 8 real-world inline continuation contracts ---


def _task8_inline_instance(xml: str):
    from qhapaq_finance import sec_filing_xbrl

    root, scopes = sec_filing_xbrl._parse_xml(xml.encode())
    return sec_filing_xbrl._inline_instance(root, scopes)


def test_inline_non_numeric_continuation_chain_is_joined_deterministically() -> None:
    instance = _task8_inline_instance(
        """\
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <body>
    <ix:nonNumeric
        name="us-gaap:AccountingPoliciesTextBlock"
        contextRef="c-1"
        continuedAt="part-1">Alpha </ix:nonNumeric>
    <ix:continuation id="part-1" continuedAt="part-2">Beta </ix:continuation>
    <ix:continuation id="part-2">Gamma</ix:continuation>
  </body>
</html>
"""
    )

    facts = list(instance)

    assert len(facts) == 1
    assert facts[0].tag == "{http://fasb.org/us-gaap/2025}AccountingPoliciesTextBlock"
    assert facts[0].text == "Alpha Beta Gamma"


def test_inline_continuation_missing_reference_fails_closed() -> None:
    from qhapaq_finance.sec_filing_xbrl import FilingNativeXbrlError

    with pytest.raises(FilingNativeXbrlError, match="continuation reference is missing"):
        _task8_inline_instance(
            """\
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <body>
    <ix:nonNumeric
        name="us-gaap:AccountingPoliciesTextBlock"
        contextRef="c-1"
        continuedAt="absent">Alpha</ix:nonNumeric>
  </body>
</html>
"""
        )


def test_inline_continuation_cycle_fails_closed() -> None:
    from qhapaq_finance.sec_filing_xbrl import FilingNativeXbrlError

    with pytest.raises(FilingNativeXbrlError, match="continuation cycle"):
        _task8_inline_instance(
            """\
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <body>
    <ix:nonNumeric
        name="us-gaap:AccountingPoliciesTextBlock"
        contextRef="c-1"
        continuedAt="part-1">Alpha</ix:nonNumeric>
    <ix:continuation id="part-1" continuedAt="part-2">Beta</ix:continuation>
    <ix:continuation id="part-2" continuedAt="part-1">Gamma</ix:continuation>
  </body>
</html>
"""
        )


def test_inline_duplicate_continuation_id_fails_closed() -> None:
    from qhapaq_finance.sec_filing_xbrl import FilingNativeXbrlError

    with pytest.raises(FilingNativeXbrlError, match="duplicate inline continuation id"):
        _task8_inline_instance(
            """\
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <body>
    <ix:nonNumeric
        name="us-gaap:AccountingPoliciesTextBlock"
        contextRef="c-1"
        continuedAt="part-1">Alpha</ix:nonNumeric>
    <ix:continuation id="part-1">Beta</ix:continuation>
    <ix:continuation id="part-1">Gamma</ix:continuation>
  </body>
</html>
"""
        )


def test_inline_numeric_continuation_remains_unsupported() -> None:
    from qhapaq_finance.sec_filing_xbrl import FilingNativeXbrlError

    with pytest.raises(FilingNativeXbrlError, match="unsupported inline numeric continuation"):
        _task8_inline_instance(
            """\
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <body>
    <ix:nonFraction
        name="us-gaap:Assets"
        contextRef="c-1"
        unitRef="USD"
        continuedAt="part-1">100</ix:nonFraction>
    <ix:continuation id="part-1">0</ix:continuation>
  </body>
</html>
"""
        )


def test_inline_fixed_zero_transform_produces_numeric_zero() -> None:
    instance = _task8_inline_instance(
        """\
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <body>
    <ix:nonFraction
        name="us-gaap:TradingSecurities"
        contextRef="c-1"
        unitRef="USD"
        format="ixt:fixed-zero"
        scale="6"
        decimals="-6">—</ix:nonFraction>
  </body>
</html>
"""
    )

    facts = list(instance)

    assert len(facts) == 1
    assert facts[0].tag == "{http://fasb.org/us-gaap/2025}TradingSecurities"
    assert facts[0].text == "0"


@pytest.mark.parametrize(
    ("words", "expected"),
    [
        ("two", "2"),
        ("three", "3"),
        ("no", "0"),
        ("None", "0"),
        ("nineteen hundred forty-four", "1944"),
        ("Seventy Thousand and one", "70001"),
    ],
)
def test_sec_numwordsen_transform_is_parsed_exactly(
    words: str,
    expected: str,
) -> None:
    instance = _task8_inline_instance(
        f"""\
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:ixt-sec="http://www.sec.gov/inlineXBRL/transformation/2015-08-31"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <body>
    <ix:nonFraction
        name="us-gaap:Assets"
        contextRef="c-1"
        unitRef="shares"
        format="ixt-sec:numwordsen"
        decimals="INF">{words}</ix:nonFraction>
  </body>
</html>
"""
    )

    facts = list(instance)

    assert len(facts) == 1
    assert facts[0].text == expected


def test_sec_numwordsen_unknown_word_fails_closed() -> None:
    from qhapaq_finance.sec_filing_xbrl import FilingNativeXbrlError

    with pytest.raises(
        FilingNativeXbrlError,
        match="unsupported SEC numwordsen value",
    ):
        _task8_inline_instance(
            """\
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:ixt-sec="http://www.sec.gov/inlineXBRL/transformation/2015-08-31"
      xmlns:us-gaap="http://fasb.org/us-gaap/2025">
  <body>
    <ix:nonFraction
        name="us-gaap:Assets"
        contextRef="c-1"
        unitRef="shares"
        format="ixt-sec:numwordsen"
        decimals="INF">approximately five</ix:nonFraction>
  </body>
</html>
"""
        )


@pytest.mark.parametrize(
    ("href", "expected"),
    [
        (
            "https://xbrl.fasb.org/srt/2025/elts/"
            "srt-2025.xsd#srt_PayablesToBrokerDealersAndClearingOrganizations",
            "srt:PayablesToBrokerDealersAndClearingOrganizations",
        ),
        (
            "https://xbrl.sec.gov/ecd/2025/ecd-2025.xsd#ecd_AdjToCompAxis",
            "ecd:AdjToCompAxis",
        ),
        (
            "https://xbrl.sec.gov/stpr/2025/stpr-2025.xsd#stpr_NY",
            "stpr:NY",
        ),
        (
            "https://xbrl.sec.gov/country/2025/country-2025.xsd#country_US",
            "country:US",
        ),
    ],
)
def test_verified_remote_standard_taxonomy_locators_are_accepted(
    href: str,
    expected: str,
) -> None:
    from qhapaq_finance import sec_filing_xbrl

    assert sec_filing_xbrl._href_qname(href, {}) == expected


@pytest.mark.parametrize(
    "href",
    [
        "https://example.com/ecd-2025.xsd#ecd_AdjToCompAxis",
        "https://xbrl.sec.gov/ecd/2025/ecd-2025.xsd?x=1#ecd_AdjToCompAxis",
        "ftp://xbrl.sec.gov/ecd/2025/ecd-2025.xsd#ecd_AdjToCompAxis",
        "https://xbrl.sec.gov/ecd/2025/us-gaap-2025.xsd#ecd_AdjToCompAxis",
        "https://xbrl.fasb.org/ecd/2025/ecd-2025.xsd#ecd_AdjToCompAxis",
    ],
)
def test_remote_taxonomy_locator_trust_remains_fail_closed(href: str) -> None:
    from qhapaq_finance import sec_filing_xbrl
    from qhapaq_finance.sec_filing_xbrl import FilingNativeXbrlError

    with pytest.raises(
        FilingNativeXbrlError,
        match="linkbase locator has no verified schema concept",
    ):
        sec_filing_xbrl._href_qname(href, {})


def test_inline_english_monthname_date_transform_is_canonical_iso_date() -> None:
    instance = _task8_inline_instance(
        """\
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"
      xmlns:dei="http://xbrl.sec.gov/dei/2025">
  <body>
    <ix:nonNumeric
        name="dei:DocumentPeriodEndDate"
        contextRef="c-1"
        format="ixt:date-monthname-day-year-en">December 31, 2025</ix:nonNumeric>
  </body>
</html>
"""
    )

    facts = list(instance)

    assert len(facts) == 1
    assert facts[0].text == "2025-12-31"


def test_inline_english_monthname_date_transform_invalid_value_fails_closed() -> None:
    from qhapaq_finance.sec_filing_xbrl import FilingNativeXbrlError

    with pytest.raises(
        FilingNativeXbrlError,
        match="unsupported or invalid inline date transform",
    ):
        _task8_inline_instance(
            """\
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:ixt="http://www.xbrl.org/inlineXBRL/transformation/2020-02-12"
      xmlns:dei="http://xbrl.sec.gov/dei/2025">
  <body>
    <ix:nonNumeric
        name="dei:DocumentPeriodEndDate"
        contextRef="c-1"
        format="ixt:date-monthname-day-year-en">Not a date</ix:nonNumeric>
  </body>
</html>
"""
        )


def test_inline_date_transform_from_untrusted_namespace_fails_closed() -> None:
    from qhapaq_finance.sec_filing_xbrl import FilingNativeXbrlError

    with pytest.raises(
        FilingNativeXbrlError,
        match="unsupported or invalid inline date transform",
    ):
        _task8_inline_instance(
            """\
<html xmlns="http://www.w3.org/1999/xhtml"
      xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:evil="https://example.com/transforms"
      xmlns:dei="http://xbrl.sec.gov/dei/2025">
  <body>
    <ix:nonNumeric
        name="dei:DocumentPeriodEndDate"
        contextRef="c-1"
        format="evil:date-monthname-day-year-en">December 31, 2025</ix:nonNumeric>
  </body>
</html>
"""
        )
