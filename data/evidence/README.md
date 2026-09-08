# Versioned evidence bundles

This directory contains the exact, immutable bytes required to reproduce committed research
contracts from a fresh clone. Each bundle is bounded to a named research increment. Files under
`data/raw/` remain ignored acquisition workspace and are not runtime inputs.

Every evidence file must have a repository-relative path, byte count, SHA-256 digest, source
identity, and retrieval metadata in its associated contract. Loaders verify size and digest before
using any content. Updating evidence requires a new identity and review; files must not be silently
replaced in place.

The QCOM bundle contains three issuer-hosted primary documents and four frozen provider responses.
Their source identities, dates where applicable, limitations, sizes, and digests are recorded in
`data/research/qcom/manifest.json` and `data/research/qcom/relative-context.json`.

Generated HTML and result manifests remain outside Git under `artifacts/` or `reports/generated/`.
CI publishes the verified report and its manifest as workflow artifacts.
