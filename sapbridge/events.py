"""Business-event envelope and validation for the MOCK SAP event source.

Events use the CloudEvents 1.0 attribute names (specversion, id, source, type, time,
subject, data). Everything in this project is synthetic: `source` must start with
"sap-mock://", so a mock event can never be mistaken for a real one.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

SPECVERSION = "1.0"
SOURCE_PREFIX = "sap-mock://"

PURCHASE_ORDER_CREATED = "sap.mock.PurchaseOrder.Created"
PURCHASE_ORDER_CHANGED = "sap.mock.PurchaseOrder.Changed"
GOODS_RECEIPT_POSTED = "sap.mock.GoodsReceipt.Posted"
EVENT_TYPES = (PURCHASE_ORDER_CREATED, PURCHASE_ORDER_CHANGED, GOODS_RECEIPT_POSTED)
PO_STATUSES = ("OPEN", "APPROVED", "CLOSED")

_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
_PO_ID = re.compile(r"^\d{10}$")
_CURRENCY = re.compile(r"^[A-Z]{3}$")
_PLANT = re.compile(r"^[A-Z0-9]{4}$")


class EventError(ValueError):
    """Raised when an event does not match the expected structure."""

    def __init__(self, path: str, message: str):
        super().__init__(f"{path}: {message}")
        self.path = path
        self.message = message


@dataclass(frozen=True)
class Event:
    id: str
    type: str
    source: str
    time: datetime  # timezone-aware, UTC
    subject: str
    data: dict[str, Any]

    @property
    def entity_key(self) -> str:
        """The business object this event belongs to (a purchase order)."""
        return f"PO#{self.data['po_id']}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "specversion": SPECVERSION,
            "id": self.id,
            "source": self.source,
            "type": self.type,
            "time": self.time.isoformat().replace("+00:00", "Z"),
            "subject": self.subject,
            "datacontenttype": "application/json",
            "data": self.data,
        }


def _obj(value: Any, path: str) -> dict:
    if not isinstance(value, dict):
        raise EventError(path, "must be an object")
    return value


def _text(obj: dict, key: str, path: str, pattern: re.Pattern | None = None) -> str:
    value = obj.get(key)
    where = f"{path}.{key}"
    if not isinstance(value, str) or not value.strip():
        raise EventError(where, "must be a non-empty string")
    if pattern is not None and not pattern.match(value):
        raise EventError(where, "has an invalid format")
    return value


def _positive_int(obj: dict, key: str, path: str) -> int:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise EventError(f"{path}.{key}", "must be a positive integer")
    return value


def _price(obj: dict, key: str, path: str) -> float:
    value = obj.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise EventError(f"{path}.{key}", "must be a number >= 0")
    return value


def _parse_time(value: Any, path: str) -> datetime:
    if not isinstance(value, str):
        raise EventError(path, "must be an ISO-8601 string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise EventError(path, "must be an ISO-8601 timestamp") from None
    if parsed.tzinfo is None:
        raise EventError(path, "must include a UTC offset")
    return parsed.astimezone(timezone.utc)


def _validate_purchase_order(raw: Any, *, created: bool) -> dict[str, Any]:
    data = _obj(raw, "$.data")
    status = data.get("status")
    if status not in PO_STATUSES:
        raise EventError("$.data.status", f"must be one of {PO_STATUSES}")
    if created and status != "OPEN":
        raise EventError("$.data.status", "must be OPEN for a Created event")
    items_raw = data.get("items")
    if not isinstance(items_raw, list) or not items_raw:
        raise EventError("$.data.items", "must be a non-empty list")
    items = []
    for index, item_raw in enumerate(items_raw):
        path = f"$.data.items[{index}]"
        item = _obj(item_raw, path)
        items.append({
            "material": _text(item, "material", path),
            "quantity": _positive_int(item, "quantity", path),
            "unit_price": _price(item, "unit_price", path),
        })
    return {
        "po_id": _text(data, "po_id", "$.data", _PO_ID),
        "supplier": _text(data, "supplier", "$.data"),
        "currency": _text(data, "currency", "$.data", _CURRENCY),
        "status": status,
        "items": items,
    }


def _validate_goods_receipt(raw: Any) -> dict[str, Any]:
    data = _obj(raw, "$.data")
    return {
        "po_id": _text(data, "po_id", "$.data", _PO_ID),
        "material": _text(data, "material", "$.data"),
        "quantity": _positive_int(data, "quantity", "$.data"),
        "plant": _text(data, "plant", "$.data", _PLANT),
    }


def validate_event(raw: Any) -> Event:
    """Validate a decoded JSON event and return a normalised Event."""
    root = _obj(raw, "$")
    if root.get("specversion") != SPECVERSION:
        raise EventError("$.specversion", f"must be {SPECVERSION!r}")
    event_type = root.get("type")
    if event_type not in EVENT_TYPES:
        raise EventError("$.type", f"must be one of {EVENT_TYPES}")
    source = _text(root, "source", "$")
    if not source.startswith(SOURCE_PREFIX):
        raise EventError("$.source", f"must start with {SOURCE_PREFIX!r} (mock data only)")

    if event_type == GOODS_RECEIPT_POSTED:
        data = _validate_goods_receipt(root.get("data"))
    else:
        data = _validate_purchase_order(root.get("data"), created=event_type == PURCHASE_ORDER_CREATED)

    subject = root.get("subject")
    if subject is None:
        subject = f"PurchaseOrder/{data['po_id']}"
    elif not isinstance(subject, str) or not subject.strip():
        raise EventError("$.subject", "must be a non-empty string when present")

    return Event(
        id=_text(root, "id", "$", _ID),
        type=event_type,
        source=source,
        time=_parse_time(root.get("time"), "$.time"),
        subject=subject,
        data=data,
    )
