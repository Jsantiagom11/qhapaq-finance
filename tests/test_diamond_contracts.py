from __future__ import annotations

from dataclasses import replace

import pytest

from qhapaq_finance.diamond.contracts import DiamondContractError, FiscalSlot

try:
    from tests.diamond_helpers import make_record, obs
except ModuleNotFoundError:
    from diamond_helpers import make_record, obs


def test_peer_group_id_is_required() -> None:
    with pytest.raises(DiamondContractError, match="PEER_GROUP_ID_REQUIRED"):
        make_record(peer_group_id="   ")


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_non_finite_observation_is_rejected(value: float) -> None:
    with pytest.raises(DiamondContractError, match="OBSERVATION_NOT_FINITE"):
        obs(value=value)


def test_duplicate_metric_slot_is_rejected() -> None:
    first = obs("revenue", FiscalSlot.TTM, 100.0)
    with pytest.raises(DiamondContractError, match="DUPLICATE_METRIC_SLOT"):
        make_record(observations=(first, replace(first, value=101.0)))
