from __future__ import annotations

from unittest.mock import MagicMock, patch
from app.features.moderation.product_review.image_pipeline.vision_client import GoogleVisionClient


@patch("app.features.moderation.product_review.image_pipeline.vision_client.vision.ImageAnnotatorClient")
def test_parse_response_suspicious_labels(mock_client):
    client = GoogleVisionClient()
    response = MagicMock()
    
    # Mock safe search annotation
    response.safe_search_annotation.adult.name = "VERY_UNLIKELY"
    response.safe_search_annotation.violence.name = "VERY_UNLIKELY"
    response.safe_search_annotation.racy.name = "VERY_UNLIKELY"
    response.safe_search_annotation.spoof.name = "VERY_UNLIKELY"
    response.safe_search_annotation.medical.name = "VERY_UNLIKELY"
    
    # Mock labels with a suspicious label like "street fighting"
    lbl_fighting = MagicMock()
    lbl_fighting.description = "street fighting"
    lbl_fighting.score = 0.85
    
    lbl_other = MagicMock()
    lbl_other.description = "student"
    lbl_other.score = 0.90
    
    response.label_annotations = [lbl_fighting, lbl_other]
    response.text_annotations = []
    
    result = client._parse_response(response)
    
    assert result.hard_violation is True
    assert "suspicious content label detected" in result.violation_reason
    assert "street fighting" in result.violation_reason


@patch("app.features.moderation.product_review.image_pipeline.vision_client.vision.ImageAnnotatorClient")
def test_parse_response_clean_labels(mock_client):
    client = GoogleVisionClient()
    response = MagicMock()
    
    response.safe_search_annotation.adult.name = "VERY_UNLIKELY"
    response.safe_search_annotation.violence.name = "VERY_UNLIKELY"
    response.safe_search_annotation.racy.name = "VERY_UNLIKELY"
    response.safe_search_annotation.spoof.name = "VERY_UNLIKELY"
    response.safe_search_annotation.medical.name = "VERY_UNLIKELY"
    
    lbl_toy = MagicMock()
    lbl_toy.description = "toy car"
    lbl_toy.score = 0.95
    
    response.label_annotations = [lbl_toy]
    response.text_annotations = []
    
    result = client._parse_response(response)
    
    assert result.hard_violation is False
    assert result.toy_label_found is True
