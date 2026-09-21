"""Offline bridge from verified filing XBRL artifacts to canonical raw evidence."""

from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
import xml.etree.ElementTree as ET
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, replace
from datetime import date
from decimal import Decimal, DecimalException, localcontext
from io import BytesIO
from pathlib import Path
from types import MappingProxyType
from urllib.parse import urlsplit

from .financial_canonicalization import (
    INITIAL_METRIC_SPECS,
    PeriodKind,
    RawFact,
    SemanticEvidence,
    XbrlCalculationArc,
    XbrlConcept,
    XbrlLabel,
    XbrlPresentationArc,
    XbrlRelationshipSet,
)
from .financial_promotion import (
    MetricPromotionPolicy,
    PromotionStrategy,
    accounting_evidence_policies,
)

_XBRLI = "http://www.xbrl.org/2003/instance"
_XBRLDI = "http://xbrl.org/2006/xbrldi"
_LINK = "http://www.xbrl.org/2003/linkbase"
_XLINK = "http://www.w3.org/1999/xlink"
_XSD = "http://www.w3.org/2001/XMLSchema"
_XSI = "http://www.w3.org/2001/XMLSchema-instance"
_INLINE_NAMESPACES = {"http://www.xbrl.org/2013/inlineXBRL", "http://www.xbrl.org/2008/inlineXBRL"}
_NamespaceScopes = dict[ET.Element, dict[str, str]]


class FilingNativeXbrlError(ValueError):
    """Verified filing artifacts cannot safely produce canonical evidence."""


@dataclass(frozen=True)
class FilingArtifact:
    path: Path
    sha256: str


_ParsedArtifact = tuple[FilingArtifact, ET.Element, _NamespaceScopes]


@dataclass(frozen=True)
class VerifiedFilingArtifacts:
    accession: str
    form: str
    filing_date: date
    report_date: date
    fiscal_year: int
    fiscal_period: str
    cik: str
    artifacts: tuple[FilingArtifact, ...]


@dataclass(frozen=True)
class FilingNativeEvidence:
    raw_facts: tuple[RawFact, ...]
    semantic_extensions: Mapping[tuple[str, str], SemanticEvidence]
    source_identities: tuple[str, ...]


@dataclass(frozen=True)
class _Context:
    start: date | None
    end: date
    dimensions: tuple[str, ...]


def parse_filing_native_evidence(
    filings: tuple[VerifiedFilingArtifacts, ...],
) -> FilingNativeEvidence:
    """Parse verified local artifacts; this function has no network-capable input."""

    all_facts: list[RawFact] = []
    all_semantics: dict[tuple[str, str], SemanticEvidence] = {}
    identities: set[str] = set()
    semantic_checksums: dict[tuple[str, str], set[str]] = {}
    filing_evidence: list[tuple[tuple[RawFact, ...], dict[tuple[str, str], SemanticEvidence]]] = []
    for filing in filings:
        facts, semantics, filing_identities = _parse_filing(filing)
        all_facts.extend(facts)
        filing_evidence.append((facts, semantics))
        for key, value in semantics.items():
            existing = all_semantics.get(key)
            if (
                existing is not None
                and replace(existing, source_artifact_checksum=value.source_artifact_checksum)
                != value
            ):
                raise FilingNativeXbrlError("contradictory extension evidence across filings")
            all_semantics[key] = value
            semantic_checksums.setdefault(key, set()).add(value.source_artifact_checksum)
        identities.update(filing_identities)
    for facts, semantics in filing_evidence:
        if any(
            (fact.taxonomy, fact.concept) in all_semantics
            and (fact.taxonomy, fact.concept) not in semantics
            for fact in facts
        ):
            raise FilingNativeXbrlError("incomplete extension evidence across filings")
    return FilingNativeEvidence(
        tuple(all_facts),
        MappingProxyType(
            {
                key: replace(
                    value,
                    source_artifact_checksum=hashlib.sha256(
                        "".join(sorted(semantic_checksums[key])).encode()
                    ).hexdigest(),
                )
                for key, value in sorted(all_semantics.items())
            }
        ),
        tuple(sorted(identities)),
    )


