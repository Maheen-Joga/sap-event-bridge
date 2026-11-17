"""A MOCK SAP event source. Everything it produces is synthetic and labelled as such.

generate_events() is deterministic for a given seed. With invalid_rate > 0 a share of the
events is deliberately corrupted, so the validation and dead-letter paths get exercised.
"""

from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

from .events import GOODS_RECEIPT_POSTED, PURCHASE_ORDER_CHANGED, PURCHASE_ORDER_CREATED

EVENTBRIDGE_SOURCE = "sapbridge.mock"  # the EventBridge `source` field; the rule matches on it
SOURCE = "sap-mock://S4-DEMO/100"      # the CloudEvents `source` attribute inside the event

MATERIALS = [f"MAT-{1000 + i}" for i in range(12)]
SUPPLIERS = [  # fictional companies
    "Nordlicht Komponenten GmbH",
    "Brandenburg Packaging GmbH",
    "Spree Logistik AG",
    "Rhein Industrietechnik GmbH",
]
PLANTS = ["BER1", "BER2", "LEJ1", "HAM1"]
_DEFAULT_START = datetime(2026, 1, 5, 8, 0, tzinfo=timezone.utc)


def _iso(moment: datetime) -> str:
    return moment.isoformat().replace("+00:00", "Z")


def _corrupt(event: dict, rng: random.Random) -> None:
    """Break an event in one of several realistic ways. The result never validates."""
    choice = rng.choice(["specversion", "source", "missing_field", "bad_po_id"])
    if choice == "specversion":
        event["specversion"] = "0.3"
    elif choice == "source":
        event["source"] = "sap-prod://real-system"
    elif choice == "missing_field":
        del event["data"][rng.choice(sorted(event["data"]))]
    else:
        event["data"]["po_id"] = "ABC"


def generate_events(
    n: int,
    seed: int = 0,
    invalid_rate: float = 0.0,
    start: datetime = _DEFAULT_START,
) -> list[dict]:
    if n < 0:
        raise ValueError("n must be >= 0")
    if not 0.0 <= invalid_rate <= 1.0:
        raise ValueError("invalid_rate must be between 0 and 1")
    rng = random.Random(seed)
    purchase_orders: list[dict] = []
    events: list[dict] = []

    for index in range(n):
        moment = start + timedelta(seconds=37 * index + rng.randint(0, 20))
        roll = rng.random()
        if not purchase_orders or roll < 0.4:
            po = {
                "po_id": f"{4500000000 + len(purchase_orders) + 1:010d}",
                "supplier": rng.choice(SUPPLIERS),
                "currency": "EUR",
                "items": [
                    {
                        "material": material,
                        "quantity": rng.randint(1, 500),
                        "unit_price": round(rng.uniform(0.5, 250.0), 2),
                    }
                    for material in rng.sample(MATERIALS, rng.randint(1, 3))
                ],
            }
            purchase_orders.append(po)
            event_type = PURCHASE_ORDER_CREATED
            data = {**po, "status": "OPEN"}
        elif roll < 0.7:
            po = rng.choice(purchase_orders)
            event_type = PURCHASE_ORDER_CHANGED
            data = {**po, "status": rng.choice(["OPEN", "APPROVED", "CLOSED"])}
        else:
            po = rng.choice(purchase_orders)
            item = rng.choice(po["items"])
            event_type = GOODS_RECEIPT_POSTED
            data = {
                "po_id": po["po_id"],
                "material": item["material"],
                "quantity": rng.randint(1, item["quantity"]),
                "plant": rng.choice(PLANTS),
            }

        event = {
            "specversion": "1.0",
            "id": f"evt-{seed:03d}-{index:06d}",
            "source": SOURCE,
            "type": event_type,
            "time": _iso(moment),
            "datacontenttype": "application/json",
            "data": json.loads(json.dumps(data)),  # deep copy, so later corruption cannot leak into POs
        }
        if rng.random() < invalid_rate:
            _corrupt(event, rng)
        events.append(event)
    return events


def to_eventbridge_entry(event: dict, bus_name: str) -> dict:
    """Shape an event as an EventBridge PutEvents entry (the CloudEvent goes in `Detail`)."""
    return {
        "Source": EVENTBRIDGE_SOURCE,
        "DetailType": str(event.get("type", "unknown")),
        "Detail": json.dumps(event),
        "EventBusName": bus_name,
    }
