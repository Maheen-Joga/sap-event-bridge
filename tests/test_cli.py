import json

import pytest

from sapbridge.cli import main, render_demo, run_demo
from sapbridge.events import validate_event


def test_generate_prints_one_json_event_per_line(capsys):
    assert main(["generate", "--n", "5", "--seed", "2", "--invalid-rate", "0"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert len(lines) == 5
    for line in lines:
        validate_event(json.loads(line))


@pytest.mark.parametrize("seed,invalid_rate", [(1, 0.0), (3, 0.2), (9, 0.5)])
def test_demo_numbers_are_consistent(seed, invalid_rate):
    summary = run_demo(n=40, seed=seed, invalid_rate=invalid_rate, duplicates=3)
    assert summary["processed"] + summary["rejected"] == summary["unique_events"]
    assert summary["duplicate"] == summary["resent"]
    assert summary["table_items"] == summary["processed"]
    assert summary["raw_objects"] == summary["processed"]
    assert summary["rejected_objects"] == summary["rejected"]
    assert summary["dlq_messages"] == summary["rejected"]


def test_demo_with_no_invalid_events_rejects_nothing():
    summary = run_demo(n=25, seed=4, invalid_rate=0.0, duplicates=2)
    assert summary["rejected"] == 0 and summary["dlq_messages"] == 0


def test_demo_output_is_readable(capsys):
    assert main(["demo", "--n", "30", "--seed", "2"]) == 0
    out = capsys.readouterr().out
    assert "processed" in out and "DLQ messages" in out


def test_bad_arguments_are_reported_without_a_traceback(capsys):
    assert main(["demo", "--n", "10", "--invalid-rate", "2"]) == 2
    assert "invalid_rate" in capsys.readouterr().err


def test_render_demo_includes_every_count():
    summary = run_demo(n=20, seed=1, invalid_rate=0.1, duplicates=1)
    text = render_demo(summary)
    assert str(summary["table_items"]) in text
