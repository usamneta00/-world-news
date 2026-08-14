"""On-demand YouTube research pipeline used by the existing FastAPI app.

The module deliberately owns no scheduler, background loop, database table, or
process lifecycle.  ``research_youtube`` is the only orchestration entry point;
each call is an independent research session derived from the supplied prompt.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import quote_plus

import requests
import yt_dlp
from bs4 import BeautifulSoup


logger = logging.getLogger(__name__)
YOUTUBE_URL = "https://www.youtube.com/watch?v={}"
MIN_FINAL_VIDEOS = 7
def _normalise_filters(raw: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    raw = raw or {}

    def number(name: str, default: float = 0.0) -> float:
        try:
            return max(0.0, float(raw.get(name) or default))
        except (TypeError, ValueError):
            return default

    language = str(raw.get("language") or "any").strip().casefold()
    live_status = str(raw.get("live_status") or "any").strip().casefold()
    channel_type = str(raw.get("channel_type") or "any").strip().casefold()
    allowed_live = {"any", "live", "upcoming", "not_live"}
    allowed_channels = {"any", "news", "official", "independent", "educational", "interview", "documentary"}
    date_from = str(raw.get("date_from") or "").strip()
    date_to = str(raw.get("date_to") or "").strip()
    if date_from and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_from):
        date_from = ""
    if date_to and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date_to):
        date_to = ""
    minimum_minutes = number("min_duration_minutes")
    maximum_minutes = number("max_duration_minutes")
    if maximum_minutes and maximum_minutes < minimum_minutes:
        minimum_minutes, maximum_minutes = maximum_minutes, minimum_minutes
    return {
        "min_duration_seconds": int(minimum_minutes * 60),
        "max_duration_seconds": int(maximum_minutes * 60),
        "date_from": date_from,
        "date_to": date_to,
        "language": language,
        "country": str(raw.get("country") or "").strip(),
        "channel_type": channel_type if channel_type in allowed_channels else "any",
        "min_views": int(number("min_views")),
        "min_reliability": min(10.0, number("min_reliability")),
        "live_status": live_status if live_status in allowed_live else "any",
        "require_transcript": bool(raw.get("require_transcript", True)),
    }


@dataclass
class ResearchBrief:
    main_topic: str
    entities: List[str] = field(default_factory=list)
    countries: List[str] = field(default_factory=list)
    people: List[str] = field(default_factory=list)
    organizations: List[str] = field(default_factory=list)
    events: List[str] = field(default_factory=list)
    subtopics: List[str] = field(default_factory=list)
    desired_video_count: Dict[str, int] = field(default_factory=lambda: {"min": MIN_FINAL_VIDEOS, "max": 10})
    preferred_languages: List[str] = field(default_factory=list)
    preferred_sources: List[str] = field(default_factory=list)
    date_policy: List[Dict[str, Any]] = field(default_factory=list)
    required_angles: List[str] = field(default_factory=list)
    excluded_content: List[str] = field(default_factory=list)
    output_requirements: List[str] = field(default_factory=list)

    def as_dict(self) -> Dict[str, Any]:
        return self.__dict__.copy()


def _json_from_text(value: str) -> Any:
    value = (value or "").strip()
    value = re.sub(r"^```(?:json)?\s*|\s*```$", "", value, flags=re.I)
    first = min([i for i in (value.find("{"), value.find("[")) if i >= 0], default=-1)
    if first > 0:
        value = value[first:]
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        end = max(value.rfind("}"), value.rfind("]"))
        if end >= 0:
            return json.loads(value[: end + 1])
        raise


async def _openai_json(system: str, prompt: str, api_key: str, max_tokens: int = 3500) -> Any:
    if not api_key:
        return None

    def call() -> Any:
        response = requests.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
            json={
                "model": os.environ.get("YOUTUBE_RESEARCH_MODEL", "gpt-4o-mini"),
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                "temperature": 0.2,
                "response_format": {"type": "json_object"},
                "max_tokens": max_tokens,
            },
            timeout=90,
        )
        response.raise_for_status()
        return _json_from_text(response.json()["choices"][0]["message"]["content"])

    try:
        return await asyncio.to_thread(call)
    except Exception as exc:
        logger.warning("YouTube Research OpenAI step failed: %s", exc)
        return None


def _clean_prompt(prompt: str) -> str:
    prompt = re.sub(r"^\s*@youtube\s*", "", prompt or "", flags=re.I)
    return re.sub(r"\s+", " ", prompt).strip()


def _derive_main_topic(prompt: str) -> str:
    """Keep the subject matter while dropping operational search instructions."""
    raw = re.sub(r"^\s*@youtube\s*", "", prompt or "", flags=re.I)
    parts = [re.sub(r"\s+", " ", part).strip(" .،؛") for part in re.split(r"[\r\n]+|(?<=[.!؟])\s+", raw)]
    instruction = re.compile(
        r"^(?:ابحث|أريد|اريد|اعرض|أعطني|اعطني|ابدأ|ابدا|وس[ّ]?ع|find|search|show|give|start)\b",
        re.I,
    )
    topics = [part for part in parts if len(part) >= 12 and not instruction.search(part)]
    topic = " ".join(topics[:3]) if topics else _clean_prompt(prompt)
    # Search engines work better with a focused topic than a full pasted article.
    words = topic.split()
    return " ".join(words[:60])


def _extract_count(prompt: str) -> Dict[str, int]:
    pairs = re.findall(r"(\d{1,2})\s*(?:-|–|—|إلى|الى|حتى|to)\s*(\d{1,2})", prompt, re.I)
    if pairs:
        low, high = map(int, pairs[-1])
        low, high = min(low, high), max(low, high)
        return {"min": max(MIN_FINAL_VIDEOS, min(low, 20)), "max": max(MIN_FINAL_VIDEOS, min(high, 20))}
    match = re.search(r"(\d{1,2})\s*(?:فيديو|فيديوهات|videos?)", prompt, re.I)
    if match:
        count = max(1, min(int(match.group(1)), 20))
        return {"min": max(MIN_FINAL_VIDEOS, count), "max": max(MIN_FINAL_VIDEOS, count)}
    return {"min": MIN_FINAL_VIDEOS, "max": 10}


def _extract_date_policy(prompt: str) -> List[Dict[str, Any]]:
    text = prompt.lower()
    policies: List[Dict[str, Any]] = []
    if re.search(r"24\s*(?:ساعة|ساعه|hours?)", text):
        return [{"days": 1, "label": "آخر 24 ساعة", "expand_if_needed": False}]
    if re.search(r"(?:أسبوع|اسبوع|week)", text):
        policies.append({"days": 7, "label": "آخر أسبوع", "expand_if_needed": True})
    if re.search(r"(?:شهر|month)", text):
        policies.append({"days": 30, "label": "آخر شهر", "expand_if_needed": False})
    year_match = re.search(r"(?:آخر|اخر|last)\s+(\d+)\s*(?:يوم|days?)", text)
    if year_match:
        days = max(1, min(int(year_match.group(1)), 3650))
        return [{"days": days, "label": f"آخر {days} يومًا", "expand_if_needed": False}]
    return policies


async def analyze_prompt(user_prompt: str, api_key: str = "") -> ResearchBrief:
    cleaned = _clean_prompt(user_prompt)
    fallback = ResearchBrief(
        main_topic=_derive_main_topic(user_prompt),
        desired_video_count=_extract_count(cleaned),
        preferred_languages=["ar"] if re.search(r"عربي|العربية|arabic", cleaned, re.I) else [],
        date_policy=_extract_date_policy(cleaned),
        excluded_content=["shorts"] if re.search(r"تحليل|عميق|analysis|documentary", cleaned, re.I) else [],
        output_requirements=["verified_youtube_links", "connected_sequence"],
    )
    schema = fallback.as_dict()
    ai = await _openai_json(
        "أنت مخطط بحث YouTube. استخرج القيود من طلب المستخدم فقط ولا تضف موضوعات ثابتة. أجب JSON فقط.",
        f"حلل الطلب التالي إلى المخطط المرفق. تعليمات المستخدم لها الأولوية.\nالطلب: {cleaned}\nالمخطط: {json.dumps(schema, ensure_ascii=False)}",
        api_key,
    )
    if not isinstance(ai, dict):
        return fallback
    allowed = set(schema)
    values = {key: ai.get(key, schema[key]) for key in allowed}
    values["main_topic"] = str(values.get("main_topic") or cleaned)
    counts = values.get("desired_video_count") or fallback.desired_video_count
    values["desired_video_count"] = {
        "min": max(MIN_FINAL_VIDEOS, min(int(counts.get("min", fallback.desired_video_count["min"])), 20)),
        "max": max(MIN_FINAL_VIDEOS, min(int(counts.get("max", fallback.desired_video_count["max"])), 20)),
    }
    if values["desired_video_count"]["max"] < values["desired_video_count"]["min"]:
        values["desired_video_count"]["max"] = values["desired_video_count"]["min"]
    for key in (
        "entities", "countries", "people", "organizations", "events", "subtopics",
        "preferred_languages", "preferred_sources", "required_angles", "excluded_content", "output_requirements",
    ):
        raw = values.get(key)
        values[key] = [str(item).strip() for item in raw if str(item).strip()] if isinstance(raw, list) else schema[key]
    date_policy = values.get("date_policy")
    if isinstance(date_policy, list):
        date_policy = [item for item in date_policy if isinstance(item, dict) and item.get("days")]
    else:
        date_policy = []
    values["date_policy"] = date_policy or fallback.date_policy
    return ResearchBrief(**values)


def _fallback_queries(brief: ResearchBrief) -> List[Dict[str, Any]]:
    topic = brief.main_topic
    angles = brief.required_angles or brief.subtopics
    if not angles:
        angles = ["overview", "analysis", "expert_interview", "evidence", "opposing_view", "future_scenarios"]
    suffixes = {
        "overview": "شرح وتفاصيل",
        "analysis": "تحليل معمق",
        "expert_interview": "مقابلة خبير",
        "evidence": "حقائق وأدلة",
        "opposing_view": "وجهة نظر أخرى",
        "future_scenarios": "سيناريوهات مستقبلية",
    }
    queries = []
    for index, angle in enumerate(angles[:10]):
        suffix = suffixes.get(str(angle), str(angle))
        queries.append({"query": f"{topic} {suffix}", "angle": str(angle), "priority": max(5, 10 - index)})
    for suffix, angle in [("analysis explained", "international_analysis"), ("expert interview", "expert_interview"), ("evidence documentary", "evidence")]:
        queries.append({"query": f"{topic} {suffix}", "angle": angle, "priority": 7})
    return queries


async def build_search_plan(brief: ResearchBrief, api_key: str = "") -> List[Dict[str, Any]]:
    ai = await _openai_json(
        "أنت باحث YouTube متعدد اللغات. أنشئ زوايا وعبارات بحث متنوعة من الموضوع الحالي وحده. أجب JSON فقط.",
        "أنشئ 6 إلى 12 عبارة بحث، ابدأ باللغة المطلوبة وأضف الإنجليزية فقط عندما توسع المصادر. "
        "لا تستخدم قائمة قنوات مغلقة. أعد {\"queries\":[{\"query\":\"...\",\"angle\":\"...\",\"priority\":10}]}.\n"
        f"موجز البحث: {json.dumps(brief.as_dict(), ensure_ascii=False)}",
        api_key,
    )
    raw = ai.get("queries") if isinstance(ai, dict) else None
    if not isinstance(raw, list):
        return _fallback_queries(brief)
    result, seen = [], set()
    for item in raw:
        if not isinstance(item, dict) or not str(item.get("query", "")).strip():
            continue
        query = str(item["query"]).strip()
        key = query.casefold()
        if key in seen:
            continue
        seen.add(key)
        result.append({"query": query, "angle": str(item.get("angle") or "general"), "priority": int(item.get("priority") or 5)})
    return result[:12] or _fallback_queries(brief)


def search_youtube(query: str, limit: int = 30) -> List[Dict[str, Any]]:
    options = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": True,
        "skip_download": True,
        "playlistend": limit,
        "ignoreerrors": True,
        "socket_timeout": 15,
        "retries": 1,
        "extractor_retries": 1,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(f"ytsearch{limit}:{query}", download=False) or {}
    items = []
    for entry in info.get("entries") or []:
        if not entry or not entry.get("id"):
            continue
        video_id = entry["id"]
        items.append({
            "video_id": video_id,
            "title": entry.get("title") or "",
            "channel": entry.get("channel") or entry.get("uploader") or "",
            "url": YOUTUBE_URL.format(video_id),
            "duration": entry.get("duration"),
            "timestamp": entry.get("timestamp"),
        })
    return items


def _extract_balanced_json(text: str, marker: str) -> Optional[Dict[str, Any]]:
    start = text.find(marker)
    if start < 0:
        return None
    start = text.find("{", start + len(marker))
    if start < 0:
        return None
    depth, quoted, escaped = 0, False, False
    for index in range(start, len(text)):
        char = text[index]
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(text[start:index + 1])
                except json.JSONDecodeError:
                    return None
    return None


def _fast_video_metadata(video_id: str) -> Optional[Dict[str, Any]]:
    url = YOUTUBE_URL.format(video_id)
    response = requests.get(
        url,
        headers={"User-Agent": "Mozilla/5.0", "Accept-Language": "ar,en-US;q=0.8,en;q=0.7"},
        timeout=15,
    )
    response.raise_for_status()
    data = _extract_balanced_json(response.text, "ytInitialPlayerResponse")
    if not data:
        return None
    status = (data.get("playabilityStatus") or {}).get("status")
    details = data.get("videoDetails") or {}
    micro = ((data.get("microformat") or {}).get("playerMicroformatRenderer") or {})
    if status not in {"OK", "LIVE_STREAM_OFFLINE"} or details.get("videoId") != video_id:
        return None
    thumbnails = ((details.get("thumbnail") or {}).get("thumbnails") or micro.get("thumbnail", {}).get("thumbnails") or [])
    upload_date = str(micro.get("uploadDate") or micro.get("publishDate") or "").replace("-", "")
    return {
        "video_id": video_id,
        "title": details.get("title") or micro.get("title", {}).get("simpleText") or "",
        "channel": details.get("author") or micro.get("ownerChannelName") or "",
        "channel_id": details.get("channelId") or micro.get("externalChannelId") or "",
        "uploader": details.get("author") or "",
        "upload_date": upload_date if re.fullmatch(r"\d{8}", upload_date) else "",
        "timestamp": None,
        "duration": int(details.get("lengthSeconds") or 0) or None,
        "description": details.get("shortDescription") or micro.get("description", {}).get("simpleText") or "",
        "view_count": int(details.get("viewCount") or 0) or None,
        "live_status": "is_live" if details.get("isLiveContent") else "not_live",
        "original_url": url,
        "webpage_url": url,
        "thumbnail": thumbnails[-1].get("url") if thumbnails else f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        "language": "",
        "availability": "public",
    }


def fetch_video_metadata(video_id: str) -> Optional[Dict[str, Any]]:
    try:
        fast = _fast_video_metadata(video_id)
        if fast:
            return fast
    except Exception as exc:
        logger.info("Fast YouTube metadata fallback for %s: %s", video_id, exc)

    options = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "ignoreerrors": True,
        "noplaylist": True,
        "no_check_formats": True,
        "ignore_no_formats_error": True,
        "socket_timeout": 15,
        "retries": 1,
        "extractor_retries": 1,
    }
    with yt_dlp.YoutubeDL(options) as ydl:
        info = ydl.extract_info(YOUTUBE_URL.format(video_id), download=False)
    if not info or not info.get("id"):
        return None
    return {
        "video_id": info.get("id"),
        "title": info.get("title") or "",
        "channel": info.get("channel") or info.get("uploader") or "",
        "channel_id": info.get("channel_id") or "",
        "uploader": info.get("uploader") or "",
        "upload_date": info.get("upload_date") or "",
        "timestamp": info.get("timestamp"),
        "duration": info.get("duration"),
        "description": info.get("description") or "",
        "view_count": info.get("view_count"),
        "live_status": info.get("live_status") or "",
        "original_url": info.get("original_url") or YOUTUBE_URL.format(video_id),
        "webpage_url": info.get("webpage_url") or YOUTUBE_URL.format(video_id),
        "thumbnail": info.get("thumbnail") or f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg",
        "language": info.get("language") or "",
        "availability": info.get("availability") or "",
    }


def verify_video(video_id: str) -> Optional[Dict[str, Any]]:
    metadata = fetch_video_metadata(video_id)
    if not metadata or metadata.get("video_id") != video_id or not metadata.get("title"):
        return None
    if metadata.get("availability") in {"private", "subscriber_only", "premium_only"}:
        return None
    return metadata


def _tokens(text: str) -> set:
    text = re.sub(r"[^\w\u0600-\u06ff]+", " ", (text or "").casefold())
    return {token for token in text.split() if len(token) > 2}


def _overlap(left: str, right: str) -> float:
    a, b = _tokens(left), _tokens(right)
    return len(a & b) / max(1, min(len(a), 12))


def _published_at(item: Dict[str, Any]) -> Optional[datetime]:
    if item.get("timestamp"):
        try:
            return datetime.fromtimestamp(float(item["timestamp"]), tz=timezone.utc)
        except (ValueError, TypeError, OSError):
            pass
    if re.fullmatch(r"\d{8}", str(item.get("upload_date") or "")):
        return datetime.strptime(item["upload_date"], "%Y%m%d").replace(tzinfo=timezone.utc)
    return None


def _date_filter(items: Sequence[Dict[str, Any]], policies: Sequence[Dict[str, Any]], needed: int) -> Tuple[List[Dict[str, Any]], str]:
    if not policies:
        return list(items), "لم يحدد المستخدم نطاقًا زمنيًا"
    now = datetime.now(timezone.utc)
    for index, policy in enumerate(policies):
        if not isinstance(policy, dict):
            continue
        try:
            days = max(1, int(policy.get("days") or 0))
        except (TypeError, ValueError):
            continue
        cutoff = now - timedelta(days=days)
        filtered = [item for item in items if _published_at(item) and _published_at(item) >= cutoff]
        if len(filtered) >= needed or index == len(policies) - 1 or not policy.get("expand_if_needed", True):
            return filtered, str(policy.get("label") or f"آخر {days} يومًا")
    last = next((policy for policy in reversed(policies) if isinstance(policy, dict)), {})
    return [], str(last.get("label") or "")


def _infer_channel_type(item: Dict[str, Any]) -> str:
    text = f"{item.get('channel', '')} {item.get('title', '')} {item.get('description', '')[:1200]}".casefold()
    patterns = (
        ("official", "official رسمي وزارة government presidency الأمم المتحدة un news"),
        ("news", "news أخبار إخبارية breaking مباشر العربية الجزيرة bbc cnn sky reuters"),
        ("interview", "interview مقابلة حوار podcast بودكاست ضيف"),
        ("documentary", "documentary وثائقي وثائق تحقيق investigation"),
        ("educational", "explained شرح تعليمي محاضرة lecture academy أكاديمية"),
    )
    for channel_type, terms in patterns:
        if any(term in text for term in terms.split()):
            return channel_type
    return "independent"


def _filter_failures(item: Dict[str, Any], filters: Dict[str, Any], language_match: bool) -> List[str]:
    failures: List[str] = []
    duration = float(item.get("duration") or 0)
    published = _published_at(item)
    if filters["min_duration_seconds"] and (not duration or duration < filters["min_duration_seconds"]):
        failures.append("أقصر من المدة الدنيا")
    if filters["max_duration_seconds"] and (not duration or duration > filters["max_duration_seconds"]):
        failures.append("أطول من المدة القصوى")
    if filters["date_from"]:
        cutoff = datetime.strptime(filters["date_from"], "%Y-%m-%d").replace(tzinfo=timezone.utc)
        if not published or published < cutoff:
            failures.append("أقدم من تاريخ البداية")
    if filters["date_to"]:
        cutoff = datetime.strptime(filters["date_to"], "%Y-%m-%d").replace(tzinfo=timezone.utc) + timedelta(days=1)
        if not published or published >= cutoff:
            failures.append("أحدث من تاريخ النهاية")
    if not language_match:
        failures.append("اللغة غير مطابقة")
    body = f"{item.get('channel', '')} {item.get('title', '')} {item.get('description', '')[:2000]}".casefold()
    if filters["country"] and filters["country"].casefold() not in body:
        failures.append("البلد غير ظاهر في بيانات الفيديو")
    if filters["channel_type"] != "any" and item.get("channel_type") != filters["channel_type"]:
        failures.append("نوع القناة غير مطابق")
    if filters["min_views"] and float(item.get("view_count") or 0) < filters["min_views"]:
        failures.append("المشاهدات أقل من الحد")
    live_status = str(item.get("live_status") or "not_live").casefold()
    if filters["live_status"] == "live" and live_status not in {"is_live", "live"}:
        failures.append("ليس بثًا مباشرًا")
    elif filters["live_status"] == "upcoming" and live_status not in {"is_upcoming", "upcoming"}:
        failures.append("ليس بثًا قادمًا")
    elif filters["live_status"] == "not_live" and live_status in {"is_live", "live", "is_upcoming", "upcoming"}:
        failures.append("الفيديو بث مباشر أو قادم")
    return failures


def _score_candidate(item: Dict[str, Any], brief: ResearchBrief, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    filters = filters or _normalise_filters(None)
    body = f"{item.get('title', '')} {item.get('description', '')[:2500]}"
    topic_overlap = _overlap(brief.main_topic, body)
    query_overlap = max((_overlap(query, body) for query in item.get("matched_queries") or []), default=0.0)
    relevance = min(10.0, 2.5 + 12 * max(topic_overlap, query_overlap * 0.8))
    duration = float(item.get("duration") or 0)
    depth = min(10.0, 3 + math.log1p(duration / 60)) if duration else 3.0
    analysis_terms = "تحليل مقابلة نقاش وثائقي خبير analysis interview documentary discussion explained"
    discussion = min(10.0, depth * 0.55 + 5 * _overlap(analysis_terms, body))
    views = float(item.get("view_count") or 0)
    source = min(10.0, 4 + math.log10(max(1, views)) * 0.65 + (1 if item.get("channel_id") else 0))
    evidence_terms = "مصدر مصادر وثيقة تقرير بيانات دراسة evidence source report data study official"
    evidence_score = min(10.0, 2.0 + _overlap(evidence_terms, body) * 12)
    reliability = min(10.0, source * 0.72 + evidence_score * 0.28)
    published = _published_at(item)
    age_days = (datetime.now(timezone.utc) - published).days if published else 365
    freshness = max(0.0, 10 - math.log1p(max(0, age_days)) * 1.7)
    preferred_source = any(
        source.casefold() in str(item.get("channel") or "").casefold()
        for source in brief.preferred_sources if str(source).strip()
    )
    excluded_hit = any(
        term.casefold() in body.casefold()
        for term in brief.excluded_content if str(term).strip()
    )
    if "shorts" in {str(term).casefold() for term in brief.excluded_content} and duration and duration <= 70:
        excluded_hit = True
    item["channel_type"] = _infer_channel_type(item)
    language = str(item.get("language") or "").casefold()
    aliases = {"العربية": "ar", "عربي": "ar", "arabic": "ar", "الإنجليزية": "en", "انجليزي": "en", "english": "en"}
    requested_languages = list(brief.preferred_languages)
    if filters["language"] != "any":
        requested_languages = [filters["language"]]
    languages = {aliases.get(str(lang).casefold(), str(lang).casefold()[:2]) for lang in requested_languages}
    language_match = not languages or not language or any(language.startswith(lang) for lang in languages)
    filter_failures = _filter_failures(item, filters, language_match)
    if filters["min_reliability"] and reliability < filters["min_reliability"]:
        filter_failures.append("الموثوقية أقل من الحد")
    item.update({
        "relevance_score": round(relevance, 1),
        "discussion_strength": round(discussion, 1),
        "depth_score": round(depth, 1),
        "source_quality": round(source, 1),
        "reliability_score": round(reliability, 1),
        "evidence_score": round(evidence_score, 1),
        "freshness_score": round(freshness, 1),
        "novelty_score": 5.0,
        "sequence_value": 5.0,
        "filter_failures": filter_failures,
        "filters_matched": not filter_failures,
        "accepted": relevance >= 3.5 and bool(item.get("title")) and not excluded_hit and not filter_failures,
        "rejection_reason": (
            "محتوى مستبعد حسب طلب المستخدم" if excluded_hit else
            "، ".join(filter_failures) if filter_failures else
            None if relevance >= 3.5 else "صلة ضعيفة بموضوع البحث"
        ),
    })
    item["query_match_score"] = round(min(10.0, query_overlap * 10), 1)
    item["total_score"] = round(relevance * 0.3 + discussion * 0.18 + depth * 0.12 + reliability * 0.18 + freshness * 0.09 + item["query_match_score"] * 0.08 + evidence_score * 0.05 + (0.7 if preferred_source else 0), 2)
    return item


def _deduplicate(candidates: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    unique: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates:
        video_id = candidate.get("video_id")
        if not video_id:
            continue
        if video_id not in unique:
            unique[video_id] = candidate
        else:
            angles = set(unique[video_id].get("matched_angles") or [])
            angles.update(candidate.get("matched_angles") or [])
            unique[video_id]["matched_angles"] = sorted(angles)
            queries = set(unique[video_id].get("matched_queries") or [])
            queries.update(candidate.get("matched_queries") or [])
            unique[video_id]["matched_queries"] = sorted(queries)
    return list(unique.values())


def _balanced_discovery_order(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Round-robin strong candidates across research angles.

    A global top-N often over-represents one popular query. Balancing first by
    angle makes the later metadata comparison cover the whole research plan.
    """
    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for candidate in candidates:
        angle = str((candidate.get("matched_angles") or ["general"])[0])
        buckets.setdefault(angle, []).append(candidate)
    for bucket in buckets.values():
        bucket.sort(key=lambda item: item.get("discovery_score", 0), reverse=True)
    ordered: List[Dict[str, Any]] = []
    bucket_names = sorted(buckets, key=lambda name: buckets[name][0].get("discovery_score", 0), reverse=True)
    while bucket_names:
        next_names = []
        for name in bucket_names:
            if buckets[name]:
                ordered.append(buckets[name].pop(0))
            if buckets[name]:
                next_names.append(name)
        bucket_names = next_names
    return ordered


