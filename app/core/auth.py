import hashlib
import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol


class AuthenticationError(Exception):
    """Credential missing or not valid. Deliberately carries no detail about why."""


@dataclass(frozen=True)
class Identity:
    """Authenticated caller. Always derived from a verified credential, never from client input."""

    user_id: str


class TokenVerifier(Protocol):
    def verify(self, token: str) -> Identity:
        """Returns the identity the token belongs to; raises AuthenticationError otherwise."""
        ...


class ApiKeyVerifier:
    """Verifies per-user API keys against stored SHA-256 hashes (key hash -> user_id)."""

    def __init__(self, key_hashes: Mapping[str, str]) -> None:
        self._key_hashes = dict(key_hashes)

    def verify(self, token: str) -> Identity:
        if not token:
            raise AuthenticationError
        digest = hashlib.sha256(token.encode()).hexdigest()
        matched: str | None = None
        for stored_hash, user_id in self._key_hashes.items():
            if hmac.compare_digest(digest, stored_hash):
                matched = user_id
        if matched is None:
            raise AuthenticationError
        return Identity(user_id=matched)


def extract_bearer_token(authorization: str | None) -> str | None:
    """Returns the token from an `Authorization: Bearer <token>` header, or None if absent or malformed."""
    if not authorization:
        return None
    scheme, _, token = authorization.strip().partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        return None
    return token
