"""sap-event-bridge: a pipeline for mock SAP business events on AWS."""

from .events import Event, EventError, validate_event
from .mock_source import generate_events, to_eventbridge_entry

__all__ = [
    "Event",
    "EventError",
    "generate_events",
    "to_eventbridge_entry",
    "validate_event",
]
__version__ = "0.1.0"
