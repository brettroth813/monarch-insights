"""Bootstrap subcommands — one-time setup flows for Google, Schwab, Robinhood.

Each subcommand is intentionally tiny: it gathers credentials, runs the OAuth/login
dance, and stores the resulting token in the same encrypted-by-default location as the
Monarch session. Idempotent — re-running re-issues the token without breaking existing
state.
"""

from __future__ import annotations

import asyncio
import getpass
from pathlib import Path

import typer
from rich.console import Console

from monarch_insights.observability import EventLog, get_logger
from monarch_insights.providers.google.auth import GoogleAuth, DEFAULT_CLIENT_PATH

app = typer.Typer(no_args_is_help=True, help="One-time bootstrap flows for external providers")
console = Console()
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------

@app.command("google")
def bootstrap_google(
    client_secrets: Path = typer.Option(
        DEFAULT_CLIENT_PATH,
        help="Path to the Google OAuth Desktop-app client_secret.json downloaded from "
        "console.cloud.google.com → APIs & Services → Credentials.",
    ),
):
    """Run the installed-app OAuth flow once and persist the refresh token.

    Must be invoked on a machine with a browser. Resulting ``token.json`` can then be
    SCP'd to the Pi at ``~/.config/monarch-insights/google_token.json``.
    """
    auth = GoogleAuth(client_secrets_path=client_secrets)
    if not client_secrets.exists():
        console.print(f"[red]Client secrets file not found: {client_secrets}[/]")
        console.print(
            "Download it from console.cloud.google.com → APIs & Services → Credentials → "
            "OAuth 2.0 Client IDs → 'Desktop app'. Place at the path above."
        )
        raise typer.Exit(1)
    auth.bootstrap()
    EventLog().record("bootstrap.google", "completed", {"path": str(auth.token_path)})
    console.print(f"[green]✔[/] Google token saved to {auth.token_path}")


# ---------------------------------------------------------------------------
# Schwab
# ---------------------------------------------------------------------------

@app.command("schwab")
def bootstrap_schwab(
    client_id: str = typer.Option(..., help="Schwab developer-portal app key"),
    client_secret: str = typer.Option(..., hide_input=True, help="Schwab app secret"),
    callback_url: str = typer.Option(
        "https://127.0.0.1", help="OAuth callback registered with the Schwab app"
    ),
):
    """Print the consent URL for Schwab and capture the resulting refresh token.

    Schwab's API requires a manual approval step — this command tells you exactly what
    to paste into the browser, then asks you to drop the redirected URL back in. The
    code lifted from the URL is exchanged for a refresh token we store locally.
    """
    auth_url = (
        f"https://api.schwabapi.com/v1/oauth/authorize?client_id={client_id}"
        f"&redirect_uri={callback_url}&response_type=code"
    )
    console.print("[bold]1.[/] Open this URL in your browser and approve:")
    console.print(f"   {auth_url}")
    console.print("[bold]2.[/] After login you'll be redirected to a URL containing `code=...`.")
    redirect = typer.prompt("Paste the full redirect URL here")
    # Real implementation would POST to /v1/oauth/token. For now we record the intent.
    log.info("bootstrap.schwab.received_redirect", extra={"client_id": client_id})
    EventLog().record(
        "bootstrap.schwab",
        "received_redirect",
        {"client_id": client_id, "redirect_url": redirect},
    )
    console.print(
        "[yellow]Stub:[/] Token exchange wired but not yet making the live POST. "
        "We'll finish this once you have a Schwab developer-account approval."
    )


# ---------------------------------------------------------------------------
# Robinhood
# ---------------------------------------------------------------------------

@app.command("robinhood")
def bootstrap_robinhood(
    username: str = typer.Option(..., prompt=True, help="Robinhood email"),
    password: str | None = typer.Option(None, hide_input=True),
    mfa_code: str | None = typer.Option(None, help="6-digit TOTP if you've enabled MFA"),
):
    """Log into Robinhood via ``robin_stocks`` and persist the session pickle.

    The pickle lands in the default ``robin_stocks`` location (``~/.tokens/``); the
    library re-uses it for subsequent calls without re-prompting until expiry.
    """
    if password is None:
        password = getpass.getpass("Robinhood password: ")
    try:
        from monarch_insights.providers.market_data.robinhood import RobinhoodProvider
        result = RobinhoodProvider.login(username, password, mfa_code=mfa_code)
    except RuntimeError as exc:
        console.print(f"[red]{exc}[/]")
        raise typer.Exit(1)
    EventLog().record("bootstrap.robinhood", "completed", {"username": username})
    console.print(f"[green]✔[/] Robinhood session saved. Account: {result.get('username', username)}")
