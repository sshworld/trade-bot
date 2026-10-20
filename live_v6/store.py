"""Crash-safe JSON journal (write tmp → fsync → rename). The journal is a cache: the exchange is the truth."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path


class MemoryStore:
    def __init__(self, data: dict | None = None):
        self.data = data or {}

    def load(self) -> dict:
        return copy.deepcopy(self.data)

    def save(self, state: dict):
        self.data = copy.deepcopy(state)


class JsonStore:
    def __init__(self, path):
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        return json.loads(self.path.read_text())

    def save(self, state: dict):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        with open(tmp, "w") as f:
            json.dump(state, f, default=str)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, self.path)
