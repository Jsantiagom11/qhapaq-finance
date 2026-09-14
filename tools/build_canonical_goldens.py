#!/usr/bin/env python3
"""Build immutable, source-led canonicalization goldens from sec-corpus-v2.

This is an audit utility, not a resolver.  Its selections are deliberately
spelled out below after reviewing the frozen filing facts; it never imports
production canonicalization code or ranks candidates.
"""

from __future__ import annotations

import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

CORPUS = Path("tests/fixtures/sec_corpus")
OUT = Path("tests/fixtures/canonical_goldens/v1")
METRICS = (
    "revenue",
    "operating_income",
    "net_income",
    "cash_and_equivalents",
    "total_debt",
    "total_assets",
    "total_liabilities",
    "shareholders_equity",
    "diluted_shares",
)

# Explicit, reviewed observations.  Values are in the SEC-reported units.
# Debt is intentionally conservative: AMZN has incompatible face/carrying
# presentations and VRTX has no quantified debt observation, so neither is
# promoted to RESOLVED.
SOURCES: dict[str, dict[str, tuple[str, int | None, str | None, str | None]]] = {
    "AAPL": {
        "revenue": (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            416161000000,
            None,
            "STANDARD_CONCEPT",
        ),
        "operating_income": ("OperatingIncomeLoss", 133050000000, None, "STANDARD_CONCEPT"),
        "net_income": ("NetIncomeLoss", 112010000000, None, "STANDARD_CONCEPT"),
        "cash_and_equivalents": (
            "CashAndCashEquivalentsAtCarryingValue",
            35934000000,
            None,
            "STANDARD_CONCEPT",
        ),
        "total_debt": (
            "DerivedLongTermDebtAndCommercialPaper",
            98657000000,
            "LongTermDebtCurrent=12350000000 + LongTermDebtNoncurrent=78328000000 + "
            "CommercialPaper=7979000000",
            "DERIVED",
        ),
        "total_assets": ("Assets", 359241000000, None, "STANDARD_CONCEPT"),
        "total_liabilities": ("Liabilities", 285508000000, None, "STANDARD_CONCEPT"),
        "shareholders_equity": ("StockholdersEquity", 73733000000, None, "STANDARD_CONCEPT"),
        "diluted_shares": (
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            15004697000,
            None,
            "STANDARD_CONCEPT",
        ),
    },
    "QCOM": {
        "revenue": ("Revenues", 44284000000, None, None),
        "operating_income": ("OperatingIncomeLoss", 12355000000, None, "STANDARD_CONCEPT"),
        "net_income": ("NetIncomeLoss", 5541000000, None, "STANDARD_CONCEPT"),
        "cash_and_equivalents": (
            "CashAndCashEquivalentsAtCarryingValue",
            5520000000,
            None,
            "STANDARD_CONCEPT",
        ),
        "total_debt": ("DebtLongtermAndShorttermCombinedAmount", 14811000000, None, None),
        "total_assets": ("Assets", 50143000000, None, "STANDARD_CONCEPT"),
        "total_liabilities": ("Liabilities", 28937000000, None, "STANDARD_CONCEPT"),
        "shareholders_equity": (
            "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
            21206000000,
            None,
            "STANDARD_ALIAS",
        ),
        "diluted_shares": (
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            1105000000,
            None,
            "STANDARD_CONCEPT",
        ),
    },
    "NVDA": {
        "revenue": ("Revenues", 215938000000, None, None),
        "operating_income": ("OperatingIncomeLoss", 130387000000, None, "STANDARD_CONCEPT"),
        "net_income": ("NetIncomeLoss", 120067000000, None, "STANDARD_CONCEPT"),
        "cash_and_equivalents": (
            "CashAndCashEquivalentsAtCarryingValue",
            10605000000,
            None,
            "STANDARD_CONCEPT",
        ),
        "total_debt": (
            "DerivedLongTermDebt",
            8468000000,
            "LongTermDebtCurrent=999000000 + LongTermDebtNoncurrent=7469000000",
            "DERIVED",
        ),
        "total_assets": ("Assets", 206803000000, None, "STANDARD_CONCEPT"),
        "total_liabilities": ("Liabilities", 49510000000, None, "STANDARD_CONCEPT"),
        "shareholders_equity": ("StockholdersEquity", 157293000000, None, "STANDARD_CONCEPT"),
        "diluted_shares": (
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            24514000000,
            None,
            "STANDARD_CONCEPT",
        ),
    },
    "COST": {
        "revenue": (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            275235000000,
            None,
            "STANDARD_CONCEPT",
        ),
        "operating_income": ("OperatingIncomeLoss", 10383000000, None, "STANDARD_CONCEPT"),
        "net_income": ("NetIncomeLoss", 8099000000, None, "STANDARD_CONCEPT"),
        "cash_and_equivalents": (
            "CashAndCashEquivalentsAtCarryingValue",
            14161000000,
            None,
            "STANDARD_CONCEPT",
        ),
        "total_debt": ("DebtInstrumentCarryingAmount", 5805000000, None, None),
        "total_assets": ("Assets", 77099000000, None, "STANDARD_CONCEPT"),
        "total_liabilities": ("Liabilities", 47935000000, None, "STANDARD_CONCEPT"),
        "shareholders_equity": ("StockholdersEquity", 29164000000, None, "STANDARD_CONCEPT"),
        "diluted_shares": (
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            444803000,
            None,
            "STANDARD_CONCEPT",
        ),
    },
    "AMZN": {
        "revenue": (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            716924000000,
            None,
            "STANDARD_CONCEPT",
        ),
        "operating_income": ("OperatingIncomeLoss", 79975000000, None, "STANDARD_CONCEPT"),
        "net_income": ("NetIncomeLoss", 77670000000, None, "STANDARD_CONCEPT"),
        "cash_and_equivalents": (
            "CashAndCashEquivalentsAtCarryingValue",
            86810000000,
            None,
            "STANDARD_CONCEPT",
        ),
        "total_debt": (
            "LongTermDebt",
            None,
            "AMBIGUOUS: LongTermDebt=68836000000 (face value) conflicts with "
            "LongTermDebtCurrent + LongTermDebtNoncurrent=68396000000 (carrying "
            "components); ShortTermBorrowings=455000000 is separately reported.",
            None,
        ),
        "total_assets": ("Assets", 818042000000, None, "STANDARD_CONCEPT"),
        "total_liabilities": (
            "",
            None,
            "MISSING: the selected filing has LiabilitiesAndStockholdersEquity and "
            "component liabilities, but no consolidated Liabilities fact; no aggregation "
            "rule is introduced.",
            None,
        ),
        "shareholders_equity": ("StockholdersEquity", 411065000000, None, "STANDARD_CONCEPT"),
        "diluted_shares": (
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            10827000000,
            None,
            "STANDARD_CONCEPT",
        ),
    },
    "VRTX": {
        "revenue": (
            "RevenueFromContractWithCustomerExcludingAssessedTax",
            12001300000,
            None,
            "STANDARD_CONCEPT",
        ),
        "operating_income": ("OperatingIncomeLoss", 4173300000, None, "STANDARD_CONCEPT"),
        "net_income": ("NetIncomeLoss", 3953200000, None, "STANDARD_CONCEPT"),
        "cash_and_equivalents": (
            "CashAndCashEquivalentsAtCarryingValue",
            5084800000,
            None,
            "STANDARD_CONCEPT",
        ),
        "total_debt": (
            "",
            None,
            "MISSING: no quantified debt or borrowing balance in the selected 10-K; "
            "lease liabilities are not substituted.",
            None,
        ),
        "total_assets": ("Assets", 25643000000, None, "STANDARD_CONCEPT"),
        "total_liabilities": ("Liabilities", 6977200000, None, "STANDARD_CONCEPT"),
        "shareholders_equity": ("StockholdersEquity", 18665800000, None, "STANDARD_CONCEPT"),
        "diluted_shares": (
            "WeightedAverageNumberOfDilutedSharesOutstanding",
            258000000,
            None,
            "STANDARD_CONCEPT",
        ),
    },
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def _observation(
    companyfacts: dict[str, Any], concept: str, accession: str, report_date: str, value: int
) -> dict[str, Any]:
    for taxonomy, concepts in companyfacts["facts"].items():
        if concept not in concepts:
            continue
        for unit, observations in concepts[concept]["units"].items():
            for item in observations:
                if (
                    item.get("accn") == accession
                    and item.get("end") == report_date
                    and item.get("val") == value
                    and item.get("form") == "10-K"
                ):
                    return {"taxonomy": taxonomy, "unit": unit, "fact": item}
    raise ValueError(f"selected fact unavailable: {concept} {value} {accession}")


def _xbrl_corresponds(path: Path, concept: str, report_date: str, value: int) -> bool:
    """Confirm the selected entity-level value exists in the filing inline XBRL."""
    root = ET.parse(path).getroot()
    ns = {"ix": "http://www.xbrl.org/2013/inlineXBRL", "xbrli": "http://www.xbrl.org/2003/instance"}
    contexts = {item.get("id"): item for item in root.findall(".//xbrli:context", ns)}
    for item in root.findall(".//ix:nonFraction", ns):
        if item.get("name") != f"us-gaap:{concept}":
            continue
        context = contexts.get(item.get("contextRef"))
        period_end = (
            context.findtext("xbrli:period/xbrli:endDate", namespaces=ns)
            if context is not None
            else None
        )
        instant = (
            context.findtext("xbrli:period/xbrli:instant", namespaces=ns)
            if context is not None
            else None
        )
        if context is None or report_date not in {period_end, instant}:
            continue
        if context.find(".//xbrli:segment", ns) is not None:
            continue
        try:
            raw = "".join(item.itertext()).strip().replace(",", "")
            observed = int(float(raw) * (10 ** int(item.get("scale", "0"))))
        except ValueError:
            continue
        if item.get("sign") == "-":
            observed = -observed
        if observed == value:
            return True
    return False


def _metric(
    ticker: str,
    name: str,
    selection: tuple[str, int | None, str | None, str | None],
    issuer: dict[str, Any],
    cf: dict[str, Any],
    filing_artifact: dict[str, Any],
) -> dict[str, Any]:
    concept, value, detail, method = selection
    filing = issuer["selected_filings"]["10-K"]
    is_duration = name in {"revenue", "operating_income", "net_income", "diluted_shares"}
    status = (
        "RESOLVED"
        if value is not None
        else ("AMBIGUOUS" if ticker == "AMZN" and name == "total_debt" else "MISSING")
    )
    record: dict[str, Any] = {
        "expected_status": status,
        "metric": name,
        "ticker": ticker,
        "filing_form": "10-K",
        "source_accession": filing["accession"],
        "filed_date": filing["filing_date"],
        "report_date": filing["report_date"],
        "source_artifact_path": filing_artifact["path"],
        "source_artifact_sha256": filing_artifact["sha256"],
        "source_concept_qname": f"us-gaap:{concept}" if concept else None,
        "period_kind": "DURATION" if is_duration else "INSTANT",
        "dimensional_context": "consolidated entity-level; no dimensions used",
        "resolution_rationale": detail
        or "Selected consolidated observation corroborates companyfacts and filing inline XBRL.",
    }
    if value is not None:
        # A derived debt total has no synthetic SEC fact.  Preserve every
        # additive component instead of pretending that it is a reported one.
        if method == "DERIVED":
            components = []
            for token in (detail or "").split(" + "):
                component, raw_value = token.split("=")
                item = _observation(
                    cf, component, filing["accession"], filing["report_date"], int(raw_value)
                )
                if not _xbrl_corresponds(
                    CORPUS / ticker / filing_artifact["path"],
                    component,
                    filing["report_date"],
                    int(raw_value),
                ):
                    raise ValueError(f"filing XBRL does not corroborate {ticker} {component}")
                components.append(
                    {
                        "source_concept_qname": f"{item['taxonomy']}:{component}",
                        "value": int(raw_value),
                        "unit": item["unit"],
                    }
                )
            evidence = {"taxonomy": "us-gaap", "unit": "USD", "fact": {"start": None}}
            record["derivation"] = {"operator": "sum", "components": components}
        else:
            evidence = _observation(cf, concept, filing["accession"], filing["report_date"], value)
            if not _xbrl_corresponds(
                CORPUS / ticker / filing_artifact["path"], concept, filing["report_date"], value
            ):
                raise ValueError(f"filing XBRL does not corroborate {ticker} {concept}")
        period = (
            {"start_date": evidence["fact"].get("start"), "end_date": filing["report_date"]}
            if is_duration
            else {"instant": filing["report_date"]}
        )
        record.update(
            {
                "expected_normalized_value": value,
                "normalized_unit": evidence["unit"],
                "taxonomy": evidence["taxonomy"],
                "period": period,
                "companyfacts_corroboration": {
                    "path": "companyfacts.json",
                    "sha256": issuer["companyfacts"]["sha256"],
                    "fact_identity": {
                        key: evidence["fact"].get(key)
                        for key in (
                            "accn",
                            "form",
                            "filed",
                            "fy",
                            "fp",
                            "start",
                            "end",
                            "val",
                            "frame",
                        )
                    },
                },
            }
        )
        if method:
            record["expected_resolution_method"] = method
    return record


def build() -> dict[str, Any]:
    root_manifest = json.loads((CORPUS / "manifest.json").read_text())
    issuers: list[dict[str, str]] = []
    for ticker in sorted(SOURCES):
        issuer_path = CORPUS / ticker / "manifest.json"
        issuer = json.loads(issuer_path.read_text())
        cf = json.loads((CORPUS / ticker / "companyfacts.json").read_text())
        filing = issuer["selected_filings"]["10-K"]
        artifact = next(
            x for x in issuer["artifacts"] if x["path"].endswith("/" + filing["primary_document"])
        )
        if (
            _sha(CORPUS / ticker / artifact["path"]) != artifact["sha256"]
            or _sha(CORPUS / ticker / "companyfacts.json") != issuer["companyfacts"]["sha256"]
        ):
            raise ValueError(f"broken frozen provenance for {ticker}")
        payload = {
            "schema_version": "canonical-golden-v1",
            "ticker": ticker,
            "CIK": issuer["cik"],
            "source_corpus_version": root_manifest["schema_version"],
            "source_issuer_manifest_sha256": _sha(issuer_path),
            "target_fiscal_year": next(iter(cf["facts"].values()))
            and max(
                i.get("fy", 0) or 0
                for concepts in cf["facts"].values()
                for d in concepts.values()
                for rows in d["units"].values()
                for i in rows
                if i.get("accn") == filing["accession"]
            ),
            "target_report_date": filing["report_date"],
            "metrics": [
                _metric(ticker, metric, SOURCES[ticker][metric], issuer, cf, artifact)
                for metric in METRICS
            ],
            "evidence_notes": [
                "Frozen companyfacts and selected filing inline XBRL were reviewed; "
                "no dimensional observation is selected."
            ],
        }
        content = _canonical(payload)
        target = OUT / f"{ticker}.json"
        if target.exists() and target.read_bytes() != content:
            raise RuntimeError(f"immutable v1 conflict: {target}; create a version bump")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        issuers.append(
            {
                "ticker": ticker,
                "path": f"{ticker}.json",
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    manifest = {
        "schema_version": "canonical-golden-manifest-v1",
        "sec_corpus_root_manifest_sha256": _sha(CORPUS / "manifest.json"),
        "issuer_goldens": issuers,
    }
    content = _canonical(manifest)
    target = OUT / "manifest.json"
    if target.exists() and target.read_bytes() != content:
        raise RuntimeError("immutable v1 conflict: manifest; create a version bump")
    target.write_bytes(content)
    matrix = [
        "# SEC canonical goldens v1 — audit matrix",
        "",
        "| Ticker | Metric | Status | Value | Unit | Source concept | Accession | "
        "Period | Confidence | Notes |",
        "|---|---|---|---:|---|---|---|---|---|---|",
    ]
    for issuer in issuers:
        golden = json.loads((OUT / issuer["path"]).read_text())
        for item in golden["metrics"]:
            period = (
                item["period"].get("instant") if "period" in item else golden["target_report_date"]
            )
            if "period" in item and "end_date" in item["period"]:
                period = f"{item['period']['start_date']}–{item['period']['end_date']}"
            confidence = (
                "high" if item["expected_status"] == "RESOLVED" else "preserved uncertainty"
            )
            notes = item["resolution_rationale"].replace("|", "/")
            matrix.append(
                (
                    "| {ticker} | {metric} | {status} | {value} | {unit} | {concept} | "
                    "{accession} | {period} | {confidence} | {notes} |"
                ).format(
                    ticker=item["ticker"],
                    metric=item["metric"],
                    status=item["expected_status"],
                    value=item.get("expected_normalized_value", "—"),
                    unit=item.get("normalized_unit", "—"),
                    concept=item.get("source_concept_qname", "—"),
                    accession=item["source_accession"],
                    period=period,
                    confidence=confidence,
                    notes=notes,
                )
            )
    matrix_target = OUT / "AUDIT_MATRIX.md"
    matrix_content = ("\n".join(matrix) + "\n").encode()
    if matrix_target.exists() and matrix_target.read_bytes() != matrix_content:
        raise RuntimeError("immutable v1 conflict: audit matrix; create a version bump")
    matrix_target.write_bytes(matrix_content)
    return manifest


if __name__ == "__main__":
    build()
