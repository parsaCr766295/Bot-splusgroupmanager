import json
from pathlib import Path

from railway_entrypoint import normalize_phone, session_is_ready
from splus_manager.__main__ import _is_outgoing_command_text


ROOT = Path(__file__).resolve().parents[1]


def test_railway_config_runs_worker_without_overlap():
    config = json.loads((ROOT / "railway.json").read_text(encoding="utf-8"))
    assert config["build"]["builder"] == "DOCKERFILE"
    assert config["build"]["dockerfilePath"] == "Dockerfile"
    assert "startCommand" not in config["deploy"]
    assert config["deploy"]["restartPolicyType"] == "ALWAYS"
    assert config["deploy"]["overlapSeconds"] == 0
    assert isinstance(config["deploy"]["overlapSeconds"], int)
    assert config["deploy"]["drainingSeconds"] == 10
    assert isinstance(config["deploy"]["drainingSeconds"], int)


def test_tracker_file_does_not_count_as_session(tmp_path: Path):
    phone = "+989121234567"
    (tmp_path / "plus_989121234567_tracker.json").write_text("tracker", encoding="utf-8")
    assert not session_is_ready(tmp_path, phone)


def test_exact_account_session_is_detected(tmp_path: Path):
    (tmp_path / "plus_989121234567.session").write_text("session", encoding="utf-8")
    assert session_is_ready(tmp_path, "09121234567")


def test_phone_normalization_does_not_depend_on_soropy():
    assert normalize_phone("0912 123 4567") == "+989121234567"
    assert normalize_phone("+989121234567") == "+989121234567"


def test_docker_image_installs_runtime_dependency():
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert 'pip install --no-cache-dir ".[soroush]"' in dockerfile
    assert "import soropy" in dockerfile
    assert 'CMD ["python", "railway_entrypoint.py"]' in dockerfile


def test_same_account_panel_and_status_are_polled_as_commands():
    assert _is_outgoing_command_text("پنل")
    assert _is_outgoing_command_text("🤖 وضعیت")
    assert _is_outgoing_command_text("📋 راهنما")
    assert not _is_outgoing_command_text("🤖 پنل وضعیت مدیر گروه\n🟢 آنلاین")
