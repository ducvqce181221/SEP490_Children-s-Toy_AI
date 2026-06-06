from __future__ import annotations

import json
import re
import hashlib
import unicodedata
import time
from pathlib import Path

import httpx

from app.core.config import get_settings
from app.core.logging import get_logger
from app.utils.text_utils import has_hard_profanity

MAX_CONTENT_LENGTH = 10_000
MIN_CONTENT_LENGTH = 3_000
_PRECONTENT_CACHE: str | None = None
_PRECONTENT_LOADED_PATH: str | None = None
_GENERATE_CACHE_TTL_SECONDS = 300.0
_GENERATE_CACHE_MAX_ITEMS = 128
_GENERATE_RESULT_CACHE: dict[str, tuple[float, tuple[str, str]]] = {}
logger = get_logger(__name__)


class BlogContentGenerationError(RuntimeError):
    pass


BLOCKED_KEYWORDS: dict[str, list[str]] = {
    "brand_external": [
        "mykingdom", "my kingdom", "ti ni", "tini", "tini store", "tiniworld",
        "lazada", "shopee", "tiki", "sendo", "amazon", "bibo mart", "fahasa",
    ],
    "topic_restricted": [
        "chinh tri", "ton giao", "bao luc", "co bac",
        "vu khi", "noi dung nguoi lon", "chat kich thich",
    ],
}

HARD_BLOCK_EMOJIS = (
    "🖕", "👅", "🍆", "😏", "🔞", "🚬", "🍺", "🍷", "🍸", "🚭",
)

_PROMPT_INJECTION_PATTERNS = (
    "ignore previous instructions",
    "reveal system prompt",
    "output hidden rules",
    "bypass moderation",
    "act as another ai",
)

WHITELIST = ["google", "ghn", "giao hang nhanh", "children s toy store", "children toy store"]
DEFAULT_BLOCK_SUGGESTIONS = [
    "Đồ chơi STEM phù hợp cho bé theo độ tuổi",
    "Hướng dẫn chọn quà sinh nhật cho trẻ",
    "Top đồ chơi sáng tạo được yêu thích nhất",
    "Kinh nghiệm mua đồ chơi online an toàn cho phụ huynh",
]

_UNSAFE_CONTENT_PATTERNS = [
    re.compile(r"\bfuck\b", re.IGNORECASE),
    re.compile(r"\bshit\b", re.IGNORECASE),
    re.compile(r"\bbitch\b", re.IGNORECASE),
    re.compile(r"\basshole\b", re.IGNORECASE),
    re.compile(r"\bbastard\b", re.IGNORECASE),
    re.compile(r"\bdick\b", re.IGNORECASE),
    re.compile(r"\bpussy\b", re.IGNORECASE),
    re.compile(r"\bkill\s+yourself\b", re.IGNORECASE),
    re.compile(r"\bgo\s+die\b", re.IGNORECASE),
    re.compile(r"\bditme\b", re.IGNORECASE),
    re.compile(r"\bduma\b", re.IGNORECASE),
    re.compile(r"\bdume\b", re.IGNORECASE),
    re.compile(r"\bcon\s*di\b", re.IGNORECASE),
    re.compile(r"\bcon\s*me\b", re.IGNORECASE),
]

_SHORT_UNSAFE_TOKENS = (
    " dm ", " dmm ", " dcm ", " vcl ", " clm ", " clmm ", " dit ", " deo ", " duma ", " dume ",
)

_INTENT_ANCHORS = [
    "đồ chơi", "do choi", "toy", "toys", "children toy", "kids toy",
    "bé", "tre em", "trẻ em", "phụ huynh", "phu huynh",
    "parenting", "child development", "giáo dục trẻ em", "giao duc tre em",
    "learning through play", "stem toy", "toy safety",
]

_OFF_TOPIC_HINTS = [
    "chinh tri", "chính trị", "politics", "election", "review phim", "movie review",
    "nấu ăn", "nau an", "recipe", "crypto", "chung khoan", "stock market",
]
_INTENT_BLOCK_CONFIDENCE = 0.75
_INTENT_PASS_CONFIDENCE = 0.55

_ALLOWED_DOMAIN_ANCHORS = (
    "toy", "toys", "children", "child", "kids", "kid", "parenting", "learning", "stem",
    "gift", "review", "safety", "seasonal", "outdoor", "role play", "creativity",
    "anatomy", "skeleton", "brain", "doctor", "halloween", "dinosaur", "monster", "fantasy",
    "water gun", "water blaster", "foam blaster",
)

_BLOCKED_DOMAIN_HINTS = (
    "politics", "election", "religion debate", "cryptocurrency", "crypto", "forex",
    "stock trading", "gambling", "adult content", "dating", "relationship advice",
    "medical treatment", "hacking", "crime", "weapon", "drug usage",
)

_UNSAFE_THEME_HINTS = (
    "death", "dead body", "corpse", "human remains", "terrifying", "terror", "horror",
    "gore", "gory", "bloody", "blood bath", "dismember", "decapitated", "violent scene",
    "graphic", "nightmare", "fear inducing",
)

