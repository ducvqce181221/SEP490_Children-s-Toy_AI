"""
tests/unit/test_image_prefilter.py
------------------------------------
Unit tests for image_pipeline/prefilter.py.
Uses synthetic PIL images — no external API calls.
"""

from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from app.features.moderation.product_review.image_pipeline.prefilter import run_image_prefilter
from app.features.moderation.schemas import ModerationDecision


def _make_image(color: tuple, size: tuple = (200, 200)) -> Image.Image:
    return Image.new("RGB", size, color)


def _make_noise_image(size: tuple = (200, 200)) -> Image.Image:
    arr = np.random.randint(100, 200, (*size, 3), dtype=np.uint8)
    return Image.fromarray(arr)


class TestRunImagePrefilter:

    def test_black_image_rejected(self):
        img = _make_image((0, 0, 0))
        result = run_image_prefilter(img, raw_bytes=b"fake", existing_phashes=[])
        assert result.decision == ModerationDecision.REJECTED
        assert "black_image" in result.flags

    def test_very_dark_image_rejected(self):
        img = _make_image((10, 10, 10))
        result = run_image_prefilter(img, raw_bytes=b"fake", existing_phashes=[])
        assert result.decision == ModerationDecision.REJECTED

    def test_solid_white_rejected(self):
        img = _make_image((255, 255, 255))
        result = run_image_prefilter(img, raw_bytes=b"fake", existing_phashes=[])
        assert result.decision == ModerationDecision.REJECTED
        assert "uniform_image" in result.flags

    def test_solid_grey_rejected(self):
        img = _make_image((128, 128, 128))
        result = run_image_prefilter(img, raw_bytes=b"fake", existing_phashes=[])
        assert result.decision == ModerationDecision.REJECTED

    def test_noise_image_passes_prefilter(self):
        img = _make_noise_image()
        result = run_image_prefilter(img, raw_bytes=b"fake", existing_phashes=[])
        assert result.decision != ModerationDecision.REJECTED or "phash_duplicate" in result.flags

    def test_phash_duplicate_rejected(self):
        from app.utils.phash import compute_phash
        img = _make_noise_image()
        phash = compute_phash(img)
        result = run_image_prefilter(img, raw_bytes=b"fake", existing_phashes=[phash])
        assert result.decision == ModerationDecision.REJECTED
        assert "phash_duplicate" in result.flags

    def test_different_phash_not_rejected(self):
        from app.utils.phash import compute_phash
        img1 = _make_noise_image()
        img2 = _make_noise_image()
        phash1 = compute_phash(img1)
        result = run_image_prefilter(img2, raw_bytes=b"fake", existing_phashes=[phash1])
        if result.decision == ModerationDecision.REJECTED:
            assert "phash_duplicate" not in result.flags
