# Monarch Insights — Browser Sync Bookmarklet

One-click helper that captures your Monarch session token from a browser tab and
pushes it to Home Assistant. Built because Monarch's Cloudflare WAF rejects any
non-browser login (including TLS-fingerprint-impersonating libraries like
`curl_cffi`), so the only reliable way to get a token into HA is from a real
browser that's already logged in.

## How the flow works

1. You log into `app.monarch.com` normally (email+password, "Continue with Apple",
   however your account auth is set up). Your browser now has a valid Monarch
   session token.
2. You click the **Sync Monarch → HA** bookmarklet.
3. The bookmarklet finds your Monarch token (intercepts the next outgoing GraphQL
   request, grabs the `Authorization` header) and POSTs it to the HA webhook you
   configured.
4. HA validates the token by calling Monarch's `me` endpoint, stores it in the
   Monarch Insights config entry, and reloads the coordinator. Sensors start
   updating again within seconds.

## Setup (one time)

### 1. Note your webhook URL

Home Assistant created a unique webhook URL for your Monarch Insights integration
on the first setup. You can find it with:

```bash
.venv/bin/python -m monarch_insights.cli.main bookmarklet
```

…or manually by opening your HA instance's `.storage/core.config_entries` and
finding the `webhook_id` under your Monarch Insights entry. The full URL is:

```
https://<your-ha-host>/api/webhook/<webhook_id>
```

Example: `https://homeassistant.local:8123/api/webhook/monarch_insights_abc123`

> **Reachable from your browser, please.** If your HA is only reachable on the
> local network, your phone/browser must be on that network when you click the
> bookmarklet. Nabu Casa Remote UI works too.

### 2. Make the bookmarklet

Copy this line, replacing `WEBHOOK_URL_HERE` with your real webhook URL:

```javascript
javascript:(async()=>{const u='WEBHOOK_URL_HERE';const orig=window.fetch;let done=false;const deadline=Date.now()+8000;window.fetch=async(...a)=>{const r=await orig(...a);try{const req=a[0];const init=a[1]||{};const hdrs=new Headers(init.headers||(req&&req.headers)||{});const auth=hdrs.get('authorization')||hdrs.get('Authorization');if(!done&&auth&&auth.toLowerCase().startsWith('token ')){done=true;const tok=auth.slice(6).trim();window.fetch=orig;const post=await orig(u,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:tok})});const txt=await post.text();alert(post.ok?('Token synced to HA ✓\\n'+txt):('HA rejected token: '+post.status+'\\n'+txt));}}catch(e){}return r;};fetch('/api/');setTimeout(()=>{if(!done){window.fetch=orig;alert('No Monarch request observed in 8s. Try navigating to a Monarch page first.');}},8500);})();
```

In your browser:

- **Chrome / Edge / Brave / Arc**: drag the bookmarklet from any HTML page that
  links it, or: right-click the bookmarks bar → **Add page…** → Name: `Sync Monarch → HA` → URL: paste the `javascript:...` string → Save.
- **Safari**: bookmarks are finicky with `javascript:` URLs. Create a new bookmark
  anywhere, then right-click → **Edit Address** → paste the string.
- **Firefox**: right-click bookmarks toolbar → **New Bookmark** → paste the URL.

## Using it

1. Open a tab on `app.monarch.com`. Log in if you're not already.
2. Click the **Sync Monarch → HA** bookmarklet.
3. Browser alert confirms success (or shows the HA rejection reason).

Takes ~1 second. Do it whenever HA reports the Monarch integration can't
authenticate (token expired) — typically weeks to months apart.

## Troubleshooting

- **Alert says "No Monarch request observed in 8s."** The bookmarklet only
  captures tokens from outgoing GraphQL calls; if the tab is idle, no request
  fires. Navigate to a different page within Monarch (e.g. Transactions →
  Accounts) with the bookmarklet still active, and it'll grab the next request.
  Retry if needed.
- **Alert says "HA rejected token: 401"**. The token is valid for reading your
  own profile but the HA integration couldn't complete setup. Check HA logs for
  the specific Monarch error.
- **Alert says "HA rejected token: 404"**. The webhook URL is wrong or HA is
  unreachable from your current network. Verify the URL and your VPN/network
  state.
- **Nothing happens at all**. Click the bookmarklet only from a tab on
  `app.monarch.com` (not any other site). If you clicked it elsewhere, the
  bookmarklet is intercepting fetches that don't have Monarch's auth header.

## Prefer a userscript?

For zero-click auto-sync, a Tampermonkey-flavoured version lives in
[`monarch_sync.user.js`](monarch_sync.user.js) — install it and the token
refreshes every time you visit `app.monarch.com`.

## Why not just intercept localStorage?

Monarch's session token does not appear to live in `localStorage` under any
well-known key — `persist:auth` only carries the OAuth `state` string for the
Apple SSO flow, and `gist.web.userToken` belongs to the in-app support widget
(Gist), not Monarch's session. Fetch interception is the reliable path.
