"""
tests/unit/test_image_post_processor.py
-----------------------------------------
Unit tests for image_pipeline/post_processor.py.
"""

from __future__ import annotations

import pytest

from app.application.moderation.image_pipeline import apply_vision_results, PrefilterImageResult
from app.integrations.google_vision import VisionAnalysisResult
from app.schemas.moderation import ModerationDecision


def test_safesearch_hard_violation_rejected():
    pre_res = PrefilterImageResult(decision=ModerationDecision.APPROVED)
    vis_res = VisionAnalysisResult(
        safe_search={"adult": "VERY_LIKELY", "violence": "VERY_UNLIKELY", "racy": "UNLIKELY", "spoof": "UNKNOWN", "medical": "UNKNOWN"},
        labels=[{"description": "toy", "score": 0.9}],
        hard_violation=True,
        violation_reason="adult content detected: VERY_LIKELY",
        toy_label_found=True,
        detected_text=None,
    )
    result = apply_vision_results(pre_res, vis_res)
    assert result.decision == ModerationDecision.REJECTED
    assert "vision_hard_violation" in result.flags
    assert "adult content detected" in result.reason


def test_ocr_url_rejected():
    pre_res = PrefilterImageResult(decision=ModerationDecision.APPROVED)
    vis_res = VisionAnalysisResult(
        safe_search={"adult": "VERY_UNLIKELY", "violence": "VERY_UNLIKELY", "racy": "VERY_UNLIKELY", "spoof": "UNKNOWN", "medical": "UNKNOWN"},
        labels=[{"description": "toy", "score": 0.9}],
        hard_violation=False,
        violation_reason=None,
        toy_label_found=True,
        detected_text="Check out my website at www.mytoy.com",
    )
    result = apply_vision_results(pre_res, vis_res)
    assert result.decision == ModerationDecision.REJECTED
    assert "vision_text_violation" in result.flags
    assert "Contains URL or shortened link" in result.reason


def test_ocr_phone_rejected():
    pre_res = PrefilterImageResult(decision=ModerationDecision.APPROVED)
    vis_res = VisionAnalysisResult(
        safe_search={"adult": "VERY_UNLIKELY", "violence": "VERY_UNLIKELY", "racy": "VERY_UNLIKELY", "spoof": "UNKNOWN", "medical": "UNKNOWN"},
        labels=[{"description": "toy", "score": 0.9}],
        hard_violation=False,
        violation_reason=None,
        toy_label_found=True,
        detected_text="Liên hệ Zalo 0901234567 nhé",
    )
    result = apply_vision_results(pre_res, vis_res)
    assert result.decision == ModerationDecision.REJECTED
    assert "vision_text_violation" in result.flags
    assert "Contains Vietnamese phone number" in result.reason


def test_ocr_bank_rejected():
    pre_res = PrefilterImageResult(decision=ModerationDecision.APPROVED)
    vis_res = VisionAnalysisResult(
        safe_search={"adult": "VERY_UNLIKELY", "violence": "VERY_UNLIKELY", "racy": "VERY_UNLIKELY", "spoof": "UNKNOWN", "medical": "UNKNOWN"},
        labels=[{"description": "toy", "score": 0.9}],
        hard_violation=False,
        violation_reason=None,
        toy_label_found=True,
        detected_text="STK BIDV: 123456789012",
    )
    result = apply_vision_results(pre_res, vis_res)
    assert result.decision == ModerationDecision.REJECTED
    assert "vision_text_violation" in result.flags
    assert "Contains bank-account-like number sequence" in result.reason


def test_no_toy_label_rejected():
    pre_res = PrefilterImageResult(decision=ModerationDecision.APPROVED)
    vis_res = VisionAnalysisResult(
        safe_search={"adult": "VERY_UNLIKELY", "violence": "VERY_UNLIKELY", "racy": "VERY_UNLIKELY", "spoof": "UNKNOWN", "medical": "UNKNOWN"},
        labels=[{"description": "laptop", "score": 0.9}, {"description": "table", "score": 0.8}],
        hard_violation=False,
        violation_reason=None,
        toy_label_found=False,
        detected_text="Clean text",
    )
    result = apply_vision_results(pre_res, vis_res)
    assert result.decision == ModerationDecision.REJECTED
    assert "no_toy_label" in result.flags


def test_valid_image_approved():
    pre_res = PrefilterImageResult(decision=ModerationDecision.APPROVED)
    vis_res = VisionAnalysisResult(
        safe_search={"adult": "VERY_UNLIKELY", "violence": "VERY_UNLIKELY", "racy": "VERY_UNLIKELY", "spoof": "UNKNOWN", "medical": "UNKNOWN"},
        labels=[{"description": "teddy bear", "score": 0.9}, {"description": "toy", "score": 0.85}],
        hard_violation=False,
        violation_reason=None,
        toy_label_found=True,
        detected_text="A beautiful toy",
    )
    result = apply_vision_results(pre_res, vis_res)
    assert result.decision == ModerationDecision.APPROVED
    assert not result.flags
    assert "toy" in result.reason


def test_ocr_profanity_rejected():
    pre_res = PrefilterImageResult(decision=ModerationDecision.APPROVED)
    vis_res = VisionAnalysisResult(
        safe_search={"adult": "VERY_UNLIKELY", "violence": "VERY_UNLIKELY", "racy": "VERY_UNLIKELY", "spoof": "UNKNOWN", "medical": "UNKNOWN"},
        labels=[{"description": "toy", "score": 0.9}],
        hard_violation=False,
        violation_reason=None,
        toy_label_found=True,
        detected_text="Đây là con cặc đồ chơi dmm",
    )
    result = apply_vision_results(pre_res, vis_res)
    assert result.decision == ModerationDecision.REJECTED
    assert "vision_profanity_violation" in result.flags
    assert "profanity" in result.reason


def test_ocr_obfuscated_phone_rejected():
    pre_res = PrefilterImageResult(decision=ModerationDecision.APPROVED)
    vis_res = VisionAnalysisResult(
        safe_search={"adult": "VERY_UNLIKELY", "violence": "VERY_UNLIKELY", "racy": "VERY_UNLIKELY", "spoof": "UNKNOWN", "medical": "UNKNOWN"},
        labels=[{"description": "toy", "score": 0.9}],
        hard_violation=False,
        violation_reason=None,
        toy_label_found=True,
        detected_text="Call zero nine one two eight zero two zero three one",
    )
    result = apply_vision_results(pre_res, vis_res)
    assert result.decision == ModerationDecision.REJECTED
    assert "vision_text_violation" in result.flags
    assert "Contains Vietnamese phone number" in result.reason


def test_ocr_obfuscated_profanity_rejected():
    pre_res = PrefilterImageResult(decision=ModerationDecision.APPROVED)
    vis_res = VisionAnalysisResult(
        safe_search={"adult": "VERY_UNLIKELY", "violence": "VERY_UNLIKELY", "racy": "VERY_UNLIKELY", "spoof": "UNKNOWN", "medical": "UNKNOWN"},
        labels=[{"description": "toy", "score": 0.9}],
        hard_violation=False,
        violation_reason=None,
        toy_label_found=True,
        detected_text="c-o-n c-ạ-c",
    )
    result = apply_vision_results(pre_res, vis_res)
    assert result.decision == ModerationDecision.REJECTED
    assert "vision_profanity_violation" in result.flags
    assert "profanity" in result.reason
