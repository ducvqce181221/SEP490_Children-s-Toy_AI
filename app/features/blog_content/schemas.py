from __future__ import annotations

from typing import Literal, Union

from pydantic import BaseModel, Field


class BlogContentGenerateRequest(BaseModel):
    action: Literal["Generate", "Improve", "Rewrite"] = "Generate"
    title: str = Field(min_length=1, max_length=255)
    description: str | None = None
    promptStructure: str = Field(min_length=1, max_length=5000)
    defaultTone: str = Field(default="Friendly", min_length=1, max_length=50)
    defaultCategoryId: int = Field(gt=0)
    sourceContent: str | None = None


class BlogContentGenerateResponse(BaseModel):
    title: str
    content: str


class BlogContentBlockedResponse(BaseModel):
    status: Literal["blocked"] = "blocked"
    violation_type: Literal["brand_external", "topic_restricted", "out_of_scope", "unsafe_content"]
    violated_keyword: str
    reason: str
    suggestions: list[str]


BlogContentGenerateEndpointResponse = Union[BlogContentGenerateResponse, BlogContentBlockedResponse]