def _parse_filing(
    filing: VerifiedFilingArtifacts,
) -> tuple[tuple[RawFact, ...], dict[tuple[str, str], SemanticEvidence], set[str]]:
    if (
        not filing.cik.isdigit()
        or len(filing.cik) != 10
        or filing.form not in {"10-K", "10-Q"}
        or filing.form.endswith("/A")
        or re.fullmatch(r"[0-9]{10}-[0-9]{2}-[0-9]{6}", filing.accession) is None
        or not 1 <= filing.fiscal_year <= 9999
        or filing.fiscal_period not in ({"FY"} if filing.form == "10-K" else {"Q1", "Q2", "Q3"})
        or filing.filing_date < filing.report_date
    ):
        raise FilingNativeXbrlError("invalid filing identity")
    parsed: list[_ParsedArtifact] = []
    identities: set[str] = set()
    for artifact in filing.artifacts:
        try:
            content = artifact.path.read_bytes()
        except OSError as exc:
            raise FilingNativeXbrlError("filing artifact is absent") from exc
        actual = hashlib.sha256(content).hexdigest()
        if actual != artifact.sha256:
            raise FilingNativeXbrlError("filing artifact checksum mismatch")
        identities.add(actual)
        suffix = artifact.path.suffix.lower()
        if suffix in {".htm", ".html", ".xhtml"} and b"inlineXBRL" not in content:
            continue
        if suffix not in {".xml", ".xsd", ".htm", ".html", ".xhtml"}:
            continue
        try:
            root, namespaces = _parse_xml(content)
            parsed.append((artifact, root, namespaces))
        except ET.ParseError as exc:
            raise FilingNativeXbrlError("malformed filing XML") from exc

    schemas = [item for item in parsed if item[1].tag == f"{{{_XSD}}}schema"]
    instances = [
        (artifact, root, ns) for artifact, root, ns in parsed if root.tag == f"{{{_XBRLI}}}xbrl"
    ]
    linkbases = [(root, ns) for _, root, ns in parsed if root.tag == f"{{{_LINK}}}linkbase"]
    inline = [
        (artifact, _inline_instance(root, ns), ns)
        for artifact, root, ns in parsed
        if root.tag != f"{{{_XBRLI}}}xbrl"
        and any(
            element.tag in {f"{{{uri}}}nonFraction" for uri in _INLINE_NAMESPACES}
            for element in root.iter()
        )
    ]
    if len(instances) > 1 or not (instances or inline):
        raise FilingNativeXbrlError(
            "filing requires an unambiguous XBRL instance or inline document"
        )

    concepts, schema_ids = _schema_concepts(schemas)
    presentations, calculations, labels = _relationships(linkbases, schema_ids)
    semantics = _semantic_extensions(concepts, presentations, calculations, labels, identities)
    facts = tuple(
        fact
        for artifact, instance, namespaces in instances + inline
        for fact in _instance_facts(filing, artifact.sha256, instance, namespaces, concepts)
    )
    return facts, semantics, identities


def _parse_xml(content: bytes) -> tuple[ET.Element, _NamespaceScopes]:
    """Parse the checksum-verified bytes once, retaining lexical QName scopes."""
    if b"<!DOCTYPE" in content.replace(b"\x00", b"").upper():
        raise FilingNativeXbrlError("DTD/entity declarations are not filing evidence")
    scopes: _NamespaceScopes = {}
    stack: list[dict[str, str]] = []
    pending: dict[str, str] = {}
    parser = ET.iterparse(BytesIO(content), events=("start-ns", "start", "end"))
    for event, item in parser:
        if event == "start-ns":
            prefix, uri = item
            pending[prefix or ""] = uri
        elif event == "start":
            scope = {**(stack[-1] if stack else {}), **pending}
            pending.clear()
            scopes[item] = scope
            stack.append(scope)
        else:
            stack.pop()
    return next(iter(scopes)), scopes


