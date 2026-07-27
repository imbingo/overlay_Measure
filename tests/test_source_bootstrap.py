from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_batch_launcher_delegates_to_bootstrap_script():
    launcher = (ROOT / "start_overlay_measure.bat").read_text(encoding="utf-8")

    assert "bootstrap_and_run.ps1" in launcher
    assert "-ExecutionPolicy Bypass" in launcher


def test_bootstrap_uses_project_local_environment_and_dependency_stamp():
    bootstrap = (ROOT / "scripts" / "bootstrap_and_run.ps1").read_text(encoding="utf-8")

    assert 'Join-Path $projectRoot ".venv"' in bootstrap
    assert ".overlay_requirements.sha256" in bootstrap
    assert "Get-FileHash" in bootstrap
    assert "-m pip install" in bootstrap
    assert "requirements.txt" in bootstrap
    assert "Python 3.10-3.13" in bootstrap
