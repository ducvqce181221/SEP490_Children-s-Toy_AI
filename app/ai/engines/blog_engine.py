"""
app/ai/engines/blog_engine.py
-----------------------------
Engine sinh bài viết Blog bằng AI: quản lý xây dựng chiến lược nội dung (Dynamic Writing Strategy),
gọi AI Provider (DeepSeek chính + Groq dự phòng với cơ chế Retry), parse/format kết quả HTML bài viết,
loại bỏ rò rỉ prompt (prompt leakage), hỗ trợ sinh gợi ý bài viết thay thế và tạo bài viết dự phòng (heuristic fallback).
"""

from __future__ import annotations

import json
import re
import hashlib

from app.configs.config import get_settings
from app.core.logging import get_logger
from app.ai.providers.factory import execute_chat_completion
from app.ai.prompts.templates import (
    BLOG_SYSTEM_PROMPT,
    build_blog_user_prompt,
    load_precontent_rules,
)
from app.ai.engines.content_analyzer import (
    _build_contextual_fallback_suggestions,
)

logger = get_logger(__name__)

MAX_CONTENT_LENGTH = 10_000
MIN_CONTENT_LENGTH = 3_000


def _contains_vietnamese_signals(text: str) -> bool:
    """
    Kiểm tra xem văn bản có chứa các từ/tín hiệu Tiếng Việt hay không.
    Hệ thống tạo blog quy định đầu ra bài viết phải viết bằng Tiếng Anh.
    Nếu phát hiện các cụm từ tiếng Việt như 'mở bài', 'thân bài', 'đồ chơi', 'phụ huynh'...,
    kết quả sẽ bị đánh dấu không đạt và chuyển sang bài viết fallback tiếng Anh chuẩn.
    """
    lower = f" {(text or '').lower()} "
    return any(
        token in lower
        for token in [
            " mơ ", " mở bài ", " thân bài ", " kết bài ", " đồ chơi ",
            " phụ huynh ", " trẻ ", " không ", " tại sao ", " lời khuyên ",
            " vi sao ", " do choi ", " phu huynh ", " ket luan ",
        ]
    )


def _pick_variant(seed_text: str, options: list[str]) -> str:
    """
    Chọn 1 phần tử ngẫu nhiên từ danh sách options dựa trên mã băm SHA256 của chuỗi seed_text.
    Giúp cùng 1 input luôn trả về variant nhất quán (Deterministic Selection), nhưng các input khác nhau sẽ nhận các biến thể đa dạng.
    """
    if not options:
        return ""
    digest = hashlib.sha256(seed_text.encode("utf-8", errors="ignore")).hexdigest()
    index = int(digest[:8], 16) % len(options)
    return options[index]


