import json

import pytest

from sapbridge.events import EventError, validate_event
from sapbridge.mock_source import EVENTBRIDGE_SOURCE, generate_events, to_eventbridge_entry


def test_generation_is_deterministic_per_seed():
    assert generate_events(40, seed=5) == generate_events(40, seed=5)
    assert generate_events(40, seed=5) != generate_events(40, seed=6)


def test_all_events_validate_when_invalid_rate_is_zero():
    for event in generate_events(300, seed=1):
        validate_event(event)


def test_every_corrupted_event_fails_validation():
    events = generate_events(300, seed=2, invalid_rate=1.0)
    for event in events:
        with pytest.raises(EventError):
            validate_event(event)


def test_invalid_rate_is_roughly_respected():
    events = generate_events(1000, seed=3, invalid_rate=0.2)
    bad = 0
    for event in events:
        try:
            validate_event(event)
        except EventError:
            bad += 1
    assert 150 <= bad <= 250


def test_changes_and_receipts_reference_existing_purchase_orders():
    created, referenced = set(), set()
    for event in generate_events(300, seed=4):
        po_id = event["data"]["po_id"]
        if event["type"].endswith("PurchaseOrder.Created"):
            created.add(po_id)
        else:
            referenced.add(po_id)
    assert referenced <= created


def test_events_are_ordered_in_time_and_have_unique_ids():
    events = generate_events(200, seed=7)
    times = [e["time"] for e in events]
    assert times == sorted(times)
    assert len({e["id"] for e in events}) == len(events)


def test_all_events_are_labelled_as_mock():
    assert all(e["source"].startswith("sap-mock://") for e in generate_events(50, seed=8))


@pytest.mark.parametrize("kwargs", [dict(n=-1), dict(n=5, invalid_rate=1.5), dict(n=5, invalid_rate=-0.1)])
def test_bad_arguments_are_rejected(kwargs):
    with pytest.raises(ValueError):
        generate_events(**kwargs)


def test_eventbridge_entry_shape():
    event = generate_events(1, seed=1)[0]
    entry = to_eventbridge_entry(event, "my-bus")
    assert entry["Source"] == EVENTBRIDGE_SOURCE
    assert entry["DetailType"] == event["type"]
    assert entry["EventBusName"] == "my-bus"
    assert json.loads(entry["Detail"]) == event
