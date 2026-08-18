"""
auth.py

Instead of trusting a client-supplied company_public_id (which anyone
could tamper with), we forward the SAME bearer token the frontend sent
us straight to Slim's own "/auth" endpoint. Slim already knows how to
verify its own JWTs (it holds the signing secret, which this Python
service does not) — so we let Slim be the source of truth for
"who is this token actually for?" on every request.

This means: even if someone edits the request body to claim a
different company_public_id, it won't matter — we only trust whatever
company Slim itself says the token belongs to.
"""

import requests

from config import SLIM_API_BASE

# --------------------------------------------------
# CONFIRM THIS PATH. Your login endpoint is "/auth/login", so your
# "current user" endpoint is likely "/auth/login" following the same
# pattern -- but confirm the real path and update if different.
# --------------------------------------------------
ME_ENDPOINT = f"{SLIM_API_BASE}/auth/login"


class AuthError(Exception):
    """Raised when the token is missing, invalid, or Slim rejects it."""
    pass


def get_current_user_company(bearer_token: str) -> dict:
    """
    Forwards the bearer token to Slim's "current user" endpoint and
    returns the caller's company info: {"public_id": ..., "name": ...}

    Raises AuthError if the token is invalid/expired, the request
    fails outright, or the response doesn't have the expected shape.
    """
    if not bearer_token:
        raise AuthError("Missing authentication token.")

    try:
        resp = requests.get(
            ME_ENDPOINT,
            headers={"Authorization": f"Bearer {bearer_token}"},
            timeout=15,
        )
    except requests.exceptions.RequestException as e:
        raise AuthError(f"Could not reach authentication service: {e}") from e

    if resp.status_code == 401:
        raise AuthError("Your session has expired. Please log in again.")

    if resp.status_code >= 400:
        raise AuthError(
            f"Authentication service returned {resp.status_code} for {ME_ENDPOINT}. "
            f"Response body: {resp.text[:300]}"
        )

    body = resp.json()

    # Mirrors the shape from your original login response:
    # { "user": { "company": { "public_id": ..., "name": ... } } }
    # Adjust this extraction if /me returns a different shape —
    # print(body) temporarily to check if this raises.
    try:
        company = body["user"]["company"]
    except (KeyError, TypeError) as e:
        raise AuthError(
            f"Unexpected /me response shape. Got top-level keys: {list(body.keys())}. "
            f"Update auth.py's get_current_user_company() to match the real shape."
        ) from e

    return {
        "public_id": company["public_id"],
        "name": company["name"],
    }