def _detect_topic_profile(title: str, description: str | None, prompt_structure: str) -> dict[str, str | list[str]]:
    """
    Phân tích nội dung tiêu đề và mô tả để xác định hồ sơ chủ đề (Topic Profile).
    Các nhóm chủ đề chính bao gồm:
    - toy-safety: An toàn đồ chơi, nguy cơ hóc dị vật, chứng nhận chất lượng
    - educational-toys: Đồ chơi giáo dục, phát triển tư duy, sáng tạo
    - outdoor-toys: Đồ chơi vận động ngoài trời, thể chất
    - stem-toys: Đồ chơi khoa học, công nghệ, lập trình, xếp hình logic
    - toys-for-toddlers: Đồ chơi cho trẻ chập chập biết đi (1-3 tuổi), giác quan
    - parent-shopping-guide: Hướng dẫn mua sắm thông minh cho cha mẹ (Mặc định).
    """
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
    """
    Xây dựng chiến lược nội dung động (Dynamic Writing Strategy) cho AI:
    Lựa chọn kiểu mở bài (intro_style), cấu trúc bài viết (structure), phong cách kêu lưu hành động (cta_style),
    và định hình góc nhìn nội dung cụ thể dựa trên thông tin yêu cầu.
    """
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
        "friendly and supportive", "expert and confidence-building",
        "concise and action-oriented", "warm and community-focused",
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
    """
    Hàm sinh bài viết dự phòng (Heuristic Local Fallback) chuẩn định dạng HTML (đủ 3.000 - 6.000 ký tự).
    Được sử dụng khi dịch vụ AI LLM (DeepSeek / Groq) bị mất kết nối, quá tải hoặc phản hồi không đạt chất lượng.
    Đảm bảo hệ thống luôn trả về bài viết hoàn chỉnh, giàu thông tin và đáp ứng trải nghiệm người dùng.
    """
    strategy = _build_dynamic_writing_strategy(
        title=title, description=description, prompt_structure=prompt_structure, tone=tone,
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


def _clean_model_text(raw: str) -> str:
    """Loại bỏ các ký tự bọc Markdown codeblock (```json ... ```) khỏi văn bản phản hồi thô của AI."""
    text = (raw or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _strip_json_prefix_noise(text: str) -> str:
    """Xóa các tiền tố nhiễu dạng JSON bị thừa trong văn bản bài viết."""
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
    """
    Chuyển đổi văn bản định dạng Markdown/Text thuần sang văn bản HTML chuẩn:
    - Chuyển `#`, `##`, `###` thành các thẻ `<h1>`, `<h2>`, `<h3>`
    - Chuyển danh sách `-` hoặc `*` thành thẻ `<ul><li>...</li></ul>`
    - Chuyển văn bản in đậm `**text**` thành `<strong>text</strong>`
    - Chuyển các đoạn văn bản còn lại thành thẻ `<p>`.
    """
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
    """
    Đánh giá chất lượng của bài viết HTML do AI tạo ra.
    Trả về True (Kém chất lượng) nếu:
    - Bài viết chứa các từ khóa nhại lại prompt/metadata ("action:", "promptstructure:")
    - Độ dài bài viết ngắn hơn độ dài tối thiểu (MIN_CONTENT_LENGTH = 3.000 ký tự)
    - Bài viết thiếu cấu trúc cơ bản (thẻ <h2 và <p).
    """
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
    """Xóa các thẻ h1 trùng lặp với tiêu đề bài viết và các nhãn đánh dấu phân đoạn thừa."""
    cleaned = content_html
    cleaned = re.sub(r"^\s*<h1[^>]*>\s*" + re.escape(title.strip()) + r"\s*</h1>\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<p>\s*(title|description)\s*:\s*.*?</p>", "", cleaned, flags=re.IGNORECASE | re.DOTALL)
    cleaned = re.sub(r"<p>\s*(má»Ÿ bÃ i|than bai|thÃ¢n bÃ i|ket bai|káº¿t bÃ i)\s*:?\s*</p>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


def _remove_prompt_leakage(content_html: str, prompt_structure: str) -> str:
    """
    Loại bỏ hiện tượng rò rỉ prompt (Prompt Leakage):
    Quét và xóa các dòng văn bản bị AI sao chép nguyên văn từ danh sách dàn ý prompt_structure vào trong bài viết.
    """
    cleaned = content_html or ""
    prompt_lines = [line.strip(" -*\t\r\n") for line in (prompt_structure or "").splitlines() if line.strip()]
    for line in prompt_lines:
        if not line:
            continue
        escaped = re.escape(line)
        cleaned = re.sub(rf"<li>\s*{escaped}\s*</li>", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(rf"<p>\s*{escaped}\s*</p>", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(rf"(^|\n)\s*[-*•]\s*{escaped}\s*($|\n)", "\n", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"<ul>\s*</ul>", "", cleaned, flags=re.IGNORECASE)
    return cleaned.strip()


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


async def generate_smart_suggestions(
    title: str,
    content: str,
    violated_keyword: str,
    violation_reason: str,
) -> list[str]:
    """
    Sinh 4 gợi ý tiêu đề/chủ đề thay thế bằng AI tiếng Anh khi yêu cầu ban đầu bị chặn (bởi Safety Pre-check).
    Nếu không gọi được AI, sẽ fallback sang danh sách gợi ý theo ngữ cảnh có sẵn.
    """
    suggestion_prompt = f"""
The user requested to generate a blog with the following info:
- Title: {title}
- Description: {content}

This request was rejected due to: {violation_reason}
Violating keyword: {violated_keyword}

Task: Create exactly 4 alternative topic suggestions IN ENGLISH suitable for Children's Toy Store.

Return JSON strictly in this format (no extra text):
{{"suggestions": ["English topic 1", "English topic 2", "English topic 3", "English topic 4"]}}
"""
    settings = get_settings()
    contextual_fallback = _build_contextual_fallback_suggestions(title, content)
    if not settings.blog_deepseek_api_key:
        return contextual_fallback[:4]

    try:
        raw_completion = await execute_chat_completion(
            primary_provider_name="deepseek",
            messages=[{"role": "user", "content": suggestion_prompt}],
            temperature=0.8,
            max_tokens=300,
            response_format={"type": "json_object"},
            fallback_provider_name="groq",
        )
        raw = raw_completion.strip()
        raw = raw.replace("```json", "").replace("```", "").strip()
        parsed = json.loads(raw)
        suggestions = parsed.get("suggestions", [])
        if not isinstance(suggestions, list):
            return contextual_fallback[:4]

        cleaned = [str(item).strip() for item in suggestions if str(item).strip()]
        if len(cleaned) >= 4:
            return cleaned[:4]
        if cleaned:
            return (cleaned + contextual_fallback)[:4]
        return contextual_fallback[:4]
    except Exception:
        return contextual_fallback[:4]


async def execute_blog_generation(
    *,
    action: str,
    title: str,
    description: str | None,
    prompt_structure: str,
    tone: str,
    category_id: int,
    source_content: str | None,
) -> tuple[str, str]:
    """
    Thực thi sinh bài viết blog bằng AI:
    1. Dựng prompt chiến lược người dùng (User Prompt & System Prompt)
    2. Gọi DeepSeek (hoặc Groq dự phòng) với số lần thử lại (retries) được cấu hình
    3. Xử lý bài viết đầu ra: Parse JSON -> Chuẩn hóa tiêu đề -> Chuyển định dạng HTML
    4. Loại bỏ các ký hiệu thừa và prompt leakage (văn bản bị nhại lại từ prompt)
    5. Nếu bài viết bị lỗi/kém chất lượng hoặc chứa tín hiệu Tiếng Việt (hệ thống yêu cầu tiếng Anh),
       sẽ tự động dùng hàm sinh bài viết dự phòng local (_build_structured_fallback_html).
    """
    settings = get_settings()
    strategy = _build_dynamic_writing_strategy(
        title=title, description=description, prompt_structure=prompt_structure, tone=tone,
    )
    precontent_rules = load_precontent_rules()
    user_prompt = build_blog_user_prompt(
        action=action, title=title, description=description,
        prompt_structure=prompt_structure, tone=tone, category_id=category_id,
        source_content=source_content, strategy=strategy, precontent_rules=precontent_rules,
    )

    messages_base = [
        {"role": "system", "content": BLOG_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    last_error = "DeepSeek request failed."
    retry_attempts = settings.blog_deepseek_retry_attempts

    for attempt in range(retry_attempts):
        messages = list(messages_base)
        if attempt > 0:
            messages = [
                {"role": "system", "content": BLOG_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": user_prompt + "\nIMPORTANT RETRY: Expand depth. Ensure 3000-6000 characters, opening-body-conclusion, and no metadata echo.",
                },
            ]

        try:
            # 1. Gọi API sinh bài viết từ mô hình AI (DeepSeek chính, Groq dự phòng) dưới dạng JSON
            raw_completion = await execute_chat_completion(
                primary_provider_name="deepseek",
                messages=messages,
                temperature=settings.blog_deepseek_temperature if settings.blog_deepseek_temperature > 0 else 0.8,
                max_tokens=settings.blog_deepseek_max_tokens,
                response_format={"type": "json_object"},
                fallback_provider_name="groq",
            )
            # 2. Parse kết quả JSON thô để lấy tiêu đề và nội dung bài viết
            parsed_title, parsed_content = _try_parse_json_payload(raw_completion)
            generated_title = _ensure_rewritten_english_title(
                parsed_title, title, description, prompt_structure,
            )
            blog_content = (parsed_content or "").strip()

            # 3. Xử lý trường hợp nội dung bị rỗng (cố gắng làm sạch chuỗi thô để lấy văn bản)
            if not blog_content:
                fallback_text = _strip_json_prefix_noise(_clean_model_text(raw_completion))
                if not fallback_text:
                    raise ValueError("empty blogContent")
                blog_content = fallback_text

            # 4. Chuyển đổi định dạng bài viết sang HTML; tự sinh bài viết dự phòng nếu kết quả trống
            blog_content = _to_html_from_text(blog_content)
            if not blog_content:
                blog_content = _build_structured_fallback_html(
                    title=generated_title, description=description, prompt_structure=prompt_structure, tone=tone,
                )

            # 5. Kiểm tra chất lượng bài viết (độ dài, cấu trúc, lặp prompt). Thử lại nếu không đạt.
            if _is_low_quality_or_echo(blog_content):
                if attempt < (retry_attempts - 1):
                    continue
                blog_content = _build_structured_fallback_html(
                    title=generated_title, description=description, prompt_structure=prompt_structure, tone=tone,
                )

            # 6. Giới hạn độ dài nội dung, xóa các thẻ/nhãn thừa và xử lý rò rỉ prompt
            if len(blog_content) > MAX_CONTENT_LENGTH:
                blog_content = blog_content[:MAX_CONTENT_LENGTH]
            blog_content = _remove_forbidden_markers(blog_content, generated_title)
            blog_content = _remove_prompt_leakage(blog_content, prompt_structure)

            # 7. Đảm bảo ngôn ngữ bài viết là tiếng Anh (dùng fallback nếu phát hiện tiếng Việt)
            if _contains_vietnamese_signals(blog_content):
                blog_content = _build_structured_fallback_html(
                    title=generated_title, description=description, prompt_structure=prompt_structure, tone=tone,
                )

            return generated_title, blog_content
        except Exception as exc:
            # 8. Ghi nhận lỗi trong lần thử hiện tại và tiếp tục vòng lặp retry
            logger.warning("Generation attempt failed", attempt=attempt + 1, error=str(exc))
            continue

    # Fallback to local heuristic article generation if all fails
    fallback_title = _ensure_rewritten_english_title(
        None, title, description, prompt_structure,
    )
    fallback_html = _build_structured_fallback_html(
        title=fallback_title, description=description, prompt_structure=prompt_structure, tone=tone,
    )
    if len(fallback_html) > MAX_CONTENT_LENGTH:
        fallback_html = fallback_html[:MAX_CONTENT_LENGTH]
    fallback_html = _remove_prompt_leakage(fallback_html, prompt_structure)
    return fallback_title, fallback_html