def _inline_instance(root: ET.Element, scopes: _NamespaceScopes) -> ET.Element:
    """Translate supported inline facts to the same XML instance parsing path."""
    instance = ET.Element(f"{{{_XBRLI}}}xbrl")
    scopes[instance] = scopes[root]

    continuations: dict[str, ET.Element] = {}
    for candidate in root.iter():
        if not candidate.tag.startswith("{"):
            continue
        namespace, local = _clark(candidate.tag)
        if namespace not in _INLINE_NAMESPACES or local != "continuation":
            continue
        identifier = candidate.attrib.get("id")
        if not identifier:
            raise FilingNativeXbrlError("inline continuation has no id")
        if identifier in continuations:
            raise FilingNativeXbrlError("duplicate inline continuation id")
        continuations[identifier] = candidate

    for element in root.iter():
        if element.tag in {f"{{{_XBRLI}}}context", f"{{{_XBRLI}}}unit"}:
            instance.append(element)
        if not element.tag.startswith("{"):
            continue
        namespace, local = _clark(element.tag)
        if namespace not in _INLINE_NAMESPACES:
            continue
        if local == "fraction":
            raise FilingNativeXbrlError("unsupported inline fraction")
        if local not in {"nonFraction", "nonNumeric"}:
            continue
        if element.attrib.get("target"):
            raise FilingNativeXbrlError("unsupported inline target")
        if local == "nonFraction" and element.attrib.get("continuedAt"):
            raise FilingNativeXbrlError("unsupported inline numeric continuation")
        fact_namespace, concept = _resolve_qname(element.attrib.get("name", ""), scopes[element])
        fact = ET.Element(f"{{{fact_namespace}}}{concept}", dict(element.attrib))
        text = _continued_inline_text(element, continuations).strip()

        if local == "nonNumeric":
            format_name = element.attrib.get("format")
            if format_name:
                format_namespace, transform = _resolve_qname(
                    format_name,
                    scopes[element],
                )
                if transform == "date-monthname-day-year-en":
                    if not re.fullmatch(
                        r"http://www.xbrl.org/inlineXBRL/transformation/[0-9-]+",
                        format_namespace,
                    ):
                        raise FilingNativeXbrlError("unsupported or invalid inline date transform")
                    try:
                        text = (
                            dt.datetime.strptime(
                                text,
                                "%B %d, %Y",
                            )
                            .date()
                            .isoformat()
                        )
                    except ValueError as exc:
                        raise FilingNativeXbrlError(
                            "unsupported or invalid inline date transform"
                        ) from exc

        if local == "nonFraction" and element.attrib.get(f"{{{_XSI}}}nil") not in {"true", "1"}:
            format_name = element.attrib.get("format")
            if format_name:
                format_namespace, transform = _resolve_qname(format_name, scopes[element])

                standard_transform = re.fullmatch(
                    r"http://www.xbrl.org/inlineXBRL/transformation/[0-9-]+",
                    format_namespace,
                )
                sec_numwords = (
                    format_namespace == "http://www.sec.gov/inlineXBRL/transformation/2015-08-31"
                    and transform == "numwordsen"
                )

                if sec_numwords:
                    text = str(_parse_sec_numwordsen(text))
                elif not standard_transform:
                    raise FilingNativeXbrlError("unsupported or invalid inline numeric transform")
                elif transform == "fixed-zero":
                    text = "0"
                elif transform in {"num-dot-decimal", "numdotdecimal"}:
                    if not re.fullmatch(
                        r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?",
                        text,
                    ):
                        raise FilingNativeXbrlError(
                            "unsupported or invalid inline numeric transform"
                        )
                    text = text.replace(",", "")
                else:
                    raise FilingNativeXbrlError("unsupported or invalid inline numeric transform")
            sign = element.attrib.get("sign")
            if sign not in {None, "-"}:
                raise FilingNativeXbrlError("invalid inline sign")
            if sign == "-":
                text = f"-{text}"
        fact.text = text
        scopes[fact] = scopes[element]
        instance.append(fact)
    return instance


def _parse_sec_numwordsen(value: str) -> int:
    """Parse the SEC ixt-sec:numwordsen integer transformation."""

    normalized = value.strip().lower().replace(",", " ").replace("-", " ")
    tokens = [token for token in normalized.split() if token != "and"]

    if tokens in (["no"], ["none"]):
        return 0
    if not tokens:
        raise FilingNativeXbrlError("unsupported SEC numwordsen value")

    units = {
        "zero": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
    }
    tens = {
        "twenty": 20,
        "thirty": 30,
        "forty": 40,
        "fifty": 50,
        "sixty": 60,
        "seventy": 70,
        "eighty": 80,
        "ninety": 90,
    }
    scales = {
        "thousand": 1_000,
        "million": 1_000_000,
        "billion": 1_000_000_000,
        "trillion": 1_000_000_000_000,
    }

    total = 0
    current = 0

    for token in tokens:
        if token in units:
            current += units[token]
        elif token in tens:
            current += tens[token]
        elif token == "hundred":
            if current == 0:
                raise FilingNativeXbrlError("unsupported SEC numwordsen value")
            current *= 100
        elif token in scales:
            if current == 0:
                raise FilingNativeXbrlError("unsupported SEC numwordsen value")
            total += current * scales[token]
            current = 0
        else:
            raise FilingNativeXbrlError("unsupported SEC numwordsen value")

    return total + current


def _continued_inline_text(
    element: ET.Element,
    continuations: dict[str, ET.Element],
) -> str:
    """Return inline text plus a validated continuedAt chain."""

    parts = [_inline_text(element)]
    reference = element.attrib.get("continuedAt")
    seen: set[str] = set()

    while reference:
        if reference in seen:
            raise FilingNativeXbrlError("inline continuation cycle")
        seen.add(reference)

        continuation = continuations.get(reference)
        if continuation is None:
            raise FilingNativeXbrlError("inline continuation reference is missing")

        parts.append(_inline_text(continuation))
        reference = continuation.attrib.get("continuedAt")

    return "".join(parts)


