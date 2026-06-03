from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from app.features.blog_content import service
from app.features.blog_content.service import generate_blog_content, safety_check


def test_safety_check_blocks_external_brand_variants() -> None:
    cases = [
        ("Review MyKingdom toys", "Compare My Kingdom with toy shopping for parents"),
        ("Mua do choi tren Shopee", "Goi y chon do choi tre em tren shopee.vn"),
        ("Tí Nị Store có gì cho bé", "Viết blog về khu vui chơi Ti Ni Store"),
    ]

    for title, prompt in cases:
        result = safety_check(title=title, prompt_structure=prompt)

        assert result is not None
        assert result["status"] == "blocked"
        assert result["violation_type"] == "brand_external"
        assert result["reason"] == "external_brand"


@pytest.mark.asyncio
async def test_generate_does_not_block_external_brand_in_source_content(monkeypatch) -> None:
    html_body = (
        "<h2>Why STEM Toys Help Children Learn</h2>"
        "<p>STEM toys give children a calm way to explore patterns, problem solving, and "
        "creative thinking through play. Parents can start with age appropriate building "
        "sets, matching games, simple science kits, and open ended activities that invite "
        "children to ask questions.</p>"
        "<h2>Choosing Safe Learning Materials</h2>"
        "<p>Look for smooth edges, clear age labels, durable parts, and activities that match "
        "the child's attention span. A good toy should be simple enough to begin quickly and "
        "flexible enough to support repeated play.</p>"
        "<h2>Turning Play Into Daily Habits</h2>"
        "<p>Short play sessions after school or on weekends can make learning feel natural. "
        "Parents can ask children to explain what they built, predict what happens next, or "
        "combine toys with drawing and storytelling.</p>"
        "<p>"
        + ("Thoughtful toy choices support confidence, curiosity, and family connection. " * 40)
        + "</p>"
    )
    model_payload = json.dumps(
        {"title": "STEM Toys That Support Everyday Learning", "content": html_body}
    )

    class FakeResponse:
        status_code = 200
        text = ""

        def json(self) -> dict[str, object]:
            return {"choices": [{"message": {"content": model_payload}}]}

    class FakeAsyncClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> "FakeAsyncClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def post(self, *args: object, **kwargs: object) -> FakeResponse:
            return FakeResponse()

    fake_settings = SimpleNamespace(
        blog_deepseek_api_key="test-key",
        blog_deepseek_model="deepseek-chat",
        blog_deepseek_base_url="https://api.deepseek.com",
        blog_deepseek_temperature=0.8,
        blog_deepseek_max_tokens=4096,
        blog_deepseek_timeout_seconds=5,
        blog_deepseek_retry_attempts=1,
    )

    monkeypatch.setattr(service, "get_settings", lambda: fake_settings)
    monkeypatch.setattr(service.httpx, "AsyncClient", FakeAsyncClient)
    service._GENERATE_RESULT_CACHE.clear()

    title, content = await generate_blog_content(
        action="Improve",
        title="STEM toys for children",
        description=None,
        prompt_structure="Write about safe STEM toys for children and parents.",
        tone="Friendly",
        category_id=1,
        source_content="Old draft mentioned Shopee and MyKingdom as examples.",
    )

    assert title == "STEM Toys That Support Everyday Learning"
    assert "STEM toys give children" in content
