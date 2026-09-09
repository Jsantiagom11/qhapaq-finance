from dataclasses import dataclass


@dataclass(frozen=True)
class LocalResearchProfile:
    """The deliberately small, zero-cost local inference configuration."""

    provider: str = "ollama"
    model: str = "qwen3.5:9b"
    endpoint: str = "http://127.0.0.1:11434"
    temperature: int = 0
    think: bool = False
    stream: bool = False
    max_contract_repairs: int = 1
    unload_after_run: bool = True


LOCAL_RESEARCH_PROFILE = LocalResearchProfile()


@dataclass(frozen=True)
class ResearchConfig:
    """Explicit assumptions used by the baseline experiment."""

    lookback_days: int = 60
    rebalance_days: int = 21
    top_n: int = 3
    transaction_cost_bps: float = 10.0
    annualization: int = 252

    def __post_init__(self) -> None:
        if self.lookback_days < 2:
            raise ValueError("lookback_days must be at least 2")
        if self.rebalance_days < 1:
            raise ValueError("rebalance_days must be positive")
        if self.top_n < 1:
            raise ValueError("top_n must be positive")
        if self.transaction_cost_bps < 0:
            raise ValueError("transaction_cost_bps cannot be negative")

    @property
    def transaction_cost(self) -> float:
        return self.transaction_cost_bps / 10_000
