"""Alerting engine: rules + dispatchers (HA, Gmail, push)."""

from monarch_insights.alerts.engine import Alert, AlertEngine, AlertRule, Severity
from monarch_insights.alerts.rules import default_rules
from monarch_insights.alerts.dispatchers import (
    AlertDispatcher,
    HassNotifyDispatcher,
    LogDispatcher,
    StoreDispatcher,
)

__all__ = [
    "Alert",
    "AlertDispatcher",
    "AlertEngine",
    "AlertRule",
    "HassNotifyDispatcher",
    "LogDispatcher",
    "Severity",
    "StoreDispatcher",
    "default_rules",
]
