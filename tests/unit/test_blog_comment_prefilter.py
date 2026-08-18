from __future__ import annotations

from app.ai.engines.content_analyzer import run_blog_comment_prefilter


class TestBlogCommentPrefilter:
    def test_short_greeting_is_not_rejected(self):
        result = run_blog_comment_prefilter("hi")
        assert not result.rejected

    def test_url_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("Check this out: https://example.com")
        assert result.rejected
        assert result.category == "spam"

    def test_email_is_rejected_as_privacy(self):
        result = run_blog_comment_prefilter("Email toi la abc@gmail.com")
        assert result.rejected
        assert result.category == "privacy"

    def test_phone_without_separator_is_rejected_as_privacy(self):
        result = run_blog_comment_prefilter("Lien he 0912345678")
        assert result.rejected
        assert result.category == "privacy"

    def test_phone_with_separator_is_rejected_as_privacy(self):
        result = run_blog_comment_prefilter("Lien he +84 912 345 678")
        assert result.rejected
        assert result.category == "privacy"

    def test_bank_account_like_number_is_rejected_as_privacy(self):
        result = run_blog_comment_prefilter("So tai khoan 1234 5678 9012")
        assert result.rejected
        assert result.category == "privacy"

    def test_address_like_personal_info_is_rejected_as_privacy(self):
        result = run_blog_comment_prefilter("Dia chi nha toi so 12, duong Le Loi, quan 1")
        assert result.rejected
        assert result.category == "privacy"

    def test_repeated_char_spam_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("aaaaaaaaaaaaaaaaaaaa")
        assert result.rejected
        assert result.category == "spam"

    def test_symbol_only_noise_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("............")
        assert result.rejected
        assert result.category == "spam"

    def test_repeated_meaningless_phrase_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("test test test test")
        assert result.rejected
        assert result.category == "spam"

    def test_repeated_pattern_token_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("asdasdasd")
        assert result.rejected
        assert result.category == "spam"

    def test_keyboard_walk_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("qwertyuiop")
        assert result.rejected
        assert result.category == "spam"

    def test_numeric_noise_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("123123123123")
        assert result.rejected
        assert result.category == "spam"

    def test_multi_token_gibberish_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("IH DKSDjndoua mhnjdasdjkad m")
        assert result.rejected
        assert result.category == "spam"

    def test_emoji_only_inappropriate_content_is_rejected(self):
        result = run_blog_comment_prefilter("🖕🖕")
        assert result.rejected
        assert result.category == "offensive"

    def test_emoji_dominant_inappropriate_content_is_rejected(self):
        result = run_blog_comment_prefilter("🍺🍻 ngon")
        assert result.rejected
        assert result.category == "adult"

    def test_neutral_discussion_with_blocked_emoji_is_not_rejected(self):
        result = run_blog_comment_prefilter("Bai viet nay dang giai thich vi sao emoji 🤤 co the bi hieu sai")
        assert not result.rejected

    def test_social_handle_tiktok_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("@besttoydeals")
        assert result.rejected
        assert result.category == "spam"

    def test_social_handle_instagram_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("@toystore_official")
        assert result.rejected
        assert result.category == "spam"

    def test_discord_contact_invite_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("add me on discord")
        assert result.rejected
        assert result.category == "spam"

    def test_external_contact_phrase_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("contact me via social media to discuss")
        assert result.rejected
        assert result.category == "spam"

    def test_username_on_tiktok_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("besttoydeals tren TikTok")
        assert result.rejected
        assert result.category == "spam"

    def test_instagram_lookup_phrase_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("find me on Instagram as toystore_official")
        assert result.rejected
        assert result.category == "spam"

    def test_x_twitter_dm_with_handle_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("dm me on X/Twitter @besttoyshop2026")
        assert result.rejected
        assert result.category == "spam"

    def test_off_platform_contact_phrase_is_rejected_as_spam(self):
        result = run_blog_comment_prefilter("let's talk off platform on telegram")
        assert result.rejected
        assert result.category == "spam"

    def test_regular_platform_discussion_is_not_rejected(self):
        result = run_blog_comment_prefilter("Bai viet nay phan tich xu huong do choi tren instagram")
        assert not result.rejected

    def test_laughter_and_onomatopoeia_not_rejected(self):
        assert not run_blog_comment_prefilter("hahahaha bài viết vui quá").rejected
        assert not run_blog_comment_prefilter("hihihihi bé nhà mình thích lắm").rejected
        assert not run_blog_comment_prefilter("hohohoho đồ chơi giáng sinh").rejected
        assert not run_blog_comment_prefilter("xe ô tô bíp bíp bíp").rejected
        assert not run_blog_comment_prefilter("tàu hỏa chạy tu tu tu tu").rejected
        assert not run_blog_comment_prefilter("chuông kêu reng reng reng").rejected

    def test_gift_and_family_context_not_rejected(self):
        assert not run_blog_comment_prefilter("Shop có tặng quà cho bé nhân dịp sinh nhật").rejected
        assert not run_blog_comment_prefilter("Dẫn con đi chơi công viên và mua đồ chơi").rejected
        assert not run_blog_comment_prefilter("Tình cảm giữa con, mẹ nên lắng nghe").rejected

    def test_date_and_measurements_not_rejected_as_phone(self):
        assert not run_blog_comment_prefilter("Bé sinh ngày 08.05.2020 rất thích xếp hình").rejected
        assert not run_blog_comment_prefilter("Bé nặng 08-09kg chơi vừa vặn").rejected
        assert not run_blog_comment_prefilter("Kích thước hộp đồ chơi 0.8-0.9m").rejected

    def test_tracking_and_barcode_not_rejected_as_bank_account(self):
        assert not run_blog_comment_prefilter("Tra giúp mình mã vận đơn 123456789012").rejected
        assert not run_blog_comment_prefilter("Mã vạch trên hộp là 8938505012345").rejected