_EDUCATIONAL_SAFETY_CONTEXT = (
    "educational", "education", "learning", "stem", "anatomy", "biology", "science",
    "model", "toy", "toys", "children", "kids", "child development", "role play",
)


def _build_contextual_fallback_suggestions(title: str, content: str) -> list[str]:
    combined = _normalize_for_check(f"{title} {content}")
    if any(token in combined for token in ["review", "danh gia", "so sanh"]):
        return [
            "Khám phá Children's Toy Store - nền tảng đồ chơi trẻ em trực tuyến cho gia đình hiện đại",
            "Review top đồ chơi bán chạy tại Children's Toy Store theo từng nhóm tuổi",
            "So sánh các nhóm đồ chơi giáo dục giúp bé phát triển tư duy và sáng tạo",
            "Kinh nghiệm chọn đồ chơi online an toàn cho phụ huynh có con nhỏ",
        ]
    if any(token in combined for token in ["mua", "buy", "gia", "price", "khuyen mai", "voucher"]):
        return [
            "Hướng dẫn mua đồ chơi tại Children's Toy Store nhanh gọn và an toàn",
            "Top sản phẩm đáng mua tại Children's Toy Store cho bé theo độ tuổi",
            "Mẹo chọn đồ chơi giáo dục phù hợp ngân sách mà vẫn hiệu quả cho trẻ",
            "Bí quyết mua đồ chơi online thông minh cho phụ huynh bận rộn",
        ]
    return [
        "Khám phá Children's Toy Store và các tính năng hỗ trợ mua đồ chơi cho gia đình",
        "Gợi ý đồ chơi nổi bật tại Children's Toy Store theo nhu cầu phát triển của bé",
        "Top hoạt động chơi mà học giúp trẻ phát triển kỹ năng toàn diện tại nhà",
        "Kinh nghiệm chọn đồ chơi đúng độ tuổi để phụ huynh mua sắm an tâm hơn",
    ]


def _has_vietnamese_diacritic(value: str) -> bool:
    return bool(re.search(r"[ăâđêôơưáàảãạắằẳẵặấầẩẫậéèẻẽẹếềểễệíìỉĩịóòỏõọốồổỗộớờởỡợúùủũụứừửữựýỳỷỹỵ]", (value or "").lower()))


def _normalize_for_check(value: str, *, strip_diacritic: bool = True) -> str:
    lowered = (value or "").lower()
    if strip_diacritic:
        normalized = "".join(
            ch for ch in unicodedata.normalize("NFKD", lowered) if not unicodedata.combining(ch)
        )
        alpha_num_space = re.sub(r"[^a-z0-9\s]", " ", normalized)
    else:
        alpha_num_space = re.sub(r"[^\w\s]", " ", lowered, flags=re.UNICODE)
    return re.sub(r"\s+", " ", alpha_num_space).strip()


def _build_deepseek_endpoints(base_url: str) -> list[str]:
    base = (base_url or "https://api.deepseek.com").rstrip("/")
    if base.endswith("/chat/completions"):
        return [base]
    if base.endswith("/v1"):
        return [f"{base}/chat/completions"]
    return [f"{base}/chat/completions", f"{base}/v1/chat/completions"]


def _make_generate_cache_key(
    action: str,
    title: str,
    description: str | None,
    prompt_structure: str,
    tone: str,
    category_id: int,
    source_content: str | None,
) -> str:
    raw = "|".join([
        action or "",
        title or "",
        description or "",
        prompt_structure or "",
        tone or "",
        str(category_id),
        source_content or "",
    ])
    return hashlib.sha256(raw.encode("utf-8", errors="ignore")).hexdigest()


def _cache_get(key: str) -> tuple[str, str] | None:
    now = time.monotonic()
    cached = _GENERATE_RESULT_CACHE.get(key)
    if not cached:
        return None
    ts, value = cached
    if now - ts > _GENERATE_CACHE_TTL_SECONDS:
        _GENERATE_RESULT_CACHE.pop(key, None)
        return None
    return value


def _cache_put(key: str, value: tuple[str, str]) -> None:
    now = time.monotonic()
    if len(_GENERATE_RESULT_CACHE) >= _GENERATE_CACHE_MAX_ITEMS:
        oldest_key = min(_GENERATE_RESULT_CACHE.items(), key=lambda item: item[1][0])[0]
        _GENERATE_RESULT_CACHE.pop(oldest_key, None)
    _GENERATE_RESULT_CACHE[key] = (now, value)


def _contains_keyword(normalized_text: str, keyword: str) -> bool:
    normalized_kw = _normalize_for_check(keyword, strip_diacritic=True)
    if not normalized_kw:
        return False
    if len(normalized_kw) < 5:
        return re.search(rf"\b{re.escape(normalized_kw)}\b", normalized_text, flags=re.IGNORECASE) is not None
    return f" {normalized_kw} " in f" {normalized_text} "


def _detect_external_brand(title: str, prompt_structure: str) -> str | None:
    normalized = _normalize_for_check(_build_user_context(title, prompt_structure), strip_diacritic=True)
    for keyword in BLOCKED_KEYWORDS["brand_external"]:
        if _contains_keyword(normalized, keyword):
            return keyword
    return None


