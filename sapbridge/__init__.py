"""sap-event-bridge: a pipeline for mock SAP business events on AWS."""

from .events import Event, EventError, validate_event

__all__ = [
    "Event",
    "EventError",
    "validate_event",
]
__version__ = "0.1.0"
