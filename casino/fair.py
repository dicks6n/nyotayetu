"""Provably-fair random floats: HMAC_SHA256(server_seed, "client_seed:nonce:cursor"),
each 4 bytes -> one float in [0, 1). Mirrored in static/js/casino-fair.js for verification."""
from __future__ import annotations

import hashlib
import hmac


def floats(server_seed: str, client_seed: str, nonce: int, count: int) -> list[float]:
    out, cursor = [], 0
    while len(out) < count:
        digest = hmac.new(server_seed.encode(), f"{client_seed}:{nonce}:{cursor}".encode(), hashlib.sha256).digest()
        for i in range(0, 32, 4):
            b = digest[i:i + 4]
            out.append(b[0] / 256 + b[1] / 256 ** 2 + b[2] / 256 ** 3 + b[3] / 256 ** 4)
            if len(out) == count:
                break
        cursor += 1
    return out
