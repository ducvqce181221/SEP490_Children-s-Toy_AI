from __future__ import annotations

import pytest
from app.utils.text_utils import normalize_vietnamese_text, has_hard_profanity


def test_normalize_vietnamese_text():
    assert normalize_vietnamese_text("Sản phẩm tốt!") == "san pham tot!"
    assert normalize_vietnamese_text("   Đẹp   lắm   ") == "dep lam"
    assert normalize_vietnamese_text("ĐỒ CHƠI TRẺ EM") == "do choi tre em"
    assert normalize_vietnamese_text("") == ""
    assert normalize_vietnamese_text(None) == ""


def test_has_hard_profanity():
    # Direct bad words (casing and accents should be normalized)
    assert has_hard_profanity("con cac")
    assert has_hard_profanity("con cặc")
    assert has_hard_profanity("địt con mẹ")
    assert has_hard_profanity("dmm")
    assert has_hard_profanity("cl")
    assert has_hard_profanity("lol")
    assert has_hard_profanity("vãi")
    assert has_hard_profanity("chó đẻ")
    
    # Teen code and vulgar slangs
    assert has_hard_profanity("Sãn phẩm như con kặc cà cko's")
    assert has_hard_profanity("con cko's")
    assert has_hard_profanity("kac")
    assert has_hard_profanity("cko")

    # Clean words should not match
    assert not has_hard_profanity("Sản phẩm tốt")
    assert not has_hard_profanity("Cá cảnh đẹp")
    assert not has_hard_profanity("các sản phẩm của tôi")
    assert not has_hard_profanity("cho em hỏi")
    assert not has_hard_profanity("Dịch vụ ổn định")
    assert not has_hard_profanity(None)
    assert not has_hard_profanity("")
