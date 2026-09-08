# QCOM market-cap fallback fix

A real Qhapaq One render showed QCOM with verified evidence but `INSUFFICIENT DATA` because the live yfinance snapshot omitted `fast_info.market_cap`.

The fix keeps the market layer provider-scoped and generic:

1. prefer `fast_info.market_cap`;
2. fall back to `info.marketCap`;
3. if absent, derive equity value from `info.sharesOutstanding * observed price`;
4. leave market cap missing if all provider metadata paths fail.

This value remains a timestamped market observation, not frozen research evidence. The fallback is unit-tested and does not add issuer-specific logic.
