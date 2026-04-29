from pathlib import Path

from pkgwarden_cli.process_runner import ProcessResult, run_process


def test_run_process_captures_stdout_and_returncode(tmp_path: Path) -> None:
    result = run_process(["python", "-c", "print('hi')"], cwd=tmp_path)
    assert isinstance(result, ProcessResult)
    assert result.returncode == 0
    assert "hi" in result.stdout


def test_run_process_captures_failure(tmp_path: Path) -> None:
    result = run_process(
        ["python", "-c", "import sys; sys.stderr.write('boom'); sys.exit(3)"],
        cwd=tmp_path,
    )
    assert result.returncode == 3
    assert "boom" in result.stderr


def test_run_process_handles_missing_binary(tmp_path: Path) -> None:
    result = run_process(["pkgwarden-nonexistent-binary"], cwd=tmp_path)
    assert result.returncode != 0
    assert result.stderr
