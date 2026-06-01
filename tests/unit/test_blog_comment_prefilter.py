from __future__ import annotations

from app.features.moderation.blog_comment.prefilter import run_blog_comment_prefilter


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

