"""
tests/unit/test_moderation_service.py
---------------------------------------
Unit/Integration tests for ModerationOrchestrator and GoogleVisionClient batching logic.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from PIL import Image

from app.integrations.google_vision import VisionAnalysisResult
from app.schemas.moderation import (
    ImagePipelineResult, ModerationDecision, ModerationStatus, ReviewImageRecord,
    ReviewRecord, TextPipelineResult,
)
from app.application.moderation.product_review import ModerationOrchestrator
from app.utils.image_utils import ImageLoadResult


@pytest.mark.asyncio
async def test_moderation_orchestrator_batch_processing(mocker):
    # Mock settings
    mocker.patch("app.application.moderation.product_review.get_settings")
    
    # Mock Repository
    mock_repo = MagicMock()
    mock_repo.fetch_images_for_review = AsyncMock(return_value=[
        ReviewImageRecord(
            review_product_image_id=10,
            review_product_id=1,
            image_url="http://example.com/toy1.jpg",
            moderation_status=ModerationStatus.PENDING,
        ),
        ReviewImageRecord(
            review_product_image_id=11,
            review_product_id=1,
            image_url="http://example.com/toy2.jpg",
            moderation_status=ModerationStatus.PENDING,
        ),
    ])
    mock_repo.get_recent_rejected_count = AsyncMock(return_value=0)
    mock_repo.update_review_status = AsyncMock()
    mock_repo.update_image_status = AsyncMock()
    mock_repo.insert_moderation_log = AsyncMock()
    mock_repo.get_reviewer_name_by_review_id = AsyncMock(return_value="Customer")
    
    mocker.patch("app.application.moderation.product_review.ModerationRepository", return_value=mock_repo)

    # Mock Notification
    mock_notif = MagicMock()
    mock_notif.send_manual_review_alert = AsyncMock()
    mock_notif.send_customer_rejection_notification = AsyncMock()
    mocker.patch("app.application.moderation.product_review.NotificationService", return_value=mock_notif)



    # Mock image loading
    mock_image = Image.new("RGB", (200, 200), (128, 128, 128))
    mock_load = mocker.patch("app.application.moderation.product_review.load_image_from_url")
    mock_load.return_value = ImageLoadResult(image=mock_image, raw_bytes=b"fakebytes", size_bytes=9999, error=None)

    # Mock local pre-filter
    from app.application.moderation.image_pipeline import PrefilterImageResult
    mock_prefilter = mocker.patch("app.application.moderation.product_review.run_image_prefilter")
    mock_prefilter.return_value = PrefilterImageResult(decision=ModerationDecision.APPROVED, phash="mockphash")

    # Mock Vision Client batch call
    mock_vision_client = MagicMock()
    mock_vision_client.analyze_images_batch = AsyncMock(return_value=[
        VisionAnalysisResult(
            safe_search={"adult": "VERY_UNLIKELY", "violence": "VERY_UNLIKELY", "racy": "VERY_UNLIKELY"},
            labels=[{"description": "toy", "score": 0.9}],
            hard_violation=False,
            violation_reason=None,
            toy_label_found=True,
            detected_text=None,
        ),
        VisionAnalysisResult(
            safe_search={"adult": "VERY_UNLIKELY", "violence": "VERY_UNLIKELY", "racy": "VERY_UNLIKELY"},
            labels=[{"description": "toy", "score": 0.8}],
            hard_violation=False,
            violation_reason=None,
            toy_label_found=True,
            detected_text="Call 0901234567 for info", # This should trigger text violation rejection
        ),
    ])
    mocker.patch("app.application.moderation.product_review.get_vision_client", return_value=mock_vision_client)

    # Mock Text Pipeline
    mock_text_res = TextPipelineResult(
        decision=ModerationDecision.APPROVED,
        confidence=1.0,
        category="clean",
        reason="Clean review text",
    )
    orchestrator = ModerationOrchestrator()
    mocker.patch.object(orchestrator, "_run_text_pipeline", return_value=mock_text_res)

    # Review to process
    review = ReviewRecord(
        review_id=1,
        account_id=2,
        product_id=3,
        order_id=4,
        rating=5,
        comment="This toy is great!",
        moderation_status=ModerationStatus.PENDING,
        created_at=datetime.utcnow(),
    )

    # Execute
    await orchestrator.moderate_review(review)

    # Assertions
    assert mock_load.call_count == 2
    mock_vision_client.analyze_images_batch.assert_called_once_with([b"fakebytes", b"fakebytes"])
    mock_repo.update_review_status.assert_called_once_with(1, ModerationStatus.REJECTED)
    assert mock_repo.update_image_status.call_count == 2
    mock_repo.update_image_status.assert_any_call(10, ModerationStatus.APPROVED, "mockphash")
    mock_repo.update_image_status.assert_any_call(11, ModerationStatus.REJECTED, "mockphash")


@pytest.mark.asyncio
async def test_moderation_orchestrator_rating_only_review(mocker):
    # Mock settings
    mocker.patch("app.application.moderation.product_review.get_settings")

    # Mock Repository
    mock_repo = MagicMock()
    mock_repo.fetch_images_for_review = AsyncMock(return_value=[])
    mock_repo.get_recent_rejected_count = AsyncMock(return_value=0)
    mock_repo.update_review_status = AsyncMock()
    mock_repo.insert_moderation_log = AsyncMock()

    mocker.patch("app.application.moderation.product_review.ModerationRepository", return_value=mock_repo)

    # Mock Notification
    mock_notif = MagicMock()
    mocker.patch("app.application.moderation.product_review.NotificationService", return_value=mock_notif)

    orchestrator = ModerationOrchestrator()

    # Review to process (empty comment, rating = 5)
    review = ReviewRecord(
        review_id=1,
        account_id=2,
        product_id=3,
        order_id=4,
        rating=5,
        comment="",
        moderation_status=ModerationStatus.PENDING,
        created_at=datetime.utcnow(),
    )

    # Execute
    await orchestrator.moderate_review(review)

    # Assertions: should be APPROVED automatically
    mock_repo.update_review_status.assert_called_once_with(1, ModerationStatus.APPROVED)
    # Check that it logged correctly
    mock_repo.insert_moderation_log.assert_called_once()
    args, kwargs = mock_repo.insert_moderation_log.call_args
    assert kwargs.get("action") == "Approved"
    assert kwargs.get("reason") is None
