"""
discord_notify.py

Simple Discord webhook poster used by the Local Workout Agent.

Public API
----------
post_webhook(message: str, webhook_url: str, username: str | None = None,
             avatar_url: str | None = None, retries: int = 2) -> bool

Returns True on success, False on failure.

Notes
- Requires the `requests` package.
- Keep the webhook URL secret. The app reads DISCORD_WEBHOOK_URL from the
  environment when posting from the web UI.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Optional

import requests

DEFAULT_TIMEOUT = 5.0
DEFAULT_RETRIES = 2
RETRY_BACKOFF = 0.5


def post_webhook(message: str,
                 webhook_url: str,
                 username: Optional[str] = None,
                 avatar_url: Optional[str] = None,
                 retries: int = DEFAULT_RETRIES) -> bool:
    """
    Post a message to a Discord webhook.

    Parameters
    ----------
    message
        Plain text message to post.
    webhook_url
        Full Discord webhook URL.
    username
        Optional override for the webhook username.
    avatar_url
        Optional avatar image URL for the webhook message.
    retries
        Number of retry attempts on transient failures.

    Returns
    -------
    bool
        True if the post succeeded (HTTP 204), False otherwise.
    """
    if not webhook_url:
        logging.error("No webhook URL provided to post_webhook")
        return False

    payload = {"content": message}
    if username:
        payload["username"] = username
    if avatar_url:
        payload["avatar_url"] = avatar_url

    headers = {"Content-Type": "application/json"}

    attempt = 0
    while attempt <= retries:
        try:
            resp = requests.post(
                webhook_url,
                data=json.dumps(payload),
                headers=headers,
                timeout=DEFAULT_TIMEOUT,
            )
            # Discord returns 204 No Content on success for webhook posts
            if resp.status_code == 204:
                return True
            # For rate limit responses, Discord returns 429 with JSON body
            if resp.status_code == 429:
                try:
                    body = resp.json()
                    retry_after = float(body.get("retry_after", RETRY_BACKOFF))
                except Exception:
                    retry_after = RETRY_BACKOFF
                logging.warning("Rate limited by Discord; sleeping %.2fs",
                                retry_after)
                time.sleep(retry_after)
            else:
                logging.warning(
                    "Discord webhook returned status %s: %s",
                    resp.status_code,
                    resp.text[:200],
                )
                # For 5xx errors, retry; for 4xx (except 429) do not retry.
                if 500 <= resp.status_code < 600:
                    attempt += 1
                    time.sleep(RETRY_BACKOFF * attempt)
                    continue
                return False
        except requests.RequestException as exc:
            logging.exception("RequestException posting to Discord: %s", exc)
            attempt += 1
            time.sleep(RETRY_BACKOFF * attempt)
            continue

    logging.error(
        "Failed to post to Discord webhook after %d attempts", retries)
    return False
