"""Integration tests for CLI dual-mode switch and automated schedule generation commands."""

import json
from pathlib import Path
import pytest

from src.cli import build_parser, main
from src.core.models import ScheduleGenerationConfig


def test_cli_parser_modes():
    """Verify that --mode accepts 'edit' and 'create'."""
    parser = build_parser()
    args_edit = parser.parse_args(["--mode", "edit"])
    assert args_edit.mode == "edit"

    args_create = parser.parse_args(["--mode", "create"])
    assert args_create.mode == "create"

    with pytest.raises(SystemExit):
        parser.parse_args(["--mode", "invalid_mode"])


def test_cli_sample_config_generation(tmp_path):
    """Verify that --sample-config creates a valid, parseable configuration file."""
    out_file = tmp_path / "test_sample.json"
    ret = main(["--sample-config", str(out_file)])
    assert ret == 0
    assert out_file.is_file()

    content = out_file.read_text(encoding="utf-8")
    config = ScheduleGenerationConfig.from_json(content)
    assert len(config.academic_structure.years) > 0
    assert len(config.rooms) > 0


def test_cli_headless_generation_from_config(tmp_path):
    """Verify that --create-from-config solves the schedule and exports all artifacts."""
    cfg_file = tmp_path / "config.json"
    sample = ScheduleGenerationConfig.create_sample_config()
    cfg_file.write_text(sample.to_json(), encoding="utf-8")

    out_dir = tmp_path / "out_artifacts"
    ret = main(["--create-from-config", str(cfg_file), "--output-dir", str(out_dir)])
    assert ret == 0

    # Ensure artifacts directory was created
    subdirs = [d for d in out_dir.iterdir() if d.is_dir() and "generated_schedule" in d.name]
    assert len(subdirs) == 1
    run_dir = subdirs[0]

    assert (run_dir / "schedule_students.json").is_file()
    assert (run_dir / "schedule_workers.json").is_file()
    assert (run_dir / "execution.log").is_file()

    pdf_files = list(run_dir.glob("*.pdf"))
    assert len(pdf_files) >= 5  # 1 student timetable + 4 worker timetables
