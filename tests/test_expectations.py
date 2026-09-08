import pytest

from qhapaq_finance.expectations import (
    ExpectationsError,
    ReverseDcfInputs,
    present_value_equity_fcf,
    solve_implied_fcf_growth,
)


def test_reverse_dcf_recovers_known_growth() -> None:
    base = ReverseDcfInputs(
        equity_value=1.0,
        starting_fcf=100.0,
        discount_rate=0.09,
        terminal_growth=0.03,
        years=10,
    )
    target = present_value_equity_fcf(base, growth=0.14)
    inputs = ReverseDcfInputs(
        equity_value=target,
        starting_fcf=100.0,
        discount_rate=0.09,
        terminal_growth=0.03,
        years=10,
    )

    result = solve_implied_fcf_growth(inputs)

    assert result.implied_fcf_growth == pytest.approx(0.14, abs=1e-9)
    assert result.solved_present_value == pytest.approx(target, rel=1e-9)


def test_nvda_like_case_is_about_fourteen_percent() -> None:
    result = solve_implied_fcf_growth(
        ReverseDcfInputs(
            equity_value=5.55e12,
            starting_fcf=139.97e9,
            discount_rate=0.09,
            terminal_growth=0.03,
            years=10,
        )
    )

    assert result.implied_fcf_growth == pytest.approx(0.13955, abs=1e-4)


def test_discount_rate_must_exceed_terminal_growth() -> None:
    with pytest.raises(ExpectationsError, match="discount_rate must exceed terminal_growth"):
        solve_implied_fcf_growth(
            ReverseDcfInputs(
                equity_value=1_000.0,
                starting_fcf=100.0,
                discount_rate=0.03,
                terminal_growth=0.03,
            )
        )


def test_reverse_dcf_rejects_nonpositive_cash_flow() -> None:
    with pytest.raises(ExpectationsError, match="starting_fcf must be positive"):
        solve_implied_fcf_growth(
            ReverseDcfInputs(
                equity_value=1_000.0,
                starting_fcf=0.0,
                discount_rate=0.09,
                terminal_growth=0.03,
            )
        )
