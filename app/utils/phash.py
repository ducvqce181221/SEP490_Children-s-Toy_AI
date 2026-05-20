"""
app/utils/phash.py
------------------
Perceptual hash computation and duplicate detection utilities.
"""

from __future__ import annotations

import imagehash
from PIL import Image

from app.core.logging import get_logger

logger = get_logger(__name__)


def compute_phash(image: Image.Image) -> str:
    ph = imagehash.phash(image, hash_size=8)
    return str(ph)


def hamming_distance(hash1: str, hash2: str) -> int:
    if len(hash1) != len(hash2):
        raise ValueError(f"Hash length mismatch: {len(hash1)} vs {len(hash2)}")
    try:
        h1 = imagehash.hex_to_hash(hash1)
        h2 = imagehash.hex_to_hash(hash2)
        return h1 - h2
    except Exception as exc:
        logger.warning("Failed to compute Hamming distance", error=str(exc))
        return 64


def is_duplicate(phash: str, existing_hashes: list[str], threshold: int = 10) -> bool:
    for existing in existing_hashes:
        try:
            if hamming_distance(phash, existing) < threshold:
                return True
        except ValueError:
            continue
    return False