def _build_user_context(title: str, prompt_structure: str) -> str:
    return f"{title.strip()}\n{prompt_structure.strip()}".strip()


def _check_hard_block_emoji(title: str, prompt_structure: str) -> str | None:
    context = _build_user_context(title, prompt_structure)
    for emoji in HARD_BLOCK_EMOJIS:
        if emoji in context:
            return emoji
    return None


def _detect_prompt_injection(title: str, prompt_structure: str) -> str | None:
    normalized = _normalize_for_check(_build_user_context(title, prompt_structure), strip_diacritic=True)
    for phrase in _PROMPT_INJECTION_PATTERNS:
        if phrase in normalized:
            return phrase
    return None


def _detect_contextual_unsafe_theme(title: str, prompt_structure: str) -> str | None:
    normalized = _normalize_for_check(_build_user_context(title, prompt_structure), strip_diacritic=True)
    unsafe_hits = [hint for hint in _UNSAFE_THEME_HINTS if hint in normalized]
    if not unsafe_hits:
        return None

    edu_hits = [hint for hint in _EDUCATIONAL_SAFETY_CONTEXT if hint in normalized]
    graphic_only_hits = [hint for hint in unsafe_hits if hint in {"human remains", "gore", "gory", "dismember", "decapitated", "graphic"}]

    # Block when unsafe theme dominates or any graphic indicator appears.
    if graphic_only_hits:
        return graphic_only_hits[0]
    if len(unsafe_hits) >= 2 and len(edu_hits) == 0:
        return unsafe_hits[0]
    if len(unsafe_hits) >= 3 and len(edu_hits) <= 1:
        return unsafe_hits[0]
    return None


def safety_check(title: str, prompt_structure: str) -> dict[str, str | list[str]] | None:
    context = _build_user_context(title, prompt_structure)
    injection = _detect_prompt_injection(title, prompt_structure)
    if injection:
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": injection,
            "reason": "prompt_injection",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }

    external_brand = _detect_external_brand(title, prompt_structure)
    if external_brand:
        return {
            "status": "blocked",
            "violation_type": "brand_external",
            "violated_keyword": external_brand,
            "reason": "external_brand",
            "suggestions": _build_contextual_fallback_suggestions(title, prompt_structure)[:4],
        }

    contextual_unsafe = _detect_contextual_unsafe_theme(title, prompt_structure)
    if contextual_unsafe:
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": contextual_unsafe,
            "reason": "unsafe_content",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }

    unsafe_match = _detect_unsafe_content(context)
    if unsafe_match:
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": unsafe_match,
            "reason": "unsafe_content",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }
    return None


def _detect_unsafe_content(text: str) -> str | None:
    if has_hard_profanity(text):
        return "hard_profanity"

    is_vietnamese = _has_vietnamese_diacritic(text)
    normalized = _normalize_for_check(text, strip_diacritic=not is_vietnamese)
    tokenized = f" {normalized} "
    for short_token in _SHORT_UNSAFE_TOKENS:
        if short_token in tokenized:
            return short_token.strip()

    for pattern in _UNSAFE_CONTENT_PATTERNS:
        match = pattern.search(normalized)
        if match:
            return match.group(0)
    return None


def _fallback_intent_classification(
    title: str,
    description: str | None,
    prompt_structure: str,
    category_id: int,
) -> dict[str, str | bool | float]:
    combined = _build_user_context(title, prompt_structure)
    normalized = _normalize_for_check(combined, strip_diacritic=True)
    if not normalized:
        return {
            "is_relevant": False,
            "confidence": 0.95,
            "reason": "off_topic",
            "suggestion": "Hãy thêm ngữ cảnh về đồ chơi, phụ huynh hoặc phát triển trẻ em.",
            "decision": "block",
            "source": "heuristic",
        }

    anchor_hits = sum(1 for anchor in _ALLOWED_DOMAIN_ANCHORS if anchor in normalized)
    off_topic_hits = sum(1 for hint in _BLOCKED_DOMAIN_HINTS if hint in normalized)
    token_count = max(1, len(normalized.split()))
    relevance_score = min(1.0, ((anchor_hits * 1.3) + (0.8 if category_id > 0 else 0.0)) / token_count)

    if off_topic_hits > 0 and anchor_hits == 0:
        return {
            "is_relevant": False,
            "confidence": 0.9,
            "reason": "off_topic",
            "suggestion": "Hãy chuyển prompt sang chủ đề toy store, ví dụ chọn đồ chơi theo độ tuổi hoặc toy safety.",
            "decision": "block",
            "source": "heuristic",
        }

    if relevance_score >= _INTENT_PASS_CONFIDENCE:
        return {
            "is_relevant": True,
            "confidence": relevance_score,
            "reason": "",
            "suggestion": "",
            "decision": "pass",
            "source": "heuristic",
        }

    return {
        "is_relevant": True,
        "confidence": relevance_score,
        "reason": "Intent chưa rõ hoàn toàn, cho phép đi tiếp để tránh block nhầm.",
        "suggestion": "",
        "decision": "review",
        "source": "heuristic",
    }


