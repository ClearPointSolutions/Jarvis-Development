"""Authoritative Python domain and wire contracts for Jarvis V1."""

from jarvis_contracts.api import ApiErrorResponse, EventPage, LoginRequest, SessionResponse
from jarvis_contracts.commands import RunCommandRequest
from jarvis_contracts.events import NewEvent, NormalizedEvent
from jarvis_contracts.workflow import WorkflowSpec

__version__ = "1.0.0"

__all__ = [
    "ApiErrorResponse",
    "EventPage",
    "LoginRequest",
    "NewEvent",
    "NormalizedEvent",
    "RunCommandRequest",
    "SessionResponse",
    "WorkflowSpec",
]
