from __future__ import annotations

import hashlib
import random
from pathlib import Path
from typing import Any

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt


def _seed_from_id(video_id: str) -> int:
    digest = hashlib.sha256(video_id.encode("utf-8")).hexdigest()
    return int(digest[8:24], 16)


def build_curve(video_id: str, points: int = 60) -> list[dict[str, float]]:
    seed = _seed_from_id(video_id)
    rng = random.Random(seed)
    curve: list[dict[str, float]] = []
    value = rng.uniform(0.2, 0.5)
    for i in range(points):
        delta = rng.uniform(-0.08, 0.12)
        value = min(1.0, max(0.0, value + delta))
        curve.append({"t": float(i), "v": round(value, 3)})
    return curve


def save_curve_image(curve: list[dict[str, Any]], path: Path) -> None:
    times = [float(p.get("t", idx)) for idx, p in enumerate(curve)]
    values = [float(p.get("v", 0.0)) for p in curve]
    plt.figure(figsize=(8, 3))
    plt.plot(times, values, color="#2563eb", linewidth=2)
    plt.ylim(0, 1)
    plt.xlabel("Time (s)")
    plt.ylabel("Emotion")
    plt.title("Emotion Curve")
    plt.grid(alpha=0.2)
    plt.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    plt.savefig(path, dpi=160)
    plt.close()
