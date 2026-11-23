"""Password hashing with scrypt (memory-hard KDF, RFC 7914) via the stdlib.

Format: scrypt$<log2 N>$<r>$<p>$<salt b64>$<hash b64>.  Parameters are part of
the hash so they can be raised later; `needs_rehash` reports outdated hashes.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re

_N_LOG2, _R, _P, _DKLEN = 15, 8, 1, 32  # N = 32768 (~32 MiB), OWASP-compliant scrypt parameters
_MAXMEM = 128 * 1024 * 1024


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2 ** _N_LOG2, r=_R, p=_P, dklen=_DKLEN, maxmem=_MAXMEM)
    return f"scrypt${_N_LOG2}${_R}${_P}${base64.b64encode(salt).decode()}${base64.b64encode(dk).decode()}"


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        # Burn comparable CPU time so unknown accounts are not distinguishable by timing.
        hashlib.scrypt(password.encode(), salt=b"0" * 16, n=2 ** _N_LOG2, r=_R, p=_P, dklen=_DKLEN, maxmem=_MAXMEM)
        return False
    try:
        algo, n_log2, r, p, salt_b64, hash_b64 = encoded.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt_b64), n=2 ** int(n_log2), r=int(r),
                            p=int(p), dklen=len(base64.b64decode(hash_b64)), maxmem=_MAXMEM)
        return hmac.compare_digest(dk, base64.b64decode(hash_b64))
    except (ValueError, TypeError):
        return False


def needs_rehash(encoded: str) -> bool:
    try:
        _, n_log2, r, p, *_ = encoded.split("$")
        return (int(n_log2), int(r), int(p)) != (_N_LOG2, _R, _P)
    except ValueError:
        return True


def password_policy_errors(password: str, min_length: int = 12) -> list[str]:
    errors = []
    if len(password) < min_length:
        errors.append(f"must be at least {min_length} characters")
    if not re.search(r"[A-Z]", password) or not re.search(r"[a-z]", password):
        errors.append("must contain upper- and lower-case letters")
    if not re.search(r"\d", password):
        errors.append("must contain a digit")
    if not re.search(r"[^A-Za-z0-9]", password):
        errors.append("must contain a symbol")
    return errors
