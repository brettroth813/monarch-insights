"""Bulk data ingestion — pulls historical finance data into the local cache from
sources other than Monarch's live API.

Currently covered:

* :mod:`monarch_insights.ingest.csv_monarch` — imports Monarch Money's
  ``Transactions.csv`` and ``Balances.csv`` exports.

Future sources (e.g. bank OFX/QFX, custodian PDFs) will land here with the same
shape: produce :class:`monarch_insights.models.Account` + :class:`Transaction`
instances and write them to the :class:`MonarchCache` that insights + sensors
already read from.
"""

from monarch_insights.ingest.csv_monarch import (
    ImportResult,
    MonarchCsvImporter,
    stable_account_id,
)

__all__ = ["ImportResult", "MonarchCsvImporter", "stable_account_id"]