def _deduplicate_reuploads(candidates: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Collapse likely reuploads while retaining the strongest/original-looking item."""
    groups: List[List[Dict[str, Any]]] = []
    for candidate in candidates:
        title_tokens = _tokens(candidate.get("title", ""))
        group = next((g for g in groups if title_tokens and len(title_tokens & _tokens(g[0].get("title", ""))) / max(1, len(title_tokens | _tokens(g[0].get("title", "")))) >= 0.86), None)
        if group is None:
            groups.append([candidate])
        else:
            group.append(candidate)
    unique = []
    for group in groups:
        best = max(group, key=lambda item: (float(item.get("view_count") or 0), bool(item.get("channel_id")), float(item.get("total_score") or 0)))
        best["possible_reuploads_removed"] = len(group) - 1
        unique.append(best)
    return unique


async def _map_limited(func: Callable[[str], Any], ids: Sequence[str], concurrency: int = 4) -> List[Any]:
    semaphore = asyncio.Semaphore(concurrency)

    async def one(video_id: str) -> Any:
        async with semaphore:
            try:
                return await asyncio.to_thread(func, video_id)
            except Exception as exc:
                logger.info("YouTube metadata skipped for %s: %s", video_id, exc)
                return None

    return await asyncio.gather(*(one(video_id) for video_id in ids))


async def _search_plan_queries(
    plan: Sequence[Dict[str, Any]],
    search_fn: Callable[[str, int], List[Dict[str, Any]]],
    per_query: int,
) -> List[Any]:
    semaphore = asyncio.Semaphore(3)

    async def one(item: Dict[str, Any]) -> Any:
        async with semaphore:
            try:
                return await asyncio.to_thread(search_fn, item["query"], per_query)
            except Exception as exc:
                return exc

    return await asyncio.gather(*(one(item) for item in plan))


def _select_diverse(items: Sequence[Dict[str, Any]], maximum: int) -> List[Dict[str, Any]]:
    selected, remaining = [], list(items)
    channels: Dict[str, int] = {}
    angles: Dict[str, int] = {}
    while remaining and len(selected) < maximum:
        def adjusted(item: Dict[str, Any]) -> float:
            channel = str(item.get("channel") or "").casefold()
            angle = str((item.get("matched_angles") or ["general"])[0])
            return float(item.get("selection_score") or item.get("total_score") or 0) - channels.get(channel, 0) * 1.8 - angles.get(angle, 0) * 0.7

        best = max(remaining, key=adjusted)
        remaining.remove(best)
        channel = str(best.get("channel") or "").casefold()
        angle = str((best.get("matched_angles") or ["general"])[0])
        channels[channel] = channels.get(channel, 0) + 1
        angles[angle] = angles.get(angle, 0) + 1
        best["novelty_score"] = round(max(1.0, 10 - (channels[channel] - 1) * 3 - (angles[angle] - 1)), 1)
        selected.append(best)
    return selected


def _selection_pool(
    enriched: Sequence[Dict[str, Any]],
    dated: Sequence[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """Prefer strict matches, then expand constraints without returning too few.

    Explicitly excluded content remains excluded. Date, language, and the soft
    relevance threshold may be relaxed, but the relaxation is visible in the
    final report on every affected video.
    """
    dated_ids = {item["video_id"] for item in dated}
    tiers: Dict[str, List[Dict[str, Any]]] = {
        "strict_match": [],
        "expanded_date": [],
        "best_available": [],
    }
    for item in enriched:
        reason = str(item.get("rejection_reason") or "")
        if reason == "محتوى مستبعد حسب طلب المستخدم":
            continue
        candidate = dict(item)
        if candidate["video_id"] in dated_ids and candidate.get("accepted"):
            candidate["selection_tier"] = "strict_match"
            candidate["selection_note"] = "مطابق للموضوع والقيود المطلوبة."
            tier_bonus = 100
        elif candidate.get("accepted"):
            candidate["selection_tier"] = "expanded_date"
            candidate["selection_note"] = "اختيار قوي مطابق للموضوع بعد توسيع النطاق الزمني."
            tier_bonus = 50
        else:
            candidate["selection_tier"] = "best_available"
            candidate["selection_note"] = "أفضل خيار موثق متاح لإكمال السلسلة بعد تخفيف شرط الصلة أو اللغة."
            candidate["total_score"] = round(float(candidate.get("total_score") or 0) - 1.25, 2)
            tier_bonus = 0
        candidate["selection_score"] = round(
            tier_bonus + float(candidate.get("total_score") or 0) + float(candidate.get("relevance_score") or 0) * 0.4,
            2,
        )
        tiers[candidate["selection_tier"]].append(candidate)

    ordered: List[Dict[str, Any]] = []
    for tier in ("strict_match", "expanded_date", "best_available"):
        ordered.extend(sorted(tiers[tier], key=lambda item: item.get("total_score", 0), reverse=True))
    return ordered, {tier: len(items) for tier, items in tiers.items()}


async def _enrich_transcripts(
    items: List[Dict[str, Any]],
    transcript_fetcher: Optional[Callable[[str], Dict[str, Any]]],
    limit: int,
) -> Dict[str, int]:
    if not transcript_fetcher or not items or limit <= 0:
        return {"attempted": 0, "available": 0}
    semaphore = asyncio.Semaphore(3)
    targets = items[:limit]

    async def fetch(item: Dict[str, Any]) -> None:
        async with semaphore:
            try:
                data = await asyncio.to_thread(transcript_fetcher, item["webpage_url"])
                transcript = re.sub(r"\n{3,}", "\n\n", str((data or {}).get("txt") or "")).strip()
                if transcript:
                    item["transcript"] = transcript
                    item["transcript_available"] = True
                    item["transcript_chars"] = len(transcript)
                    item["transcript_complete"] = True
                    topical = _overlap(item.get("title", ""), transcript[:12000])
                    quality = min(10.0, 2.5 + math.log1p(len(transcript) / 1000) * 1.5 + topical * 3)
                    item["transcript_quality"] = round(quality, 1)
                    item["content_evidence_score"] = round(min(10.0, quality * 0.65 + float(item.get("evidence_score") or 0) * 0.35), 1)
                    item["total_score"] = round(float(item.get("total_score") or 0) + quality * 0.3, 2)
                    item["selection_score"] = round(float(item.get("selection_score") or 0) + quality * 0.65, 2)
                else:
                    item["transcript_available"] = False
                    item["transcript_error"] = str((data or {}).get("error") or "لا تتوفر ترجمة لهذا الفيديو")[:500]
                    item["transcript_quality"] = 0.0
            except Exception as exc:
                item["transcript_available"] = False
                item["transcript_error"] = str(exc)[:500]
                item["transcript_quality"] = 0.0

    await asyncio.gather(*(fetch(item) for item in targets))
    return {"attempted": len(targets), "available": len([item for item in targets if item.get("transcript_available")])}


def _fallback_stage(item: Dict[str, Any]) -> Tuple[int, str]:
    angle = f"{item.get('angle', '')} {' '.join(item.get('matched_angles') or [])}".casefold()
    stages = (
        (0, "الخلفية والبدايات", "overview background history origins شرح خلفية تاريخ جذور"),
        (1, "بداية الحدث", "event beginning بداية نشأة"),
        (2, "الأدلة والوقائع", "evidence facts أدلة حقائق وثائق"),
        (3, "التحليل والتفسير", "analysis expert تحليل خبير"),
        (4, "النقاش والرأي المقابل", "opposing debate مقابلة نقاش معارض"),
        (5, "التطورات الراهنة", "latest current update حديث تطورات راهن"),
        (6, "النتائج والسيناريوهات", "future scenario مستقبل سيناريو نتائج"),
    )
    for rank, label, terms in stages:
        if any(term in angle for term in terms.split()):
            return rank, label
    return 3, "التحليل والتفسير"


async def _analyze_finalists(items: List[Dict[str, Any]], brief: ResearchBrief, api_key: str) -> None:
    compact = [{
        "video_id": item["video_id"], "title": item["title"], "channel": item["channel"],
        "description": item.get("description", "")[:1800], "angle": (item.get("matched_angles") or ["general"])[0],
        "published": item.get("upload_date", ""), "duration": item.get("duration"),
        "transcript_excerpt": item.get("transcript", "")[:6000],
    } for item in items]
    ai = await _openai_json(
        "أنت محلل فيديو دقيق. لا تدّع مشاهدة محتوى غير موجود في البيانات. لا تختلق ضيوفًا أو اقتباسات. أجب JSON فقط.",
        "رتّب الفيديوهات كسلسلة نقاش تعليمية تبدأ بالخلفية والجذور، ثم الوقائع والأدلة، ثم التحليل والرأي المقابل، وتنتهي بآخر التطورات والسيناريوهات. "
        "لكل video_id اكتب: summary من سطرين، main_arguments، discussion_strength من 0 إلى 10، adds_to_previous، angle، contradictions، "
        "sequence_position، narrative_stage، ordering_reason يشرح بدقة سبب موضعه، strengths قائمة نقاط القوة، weaknesses قائمة نقاط الضعف، "
        "event_claims قائمة من {date بصيغة YYYY أو YYYY-MM أو YYYY-MM-DD فقط إن كان مذكورًا، claim، certainty، evidence}. "
        "اعتمد على النص المرفق، وإن لم يتوفر فصرّح بأن التحليل مبني على البيانات الوصفية ولا تخترع تاريخًا. "
        "أعد {\"videos\":[...]}.\n"
        f"الموضوع: {brief.main_topic}\nالمرشحون: {json.dumps(compact, ensure_ascii=False)}",
        api_key,
        max_tokens=5000,
    )
    analyses = {str(v.get("video_id")): v for v in (ai or {}).get("videos", []) if isinstance(v, dict)} if isinstance(ai, dict) else {}
    for index, item in enumerate(items):
        analysis = analyses.get(item["video_id"], {})
        description = re.sub(r"\s+", " ", item.get("description") or "").strip()
        item["summary"] = str(analysis.get("summary") or description[:320] or "يعالج الفيديو الموضوع من الزاوية الموضحة في عنوانه وبياناته المتاحة.")
        item["main_arguments"] = analysis.get("main_arguments") if isinstance(analysis.get("main_arguments"), list) else []
        item["contradictions"] = analysis.get("contradictions") if isinstance(analysis.get("contradictions"), list) else []
        item["angle"] = str(analysis.get("angle") or (item.get("matched_angles") or ["general"])[0])
        item["adds_to_previous"] = str(analysis.get("adds_to_previous") or ("يمهد لفهم القضية." if index == 0 else "يضيف زاوية مختلفة إلى ما سبق."))
        fallback_rank, fallback_label = _fallback_stage(item)
        item["narrative_stage"] = str(analysis.get("narrative_stage") or fallback_label)
        item["ordering_reason"] = str(analysis.get("ordering_reason") or (
            "وُضع أولًا لأنه يقدم المدخل والسياق اللازمين لفهم بقية السلسلة."
            if index == 0 else "وُضع هنا لأنه يبني على السياق السابق ويضيف طبقة جديدة إلى النقاش."
        ))
        item["strengths"] = analysis.get("strengths") if isinstance(analysis.get("strengths"), list) else [
            "صلة قوية بموضوع البحث",
            "بيانات الفيديو والرابط تحققت بنجاح",
        ]
        item["weaknesses"] = analysis.get("weaknesses") if isinstance(analysis.get("weaknesses"), list) else ([
            "لا تتوفر ترجمة قابلة للاستخراج؛ التحليل مبني على العنوان والوصف."
        ] if not item.get("transcript_available") else ["قد يعرض زاوية واحدة ويحتاج إلى مقارنته ببقية السلسلة."])
        claims = analysis.get("event_claims")
        item["event_claims"] = [claim for claim in claims if isinstance(claim, dict)] if isinstance(claims, list) else []
        try:
            item["sequence_position"] = max(1, int(analysis.get("sequence_position", fallback_rank * 10 + index + 1)))
        except (TypeError, ValueError):
            item["sequence_position"] = fallback_rank * 10 + index + 1
        if analysis.get("discussion_strength") is not None:
            try:
                item["discussion_strength"] = max(0, min(10, round(float(analysis["discussion_strength"]), 1)))
            except (TypeError, ValueError):
                pass
    items.sort(key=lambda item: item.get("sequence_position", 999))
    for index, item in enumerate(items, start=1):
        item["sequence_position"] = index
        item["sequence_value"] = round(max(1.0, 10.0 - (index - 1) * 0.3), 1)


def _build_event_timeline(items: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    timeline: List[Dict[str, Any]] = []
    for item in items:
        for claim in item.get("event_claims") or []:
            date = str(claim.get("date") or "").strip()
            if date and not re.fullmatch(r"\d{4}(?:-\d{2})?(?:-\d{2})?", date):
                date = ""
            statement = str(claim.get("claim") or "").strip()
            if not statement:
                continue
            timeline.append({
                "date": date or "غير مؤرخ",
                "claim": statement,
                "certainty": str(claim.get("certainty") or "غير محدد"),
                "evidence": str(claim.get("evidence") or "مستخرج من تحليل الفيديو"),
                "video_id": item["video_id"],
                "video_title": item["title"],
                "sequence_position": item.get("sequence_position"),
                "webpage_url": item.get("webpage_url"),
            })
        if not item.get("event_claims"):
            published = _published_at(item)
            timeline.append({
                "date": published.strftime("%Y-%m-%d") if published else "غير مؤرخ",
                "claim": item.get("summary") or item.get("title"),
                "certainty": "بيانات وصفية",
                "evidence": "تاريخ نشر الفيديو وملخصه؛ لا يمثل بالضرورة تاريخ وقوع الحدث.",
                "video_id": item["video_id"],
                "video_title": item["title"],
                "sequence_position": item.get("sequence_position"),
                "webpage_url": item.get("webpage_url"),
            })

    def timeline_key(event: Dict[str, Any]) -> Tuple[int, str, int]:
        date = str(event.get("date") or "")
        return (1 if date == "غير مؤرخ" else 0, date, int(event.get("sequence_position") or 999))

    timeline.sort(key=timeline_key)
    return {
        "items": timeline,
        "coverage_note": "الخريطة تميّز بين تاريخ الحدث المستخرج من النص وتاريخ نشر الفيديو، ولا تنسب تاريخًا غير موجود في المصدر.",
    }


def _latest_web_development(topic: str) -> Optional[Dict[str, str]]:
    try:
        url = f"https://news.google.com/rss/search?q={quote_plus(topic)}&hl=ar&gl=SA&ceid=SA:ar"
        response = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "xml")
        item = soup.find("item")
        if not item:
            return None
        source = item.find("source")
        return {
            "title": item.title.get_text(strip=True) if item.title else "",
            "url": item.link.get_text(strip=True) if item.link else "",
            "source": source.get_text(strip=True) if source else "Google News",
            "published": item.pubDate.get_text(strip=True) if item.pubDate else "",
        }
    except Exception as exc:
        logger.info("Latest-development lookup skipped: %s", exc)
        return None


def _search_terms(plan: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
    arabic, english = [], []
    for item in plan:
        query = str(item.get("query") or "")
        target = arabic if re.search(r"[\u0600-\u06ff]", query) else english
        if query and query not in target:
            target.append(query)
    return {"arabic": arabic[:5], "english": english[:5]}


async def research_youtube(
    user_prompt: str,
    *,
    api_key: Optional[str] = None,
    search_fn: Callable[[str, int], List[Dict[str, Any]]] = search_youtube,
    metadata_fn: Callable[[str], Optional[Dict[str, Any]]] = verify_video,
    transcript_fetcher: Optional[Callable[[str], Dict[str, Any]]] = None,
    exclude_video_ids: Sequence[str] = (),
    filters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Run one complete on-demand research session and return a final report."""
    if not user_prompt or len(user_prompt.strip()) < 8:
        raise ValueError("يرجى إدخال موضوع بحث واضح ومفصل.")
    api_key = api_key if api_key is not None else os.environ.get("OPENAI_API_KEY", "")
    started = datetime.now(timezone.utc)
    applied_filters = _normalise_filters(filters)
    brief = await analyze_prompt(user_prompt, api_key)
    plan = await build_search_plan(brief, api_key)
    query_context = " ".join(part for part in (
        applied_filters["country"],
        "عربي" if applied_filters["language"] == "ar" else "English" if applied_filters["language"] == "en" else "",
    ) if part)
    if query_context:
        plan = [{**item, "query": f"{item['query']} {query_context}".strip()} for item in plan]

    per_query = max(12, min(30, math.ceil(160 / max(1, len(plan)))))
    search_results = await _search_plan_queries(plan, search_fn, per_query)
    discovered: List[Dict[str, Any]] = []
    for query, result in zip(plan, search_results):
        if isinstance(result, Exception):
            logger.info("YouTube query failed (%s): %s", query["query"], result)
            continue
        for candidate in result:
            candidate = dict(candidate)
            candidate["matched_queries"] = [query["query"]]
            candidate["matched_angles"] = [query["angle"]]
            candidate["query_priority"] = query["priority"]
            discovered.append(candidate)
    unique = _deduplicate(discovered)
    excluded_ids = {str(video_id).strip() for video_id in exclude_video_ids if str(video_id).strip()}
    excluded_previous_count = len([item for item in unique if item.get("video_id") in excluded_ids])
    if excluded_ids:
        unique = [item for item in unique if item.get("video_id") not in excluded_ids]
    if not unique:
        raise RuntimeError("لم يعثر YouTube على نتائج جديدة مختلفة عن جلسة البحث السابقة لهذا الطلب.")

    for item in unique:
        item["discovery_score"] = _overlap(brief.main_topic, item.get("title", "")) * 10 + float(item.get("query_priority") or 0)
    ranked_discovery = _balanced_discovery_order(unique)
    # If strict matches remain scarce, inspect a much wider pool before
    # relaxing constraints. This favors the strongest videos across all query
    # angles instead of merely filling the requested count from the first page.
    deep_limit = min(len(ranked_discovery), max(80, brief.desired_video_count["max"] * 8))
    enriched: List[Dict[str, Any]] = []
    checked = 0
    # Inspect in batches. Continue beyond the first twenty when verification or
    # explicit exclusions leave too few candidates for the requested sequence.
    while checked < deep_limit:
        batch = ranked_discovery[checked:min(checked + 20, deep_limit)]
        metadata = await _map_limited(metadata_fn, [item["video_id"] for item in batch])
        metadata_by_id = {item["video_id"]: item for item in metadata if item}
        for item in batch:
            full = metadata_by_id.get(item["video_id"])
            if not full:
                continue
            full["matched_queries"] = item.get("matched_queries", [])
            full["matched_angles"] = item.get("matched_angles", [])
            full["discovery_score"] = item.get("discovery_score", 0)
            enriched.append(_score_candidate(full, brief, applied_filters))
        checked += len(batch)
        usable = [item for item in enriched if item.get("rejection_reason") != "محتوى مستبعد حسب طلب المستخدم"]
        snapshot = _deduplicate_reuploads(enriched)
        snapshot_dated, _ = _date_filter(snapshot, brief.date_policy, brief.desired_video_count["min"])
        strict_count = len([item for item in (snapshot_dated if brief.date_policy else snapshot) if item.get("accepted")])
        if checked >= 40 and strict_count >= brief.desired_video_count["min"]:
            break
        if checked >= deep_limit and len(usable) >= MIN_FINAL_VIDEOS:
            break

    enriched = _deduplicate_reuploads(enriched)
    dated, applied_date_policy = _date_filter(enriched, brief.date_policy, brief.desired_video_count["min"])
    eligible = [item for item in dated if item["accepted"]]
    if not brief.date_policy:
        eligible = [item for item in enriched if item["accepted"]]
    ranked, tier_counts = _selection_pool(enriched, dated if brief.date_policy else enriched)
    finalist_pool = ranked[: max(brief.desired_video_count["max"] * 4, 28)]
    default_probe_count = min(20, max(14, brief.desired_video_count["max"] * 2))
    try:
        configured_probe_count = int(os.environ.get("YOUTUBE_RESEARCH_TRANSCRIPTS", str(default_probe_count)))
    except ValueError:
        configured_probe_count = default_probe_count
    probe_count = min(len(finalist_pool), max(default_probe_count, configured_probe_count))
    transcript_stats = await _enrich_transcripts(
        finalist_pool,
        transcript_fetcher if applied_filters["require_transcript"] else None,
        probe_count,
    )
    finalist_pool.sort(key=lambda item: item.get("selection_score", 0), reverse=True)
    selected = _select_diverse(finalist_pool, brief.desired_video_count["max"])

    await _analyze_finalists(selected, brief, api_key)
    timeline = _build_event_timeline(selected)
    contradictions = []
    for item in selected:
        for conflict in item.get("contradictions") or []:
            contradictions.append({"video_id": item["video_id"], "conflict": conflict})

    current_topic = bool(re.search(r"خبر|حديث|جديد|حالي|سياسي|عسكري|اقتصاد|news|latest|current", user_prompt, re.I))
    latest = await asyncio.to_thread(_latest_web_development, brief.main_topic) if current_topic else None
    finished = datetime.now(timezone.utc)
    return {
        "topic": brief.main_topic,
        "brief": brief.as_dict(),
        "filters": applied_filters,
        "search_plan": plan,
        "stats": {
            "queries": len(plan),
            "discovered": len(discovered),
            "unique": len(unique),
            "excluded_from_previous_search": excluded_previous_count,
            "metadata_checked": len(enriched),
            "discovery_pool_examined": checked,
            "eligible": len(eligible),
            "selected": len(selected),
            "selection_tiers": tier_counts,
            "selection_strategy": "strict_then_expanded_best_across_angles",
            "transcripts_attempted": transcript_stats["attempted"],
            "transcripts_available": transcript_stats["available"],
            "date_policy_applied": applied_date_policy,
            "duration_seconds": round((finished - started).total_seconds(), 2),
        },
        "videos": selected,
        "timeline": timeline,
        "contradictions": contradictions,
        "latest_development": latest,
        "search_terms": _search_terms(plan),
        "warnings": (
            ([f"تم توسيع بعض القيود لاختيار أفضل {len(selected)} فيديوهات موثقة بدل الاكتفاء بالنتائج المطابقة حرفيًا."]
             if any(item.get("selection_tier") != "strict_match" for item in selected) else [])
            + ([f"لم يتوفر سوى {len(selected)} فيديوهات قابلة للتحقق، رغم فحص نتائج إضافية؛ الحد المستهدف {brief.desired_video_count['min']}." ]
               if len(selected) < brief.desired_video_count["min"] else [])
            + ([f"تعذر استخراج ترجمة لبعض المرشحين: نجح {transcript_stats['available']} من {transcript_stats['attempted']}. تم توضيح ذلك داخل نقاط ضعف كل فيديو."]
               if transcript_stats["attempted"] and transcript_stats["available"] < transcript_stats["attempted"] else [])
        ),
        "generated_at": finished.isoformat(),
    }
