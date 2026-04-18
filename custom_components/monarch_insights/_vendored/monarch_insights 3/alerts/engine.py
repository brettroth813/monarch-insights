"""Alert engine — reduces insight outputs to a stream of structured alerts.

A "rule" is just a callable that takes an ``AlertContext`` (everything insights might
need: accounts, transactions, holdings, recurring, projections, signals, market data
provider) and yields zero or more ``Alert`` objects. Dispatchers consume the stream.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable, Iterable

from monarch_insights.observability import get_logger

log = get_logger(__name__)


class Severity(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


@dataclass
class Alert:
    id: str
    kind: str
    title: str
    message: str
    severity: Severity = Severity.INFO
    detail: dict = field(default_factory=dict)
    suggested_action: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @classmethod
    def new(cls, kind: str, title: str, message: str, **kwargs) -> Alert:
        return cls(id=str(uuid.uuid4()), kind=kind, title=title, message=message, **kwargs)


@dataclass
class AlertContext:
    accounts: list = field(default_factory=list)
    transactions: list = field(default_factory=list)
    holdings: list = field(default_factory=list)
    recurring: list = field(default_factory=list)
    budgets: list = field(default_factory=list)
    goals: list = field(default_factory=list)
    targets: dict = field(default_factory=dict)
    today: date = field(default_factory=date.today)
    extras: dict = field(default_factory=dict)


AlertRule = Callable[[AlertContext], Iterable[Alert]]


class AlertEngine:
    def __init__(self, rules: Iterable[AlertRule] | None = None) -> None:
        self.rules: list[AlertRule] = list(rules or [])

    def add_rule(self, rule: AlertRule) -> None:
        self.rules.append(rule)

    def evaluate(self, context: AlertContext) -> list[Alert]:
        """Run every registered rule and collect the alerts they emit.

        One misbehaving rule shouldn't take down the pipeline, so we wrap each rule in
        a try/except and log the failure with structured context. Callers receive
        whatever alerts the remaining rules produced.
        """
        alerts: list[Alert] = []
        for rule in self.rules:
            rule_name = getattr(rule, "__name__", repr(rule))
            try:
                rule_alerts = list(rule(context) or [])
                alerts.extend(rule_alerts)
                log.debug(
                    "alert.rule.evaluated",
                    extra={"rule": rule_name, "emitted": len(rule_alerts)},
                )
            except Exception:
                log.exception("alert.rule.failed", extra={"rule": rule_name})
        log.info(
            "alert.engine.evaluated",
            extra={
                "rules": len(self.rules),
                "alerts": len(alerts),
                "critical": sum(1 for a in alerts if a.severity == Severity.CRITICAL),
                "warn": sum(1 for a in alerts if a.severity == Severity.WARN),
            },
        )
        return alerts

    async def dispatch(
        self,
        alerts: Iterable[Alert],
        dispatchers: Iterable["AlertDispatcher"],
    ) -> None:
        """Fan each alert out to every dispatcher.

        Dispatchers are isolated: a failure in one (e.g. HA REST endpoint down) does not
        block the others. Every dispatch attempt is logged with structured context so
        downstream tools can count delivery failures.
        """
        dispatchers = list(dispatchers)
        for alert in alerts:
            for d in dispatchers:
                dispatcher_name = d.__class__.__name__
                try:
                    await d.send(alert)
                    log.debug(
                        "alert.dispatched",
                        extra={
                            "alert_id": alert.id,
                            "kind": alert.kind,
                            "severity": alert.severity.value,
                            "dispatcher": dispatcher_name,
                        },
                    )
                except Exception as exc:  # noqa: BLE001 — deliberately tolerant
                    log.warning(
                        "alert.dispatch.failed",
                        extra={
                            "alert_id": alert.id,
                            "dispatcher": dispatcher_name,
                            "error": repr(exc),
                        },
                    )