async def classify_intent(
    *,
    title: str,
    description: str | None,
    prompt_structure: str,
    category_id: int,
) -> dict[str, str | bool | float]:
    return _fallback_intent_classification(title, description, prompt_structure, category_id)


def _build_source_content_warning(source_content: str | None) -> str | None:
    if not source_content:
        return None
    source_violation = _detect_unsafe_content(source_content)
    if source_violation:
        return (
            "Nguồn nội dung cũ có dấu hiệu từ ngữ nhạy cảm, hệ thống tiếp tục generate cho Improve mode "
            f"và bỏ qua block từ sourceContent (matched: {source_violation})."
        )
    return None


async def generate_smart_suggestions(
    title: str,
    content: str,
    violated_keyword: str,
    violation_reason: str,
) -> list[str]:
    suggestion_prompt = f"""
Người dùng vừa yêu cầu tạo blog với thông tin sau:
- Tiêu đề (title): {title}
- Nội dung mô tả (content): {content}

Yêu cầu này bị từ chối vì lý do: {violation_reason}
Từ vi phạm: {violated_keyword}

Nhiệm vụ của bạn: Tạo đúng 4 gợi ý chủ đề thay thế PHÙ HỢP cho website Children's Toy Store.

NGUYÊN TẮC GỢI Ý:
1. Phân tích ý định của người dùng từ title và content họ đã nhập.
2. Giữ lại tinh thần/mục đích của yêu cầu gốc nhưng chuyển hướng về Children's Toy Store.
3. Các gợi ý phải đa dạng:
   - 1 gợi ý: giới thiệu tính năng/dịch vụ của Children's Toy Store (thay thế trực tiếp)
   - 1 gợi ý: cùng thể loại nội dung nhưng về sản phẩm của Children's Toy Store
   - 1 gợi ý: chủ đề liên quan đến đồ chơi/giáo dục trẻ em
   - 1 gợi ý: góc độ khác của cùng chủ đề, phù hợp cho phụ huynh

Trả về JSON theo đúng format, không thêm text nào khác:
{{"suggestions": ["gợi ý 1", "gợi ý 2", "gợi ý 3", "gợi ý 4"]}}
"""
    settings = get_settings()
    contextual_fallback = _build_contextual_fallback_suggestions(title, content)
    if not settings.blog_deepseek_api_key:
        return contextual_fallback[:4]

    model = settings.blog_deepseek_model or "deepseek-chat"
    endpoints = _build_deepseek_endpoints(settings.blog_deepseek_base_url)
    headers = {
        "Authorization": f"Bearer {settings.blog_deepseek_api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": suggestion_prompt}],
        "max_tokens": 300,
        "temperature": 0.8,
        "response_format": {"type": "json_object"},
    }

    try:
        async with httpx.AsyncClient(timeout=settings.blog_deepseek_timeout_seconds) as client:
            for endpoint in endpoints:
                resp = await client.post(endpoint, json=payload, headers=headers)
                if resp.status_code >= 400:
                    continue

                body = resp.json()
                raw = str(body["choices"][0]["message"]["content"]).strip()
                raw = raw.replace("```json", "").replace("```", "").strip()
                parsed = json.loads(raw)
                suggestions = parsed.get("suggestions", [])
                if not isinstance(suggestions, list):
                    continue

                cleaned = [str(item).strip() for item in suggestions if str(item).strip()]
                if len(cleaned) >= 4:
                    return cleaned[:4]
                if cleaned:
                    return (cleaned + contextual_fallback)[:4]

        return contextual_fallback[:4]
    except Exception:
        return contextual_fallback[:4]


def _load_precontent_rules() -> str:
    global _PRECONTENT_CACHE, _PRECONTENT_LOADED_PATH
    if _PRECONTENT_CACHE is not None:
        return _PRECONTENT_CACHE

    base_dir = Path(__file__).resolve().parents[1]
    candidate_paths = [
        base_dir / "moderation" / "product_review" / "text_pipeline" / "precontent.txt",
        base_dir / "moderation" / "text_pipeline" / "precontent.txt",
    ]
    precontent_path = next((path for path in candidate_paths if path.exists()), None)
    if precontent_path is None:
        logger.error("Precontent rules file not found", candidate_paths=[str(path) for path in candidate_paths])
        raise RuntimeError("Moderation rules failed to load: precontent.txt was not found.")

    _PRECONTENT_LOADED_PATH = str(precontent_path)
    raw = precontent_path.read_bytes()
    for encoding in ("utf-8", "utf-8-sig", "cp1258", "latin-1"):
        try:
            _PRECONTENT_CACHE = raw.decode(encoding).strip()
            if not _PRECONTENT_CACHE:
                logger.error("Precontent rules loaded empty", path=_PRECONTENT_LOADED_PATH, encoding=encoding)
                raise RuntimeError("Moderation rules failed to load: precontent.txt is empty.")
            logger.info("Loaded precontent rules", path=_PRECONTENT_LOADED_PATH, encoding=encoding, chars=len(_PRECONTENT_CACHE))
            return _PRECONTENT_CACHE
        except UnicodeDecodeError:
            continue
    _PRECONTENT_CACHE = raw.decode("utf-8", errors="ignore").strip()
    if not _PRECONTENT_CACHE:
        logger.error("Precontent rules loaded empty after fallback decode", path=_PRECONTENT_LOADED_PATH)
        raise RuntimeError("Moderation rules failed to load: precontent decode returned empty content.")
    logger.info("Loaded precontent rules", path=_PRECONTENT_LOADED_PATH, encoding="utf-8-fallback", chars=len(_PRECONTENT_CACHE))
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
    has_structure = ("<h2" in lower_content) and ("<p" in lower_content)
    return has_echo or too_short or not has_structure


