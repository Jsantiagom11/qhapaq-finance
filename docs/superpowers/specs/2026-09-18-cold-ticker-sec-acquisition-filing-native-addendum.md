# Cold-Ticker SEC Acquisition — Filing-Native Bridge Addendum

This addendum is authoritative together with `2026-09-18-cold-ticker-sec-acquisition-v2-design.md` and closes an implementation dependency discovered during plan review.

## Why this addendum exists

Downloading filing artifacts alone cannot repair a canonical SEC gap. The current generic accounting path promotes from SEC `companyfacts`; `LocalSecCorpus` validates filing artifacts but does not feed filing-native XBRL facts or extension relationships into generic accounting promotion.

Therefore a filing fallback is only meaningful if acquired filing-native artifacts are converted into the existing financial canonicalization vocabulary and then allowed to repair only the unresolved canonical requirements.

## Required bridge

Introduce one focused filing-native XBRL bridge, preferably `src/qhapaq_finance/sec_filing_xbrl.py` unless repository inspection identifies a more coherent existing boundary.

The bridge consumes only verified local filing artifacts and produces existing canonicalization inputs. It does not perform HTTP and does not calculate finance.

### Inputs

A validated filing artifact set for one or more selected original 10-K/10-Q filings:

- extracted XBRL instance XML when available;
- issuer XSD;
- label linkbase;
- presentation linkbase;
- calculation linkbase;
- primary filing/iXBRL document only when needed to recover facts not present in an extracted instance;
- filing identity: accession, form, filing/report dates, CIK, checksums.

### Outputs

Reuse the existing types in `financial_canonicalization.py`:

- `RawFact`
- `XbrlConcept`
- `XbrlLabel`
- `XbrlPresentationArc`
- `XbrlCalculationArc`
- `XbrlRelationshipSet`
- `SemanticEvidence`
- `FactContext.semantic_extensions` / `extension_mappings`

Do not introduce a second financial-canonical model.

## Parsing rules

Use a deterministic XML parser available in the standard library unless repository evidence proves it insufficient. A new dependency requires explicit justification.

The parser must:

1. validate and resolve XBRL contexts to exact duration/instant dates;
2. resolve units without guessing scale;
3. preserve accession/form/source identity and checksum lineage;
4. reject non-finite numeric values;
5. preserve dimensions and consolidation semantics rather than silently flattening them;
6. parse schema concepts and period type;
7. parse presentation/calculation relationships by QName and role;
8. parse labels only as supporting evidence, never as sole authorization for a metric mapping;
9. fail closed on contradictory or incomplete relationship evidence.

## Extension authorization

An issuer extension fact may repair a canonical gap only when the existing `FinancialCanonicalizer` can authorize it through structural semantic evidence.

A label resemblance, magnitude, or position in a statement is insufficient by itself.

The filing-native bridge may produce `SemanticEvidence`, but metric acceptance remains owned by existing canonicalization rules.

## Standard filing-native facts

Standard-taxonomy filing-native facts may supplement companyfacts when the aggregate API omitted or could not provide a compatible observation. They remain subject to the same unit, period, filing, consolidation, dimension, and ambiguity rules as companyfacts-derived `RawFact` values.

## TTM coverage

A recoverable duration gap may require more than the newest filing. The deterministic `FilingFallbackPlan` must select the minimum bounded period set required by the existing TTM contract.

For example, a duration metric requiring annual plus comparable YTD coverage may require the relevant original 10-K and original 10-Q periods. The plan must derive this from canonical requirements and submissions metadata; it must not recursively download filings until something works.

One fallback phase may contain multiple explicitly planned filing artifacts, but the phase occurs at most once.

## Merge policy

Filing-native evidence supplements, not blindly overrides, companyfacts.

The post-fallback canonicalization input is the union of:

- already validated companyfacts-derived raw facts; and
- verified filing-native raw facts/semantic evidence from the bounded fallback plan.

If compatible sources disagree for the same canonical requirement and existing rules cannot reconcile them, the result is `BLOCKED` or a canonical conflict according to the existing fail-closed contract. Do not choose the numerically convenient value.

## Gate behavior after fallback

After one fallback phase:

```text
verified filing artifacts
    -> filing-native bridge
    -> combined canonicalization input
    -> existing promotion/accounting normalization
    -> READY | GAP | BLOCKED
```

`READY` requires an `AccountingSnapshot` satisfying the same contract as the companyfacts-only fast path.

A remaining legitimate coverage gap after successful parsing/canonicalization is `EVIDENCE_REQUIRED` at request level.

Malformed XBRL, checksum/source-identity failure, contradictory semantic relationships, or unreconcilable canonical conflict is `BLOCKED`.

## Non-negotiable tests

Add deterministic fixtures/tests proving:

1. a standard filing-native fact omitted from companyfacts can repair a typed GAP;
2. an issuer-extension fact is accepted only with sufficient structural semantic evidence;
3. the same extension fact is rejected when only a label is available;
4. contradictory presentation/calculation evidence fails closed;
5. context/unit/dimension mismatches do not repair the gap;
6. TTM fallback planning selects the minimum explicit filing set needed by the requirement;
7. post-fallback canonicalization merges companyfacts and filing-native evidence without ticker-specific branches;
8. no parser or bridge function performs network I/O;
9. successful download without successful bridge/canonicalization never becomes trusted READY evidence.

## Scope guard

This addendum does not authorize broad XBRL analytics, arbitrary taxonomy inference, scraping every filing, natural-language semantic mapping, or a new accounting engine. It adds only the minimum filing-native evidence bridge required to make the already-approved bounded fallback real.