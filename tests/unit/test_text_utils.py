from __future__ import annotations

from app.utils.text_utils import has_hard_profanity, normalize_vietnamese_text


def test_normalize_vietnamese_text_keeps_boundaries() -> None:
    assert normalize_vietnamese_text("Sản phẩm tốt!") == "san pham tot!"
    assert normalize_vietnamese_text("   Đẹp   lắm   ") == "dep lam"
    assert normalize_vietnamese_text("ĐỒ CHƠI TRẺ EM") == "do choi tre em"
    assert normalize_vietnamese_text("") == ""
    assert normalize_vietnamese_text(None) == ""


def test_has_hard_profanity_blocks_real_cases() -> None:
    assert has_hard_profanity("con cac")
    assert has_hard_profanity("con cặc")
    assert has_hard_profanity("địt con mẹ")
    assert has_hard_profanity("dmm")
    assert has_hard_profanity("chó đẻ")
    assert has_hard_profanity("thằng khốn nạn")
    assert has_hard_profanity("mất dạy")
    assert has_hard_profanity("c-o-n c-ạ-c")
    assert has_hard_profanity("con cko's")
    assert has_hard_profanity("kac")


def test_has_hard_profanity_avoids_compact_false_positive() -> None:
    assert not has_hard_profanity("splash it with water")
    assert not has_hard_profanity("friendship activities")
    assert not has_hard_profanity("bullshitology")
    assert not has_hard_profanity("đồ chơi trẻ em")
    assert not has_hard_profanity("cửa hàng đồ chơi")
    assert not has_hard_profanity("học sinh")
