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


@patch("app.features.moderation.product_review.image_pipeline.vision_client.vision.ImageAnnotatorClient")
def test_parse_response_toy_gun_allowed(mock_client):
    client = GoogleVisionClient()
    response = MagicMock()
    
    response.safe_search_annotation.adult.name = "VERY_UNLIKELY"
    response.safe_search_annotation.violence.name = "VERY_UNLIKELY"
    response.safe_search_annotation.racy.name = "VERY_UNLIKELY"
    response.safe_search_annotation.spoof.name = "VERY_UNLIKELY"
    response.safe_search_annotation.medical.name = "VERY_UNLIKELY"
    
    lbl_gun = MagicMock()
    lbl_gun.description = "gun"
    lbl_gun.score = 0.85
    
    lbl_toy = MagicMock()
    lbl_toy.description = "toy gun"
    lbl_toy.score = 0.80
    
    response.label_annotations = [lbl_gun, lbl_toy]
    response.text_annotations = []
    
    result = client._parse_response(response)
    
    assert result.hard_violation is False
    assert result.toy_label_found is True


@patch("app.features.moderation.product_review.image_pipeline.vision_client.vision.ImageAnnotatorClient")
def test_parse_response_water_gun_allowed(mock_client):
    client = GoogleVisionClient()
    response = MagicMock()
    
    response.safe_search_annotation.adult.name = "VERY_UNLIKELY"
    response.safe_search_annotation.violence.name = "VERY_UNLIKELY"
    response.safe_search_annotation.racy.name = "VERY_UNLIKELY"
    response.safe_search_annotation.spoof.name = "VERY_UNLIKELY"
    response.safe_search_annotation.medical.name = "VERY_UNLIKELY"
    
    lbl_pistol = MagicMock()
    lbl_pistol.description = "pistol"
    lbl_pistol.score = 0.80
    
    lbl_water = MagicMock()
    lbl_water.description = "water gun"
    lbl_water.score = 0.85
    
    response.label_annotations = [lbl_pistol, lbl_water]
    response.text_annotations = []
    
    result = client._parse_response(response)
    
    assert result.hard_violation is False
    assert result.toy_label_found is True


@patch("app.features.moderation.product_review.image_pipeline.vision_client.vision.ImageAnnotatorClient")
def test_parse_response_real_handgun_rejected(mock_client):
    client = GoogleVisionClient()
    response = MagicMock()
    
    response.safe_search_annotation.adult.name = "VERY_UNLIKELY"
    response.safe_search_annotation.violence.name = "VERY_UNLIKELY"
    response.safe_search_annotation.racy.name = "VERY_UNLIKELY"
    response.safe_search_annotation.spoof.name = "VERY_UNLIKELY"
    response.safe_search_annotation.medical.name = "VERY_UNLIKELY"
    
    lbl_handgun = MagicMock()
    lbl_handgun.description = "handgun"
    lbl_handgun.score = 0.95
    
    response.label_annotations = [lbl_handgun]
    response.text_annotations = []
    
    result = client._parse_response(response)
    
    assert result.hard_violation is True
    assert "real weapon detected" in result.violation_reason


@patch("app.features.moderation.product_review.image_pipeline.vision_client.vision.ImageAnnotatorClient")
def test_parse_response_unverified_gun_rejected(mock_client):
    client = GoogleVisionClient()
    response = MagicMock()
    
    response.safe_search_annotation.adult.name = "VERY_UNLIKELY"
    response.safe_search_annotation.violence.name = "VERY_UNLIKELY"
    response.safe_search_annotation.racy.name = "VERY_UNLIKELY"
    response.safe_search_annotation.spoof.name = "VERY_UNLIKELY"
    response.safe_search_annotation.medical.name = "VERY_UNLIKELY"
    
    lbl_gun = MagicMock()
    lbl_gun.description = "gun"
    lbl_gun.score = 0.85
    
    response.label_annotations = [lbl_gun]
    response.text_annotations = []
    
    result = client._parse_response(response)
    
    assert result.hard_violation is True
    assert "unverified weapon/firearm detected" in result.violation_reason


@patch("app.features.moderation.product_review.image_pipeline.vision_client.vision.ImageAnnotatorClient")
def test_parse_response_toy_gun_labeled_as_firearm(mock_client):
    client = GoogleVisionClient()
    response = MagicMock()
    
    response.safe_search_annotation.adult.name = "VERY_UNLIKELY"
    response.safe_search_annotation.violence.name = "VERY_UNLIKELY"
    response.safe_search_annotation.racy.name = "VERY_UNLIKELY"
    response.safe_search_annotation.spoof.name = "VERY_UNLIKELY"
    response.safe_search_annotation.medical.name = "VERY_UNLIKELY"
    
    # Mock Google Vision identifying a Glock toy gun as handgun and firearm
    lbl_firearm = MagicMock()
    lbl_firearm.description = "firearm"
    lbl_firearm.score = 0.90
    
    lbl_handgun = MagicMock()
    lbl_handgun.description = "handgun"
    lbl_handgun.score = 0.85
    
    lbl_toy = MagicMock()
    lbl_toy.description = "toy"
    lbl_toy.score = 0.80
    
    response.label_annotations = [lbl_firearm, lbl_handgun, lbl_toy]
    response.text_annotations = []
    
    result = client._parse_response(response)
    
    # Must bypass rejections and be approved!
    assert result.hard_violation is False
    assert result.toy_label_found is True


