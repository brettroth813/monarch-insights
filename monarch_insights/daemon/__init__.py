"""Long-running background daemon.

The CLI ``monarch-insights daemon run`` starts an asyncio scheduler that:

* Refreshes Monarch on a configurable interval (default hourly).
* Runs the alert engine after each refresh.
* Writes a daily digest at a configurable hour (default 07:00 local).
* Updates watchlist signal scores.
* Logs everything to the structured logger + event log so you can mine the history.
"""

from monarch_insights.daemon.scheduler import DaemonConfig, MonarchDaemon

__all__ = ["DaemonConfig", "MonarchDaemon"]
