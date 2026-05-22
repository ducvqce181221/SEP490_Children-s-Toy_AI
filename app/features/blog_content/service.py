from __future__ import annotations

import json
import re
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger

MAX_CONTENT_LENGTH = 10_000
MIN_CONTENT_LENGTH = 3_000
_PRECONTENT_CACHE: str | None = None
logger = get_logger(__name__)


class BlogContentGenerationError(RuntimeError):
    pass


def _load_precontent_rules() -> str:
    global _PRECONTENT_CACHE
    if _PRECONTENT_CACHE is not None:
        return _PRECONTENT_CACHE

    precontent_path = Path(__file__).resolve().parents[1] / "moderation" / "text_pipeline" / "precontent.txt"
    if not precontent_path.exists():
        _PRECONTENT_CACHE = ""
        return _PRECONTENT_CACHE

    raw = precontent_path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "cp1258", "latin-1"):
        try:
            _PRECONTENT_CACHE = raw.decode(encoding).strip()
            return _PRECONTENT_CACHE
        except UnicodeDecodeError:
            continue
    _PRECONTENT_CACHE = raw.decode("utf-8", errors="ignore").strip()
    return _PRECONTENT_CACHE


def _clean_model_text(raw: str) -> str:
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _strip_json_prefix_noise(text: str) -> str:
    cleaned = text.strip()
    cleaned = re.sub(
        r'^\s*\{\s*"title"\s*:\s*".*?"\s*,\s*"(?:content|blogContent)"\s*:\s*"',
        "",
        cleaned,
        flags=re.IGNORECASE | re.DOTALL,
    )
    cleaned = cleaned.rstrip('"} \n\r\t')
    cleaned = re.sub(r"^\s*(title|description)\s*:\s*.*$", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    cleaned = re.sub(r"^\s*(má»Ÿ bÃ i|than bai|thÃ¢n bÃ i|ket bai|káº¿t bÃ i)\s*:\s*", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)
    return cleaned.strip()


def _to_html_from_text(raw_text: str) -> str:
    text = _clean_model_text(raw_text).replace("\\n", "\n")
    if not text:
        return ""

    if "<p" in text or "<h1" in text or "<h2" in text or "<ul" in text or "<li" in text:
        return text

    lines = [line.strip() for line in text.splitlines() if line.strip()]
    if not lines:
        return ""

    html_parts: list[str] = []
    in_list = False

    def close_list() -> None:
        nonlocal in_list
        if in_list:
            html_parts.append("</ul>")
            in_list = False

    def fmt_inline(s: str) -> str:
        return re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)

    for line in lines:
        if line.startswith("### "):
            close_list()
            html_parts.append(f"<h3>{fmt_inline(line[4:])}</h3>")
            continue
        if line.startswith("## "):
            close_list()
            html_parts.append(f"<h2>{fmt_inline(line[3:])}</h2>")
            continue
        if line.startswith("# "):
            close_list()
            html_parts.append(f"<h1>{fmt_inline(line[2:])}</h1>")
            continue
        if line.startswith("- ") or line.startswith("* "):
            if not in_list:
                html_parts.append("<ul>")
                in_list = True
            html_parts.append(f"<li>{fmt_inline(line[2:])}</li>")
            continue
        close_list()
        html_parts.append(f"<p>{fmt_inline(line)}</p>")

    close_list()
    return "".join(html_parts)


def _is_low_quality_or_echo(content_html: str) -> bool:
    lower_content = content_html.lower()
    has_echo = (
        ("action:" in lower_content and "promptstructure:" in lower_content)
        or ("title/input:" in lower_content)
        or ("{\"title\"" in lower_content and "\"content\"" in lower_content)
        or ("description:" in lower_content)
        or ("má»Ÿ bÃ i" in lower_content)
        or ("thÃ¢n bÃ i" in lower_content)
        or ("káº¿t bÃ i" in lower_content)
    )
    too_short = len(content_html) < MIN_CONTENT_LENGTH
    has_structure = ("<h1" in lower_content) and ("<h2" in lower_content) and ("<p" in lower_content)
    return has_echo or too_short or not has_structure


