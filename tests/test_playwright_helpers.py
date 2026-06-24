from pathlib import Path

from media_automata.platforms.playwright_helpers import chromium_launch_kwargs


def test_chromium_launch_kwargs_prefers_configured_executable(tmp_path: Path, monkeypatch) -> None:
    executable = tmp_path / "chrome"
    executable.write_text("", encoding="utf-8")
    monkeypatch.setenv("PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH", str(executable))

    assert chromium_launch_kwargs() == {"executable_path": str(executable)}
