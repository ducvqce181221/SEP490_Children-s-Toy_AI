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
    assert has_hard_profanity("vãi cả cức")
    assert has_hard_profanity("v~ cả cứk")

    # Mild slang / ambiguous words are NOT strictly blocked by pre-filter (processed by LLM instead)
    assert not has_hard_profanity("cl")
    assert not has_hard_profanity("lol")
    assert not has_hard_profanity("vãi")
    assert not has_hard_profanity("đỉnh vcl")
    assert not has_hard_profanity("buổi sáng")

    # Clean words should not match
    assert not has_hard_profanity("Sản phẩm tốt")
    assert not has_hard_profanity("Cá cảnh đẹp")
    assert not has_hard_profanity("các sản phẩm của tôi")
    assert not has_hard_profanity("cho em hỏi")
    assert not has_hard_profanity("Dịch vụ ổn định")
    assert not has_hard_profanity(None)
    assert not has_hard_profanity("")


def test_clean_and_normalize_text():
    from app.utils.text_utils import clean_and_normalize_text

    # 1. Test teencode / obfuscated Vietnamese drug-related comment
    teencode_text = "ne^u ba.n muo^'n mua ha`ng tra'ng thi` lie^n he^"
    normalized_teencode = clean_and_normalize_text(teencode_text)
    assert normalized_teencode == "neu ban muon mua hang trang thi lien he"

    # 2. Test English phone number words
    phone_words_eng = "zero nine one two eight zero two zero three one"
    normalized_phone_eng = clean_and_normalize_text(phone_words_eng)
    assert normalized_phone_eng == "0912802031"

    # 3. Test Vietnamese phone number words
    phone_words_vi = "khong chin mot hai tam khong hai khong ba mot"
    normalized_phone_vi = clean_and_normalize_text(phone_words_vi)
    assert normalized_phone_vi == "0912802031"

    # 4. Test mixed language and obfuscation spacing (e.g. g un -> gun)
    mixed_text = "If bạn want to mua a g un, please liên hệ sdt below"
    normalized_mixed = clean_and_normalize_text(mixed_text)
    assert normalized_mixed == "if ban want to mua a gun please lien he sdt below"

    # 5. Null or empty cases
    assert clean_and_normalize_text(None) == ""
    assert clean_and_normalize_text("") == ""
