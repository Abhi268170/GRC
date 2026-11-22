"""Password hashing (Argon2). Hashing takes tens of milliseconds of CPU, so request handlers use
the async wrappers, which run it in a thread and keep the event loop free."""

import asyncio

from pwdlib import PasswordHash

_hasher = PasswordHash.recommended()  # argon2

# Checked when a login names an email that doesn't exist, so that it takes as long as a real check
# and the response time doesn't reveal which emails have accounts.
_DUMMY_HASH = _hasher.hash("not-a-real-password")


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return _hasher.verify(password, password_hash)


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(_hasher.hash, password)


async def verify_password_async(password: str, password_hash: str | None) -> bool:
    """With no hash (unknown account) it still does the work of a check, and returns False."""
    ok = await asyncio.to_thread(_hasher.verify, password, password_hash or _DUMMY_HASH)
    return ok and password_hash is not None