def _remove_forbidden_markers(content_html: str, title: str) -> str:
    cleaned = content_html
    cleaned = re.sub(r"^\s*<h1[^>]*>\s*" + re.escape(title.strip()) + r"\s*</h1>\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<p>\s*(title|description)\s*:\s*.*?</p>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<p>\s*(má»Ÿ bÃ i|than bai|thÃ¢n bÃ i|ket bai|káº¿t bÃ i)\s*:?\s*</p>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _remove_prompt_leakage(content_html: str, prompt_structure: str) -> str:
    cleaned = content_html or ""
    prompt_lines = [line.strip(" -*\t\r\n") for line in (prompt_structure or "").splitlines() if line.strip()]
    for line in prompt_lines:
        if not line:
            continue
        escaped = re.escape(line)
        cleaned = re.sub(
            rf"<li>\s*{escaped}\s*</li>",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            rf"<p>\s*{escaped}\s*</p>",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        cleaned = re.sub(
            rf"(^|\n)\s*[-*•]\s*{escaped}\s*($|\n)",
            "\n",
            cleaned,
            flags=re.IGNORECASE,
        )
    cleaned = re.sub(r"<ul>\s*</ul>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def output_validation(content_html: str) -> tuple[str, str]:
    cleaned = content_html
    for emoji in HARD_BLOCK_EMOJIS:
        cleaned = cleaned.replace(emoji, "")

    unsafe_marker = _detect_unsafe_content(cleaned)
    if unsafe_marker:
        return "reject", unsafe_marker

    normalized = _normalize_for_check(cleaned, strip_diacritic=True)
    if any(marker in normalized for marker in ("hate", "racist", "ethnic cleansing")):
        return "reject", "hate_content"

    return "pass", cleaned



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


def _pick_variant(seed_text: str, options: list[str]) -> str:
    if not options:
        return ""
    digest = hashlib.sha256(seed_text.encode("utf-8", errors="ignore")).hexdigest()
    index = int(digest[:8], 16) % len(options)
    return options[index]


def _detect_topic_profile(title: str, description: str | None, prompt_structure: str) -> dict[str, str | list[str]]:
    combined = f"{title}\n{description or ''}\n{prompt_structure}".lower()
    topic = "parent-shopping-guide"
    if any(x in combined for x in ["toy safety", "safe toy", "an toàn", "hazard", "choking", "certification"]):
        topic = "toy-safety"
    elif any(x in combined for x in ["educational", "learn through play", "phát triển trí tuệ", "learning toy"]):
        topic = "educational-toys"
    elif any(x in combined for x in ["outdoor", "ngoài trời", "active play", "backyard"]):
        topic = "outdoor-toys"
    elif any(x in combined for x in ["stem", "steam", "robotics", "coding toy", "science kit"]):
        topic = "stem-toys"
    elif any(x in combined for x in ["toddler", "1-3 years", "preschool", "infant", "mầm non"]):
        topic = "toys-for-toddlers"

    topic_map: dict[str, dict[str, str | list[str]]] = {
        "toy-safety": {
            "angle": "risk prevention and age-appropriate safety",
            "sections": [
                "Most common toy safety risks by age group",
                "How to verify certifications, materials, and build quality",
                "A parent checklist before purchasing or gifting a toy",
            ],
            "cta": "Browse our safety-first toy collection with clear age guidance and trusted materials.",
        },
        "educational-toys": {
            "angle": "skill-building through purposeful play",
            "sections": [
                "How educational toys support language, logic, and creativity",
                "Matching toy types to learning goals at home",
                "Examples of play activities parents can do in 15 minutes",
            ],
            "cta": "Explore educational toys that make learning natural, fun, and consistent every day.",
        },
        "outdoor-toys": {
            "angle": "active play, movement, and social confidence",
            "sections": [
                "Why outdoor play matters for physical and emotional development",
                "Choosing weather-friendly and durable outdoor toys",
                "Safe setup tips for balcony, backyard, and park play",
            ],
            "cta": "Discover outdoor toys designed for movement, confidence, and family fun.",
        },
        "stem-toys": {
            "angle": "hands-on problem solving and curiosity",
            "sections": [
                "What STEM play looks like at different ages",
                "Top STEM toy categories: building, coding, science experiments",
                "How parents can guide exploration without over-instructing",
            ],
            "cta": "Find STEM toys that turn curiosity into practical thinking and creativity.",
        },
        "toys-for-toddlers": {
            "angle": "safe sensory play and early milestones",
            "sections": [
                "Development milestones toddlers need support with",
                "Toy features that are safe, simple, and engaging for toddlers",
                "Building a balanced toy routine for short attention spans",
            ],
            "cta": "Shop toddler-friendly toys that are safe, durable, and development-ready.",
        },
        "parent-shopping-guide": {
            "angle": "smart shopping decisions for long-term value",
            "sections": [
                "How to compare toy value beyond price",
                "Questions to ask before adding a toy to cart",
                "Building a balanced toy mix for your child",
            ],
            "cta": "Use our parent shopping guide to choose toys with confidence and clarity.",
        },
    }
    return topic_map.get(topic, topic_map["parent-shopping-guide"])


def _build_dynamic_writing_strategy(
    *,
    title: str,
    description: str | None,
    prompt_structure: str,
    tone: str,
) -> dict[str, str | list[str]]:
    seed = f"{title}|{description or ''}|{prompt_structure}|{tone}"
    intro_styles = [
        "Start with a short parent scenario and a relatable challenge.",
        "Open with a surprising but practical insight about child play habits.",
        "Begin with a myth-vs-fact angle that reframes toy-buying decisions.",
        "Start with a concise checklist-style opening before deeper analysis.",
    ]
    structures = [
        "problem -> explanation -> practical solutions -> checklist -> conclusion",
        "goal-based guide -> age-based examples -> mistakes to avoid -> action steps",
        "benefits-first narrative -> comparison framework -> buying strategy -> conclusion",
        "question-led sections -> evidence-backed tips -> quick-win ideas -> CTA",
    ]
    cta_styles = [
        "friendly and supportive",
        "expert and confidence-building",
        "concise and action-oriented",
        "warm and community-focused",
    ]
    topic_profile = _detect_topic_profile(title, description, prompt_structure)
    return {
        "intro_style": _pick_variant(seed + "|intro", intro_styles),
        "structure": _pick_variant(seed + "|structure", structures),
        "cta_style": _pick_variant(seed + "|cta", cta_styles),
        "topic_angle": str(topic_profile["angle"]),
        "topic_sections": list(topic_profile["sections"]),  # type: ignore[arg-type]
        "topic_cta": str(topic_profile["cta"]),
    }


def _ensure_english_title(raw_title: str | None) -> str:
    title = (raw_title or "").strip()
    if not title:
        return "A Practical Guide to Choosing Toys for Children"
    if _contains_vietnamese_signals(title):
        return "A Practical Guide to Choosing Toys for Children"
    return title


def _normalize_title_for_compare(value: str) -> str:
    cleaned = (value or "").strip().lower()
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip()


def _build_title_from_input(
    input_title: str,
    description: str | None,
    prompt_structure: str,
) -> str:
    combined_seed = f"{input_title}|{description or ''}|{prompt_structure}"
    profile = _detect_topic_profile(input_title, description, prompt_structure)
    topic_angle = str(profile["angle"])

    title_options_by_topic: dict[str, list[str]] = {
        "risk prevention and age-appropriate safety": [
            "Toy Safety Essentials Every Parent Should Know Before Buying",
            "A Parent’s Guide to Choosing Safe, Age-Appropriate Toys",
            "How to Spot Safe Toys: Practical Tips for Smarter Family Shopping",
        ],
        "skill-building through purposeful play": [
            "Educational Toys That Build Real Skills Through Everyday Play",
            "How to Choose Learning Toys That Match Your Child’s Development",
            "From Playtime to Progress: Smart Educational Toys for Kids",
        ],
        "active play, movement, and social confidence": [
            "Best Outdoor Toys to Keep Kids Active, Confident, and Engaged",
            "Outdoor Play Guide: Choosing Durable Toys for Active Children",
            "How Outdoor Toys Support Healthy Movement and Social Growth",
        ],
        "hands-on problem solving and curiosity": [
            "STEM Toys That Spark Curiosity and Real Problem-Solving Skills",
            "A Parent’s Guide to Choosing STEM Toys by Age and Interest",
            "Top STEM Toy Ideas to Help Children Learn by Building and Exploring",
        ],
        "safe sensory play and early milestones": [
            "Best Toys for Toddlers: Safe Choices for Early Learning and Play",
            "Toddler Toy Guide: What to Buy for Safety, Focus, and Development",
            "How to Choose Toys for Toddlers That Support Key Milestones",
        ],
        "smart shopping decisions for long-term value": [
            "Smart Toy Shopping Guide: How Parents Can Choose Better Every Time",
            "How to Compare Toy Value Beyond Price: A Practical Family Guide",
            "Parent Buying Guide: Choosing Toys That Last and Truly Matter",
        ],
    }

    candidate_pool = title_options_by_topic.get(topic_angle, [
        "A Practical Guide to Choosing Toys for Children",
        "How Parents Can Choose Better Toys for Growth and Play",
        "Smart Toy Buying Tips for Safer, More Meaningful Playtime",
    ])
    return _pick_variant(combined_seed, candidate_pool)


def _ensure_rewritten_english_title(
    raw_title: str | None,
    input_title: str,
    description: str | None,
    prompt_structure: str,
) -> str:
    candidate = _ensure_english_title(raw_title)
    if _normalize_title_for_compare(candidate) == _normalize_title_for_compare(input_title):
        return _build_title_from_input(input_title, description, prompt_structure)
    if _contains_vietnamese_signals(candidate):
        return _build_title_from_input(input_title, description, prompt_structure)
    return candidate


def _build_structured_fallback_html(title: str, description: str | None, prompt_structure: str, tone: str) -> str:
    strategy = _build_dynamic_writing_strategy(
        title=title,
        description=description,
        prompt_structure=prompt_structure,
        tone=tone,
    )
    intro = (
        description.strip()
        if description and not _contains_vietnamese_signals(description)
        else "This article helps parents choose safe, age-appropriate, and meaningful toys for children."
    )
    key_points = list(strategy["topic_sections"]) + [
        "Identify your child's age, interests, and developmental stage",
        "Prioritize safety, durability, and product quality",
        "Choose toys that support learning through play",
    ]
    bullet_html = "".join(f"<li>{point}</li>" for point in key_points[:8])
    content = (
        f"<p>{intro}</p>"
        f"<blockquote><p><strong>Quick tip:</strong> Start with safety and age fit, then choose toys that build creativity and life skills.</p></blockquote>"
        f"<h2>Why this topic matters for modern families</h2>"
        f"<p>Age-appropriate toys support cognitive growth, language development, and social-emotional learning in natural ways. "
        f"When parents choose intentionally, playtime becomes a daily opportunity for discovery and family connection.</p>"
        f"<p>Smart toy choices also reduce safety risks and prevent unnecessary spending on products that do not match a child's stage or needs.</p>"
        f"<h2>How to make better toy decisions</h2>"
        f"<ul>{bullet_html}</ul>"
        f"<p><strong>Checklist:</strong></p>"
        f"<ul><li>&#10003; Verify materials and safety certifications</li><li>&#10003; Match complexity to the child's age</li><li>&#10003; Stay involved to extend learning through play</li></ul>"
        f"<p>Prioritize trusted brands, transparent labeling, and durable materials. "
        f"For toys with small parts, assess choking hazards carefully; for electronic toys, review sound levels, battery safety, and cleaning requirements.</p>"
        f"<p>Balance movement toys, creative toys, and logic-based toys so children develop holistically. "
        f"Open-ended toys with multiple play paths are especially effective for imagination and problem-solving.</p>"
        f"<h2>Practical recommendations for different family routines</h2>"
        f"<p>If your schedule is busy, choose toys that support meaningful 15-20 minute play sessions each day. "
        f"If your home has more space, include active play options that help children release energy and build physical confidence.</p>"
        f"<p>Children who prefer quiet activities often enjoy building sets, coloring, and picture books. "
        f"More energetic children may benefit from pretend play, mini sports, and hands-on activity kits that sustain focus.</p>"
        f"<h2>Conclusion</h2>"
        f"<p>Choosing toys is not only a shopping task; it is an ongoing parenting strategy. "
        f"Focus on safety, age fit, and development goals so each toy creates long-term value.</p>"
        f"<p>With a {tone.lower()} and intentional approach, parents can turn everyday play into meaningful learning and lasting family memories.</p>"
        f"<p><strong>Next step:</strong> {strategy['topic_cta']}</p>"
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
) -> tuple[str, str] | dict[str, str | list[str]]:
    logger.info(
        "AI blog generation requested",
        action=action,
        title_len=len(title or ""),
        prompt_len=len(prompt_structure or ""),
        has_source=bool(source_content),
        category_id=category_id,
    )

    # Step 1: Validate request (user scope only).
    if not (title or "").strip() or not (prompt_structure or "").strip() or category_id <= 0:
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": "validation_error",
            "reason": "invalid_request",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }

    # Step 2: Emoji check (hard block list) on user scope only.
    blocked_emoji = _check_hard_block_emoji(title, prompt_structure)
    if blocked_emoji:
        return {
            "status": "blocked",
            "violation_type": "unsafe_content",
            "violated_keyword": blocked_emoji,
            "reason": "inappropriate_emoji",
            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
        }

    # Step 3: classify_intent() on user scope only.
    intent = await classify_intent(
        title=title,
        description=description,
        prompt_structure=prompt_structure,
        category_id=category_id,
    )
    if str(intent.get("decision")) == "block":
        logger.info(
            "Blog generation blocked by intent gate",
            reason=intent.get("reason"),
            confidence=intent.get("confidence"),
            source=intent.get("source"),
        )
        return {
            "status": "blocked",
            "violation_type": "out_of_scope",
            "violated_keyword": "off_topic",
            "reason": "off_topic",
            "suggestions": [str(intent.get("suggestion", DEFAULT_BLOCK_SUGGESTIONS[0]))] + DEFAULT_BLOCK_SUGGESTIONS[:3],
        }
    if str(intent.get("decision")) == "review":
        logger.info(
            "Intent gate uncertain, allow generation",
            reason=intent.get("reason"),
            confidence=intent.get("confidence"),
            source=intent.get("source"),
        )

    # Step 4: safety_check() on user scope only.
    violation = safety_check(title=title, prompt_structure=prompt_structure)
    if violation:
        smart_suggestions = await generate_smart_suggestions(
            title=title,
            content=(description or prompt_structure or "").strip(),
            violated_keyword=str(violation.get("violated_keyword", "")),
            violation_reason=str(violation.get("reason", "")),
        )
        violation["suggestions"] = smart_suggestions[:4] if smart_suggestions else DEFAULT_BLOCK_SUGGESTIONS[:4]
        logger.info(
            "Blog generation blocked by pre-check",
            violation_type=violation.get("violation_type"),
            violated_keyword=violation.get("violated_keyword"),
        )
        return violation

    # SourceContent is system scope and never causes blocking.
    source_warning = _build_source_content_warning(source_content)
    if source_warning:
        logger.warning("Source content moderation warning", detail=source_warning)

    cache_key = _make_generate_cache_key(
        action=action,
        title=title,
        description=description,
        prompt_structure=prompt_structure,
        tone=tone,
        category_id=category_id,
        source_content=source_content,
    )
    cached_result = _cache_get(cache_key)
    if cached_result is not None:
        logger.info("AI blog generation cache hit", title_len=len(title or ""))
        return cached_result

    settings = get_settings()
    if not settings.blog_deepseek_api_key:
        raise BlogContentGenerationError("DEEPSEEK_API_KEY is not configured.")

    model = settings.blog_deepseek_model or "deepseek-chat"
    endpoints = _build_deepseek_endpoints(settings.blog_deepseek_base_url)

    strategy = _build_dynamic_writing_strategy(
        title=title,
        description=description,
        prompt_structure=prompt_structure,
        tone=tone,
    )

    # Step 5: build_prompt().
    system_prompt = (
        "You are a senior blog writer for a children's toy e-commerce website. "
        "Understand Vietnamese and English input, but always output natural SEO-friendly English. "
        "Keep content family-safe and specific to toys, parenting, and child development. "
        "Write strictly about the user-provided topic and intent. "
        "Do not rewrite, redirect, or reinterpret off-topic requests into toy-store content. "
        "Avoid template-like phrasing and do not echo request metadata."
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
DynamicWritingStrategy:
- Intro style: {strategy['intro_style']}
- Article flow: {strategy['structure']}
- Topic angle: {strategy['topic_angle']}
- Suggested section ideas: {", ".join(strategy['topic_sections'])}
- CTA style: {strategy['cta_style']}
- CTA message intent: {strategy['topic_cta']}

Write one complete article with opening, body, and conclusion.
Constraints:
- 3000-6000 characters, continuous natural prose.
- Opening + at least 3 body sections with unique subheadings + conclusion.
- Do NOT include request metadata or labels like "Mo bai/Than bai/Ket bai".
- Always return English title and content (translate intent if Vietnamese input).
- Keep wording varied and specific to this prompt topic.
- Return ONLY valid JSON: {{"title":"...","content":"..."}}.
- content must be HTML and <=10000 chars using <h1>, <h2>, <h3>, <p>, <ul>, <li>, <strong>, <blockquote>.

Precontent rules (must comply):
{precontent_rules}
"""

    payload_base = {
        "model": model,
        "temperature": settings.blog_deepseek_temperature if settings.blog_deepseek_temperature > 0 else 0.8,
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

    # Step 6: call_model().
    async with httpx.AsyncClient(timeout=per_request_timeout) as client:
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
                    generated_title = _ensure_rewritten_english_title(
                        parsed_title,
                        title,
                        description,
                        prompt_structure,
                    )
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
                    blog_content = _remove_prompt_leakage(blog_content, prompt_structure)
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
                    # Step 7: output_validation().
                    validation_status, validation_payload = output_validation(blog_content)
                    if validation_status == "reject":
                        return {
                            "status": "blocked",
                            "violation_type": "unsafe_content",
                            "violated_keyword": str(validation_payload),
                            "reason": "unsafe_output",
                            "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
                        }

                    result = (generated_title, validation_payload)
                    _cache_put(cache_key, result)
                    return result
                except (KeyError, ValueError, TypeError, json.JSONDecodeError):
                    last_error = "DeepSeek response parse failed."
                    logger.warning("DeepSeek parse failed", endpoint=endpoint, attempt=attempt + 1)
                    continue

    fallback_title = _ensure_rewritten_english_title(
        None,
        title,
        description,
        prompt_structure,
    )
    fallback_html = _build_structured_fallback_html(
        title=fallback_title,
        description=description,
        prompt_structure=prompt_structure,
        tone=tone,
    )
    if len(fallback_html) > MAX_CONTENT_LENGTH:
        fallback_html = fallback_html[:MAX_CONTENT_LENGTH]
    fallback_html = _remove_prompt_leakage(fallback_html, prompt_structure)
    if fallback_html:
        validation_status, validation_payload = output_validation(fallback_html)
        if validation_status == "reject":
            return {
                "status": "blocked",
                "violation_type": "unsafe_content",
                "violated_keyword": str(validation_payload),
                "reason": "unsafe_output",
                "suggestions": DEFAULT_BLOCK_SUGGESTIONS[:4],
            }
        logger.warning(
            "Using fallback blog content after AI failure",
            reason=last_error,
            output_len=len(fallback_html),
        )
        result = (fallback_title, validation_payload)
        _cache_put(cache_key, result)
        return result
    raise BlogContentGenerationError(last_error)


