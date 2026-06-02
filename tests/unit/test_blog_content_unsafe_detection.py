from __future__ import annotations

from app.features.blog_content.service import _detect_unsafe_content


def test_detect_unsafe_content_blocks_real_profanity() -> None:
    assert _detect_unsafe_content("This is shit.") is not None
    assert _detect_unsafe_content("Go die now") is not None


def test_detect_unsafe_content_avoids_substring_false_positive() -> None:
    assert _detect_unsafe_content("splash it with water") is None
    assert _detect_unsafe_content("friendship games for children") is None
    assert _detect_unsafe_content("Educational water blaster toys for summer") is None
