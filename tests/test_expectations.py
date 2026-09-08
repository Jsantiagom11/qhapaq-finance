import pytest

from qhapaq_finance.expectations import (
    ExpectationsError,
    ReverseDcfInputs,
    present_value_equity_fcf,
    reverse_dcf_sensitivity,
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


def test_normalized_nvda_like_case_requires_about_ten_and_a_half_percent() -> None:
    result = solve_implied_fcf_growth(
        ReverseDcfInputs(
            equity_value=5.551676e12,
            starting_fcf=181.658e9,
            discount_rate=0.09,
            terminal_growth=0.03,
            years=10,
        )
    )

    assert result.implied_fcf_growth == pytest.approx(0.10539, abs=1e-4)


def test_sensitivity_grid_exposes_cost_of_equity_and_terminal_assumptions() -> None:
    points = reverse_dcf_sensitivity(
        equity_value=5.55e12,
        starting_fcf=181.658e9,
    )

    assert len(points) == 9
    lookup = {
        (point.discount_rate, point.terminal_growth): point.implied_fcf_growth
        for point in points
    }
    assert lookup[(0.08, 0.03)] == pytest.approx(0.07980, abs=1e-4)
    assert lookup[(0.09, 0.03)] == pytest.approx(0.10535, abs=1e-4)
    assert lookup[(0.10, 0.03)] == pytest.approx(0.12853, abs=1e-4)
    assert lookup[(0.10, 0.03)] > lookup[(0.09, 0.03)] > lookup[(0.08, 0.03)]
    assert lookup[(0.09, 0.02)] > lookup[(0.09, 0.03)] > lookup[(0.09, 0.04)]


def test_sensitivity_rejects_empty_grid() -> None:
    with pytest.raises(ExpectationsError, match="sensitivity grids must be non-empty"):
        reverse_dcf_sensitivity(
            equity_value=1_000.0,
            starting_fcf=100.0,
            discount_rates=(),
        )


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
