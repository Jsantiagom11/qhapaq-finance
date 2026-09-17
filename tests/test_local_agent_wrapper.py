import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[1]
WRAPPER = ROOT / "bin/qhapaq-local-agent"


def _fake_bins(tmp_path: Path, qhapaq_status: int) -> tuple[Path, Path]:
    service = tmp_path / "service"
    command = tmp_path / "qhapaq"
    service.write_text('#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$LOG"\n', encoding="utf-8")
    command.write_text(
        f'#!/usr/bin/env bash\nprintf "%s\\n" "$*" >> "$LOG"\nexit {qhapaq_status}\n',
        encoding="utf-8",
    )
    service.chmod(0o755)
    command.chmod(0o755)
    return service, command


def test_wrapper_stops_service_and_preserves_failure_status(tmp_path: Path) -> None:
    service, command = _fake_bins(tmp_path, 23)
    log = tmp_path / "log"
    environment = {
        **os.environ,
        "QHAPAQ_SYSTEMCTL_BIN": str(service),
        "QHAPAQ_BIN": str(command),
        "LOG": str(log),
    }
    result = subprocess.run(
        [str(WRAPPER), "investigate", "NVDA"], env=environment, capture_output=True, text=True
    )
    assert result.returncode == 23
    assert log.read_text(encoding="utf-8").splitlines() == [
        "start ollama.service",
        "is-active --quiet ollama.service",
        "investigate NVDA --local",
        "stop ollama.service",
    ]


def test_wrapper_stops_service_after_success(tmp_path: Path) -> None:
    service, command = _fake_bins(tmp_path, 0)
    log = tmp_path / "log"
    environment = {
        **os.environ,
        "QHAPAQ_SYSTEMCTL_BIN": str(service),
        "QHAPAQ_BIN": str(command),
        "LOG": str(log),
    }
    result = subprocess.run(
        [str(WRAPPER), "investigate", "NVDA"], env=environment, capture_output=True, text=True
    )
    assert result.returncode == 0
    assert log.read_text(encoding="utf-8").splitlines()[-1] == "stop ollama.service"


def test_wrapper_contains_no_domain_list_or_enable_command() -> None:
    content = WRAPPER.read_text(encoding="utf-8")
    assert "enable ollama" not in content
    assert "NVDA" not in content
