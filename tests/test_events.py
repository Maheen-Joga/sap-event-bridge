import copy

import pytest

from sapbridge.events import (GOODS_RECEIPT_POSTED, PURCHASE_ORDER_CHANGED, PURCHASE_ORDER_CREATED,
                              EventError, validate_event)

PO = {
    "specversion": "1.0",
    "id": "evt-001",
    "source": "sap-mock://S4-DEMO/100",
    "type": PURCHASE_ORDER_CREATED,
    "time": "2026-01-05T08:00:00Z",
    "data": {
        "po_id": "4500000001",
        "supplier": "Nordlicht Komponenten GmbH",
        "currency": "EUR",
        "status": "OPEN",
        "items": [{"material": "MAT-1001", "quantity": 10, "unit_price": 2.5}],
    },
}
RECEIPT = {
    "specversion": "1.0",
    "id": "evt-002",
    "source": "sap-mock://S4-DEMO/100",
    "type": GOODS_RECEIPT_POSTED,
    "time": "2026-01-05T09:30:00+01:00",
    "data": {"po_id": "4500000001", "material": "MAT-1001", "quantity": 4, "plant": "BER1"},
}


def mutated(base, path, value):
    event = copy.deepcopy(base)
    target = event
    for key in path[:-1]:
        target = target[key]
    if value is KeyError:
        del target[path[-1]]
    else:
        target[path[-1]] = value
    return event


def test_valid_purchase_order_parses():
    event = validate_event(PO)
    assert event.entity_key == "PO#4500000001"
    assert event.subject == "PurchaseOrder/4500000001"
    assert event.data["items"][0]["quantity"] == 10


def test_valid_goods_receipt_parses_and_time_is_converted_to_utc():
    event = validate_event(RECEIPT)
    assert event.time.isoformat() == "2026-01-05T08:30:00+00:00"
    assert event.entity_key == "PO#4500000001"


def test_to_dict_round_trips():
    event = validate_event(PO)
    assert validate_event(event.to_dict()) == event
    assert event.to_dict()["time"] == "2026-01-05T08:00:00Z"


@pytest.mark.parametrize("bad, path", [
    (mutated(PO, ["specversion"], "0.3"), "$.specversion"),
    (mutated(PO, ["type"], "sap.mock.Unknown"), "$.type"),
    (mutated(PO, ["source"], "sap-prod://real"), "$.source"),
    (mutated(PO, ["id"], "has spaces"), "$.id"),
    (mutated(PO, ["time"], "yesterday"), "$.time"),
    (mutated(PO, ["time"], "2026-01-05T08:00:00"), "$.time"),
    (mutated(PO, ["data", "po_id"], "ABC"), "$.data.po_id"),
    (mutated(PO, ["data", "currency"], "eur"), "$.data.currency"),
    (mutated(PO, ["data", "currency"], KeyError), "$.data.currency"),
    (mutated(PO, ["data", "status"], "SHIPPED"), "$.data.status"),
    (mutated(PO, ["data", "items"], []), "$.data.items"),
    (mutated(PO, ["data", "items", 0, "quantity"], -3), "$.data.items[0].quantity"),
    (mutated(PO, ["data", "items", 0, "quantity"], True), "$.data.items[0].quantity"),
    (mutated(PO, ["data", "items", 0, "unit_price"], -1), "$.data.items[0].unit_price"),
    (mutated(RECEIPT, ["data", "plant"], "toolong"), "$.data.plant"),
    (mutated(RECEIPT, ["data", "quantity"], 0), "$.data.quantity"),
])
def test_invalid_events_report_the_failing_path(bad, path):
    with pytest.raises(EventError) as exc:
        validate_event(bad)
    assert exc.value.path == path


def test_created_event_must_be_open():
    with pytest.raises(EventError, match="OPEN"):
        validate_event(mutated(PO, ["data", "status"], "APPROVED"))


def test_changed_event_may_have_any_valid_status():
    changed = mutated(mutated(PO, ["type"], PURCHASE_ORDER_CHANGED), ["data", "status"], "APPROVED")
    assert validate_event(changed).data["status"] == "APPROVED"


@pytest.mark.parametrize("not_an_object", [None, "text", 42, [PO]])
def test_non_object_input_is_rejected(not_an_object):
    with pytest.raises(EventError) as exc:
        validate_event(not_an_object)
    assert exc.value.path == "$"
