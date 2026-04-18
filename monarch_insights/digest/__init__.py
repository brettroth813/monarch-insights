"""Daily digest formatter — rolls every insight + alert into a single Markdown message.

Usage from the daemon::

    digest = DailyDigest.build(context)
    await dispatcher.send(digest.to_alert())

The same content can also be exported to Sheets / emailed / pushed to HA persistent
notification.
"""

from monarch_insights.digest.builder import DailyDigest

__all__ = ["DailyDigest"]
