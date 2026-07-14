# -*- coding: utf8 -*-
"""Redis key helper. Optional REDIS_KEY_PREFIX for shared Redis instances."""
import os


def redis_key(key: str) -> str:
    prefix = os.getenv("REDIS_KEY_PREFIX", "")
    if not prefix:
        return str(key)
    if prefix.endswith(":") or prefix.endswith("_"):
        return f"{prefix}{key}"
    return f"{prefix}:{key}"
