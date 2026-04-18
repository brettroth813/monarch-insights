// ==UserScript==
// @name         Monarch Insights — auto-sync token to Home Assistant
// @namespace    https://github.com/brettroth813/monarch-insights
// @version      0.1.0
// @description  Intercepts Monarch's graphql fetches, captures the session token, and POSTs it to a Home Assistant webhook so the Monarch Insights integration always has a fresh token.
// @author       Brett Roth
// @match        https://app.monarch.com/*
// @match        https://app.monarch.com
// @run-at       document-idle
// @grant        GM_xmlhttpRequest
// @grant        GM_setValue
// @grant        GM_getValue
// @connect      *
// ==/UserScript==

/*
 * Install:
 *   1. Set the webhook URL in the `WEBHOOK_URL` constant below, OR leave it blank
 *      and the script will prompt you once (stored via GM_setValue).
 *   2. Tampermonkey / Violentmonkey: Create new → paste → save.
 *   3. Visit app.monarch.com. On every page the script captures the first outgoing
 *      authenticated graphql request and pushes its token to HA.
 *   4. The script rate-limits itself to one successful sync every 5 minutes so it
 *      doesn't spam the webhook on every navigation.
 */

(function () {
  'use strict';

  const WEBHOOK_URL = '';   // ← paste your webhook URL here, or leave blank to be prompted
  const SYNC_COOLDOWN_MS = 5 * 60 * 1000;

  // --------------------------------------------------------------------
  // webhook URL resolution
  // --------------------------------------------------------------------

  function resolveWebhookUrl() {
    if (WEBHOOK_URL) return WEBHOOK_URL;
    const stored = typeof GM_getValue === 'function' ? GM_getValue('monarch_insights_webhook_url') : null;
    if (stored) return stored;
    const entered = prompt('Enter your Home Assistant Monarch Insights webhook URL (one-time):');
    if (entered && typeof GM_setValue === 'function') {
      GM_setValue('monarch_insights_webhook_url', entered.trim());
    }
    return (entered || '').trim();
  }

  const hookUrl = resolveWebhookUrl();
  if (!hookUrl) {
    console.warn('[monarch_sync] no webhook URL configured, script inert');
    return;
  }

  // --------------------------------------------------------------------
  // fetch interception
  // --------------------------------------------------------------------

  const origFetch = window.fetch;
  window.fetch = async function (...args) {
    const resp = await origFetch.apply(this, args);
    try {
      const init = args[1] || {};
      const hdrs = new Headers(init.headers || (args[0] && args[0].headers) || {});
      const auth = hdrs.get('authorization') || hdrs.get('Authorization');
      if (auth && auth.toLowerCase().startsWith('token ')) {
        const token = auth.slice(6).trim();
        scheduleSync(token);
      }
    } catch (err) {
      // Swallow; we don't want capture bugs to break the user's Monarch session.
      console.debug('[monarch_sync] capture check failed', err);
    }
    return resp;
  };

  // --------------------------------------------------------------------
  // Rate-limited push to HA webhook
  // --------------------------------------------------------------------

  let lastSync = 0;
  let lastToken = null;

  function scheduleSync(token) {
    if (token === lastToken && Date.now() - lastSync < SYNC_COOLDOWN_MS) return;
    lastToken = token;
    lastSync = Date.now();
    postToken(token);
  }

  function postToken(token) {
    const payload = JSON.stringify({ token });
    // Prefer GM_xmlhttpRequest so cross-origin POSTs always work; fall back to fetch
    // (the webhook URL is often same-origin to HA which is fine for fetch too).
    if (typeof GM_xmlhttpRequest === 'function') {
      GM_xmlhttpRequest({
        method: 'POST',
        url: hookUrl,
        headers: { 'Content-Type': 'application/json' },
        data: payload,
        timeout: 10000,
        onload: (r) => console.log('[monarch_sync] pushed, HA responded', r.status, r.responseText),
        onerror: (e) => console.warn('[monarch_sync] push failed', e),
      });
    } else {
      fetch(hookUrl, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: payload,
      }).then(
        (r) => console.log('[monarch_sync] pushed, HA responded', r.status),
        (e) => console.warn('[monarch_sync] push failed', e)
      );
    }
  }

  console.log('[monarch_sync] armed. Will push token to', hookUrl);
})();