def _remove_forbidden_markers(content_html: str, title: str) -> str:
    cleaned = content_html
    cleaned = re.sub(r"^\s*<h1[^>]*>\s*" + re.escape(title.strip()) + r"\s*</h1>\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<p>\s*(title|description)\s*:\s*.*?</p>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<p>\s*(má»Ÿ bÃ i|than bai|thÃ¢n bÃ i|ket bai|káº¿t bÃ i)\s*:?\s*</p>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()



def _contains_vietnamese_signals(text: str) -> bool:
    lower = f" {(text or '').lower()} "
    return any(
        token in lower
        for token in [
            " mơ ",
            " mở bài ",
            " thân bài ",
            " kết bài ",
            " đồ chơi ",
            " phụ huynh ",
            " trẻ ",
            " không ",
            " tại sao ",
            " lời khuyên ",
            " vi sao ",
            " do choi ",
            " phu huynh ",
            " ket luan ",
        ]
    )


def _ensure_english_title(raw_title: str | None) -> str:
    title = (raw_title or "").strip()
    if not title:
        return "A Practical Guide to Choosing Toys for Children"
    if _contains_vietnamese_signals(title):
        return "A Practical Guide to Choosing Toys for Children"
    return title


def _build_structured_fallback_html(title: str, description: str | None, prompt_structure: str, tone: str) -> str:
    intro = (
        description.strip()
        if description and not _contains_vietnamese_signals(description)
        else "This article helps parents choose safe, age-appropriate, and meaningful toys for children."
    )
    key_points = [x.strip(" -") for x in prompt_structure.splitlines() if x.strip()]
    if not key_points:
        key_points = [
            "Identify your child's age, interests, and developmental stage",
            "Prioritize safety, durability, and product quality",
            "Choose toys that support learning through play",
        ]
    bullet_html = "".join(f"<li>{point}</li>" for point in key_points[:8])
    content = (
        f"<p>{intro}</p>"
        f"<blockquote><p><strong>Quick tip:</strong> Start with safety and age fit, then choose toys that build creativity and life skills.</p></blockquote>"
        f"<h2>Why choosing the right toy matters</h2>"
        f"<p>Age-appropriate toys support cognitive growth, language development, and social-emotional learning in natural ways. "
        f"When parents choose intentionally, playtime becomes a daily opportunity for discovery and family connection.</p>"
        f"<p>Smart toy choices also reduce safety risks and prevent unnecessary spending on products that do not match a child's stage or needs.</p>"
        f"<h2>How to choose safe and high-value toys</h2>"
        f"<ul>{bullet_html}</ul>"
        f"<p><strong>Checklist:</strong></p>"
        f"<ul><li>&#10003; Verify materials and safety certifications</li><li>&#10003; Match complexity to the child's age</li><li>&#10003; Stay involved to extend learning through play</li></ul>"
        f"<p>Prioritize trusted brands, transparent labeling, and durable materials. "
        f"For toys with small parts, assess choking hazards carefully; for electronic toys, review sound levels, battery safety, and cleaning requirements.</p>"
        f"<p>Balance movement toys, creative toys, and logic-based toys so children develop holistically. "
        f"Open-ended toys with multiple play paths are especially effective for imagination and problem-solving.</p>"
        f"<h2>Practical recommendations for different families</h2>"
        f"<p>If your schedule is busy, choose toys that support meaningful 15-20 minute play sessions each day. "
        f"If your home has more space, include active play options that help children release energy and build physical confidence.</p>"
        f"<p>Children who prefer quiet activities often enjoy building sets, coloring, and picture books. "
        f"More energetic children may benefit from pretend play, mini sports, and hands-on activity kits that sustain focus.</p>"
        f"<h2>Conclusion</h2>"
        f"<p>Choosing toys is not only a shopping task; it is an ongoing parenting strategy. "
        f"Focus on safety, age fit, and development goals so each toy creates long-term value.</p>"
        f"<p>With a {tone.lower()} and intentional approach, parents can turn everyday play into meaningful learning and lasting family memories.</p>"
    )
    if len(content) < MIN_CONTENT_LENGTH:
        content += (
            "<p>Parents can also rotate toys by development stage to reduce boredom and maintain curiosity. "
            "A monthly review helps identify what still fits, what should be replaced, and what can be added to broaden learning experiences.</p>"
            "<p>During play, ask open-ended questions to build language and critical thinking. "
            "For example: What are you building? Why did you choose this approach? What happens if we try a different method?</p>"
            "<p>When thoughtful toy selection is combined with active parent involvement, children gain confidence, independence, and essential life skills "
            "that support both school readiness and long-term personal growth.</p>"
        )
    return content

def _try_parse_json_payload(raw_text: str) -> tuple[str | None, str | None]:
    cleaned = _clean_model_text(raw_text)
    if not cleaned:
        return None, None

    candidates: list[str] = [cleaned]
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        candidates.append(cleaned[start : end + 1])

    for candidate in candidates:
        try:
            obj = json.loads(candidate)
            if not isinstance(obj, dict):
                continue
            title = obj.get("title")
            blog_content = obj.get("content") or obj.get("blogContent")
            title_value = str(title).strip() if title is not None else None
            content_value = str(blog_content).strip() if blog_content is not None else None
            return title_value, content_value
        except (json.JSONDecodeError, TypeError, ValueError):
            continue

    return None, None


async def generate_blog_content(
    *,
    action: str,
    title: str,
    description: str | None,
    prompt_structure: str,
    tone: str,
    category_id: int,
    source_content: str | None,
) -> tuple[str, str]:
    logger.info(
        "AI blog generation requested",
        action=action,
        title_len=len(title or ""),
        prompt_len=len(prompt_structure or ""),
        has_source=bool(source_content),
        category_id=category_id,
    )

    settings = get_settings()
    if not settings.blog_deepseek_api_key:
        raise BlogContentGenerationError("DEEPSEEK_API_KEY is not configured.")

    model = settings.blog_deepseek_model or "deepseek-chat"
    base_url = (settings.blog_deepseek_base_url or "https://api.deepseek.com").rstrip("/")
    endpoints = [f"{base_url}/chat/completions", f"{base_url}/v1/chat/completions"]

    system_prompt = (
        "You are an expert multilingual blog writer for a children's toy e-commerce website. "
        "You must understand both Vietnamese and English input. "
        "Output must always be in professional, natural, SEO-friendly English. "
        "If input is Vietnamese, preserve the original meaning and generate an English article. "
        "If input is English, generate English as usual. "
        "Content must be safe, family-friendly, and relevant only to children's toys, parenting, and child development. "
        "Do not repeat input metadata or prompt fields."
    )
    precontent_rules = _load_precontent_rules()
    user_prompt = f"""
Action: {action}
Title/Input: {title}
Description: {description or ""}
PromptStructure: {prompt_structure}
Tone: {tone}
CategoryId: {category_id}
CurrentContent: {source_content or ""}

Create a complete blog article with opening, body, and conclusion.
Use natural language, practical guidance, and coherent flow.
Length requirement: content must be between 3000 and 6000 characters.
Structure requirement:
- One opening section
- At least 3 body sections with clear subheadings
- One conclusion section
IMPORTANT:
- Do NOT output title or description inside content body.
- Do NOT output labels/phrases like "Mo bai", "Than bai", "Ket bai" (or Vietnamese accented variants).
- Write continuous natural blog sections only.
- Multilingual behavior:
  - Understand both Vietnamese and English input.
  - Always produce title and content in English.
  - If input is Vietnamese, translate and optimize title to professional SEO English while preserving original intent.
  - If input is English, keep normal English generation.
Return ONLY valid JSON (no markdown, no explanation) with keys: title, content.
The content value must be HTML (<h1>, <h2>, <h3>, <p>, <ul>, <li>, <strong>, <blockquote>) and <= 10000 characters.
Use rich formatting naturally: headings, bullet lists, highlighted key points, quote blocks, and readable spacing.

Precontent rules (must comply):
{precontent_rules}
"""

    payload_base = {
        "model": model,
        "temperature": settings.blog_deepseek_temperature,
        "max_tokens": settings.blog_deepseek_max_tokens,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "response_format": {"type": "json_object"},
    }
    headers = {
        "Authorization": f"Bearer {settings.blog_deepseek_api_key}",
        "Content-Type": "application/json",
    }

    last_error = "DeepSeek request failed."
    per_request_timeout = settings.blog_deepseek_timeout_seconds
    retry_attempts = settings.blog_deepseek_retry_attempts

    for endpoint in endpoints:
        for attempt in range(retry_attempts):
            payload = dict(payload_base)
            if attempt > 0:
                payload["messages"] = [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": user_prompt
                        + "\nIMPORTANT RETRY: Expand depth. Ensure 3000-6000 characters, opening-body-conclusion, and no metadata echo.",
                    },
                ]

            try:
                logger.info("Calling DeepSeek", endpoint=endpoint, attempt=attempt + 1)
                async with httpx.AsyncClient(timeout=per_request_timeout) as client:
                    resp = await client.post(endpoint, json=payload, headers=headers)
            except httpx.TimeoutException:
                last_error = "DeepSeek request timeout."
                logger.warning("DeepSeek timeout", endpoint=endpoint, attempt=attempt + 1)
                continue
            except httpx.HTTPError as ex:
                last_error = f"DeepSeek request error: {ex}"
                logger.warning("DeepSeek HTTP error", endpoint=endpoint, attempt=attempt + 1, error=str(ex))
                continue

            if resp.status_code == 404:
                last_error = "DeepSeek endpoint not found."
                logger.warning("DeepSeek endpoint not found", endpoint=endpoint)
                break
            if resp.status_code >= 400:
                last_error = f"DeepSeek returned HTTP {resp.status_code}."
                logger.warning(
                    "DeepSeek non-success response",
                    endpoint=endpoint,
                    attempt=attempt + 1,
                    status=resp.status_code,
                    body_preview=resp.text[:300],
                )
                continue

            try:
                outer = resp.json()
                content = outer["choices"][0]["message"]["content"]
                if not content:
                    raise ValueError("empty content")

                parsed_title, parsed_content = _try_parse_json_payload(content)
                generated_title = _ensure_english_title(parsed_title or title)
                blog_content = (parsed_content or "").strip()

                if not blog_content:
                    fallback_text = _strip_json_prefix_noise(_clean_model_text(content))
                    if not fallback_text:
                        raise ValueError("empty blogContent")
                    blog_content = fallback_text

                blog_content = _to_html_from_text(blog_content)
                if not blog_content:
                    blog_content = _build_structured_fallback_html(
                        title=generated_title,
                        description=description,
                        prompt_structure=prompt_structure,
                        tone=tone,
                    )

                if _is_low_quality_or_echo(blog_content):
                    if attempt < (retry_attempts - 1):
                        continue
                    blog_content = _build_structured_fallback_html(
                        title=generated_title,
                        description=description,
                        prompt_structure=prompt_structure,
                        tone=tone,
                    )

                if len(blog_content) > MAX_CONTENT_LENGTH:
                    blog_content = blog_content[:MAX_CONTENT_LENGTH]
                blog_content = _remove_forbidden_markers(blog_content, generated_title)
                logger.info(
                    "AI blog generation succeeded",
                    endpoint=endpoint,
                    attempt=attempt + 1,
                    output_title_len=len(generated_title),
                    output_content_len=len(blog_content),
                )
                if _contains_vietnamese_signals(blog_content):
                    blog_content = _build_structured_fallback_html(
                        title=generated_title,
                        description=description,
                        prompt_structure=prompt_structure,
                        tone=tone,
                    )
                return generated_title, blog_content
            except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                last_error = "DeepSeek response parse failed."
                logger.warning("DeepSeek parse failed", endpoint=endpoint, attempt=attempt + 1)
                continue

    fallback_title = _ensure_english_title(title)
    fallback_html = _build_structured_fallback_html(
        title=fallback_title,
        description=description,
        prompt_structure=prompt_structure,
        tone=tone,
    )
    if len(fallback_html) > MAX_CONTENT_LENGTH:
        fallback_html = fallback_html[:MAX_CONTENT_LENGTH]
    if fallback_html:
        logger.warning(
            "Using fallback blog content after AI failure",
            reason=last_error,
            output_len=len(fallback_html),
        )
        return fallback_title, fallback_html
    raise BlogContentGenerationError(last_error)


