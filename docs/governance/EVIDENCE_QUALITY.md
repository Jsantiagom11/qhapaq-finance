# Evidence Quality Foundation v0.1

Qhapaq separates raw source artifacts, source manifests, extracted facts,
normalized facts, canonical facts, quality reports, and downstream research
artifacts. Raw artifacts are immutable: their SHA-256 must equal the value in
their versioned source manifest. A source can be authoritative and still fail
data quality if a parser maps its unit or period incorrectly.

`evidence-quality-profile-v1` is declarative issuer evidence metadata. It
defines the source manifests, critical facts, allowed TTM reconstructions, and
optional accounting checks. It is evaluated offline into a deterministic
quality report. Blocking failures (provenance, source integrity,
normalization, period/unit semantics, TTM compatibility, or fact completeness)
make deterministic research unavailable. A file existing is only a
prerequisite, never readiness proof.

TTM reconstruction is only allowed for declared duration contracts and uses
`FY - prior comparable YTD + current YTD`; inconsistent units, concepts, or
durations fail closed. Reconciliations, when a profile supplies them, compare
declared left/right fact sets using an explicit absolute tolerance and never
overwrite a fact. No reconciliation is reported as `NOT_APPLICABLE`.

Source manifests retain supersession links. An amendment supersedes an earlier
source for canonical selection; both artifacts remain auditable. Equal-ranked,
incompatible candidate facts fail with `QUALITY_SOURCE_CONFLICT`; sources are
never averaged. Golden facts are profile data with metric, unit, period, and
value context, so parser regressions fail loudly.

`explain_fact` returns the metric, normalized context, source locator,
transformation, raw artifact path, and SHA-256 for a fact. Current QCOM/NVDA
facts are legacy extracted records wrapped by this generic contract; their
existing valuation-specific accounting gates remain in place.

An Evidence Auditor agent may flag suspicious context, duplicate candidates,
or taxonomy ambiguity. Its findings are non-authoritative diagnostics: it may
not change numbers, infer units, repair missing periods, accept sources, or
override quality/readiness. Agent research remains downstream of a passing
deterministic quality report and a deterministic provider-compatible artifact.

Implemented: offline manifests, integrity, semantic gates, TTM contracts,
lineage, golden regressions, and readiness integration. Deferred: SEC/XBRL
network ingestion, downloaders, PDF/OCR extraction, and new issuer onboarding.
