"""Constants for the Monarch Insights HA integration."""

DOMAIN = "monarch_insights"
PLATFORMS = ["sensor"]

CONF_EMAIL = "email"
CONF_PASSWORD = "password"
CONF_MFA_METHOD = "mfa_method"
CONF_MFA_CODE = "mfa_code"
CONF_REFRESH_INTERVAL_MIN = "refresh_interval_minutes"
CONF_LOW_BALANCE_FLOOR = "low_balance_floor"
CONF_PRIMARY_CHECKING_ID = "primary_checking_account_id"

DEFAULT_REFRESH_INTERVAL = 60  # minutes
DEFAULT_LOW_BALANCE_FLOOR = 1000

ATTR_LAST_SYNC = "last_sync"
ATTR_BREAKDOWN = "breakdown"
ATTR_SOURCE_OPERATION = "source_operation"

SERVICE_REFRESH = "refresh"
SERVICE_RUN_ALERTS = "run_alerts"
SERVICE_GAP_SCAN = "gap_scan"
SERVICE_SUBMIT_LOT = "submit_cost_basis_lot"