def _inline_text(element: ET.Element) -> str:
    parts = [element.text or ""]
    for child in element:
        if child.tag not in {f"{{{uri}}}exclude" for uri in _INLINE_NAMESPACES}:
            parts.append(_inline_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _schema_concepts(
    schemas: Iterable[_ParsedArtifact],
) -> tuple[dict[str, XbrlConcept], dict[tuple[str, str], str]]:
    concepts: dict[str, XbrlConcept] = {}
    schema_ids: dict[tuple[str, str], str] = {}
    for artifact, root, scopes in schemas:
        namespaces = scopes[root]
        target_namespace = root.attrib.get("targetNamespace")
        if not target_namespace:
            raise FilingNativeXbrlError("issuer schema has no target namespace")
        prefix = next((key for key, value in namespaces.items() if value == target_namespace), None)
        if not prefix:
            raise FilingNativeXbrlError("issuer schema target namespace has no prefix")
        for element in root.findall(f"{{{_XSD}}}element"):
            name = element.attrib.get("name")
            period_value = element.attrib.get(f"{{{_XBRLI}}}periodType")
            if not name or period_value not in {"duration", "instant"}:
                continue
            qname = f"{prefix}:{name}"
            if qname in concepts:
                raise FilingNativeXbrlError("duplicate schema concept")
            concepts[qname] = XbrlConcept(
                qname,
                target_namespace,
                element.attrib.get("type"),
                PeriodKind.DURATION if period_value == "duration" else PeriodKind.INSTANT,
                element.attrib.get(f"{{{_XBRLI}}}balance"),
                element.attrib.get("substitutionGroup"),
            )
            identifier = element.attrib.get("id")
            if identifier:
                if (artifact.path.name, identifier) in schema_ids:
                    raise FilingNativeXbrlError("duplicate schema concept id")
                schema_ids[(artifact.path.name, identifier)] = qname
    return concepts, schema_ids


def _relationships(
    linkbases: Iterable[tuple[ET.Element, _NamespaceScopes]],
    schema_ids: Mapping[tuple[str, str], str],
) -> tuple[
    tuple[XbrlPresentationArc, ...],
    tuple[XbrlCalculationArc, ...],
    dict[str, tuple[XbrlLabel, ...]],
]:
    presentations: list[XbrlPresentationArc] = []
    calculations: list[XbrlCalculationArc] = []
    label_map: dict[str, list[XbrlLabel]] = {}
    for root, _ in linkbases:
        for link in root:
            local = _local(link.tag)
            if local not in {"presentationLink", "calculationLink", "labelLink"}:
                continue
            if link.tag != f"{{{_LINK}}}{local}" or any(
                not child.tag.startswith(f"{{{_LINK}}}") for child in link
            ):
                raise FilingNativeXbrlError("untrusted linkbase namespace")
            role = link.attrib.get(f"{{{_XLINK}}}role", "")
            if not role:
                raise FilingNativeXbrlError("linkbase role is absent")
            locators = {
                child.attrib[f"{{{_XLINK}}}label"]: _href_qname(
                    child.attrib[f"{{{_XLINK}}}href"], schema_ids
                )
                for child in link
                if _local(child.tag) == "loc"
                and f"{{{_XLINK}}}label" in child.attrib
                and f"{{{_XLINK}}}href" in child.attrib
            }
            if len(locators) != sum(child.tag == f"{{{_LINK}}}loc" for child in link):
                raise FilingNativeXbrlError("duplicate or incomplete linkbase locator")
            if local == "presentationLink":
                for arc in (item for item in link if _local(item.tag) == "presentationArc"):
                    _validate_arc(arc, locators)
                    parent = locators.get(arc.attrib.get(f"{{{_XLINK}}}from", ""))
                    child = locators.get(arc.attrib.get(f"{{{_XLINK}}}to", ""))
                    if parent and child:
                        presentations.append(
                            XbrlPresentationArc(
                                parent,
                                child,
                                role,
                                _float_attribute(arc, "order", 0.0),
                                arc.attrib.get("preferredLabel"),
                            )
                        )
            elif local == "calculationLink":
                for arc in (item for item in link if _local(item.tag) == "calculationArc"):
                    _validate_arc(arc, locators)
                    if "weight" not in arc.attrib:
                        raise FilingNativeXbrlError("calculation weight is absent")
                    parent = locators.get(arc.attrib.get(f"{{{_XLINK}}}from", ""))
                    child = locators.get(arc.attrib.get(f"{{{_XLINK}}}to", ""))
                    if parent and child:
                        calculations.append(
                            XbrlCalculationArc(
                                parent,
                                child,
                                _float_attribute(arc, "weight", 1.0),
                                role,
                                True,
                            )
                        )
            else:
                resources = {
                    child.attrib[f"{{{_XLINK}}}label"]: XbrlLabel(
                        child.attrib.get(f"{{{_XLINK}}}role", ""),
                        (child.text or "").strip(),
                    )
                    for child in link
                    if _local(child.tag) == "label" and f"{{{_XLINK}}}label" in child.attrib
                }
                for arc in (item for item in link if _local(item.tag) == "labelArc"):
                    concept = locators.get(arc.attrib.get(f"{{{_XLINK}}}from", ""))
                    label = resources.get(arc.attrib.get(f"{{{_XLINK}}}to", ""))
                    if concept and label and label.text:
                        label_map.setdefault(concept, []).append(label)
    return (
        tuple(presentations),
        tuple(calculations),
        {key: tuple(value) for key, value in label_map.items()},
    )


def _semantic_extensions(
    concepts: Mapping[str, XbrlConcept],
    presentations: tuple[XbrlPresentationArc, ...],
    calculations: tuple[XbrlCalculationArc, ...],
    labels: Mapping[str, tuple[XbrlLabel, ...]],
    identities: set[str],
) -> dict[tuple[str, str], SemanticEvidence]:
    standard_metrics = _standard_metric_map()
    standard_periods = _standard_period_map()
    checksum = hashlib.sha256("".join(sorted(identities)).encode()).hexdigest()
    result: dict[tuple[str, str], SemanticEvidence] = {}
    for qname, concept in concepts.items():
        structural_parents = {
            arc.parent
            for arc in presentations
            if arc.child == qname and arc.parent in standard_periods
        } | {
            arc.parent
            for arc in calculations
            if arc.child == qname and arc.parent in standard_periods
        }
        if any(
            standard_periods[parent] is not concept.period_type for parent in structural_parents
        ):
            raise FilingNativeXbrlError("period-incompatible structural relationship")

        presentation_metrics = {
            standard_metrics[arc.parent]
            for arc in presentations
            if arc.child == qname and arc.parent in standard_metrics
        }
        calculation_metrics = {
            standard_metrics[arc.parent]
            for arc in calculations
            if arc.child == qname and arc.parent in standard_metrics
        }
        if (
            presentation_metrics
            and calculation_metrics
            and (presentation_metrics != calculation_metrics or len(presentation_metrics) != 1)
        ):
            raise FilingNativeXbrlError("contradictory structural relationships")
        common = presentation_metrics & calculation_metrics
        if len(common) != 1:
            continue
        target_metric, target_period = next(iter(common))
        if concept.period_type is not target_period:
            raise FilingNativeXbrlError("period-incompatible structural relationship")
        relevant_calculations = tuple(
            arc for arc in calculations if arc.child == qname and arc.parent in standard_metrics
        )
        if any(
            arc.weight != 1.0
            or not any(
                presentation.parent == arc.parent and presentation.role == arc.role
                for presentation in presentations
                if presentation.child == qname
            )
            for arc in relevant_calculations
        ):
            raise FilingNativeXbrlError("incompatible structural calculation evidence")
        prefix, local = qname.split(":", 1)
        result[(prefix, local)] = SemanticEvidence(
            concept,
            labels.get(qname, ()),
            XbrlRelationshipSet(
                tuple(arc for arc in presentations if arc.child == qname),
                tuple(arc for arc in calculations if arc.child == qname),
            ),
            target_metric,
            checksum,
        )
    return result


def _promotion_period_kind(strategy: PromotionStrategy) -> PeriodKind | None:
    if strategy in {
        PromotionStrategy.DIRECT_INSTANT,
        PromotionStrategy.COMPOSITE_INSTANT,
        PromotionStrategy.DERIVED_INSTANT,
    }:
        return PeriodKind.INSTANT
    if strategy in {
        PromotionStrategy.DIRECT_DURATION,
        PromotionStrategy.TTM_DURATION,
        PromotionStrategy.COMPOSITE_DURATION,
    }:
        return PeriodKind.DURATION
    return None


def _standard_period_map() -> dict[str, PeriodKind]:
    periods: dict[str, set[PeriodKind]] = {}

    def record(qname: str, period_kind: PeriodKind) -> None:
        periods.setdefault(qname, set()).add(period_kind)

    # Canonical SEC concepts provide taxonomy semantics even when a concept is
    # not itself an input to the Reverse-DCF accounting promotion layer.
    for spec in INITIAL_METRIC_SPECS:
        record(
            f"{spec.standard_taxonomy}:{spec.standard_concept}",
            spec.period_kind,
        )
        for alias in spec.approved_aliases:
            record(f"{spec.standard_taxonomy}:{alias}", spec.period_kind)

    # Accounting promotion policies add the larger set of model-required
    # concepts used by the cold-ticker gate.
    def visit(policy: MetricPromotionPolicy) -> None:
        period_kind = _promotion_period_kind(policy.strategy)
        if period_kind is not None:
            for concept in policy.concepts:
                record(f"{policy.taxonomy}:{concept}", period_kind)
        for nested in policy.dependencies + policy.alternatives:
            visit(nested)

    for policy in accounting_evidence_policies():
        visit(policy)

    return {qname: next(iter(kinds)) for qname, kinds in periods.items() if len(kinds) == 1}


def _standard_metric_map() -> dict[str, tuple[str, PeriodKind]]:
    metrics: dict[str, set[tuple[str, PeriodKind]]] = {}

    def visit(policy: MetricPromotionPolicy) -> None:
        period_kind = _promotion_period_kind(policy.strategy)
        if period_kind is not None:
            for concept in policy.concepts:
                metrics.setdefault(f"{policy.taxonomy}:{concept}", set()).add(
                    (policy.metric_id, period_kind)
                )
        for nested in policy.dependencies + policy.alternatives:
            visit(nested)

    for policy in accounting_evidence_policies():
        visit(policy)
    return {qname: next(iter(values)) for qname, values in metrics.items() if len(values) == 1}


def _instance_facts(
    filing: VerifiedFilingArtifacts,
    source_identity: str,
    root: ET.Element,
    namespaces: _NamespaceScopes,
    concepts: Mapping[str, XbrlConcept],
) -> tuple[RawFact, ...]:
    contexts = _contexts(root, filing.cik)
    units = _units(root, namespaces)
    uri_prefixes = {uri: prefix for prefix, uri in namespaces[root].items() if prefix}
    uri_prefixes.update(
        {concept.namespace: qname.split(":")[0] for qname, concept in concepts.items()}
    )
    _validate_dei_identity(root, filing)
    result: list[RawFact] = []
    for index, element in enumerate(root):
        context_ref = element.attrib.get("contextRef")
        unit_ref = element.attrib.get("unitRef")
        if context_ref is None or unit_ref is None:
            if any(key in element.attrib for key in ("unitRef", "decimals", "precision")):
                raise FilingNativeXbrlError("numeric fact is missing context or unit")
            continue
        if element.attrib.get(f"{{{_XSI}}}nil") in {"true", "1"}:
            continue
        context = contexts.get(context_ref)
        unit = units.get(unit_ref)
        if context is None or unit is None:
            raise FilingNativeXbrlError("fact has unresolved context or unit")
        namespace, local = _clark(element.tag)
        prefix = uri_prefixes.get(namespace) or next(
            (key for key, uri in namespaces[element].items() if key and uri == namespace), None
        )
        if prefix is None:
            raise FilingNativeXbrlError("fact namespace has no stable prefix")
        taxonomy = _taxonomy(prefix, namespace)
        try:
            text = (element.text or "").strip()
            if not re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", text):
                raise ValueError
            exact = Decimal(text)
            scale = int(element.attrib.get("scale", "0"))
            with localcontext() as decimal_context:
                decimal_context.prec = max(28, len(exact.as_tuple().digits))
                scaled = exact.scaleb(scale)
            value = float(scaled)
        except (TypeError, ValueError, OverflowError, DecimalException) as exc:
            raise FilingNativeXbrlError("non-numeric filing fact") from exc
        if not math.isfinite(value) or (value == 0 and exact != 0):
            raise FilingNativeXbrlError("non-finite or underflowed filing fact")
        qname = f"{prefix}:{local}"
        concept = concepts.get(qname)
        if concept is not None and concept.namespace != namespace:
            raise FilingNativeXbrlError("fact namespace contradicts schema concept")
        kind = PeriodKind.DURATION if context.start is not None else PeriodKind.INSTANT
        if concept is not None and concept.period_type is not kind:
            raise FilingNativeXbrlError("fact context contradicts schema period type")
        result.append(
            RawFact(
                element.attrib.get("id") or f"{filing.accession}:{index}",
                taxonomy,
                local,
                value,
                unit,
                kind,
                context.start,
                context.end,
                filing.fiscal_year,
                filing.fiscal_period,
                filing.form,
                filing.accession,
                filing.filing_date,
                source_identity,
                context.dimensions,
                not context.dimensions,
                False,
                False,
                None,
                concept.data_type if concept else None,
                concept.balance if concept else None,
            )
        )
    return tuple(result)


def _contexts(root: ET.Element, cik: str) -> dict[str, _Context]:
    result: dict[str, _Context] = {}
    for element in root.findall(f"{{{_XBRLI}}}context"):
        identifier = element.find(f".//{{{_XBRLI}}}identifier")
        if (
            identifier is None
            or identifier.attrib.get("scheme") != "http://www.sec.gov/CIK"
            or (identifier.text or "").strip().zfill(10) != cik
        ):
            raise FilingNativeXbrlError("XBRL context CIK mismatch")
        period = element.find(f"{{{_XBRLI}}}period")
        if period is None:
            raise FilingNativeXbrlError("XBRL context has no period")
        instant = period.find(f"{{{_XBRLI}}}instant")
        start_element = period.find(f"{{{_XBRLI}}}startDate")
        end_element = period.find(f"{{{_XBRLI}}}endDate")
        try:
            if instant is not None:
                if len(period) != 1:
                    raise ValueError
                start = None
                end = date.fromisoformat((instant.text or "").strip())
            elif start_element is not None and end_element is not None:
                start = date.fromisoformat((start_element.text or "").strip())
                end = date.fromisoformat((end_element.text or "").strip())
                if len(period) != 2 or start > end:
                    raise ValueError
            else:
                raise ValueError
        except ValueError as exc:
            raise FilingNativeXbrlError("XBRL context period is invalid") from exc
        dimensions = tuple(
            sorted(
                [
                    f"{member.attrib.get('dimension', '')}={(member.text or '').strip()}"
                    for member in element.findall(f".//{{{_XBRLDI}}}explicitMember")
                ]
                + [
                    f"{member.attrib.get('dimension', '')}="
                    f"{ET.tostring(member, encoding='unicode')}"
                    for member in element.findall(f".//{{{_XBRLDI}}}typedMember")
                ]
            )
        )
        for container in (
            *element.iter(f"{{{_XBRLI}}}segment"),
            *element.iter(f"{{{_XBRLI}}}scenario"),
        ):
            seen: set[str] = set()
            for member in container:
                dimension = member.attrib.get("dimension")
                if (
                    member.tag not in {f"{{{_XBRLDI}}}explicitMember", f"{{{_XBRLDI}}}typedMember"}
                    or not dimension
                    or dimension in seen
                ):
                    raise FilingNativeXbrlError("unsupported or duplicate context dimension")
                seen.add(dimension)
                if member.tag == f"{{{_XBRLDI}}}typedMember" and len(member) != 1:
                    raise FilingNativeXbrlError("invalid typed dimension")
                if member.tag == f"{{{_XBRLDI}}}explicitMember" and not (member.text or "").strip():
                    raise FilingNativeXbrlError("invalid explicit dimension")
        identifier_value = element.attrib.get("id")
        if not identifier_value or identifier_value in result:
            raise FilingNativeXbrlError("duplicate or missing XBRL context id")
        result[identifier_value] = _Context(start, end, dimensions)
    return result


def _units(root: ET.Element, namespaces: _NamespaceScopes) -> dict[str, str]:
    def measure_value(measure: ET.Element) -> str:
        namespace, value = _resolve_qname((measure.text or "").strip(), namespaces[measure])
        return (
            value
            if namespace == "http://www.xbrl.org/2003/iso4217"
            or (namespace == _XBRLI and value in {"shares", "pure"})
            else f"{{{namespace}}}{value}"
        )

    def product(container: ET.Element) -> str:
        measures = container.findall(f"{{{_XBRLI}}}measure")
        if not measures or len(measures) != len(container):
            raise FilingNativeXbrlError("unsupported XBRL unit measures")
        return "*".join(sorted(measure_value(measure) for measure in measures))

    result: dict[str, str] = {}
    for element in root.findall(f"{{{_XBRLI}}}unit"):
        identifier = element.attrib.get("id")
        if not identifier:
            raise FilingNativeXbrlError("unsupported XBRL unit")
        divide = element.find(f"{{{_XBRLI}}}divide")
        if divide is None:
            unit = product(element)
        else:
            numerator = divide.find(f"{{{_XBRLI}}}unitNumerator")
            denominator = divide.find(f"{{{_XBRLI}}}unitDenominator")
            if len(element) != 1 or len(divide) != 2 or numerator is None or denominator is None:
                raise FilingNativeXbrlError("invalid divided XBRL unit")
            unit = f"{product(numerator)}/{product(denominator)}"
        if identifier in result and result[identifier] != unit:
            raise FilingNativeXbrlError("contradictory XBRL unit")
        result[identifier] = unit
    return result


def _validate_arc(arc: ET.Element, locators: Mapping[str, str]) -> None:
    if arc.attrib.get("use", "optional") != "optional":
        raise FilingNativeXbrlError("unsupported linkbase arc use")
    if any(arc.attrib.get(f"{{{_XLINK}}}{end}") not in locators for end in ("from", "to")):
        raise FilingNativeXbrlError("unresolved linkbase arc locator")


def _href_qname(href: str, schema_ids: Mapping[tuple[str, str], str]) -> str:
    document, separator, fragment = href.partition("#")
    basename = document.rsplit("/", 1)[-1]
    is_local_basename = document == basename and "\\" not in document

    # Issuer-extension concepts must resolve to an artifact-local schema id.
    # A remote/path-qualified document may not impersonate a verified schema
    # merely by reusing its basename.
    known = schema_ids.get((basename, fragment)) if is_local_basename else None
    if known is not None:
        return known

    if not separator or "_" not in fragment:
        raise FilingNativeXbrlError("linkbase locator has no verified schema concept")

    prefix, local = fragment.split("_", 1)
    if prefix not in {
        "us-gaap",
        "srt",
        "dei",
        "ecd",
        "stpr",
        "country",
    } or not basename.startswith(prefix):
        raise FilingNativeXbrlError("linkbase locator has no verified schema concept")

    parsed = urlsplit(document)
    if parsed.scheme or parsed.netloc:
        hostname = (parsed.hostname or "").lower()
        fasb_taxonomies = {"us-gaap", "srt"}
        sec_taxonomies = {"srt", "dei", "ecd", "stpr", "country"}

        trusted_remote = (
            prefix in fasb_taxonomies and (hostname == "fasb.org" or hostname.endswith(".fasb.org"))
        ) or (prefix in sec_taxonomies and hostname == "xbrl.sec.gov")
        if parsed.scheme not in {"http", "https"} or not trusted_remote or bool(parsed.query):
            raise FilingNativeXbrlError("linkbase locator has no verified schema concept")
    elif not is_local_basename:
        raise FilingNativeXbrlError("linkbase locator has no verified schema concept")

    return f"{prefix}:{local}"


def _resolve_qname(text: str, namespaces: Mapping[str, str]) -> tuple[str, str]:
    prefix, separator, local = text.partition(":")
    if not separator:
        prefix, local = "", prefix
    namespace = namespaces.get(prefix)
    if not namespace or not local:
        raise FilingNativeXbrlError("unresolved QName namespace")
    return namespace, local


def _validate_dei_identity(root: ET.Element, filing: VerifiedFilingArtifacts) -> None:
    expected = {
        "DocumentType": filing.form,
        "DocumentPeriodEndDate": filing.report_date.isoformat(),
        "DocumentFiscalYearFocus": str(filing.fiscal_year),
        "DocumentFiscalPeriodFocus": filing.fiscal_period,
        "EntityCentralIndexKey": filing.cik,
    }
    for element in root:
        namespace, local = _clark(element.tag)
        if re.fullmatch(r"https?://xbrl.sec.gov/dei/[0-9-]+", namespace) and local in expected:
            value = (element.text or "").strip()
            if local == "EntityCentralIndexKey":
                value = value.zfill(10)
            if value != expected[local]:
                raise FilingNativeXbrlError("DEI filing identity mismatch")


def _float_attribute(element: ET.Element, name: str, default: float) -> float:
    try:
        value = float(element.attrib.get(name, str(default)))
    except ValueError as exc:
        raise FilingNativeXbrlError(f"invalid linkbase {name}") from exc
    if not math.isfinite(value):
        raise FilingNativeXbrlError(f"non-finite linkbase {name}")
    return value


def _taxonomy(prefix: str, namespace: str) -> str:
    if re.fullmatch(r"https?://fasb.org/us-gaap/[0-9-]+", namespace):
        return "us-gaap"
    if prefix == "us-gaap":
        raise FilingNativeXbrlError("untrusted standard taxonomy namespace")
    return prefix


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _clark(tag: str) -> tuple[str, str]:
    if not tag.startswith("{") or "}" not in tag:
        raise FilingNativeXbrlError("unqualified XBRL fact")
    namespace, local = tag[1:].split("}", 1)
    return namespace, local
