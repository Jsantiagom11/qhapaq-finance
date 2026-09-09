from __future__ import annotations

import json

from qhapaq_finance.visual_audit import (
    NARROW_VIEWPORT,
    PRIMARY_VIEWPORTS,
    audit_matrix,
    snapshot_name,
    write_manifest,
    write_report,
)


def test_matrix_has_eight_canonical_ipad_states_and_two_narrow_cases() -> None:
    matrix = audit_matrix()
    assert len([spec for spec in matrix if spec.primary]) == 8
    assert len(matrix) == 10
    assert PRIMARY_VIEWPORTS == (("portrait", 1024, 1366), ("landscape", 1366, 1024))
    assert NARROW_VIEWPORT == ("narrow", 768, 1024)
    assert [spec.name for spec in matrix[:4]] == [
        "ipad-pro-13-portrait-simple-paper.png",
        "ipad-pro-13-portrait-simple-night.png",
        "ipad-pro-13-portrait-research-paper.png",
        "ipad-pro-13-portrait-research-night.png",
    ]


def test_snapshot_name_is_semantic() -> None:
    assert snapshot_name("landscape", "research", "night") == (
        "ipad-pro-13-landscape-research-night.png"
    )


def test_manifest_and_report_are_offline_and_serialized(tmp_path) -> None:
    record = {
        "name": "ipad-pro-13-portrait-simple-paper.png",
        "viewport_width": 1024,
        "viewport_height": 1366,
        "view_mode": "simple",
        "theme": "paper",
        "screenshot_path": "ipad-pro-13-portrait-simple-paper.png",
        "horizontal_overflow": 0,
        "layout_failures": [],
        "touch_target_warnings": [],
        "clipping_warnings": [],
    }
    manifest = write_manifest(tmp_path, {"ticker": "QCOM", "browser_engine": "webkit"}, [record])
    report = write_report(tmp_path, "QCOM", [record])
    assert json.loads(manifest.read_text())["snapshots"] == [record]
    assert "QCOM VISUAL QA" in report.read_text()
    assert record["screenshot_path"] in report.read_text()
