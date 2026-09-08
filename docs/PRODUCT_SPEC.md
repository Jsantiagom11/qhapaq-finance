# Product specification

Status: canonical direction; planned capabilities are not implementation claims.

## Purpose and report structure

Qhapaq Finance supports evidence-based company research and portfolio decisions through a
general-to-specific report:

```text
Portfolio summary -> economic/statistical exposures -> asset contribution
                  -> company thesis -> underlying evidence
```

The intended capabilities are:

1. Evidence-backed company selection, including valuation, value-chain dependencies, a
   counterthesis, and explicit invalidation conditions.
2. Joint portfolio analysis that combines statistical estimates with documented economic
   dependencies. Neither type of evidence substitutes for the other.
3. Before/after decision comparisons, including the option to maintain the current allocation,
   costs, uncertainty, and subsequent learning.

The existing momentum backtest remains a methodological baseline. The ECB renderer remains a
reproducibility demonstration. Neither is implemented equity research or an MPT optimizer.

## Portfolio and decision semantics

- An **observed portfolio** contains holdings supported by an identified, user-authorized source.
  Each holding's identity, quantity or weight, observation time, and source must be recorded; absent
  values remain unknown.
- A **hypothetical model portfolio** is an explicitly labeled scenario. It must never be presented
  as observed, owned, recommended, or suitable for the user.
- Watchlist membership is not evidence of a current holding.
- The system must not infer an investor mandate, portfolio weights, or expected returns.
- Horizon, reference currency, liquidity needs, risk tolerance, legal/tax/other constraints, and
  comparison benchmark are unresolved inputs until explicitly supplied and recorded. Outputs that
  depend on an unresolved input must remain unavailable or visibly conditional.
- A comparison must show the observed or stated starting allocation, the proposed hypothetical
  allocation, the maintain-current-allocation alternative, estimated costs, material uncertainty,
  and fields for later outcomes and learning.
- Automated order execution is outside scope.

Private brokerage emails, account details, and personal transactions must not be imported into the
public repository.

## Evidence contract

The primary analytical conclusion of a section must remain understandable without horizontal
scrolling at a 390 px viewport. Detailed evidence tables may use horizontal scrolling.

Every evidence item must record source identity, publication date, reporting period, retrieval date,
and a stable locator or repository-safe artifact identity where permitted. Access restrictions and
source type must be explicit.

Research records keep four categories distinct:

| Category | Meaning |
| --- | --- |
| Fact | A source-supported statement, linked to the supporting evidence. |
| Calculation | A reproducible transformation with inputs, units, formula, and applicable rounding. |
| Assumption | An explicit value or condition not established as fact. |
| Interpretation | An analyst conclusion linked to its facts, calculations, and assumptions. |

A historical observation cutoff proves only which observations a computation included. It does not
prove that each item was available at that historical time. Later publications or revisions must
not be presented as vintage evidence. The record therefore distinguishes reporting period,
publication date, retrieval date, and, where established, an information-availability date.

Missing information remains unknown, not zero. The product must reject or visibly identify invalid,
missing, conflicting, inaccessible, or post-cutoff evidence. It must not invent arbitrary geographic
risk scores, unsupported confidence scores, inferred expected returns, or other false precision.
Synthetic data may test deterministic behavior but must not be presented as an empirical
demonstration.

## Next functional increment

Validate one real company from the supplied research universe through this single path:

```text
validated primary-source evidence -> typed research record
                                  -> thesis/counterthesis/invalidation
                                  -> offline HTML report
```

The company must be selected only after the supplied research universe is available and verified in
the working environment. No spreadsheet is assumed to exist inside WSL. This increment validates
the research workflow; it does not recommend a one-stock portfolio. Expansion to five companies
and portfolio-weight optimization are separate work gated on successful completion and review of
this increment.

### Planned implementation work and acceptance criteria

| Planned work | Testable acceptance criteria |
| --- | --- |
| Select one company | The company occurs in the verified supplied universe; the universe source and retrieval evidence are recorded; selection is not described as a recommendation or holding. |
| Validate primary sources | Each accepted item has source identity, publication date, reporting period, retrieval date, stable locator, and content identity where storage is permitted; secondary-only, inaccessible, malformed, or unsupported items fail explicitly. |
| Enforce availability semantics | Tests distinguish observation cutoff from information availability; evidence published or revised after the declared cutoff cannot appear as vintage support; an unknown availability date remains unknown. |
| Create a typed research record | Schema validation keeps facts, calculations, assumptions, and interpretations distinct; missing required evidence and invalid enums/dates fail; missing numeric values remain null/unknown rather than becoming zero. |
| Express the research argument | The record includes valuation basis, material value-chain dependencies, thesis, counterthesis, and explicit testable invalidation conditions, each linked to supporting evidence or labeled as an assumption/interpretation. No arbitrary geographic-risk or unsupported confidence score is accepted. |
| Perform calculations, if any | Fixtures demonstrate deterministic formulas, units, input identities, and rounding; repeated execution produces identical structured results. No expected return or portfolio weight is inferred. |
| Render offline HTML | With network access denied, the validated record renders a self-contained report containing the required sections, clear unknown/error states, and no synthetic empirical claims; repeated rendering is deterministic apart from explicitly documented metadata. |
| Navigate to evidence | Every report claim that requires support links to an evidence entry, and every internal evidence link and anchor resolves offline; broken or missing targets fail validation. |
| Inspect the rendered result | A reviewer opens the generated HTML in its intended renderer and records actual visual inspection of hierarchy, legibility, overflow, labels, unknown states, and evidence navigation. Automated tests alone do not satisfy this criterion. |

## Later dependency-gated work

After the one-company workflow passes its acceptance criteria and review, a separately specified
increment may expand the same schema to five companies. Portfolio aggregation and weight
optimization remain later work and additionally require explicit horizon, reference currency,
liquidity needs, risk tolerance, constraints, comparison benchmark, cost model, and uncertainty
method. No optimizer may manufacture these inputs.
