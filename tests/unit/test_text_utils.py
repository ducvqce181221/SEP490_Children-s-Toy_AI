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

    # Clean words and false positive edge cases should not match
    assert not has_hard_profanity("Sản phẩm tốt")
    assert not has_hard_profanity("Cá cảnh đẹp")
    assert not has_hard_profanity("các sản phẩm của tôi")
    assert not has_hard_profanity("cho em hỏi")
    assert not has_hard_profanity("Dịch vụ ổn định")
    assert not has_hard_profanity(None)
    assert not has_hard_profanity("")

    # False Positive Cases Fixed:
    # 1. cực (cực kỳ, cực đẹp, cực tốt, cực nhanh)
    assert not has_hard_profanity("Sản phẩm cực kỳ đẹp, cực tốt và giao cực nhanh")
    assert not has_hard_profanity("cuc ky dep, cuc tot")
    # 2. dẻo (đất nặn dẻo, nhựa dẻo, kẹo dẻo)
    assert not has_hard_profanity("Đất nặn dẻo, nhựa dẻo an toàn cho bé")
    assert not has_hard_profanity("dat nan deo")
    # 3. đeo (vòng đeo tay, đồng hồ đeo tay)
    assert not has_hard_profanity("Vòng đeo tay và đồng hồ đeo tay rất xinh")
    assert not has_hard_profanity("vong deo tay")
    # 4. lớn (size lớn, kích thước lớn)
    assert not has_hard_profanity("Bộ xếp hình size lớn, kích thước lớn")
    assert not has_hard_profanity("size lon, kich thuoc lon")
    # 5. lợn (gấu bông con lợn, heo lợn nhựa)
    assert not has_hard_profanity("Gấu bông con lợn màu hồng xinh xắn")
    assert not has_hard_profanity("heo lon nhua")
    # 6. cúc / cục (nút cúc áo, cục gỗ, cục lego)
    assert not has_hard_profanity("Nút cúc áo, cục gỗ xếp hình, cục lego")
    assert not has_hard_profanity("cuc go, cuc lego, nut cuc ao")
    # 7. con chó (chú chó Paw Patrol, chó nhồi bông)
    assert not has_hard_profanity("Chú chó Paw Patrol, chó nhồi bông siêu đáng yêu")
    assert not has_hard_profanity("chu cho bong, con cho peppa")
    # 8. rác rưởi (xe dọn rác, đồ chơi phân loại rác rưởi)
    assert not has_hard_profanity("Bộ đồ chơi phân loại rác rưởi bảo vệ môi trường")
    # 9. dm (kích thước decimet, direct message)
    assert not has_hard_profanity("Kích thước hộp dài 5 dm, cao 3 dm")
    assert not has_hard_profanity("Shop check dm giúp em nha")
    # 10. đít / dệt / Bandit
    assert not has_hard_profanity("Phần đít xe mô hình có gắn pin")
    assert not has_hard_profanity("Bộ máy dệt len cho bé gái")
    assert not has_hard_profanity("Trò chơi board game Bandit")
    # 11. cko / cka (teencode gia đình: chồng / chị)
    assert not has_hard_profanity("Cko mình mua cho bé rất thích")


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
