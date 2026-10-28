"""Lightweight model persistence.

Serialises trained models to disk with a small metadata envelope so trained
artifacts can be reused across processes and inspected for when they were built.
"""
from __future__ import annotations

import os
import pickle
import time


def save_model(model, path, metadata=None):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    envelope = {
        "created_at": time.time(),
        "version": 1,
        "metadata": metadata or {},
        "model": model,
    }
    with open(path, "wb") as handle:
        pickle.dump(envelope, handle)
    return path


def load_model(path):
    with open(path, "rb") as handle:
        envelope = pickle.load(handle)
    if isinstance(envelope, dict) and "model" in envelope:
        return envelope["model"], envelope.get("metadata", {})
    return envelope, {}