@patch("app.features.moderation.product_review.image_pipeline.vision_client.vision.ImageAnnotatorClient")
def test_parse_response_water_gun_labeled_as_shotgun(mock_client):
    client = GoogleVisionClient()
    response = MagicMock()
    
    response.safe_search_annotation.adult.name = "VERY_UNLIKELY"
    response.safe_search_annotation.violence.name = "VERY_UNLIKELY"
    response.safe_search_annotation.racy.name = "VERY_UNLIKELY"
    response.safe_search_annotation.spoof.name = "VERY_UNLIKELY"
    response.safe_search_annotation.medical.name = "VERY_UNLIKELY"
    
    # Mock Google Vision identifying a water gun as shotgun and firearm
    lbl_shotgun = MagicMock()
    lbl_shotgun.description = "shotgun"
    lbl_shotgun.score = 0.88
    
    lbl_firearm = MagicMock()
    lbl_firearm.description = "firearm"
    lbl_firearm.score = 0.85
    
    lbl_water = MagicMock()
    lbl_water.description = "water gun"
    lbl_water.score = 0.92
    
    response.label_annotations = [lbl_shotgun, lbl_firearm, lbl_water]
    response.text_annotations = []
    
    result = client._parse_response(response)
    
    # Must bypass rejections and be approved!
    assert result.hard_violation is False
    assert result.toy_label_found is True


@patch("app.features.moderation.product_review.image_pipeline.vision_client.vision.ImageAnnotatorClient")
def test_parse_response_ghostface_mask_allowed(mock_client):
    client = GoogleVisionClient()
    response = MagicMock()
    
    response.safe_search_annotation.adult.name = "VERY_UNLIKELY"
    response.safe_search_annotation.violence.name = "VERY_UNLIKELY"
    response.safe_search_annotation.racy.name = "VERY_UNLIKELY"
    response.safe_search_annotation.spoof.name = "VERY_UNLIKELY"
    response.safe_search_annotation.medical.name = "VERY_UNLIKELY"
    
    lbl_tooth = MagicMock()
    lbl_tooth.description = "tooth"
    lbl_tooth.score = 0.93
    
    lbl_char = MagicMock()
    lbl_char.description = "fictional character"
    lbl_char.score = 0.82
    
    lbl_mask = MagicMock()
    lbl_mask.description = "mask"
    lbl_mask.score = 0.82
    
    response.label_annotations = [lbl_tooth, lbl_char, lbl_mask]
    response.text_annotations = []
    
    result = client._parse_response(response)
    
    assert result.hard_violation is False
    assert result.toy_label_found is True


@patch("app.features.moderation.product_review.image_pipeline.vision_client.vision.ImageAnnotatorClient")
def test_parse_response_batman_mask_allowed(mock_client):
    client = GoogleVisionClient()
    response = MagicMock()
    
    response.safe_search_annotation.adult.name = "VERY_UNLIKELY"
    response.safe_search_annotation.violence.name = "VERY_UNLIKELY"
    response.safe_search_annotation.racy.name = "VERY_UNLIKELY"
    response.safe_search_annotation.spoof.name = "VERY_UNLIKELY"
    response.safe_search_annotation.medical.name = "VERY_UNLIKELY"
    
    lbl_mask = MagicMock()
    lbl_mask.description = "mask"
    lbl_mask.score = 0.97
    
    lbl_batman = MagicMock()
    lbl_batman.description = "batman"
    lbl_batman.score = 0.96
    
    lbl_super = MagicMock()
    lbl_super.description = "superhero"
    lbl_super.score = 0.91
    
    response.label_annotations = [lbl_mask, lbl_batman, lbl_super]
    response.text_annotations = []
    
    result = client._parse_response(response)
    
    assert result.hard_violation is False
    assert result.toy_label_found is True


@patch("app.features.moderation.product_review.image_pipeline.vision_client.vision.ImageAnnotatorClient")
def test_parse_response_normal_toy_mask_allowed(mock_client):
    client = GoogleVisionClient()
    response = MagicMock()
    
    response.safe_search_annotation.adult.name = "VERY_UNLIKELY"
    response.safe_search_annotation.violence.name = "VERY_UNLIKELY"
    response.safe_search_annotation.racy.name = "VERY_UNLIKELY"
    response.safe_search_annotation.spoof.name = "VERY_UNLIKELY"
    response.safe_search_annotation.medical.name = "VERY_UNLIKELY"
    
    lbl_expr = MagicMock()
    lbl_expr.description = "facial expression"
    lbl_expr.score = 0.94
    
    lbl_mask = MagicMock()
    lbl_mask.description = "mask"
    lbl_mask.score = 0.93
    
    lbl_mascot = MagicMock()
    lbl_mascot.description = "mascot"
    lbl_mascot.score = 0.85
    
    response.label_annotations = [lbl_expr, lbl_mask, lbl_mascot]
    response.text_annotations = []
    
    result = client._parse_response(response)
    
    assert result.hard_violation is False
    assert result.toy_label_found is True
