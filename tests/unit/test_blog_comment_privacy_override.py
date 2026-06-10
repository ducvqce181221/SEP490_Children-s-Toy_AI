from __future__ import annotations

from app.application.moderation.blog_comment import BlogCommentModerationService


class TestBlogCommentPrivacyOverride:
    def test_keep_privacy_category(self):
        category = BlogCommentModerationService._resolve_reason_category(
            category="privacy",
            flags=[],
            reason="",
            comment="",
        )
        assert category == "privacy"

    def test_override_to_privacy_when_flag_signals_personal_info(self):
        category = BlogCommentModerationService._resolve_reason_category(
            category="offensive",
            flags=["contains_personal_info"],
            reason="",
            comment="",
        )
        assert category == "privacy"

    def test_override_to_privacy_when_reason_signals_personal_info(self):
        category = BlogCommentModerationService._resolve_reason_category(
            category="offensive",
            flags=[],
            reason="contains private personal information",
            comment="",
        )
        assert category == "privacy"

    def test_override_to_privacy_when_comment_has_contact_cue_and_number(self):
        category = BlogCommentModerationService._resolve_reason_category(
            category="offensive",
            flags=[],
            reason="",
            comment="thong tin cua toi SDTH 09071231",
        )
        assert category == "privacy"

    def test_keep_original_category_without_privacy_signals(self):
        category = BlogCommentModerationService._resolve_reason_category(
            category="offensive",
            flags=["toxic_language"],
            reason="abusive wording",
            comment="ban noi chuyen bat lich su",
        )
        assert category == "offensive"

