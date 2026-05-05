import json
import re
import sqlite3
import traceback
from datetime import datetime
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pandas as pd
import requests
import streamlit as st
from youtube_transcript_api import YouTubeTranscriptApi

DB_PATH = Path("eafi_benchmark.db")
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}

INTERPRETATION_GOALS = [
    "NotebookLM식 원본 해석",
    "카드뉴스 재가공용 해석",
    "사건/갈등 구조 해석",
    "벤치마크 구조 추출",
    "바이럴 후킹 구조 분석",
    "교육형 요약 재료화",
    "브랜드/eaf 전환 관점 해석",
]
SOURCE_DOMAINS = ["자동 감지", "영상/마케팅", "시장/투자", "사건/논쟁", "트렌드/이슈", "교육/노하우", "라이프스타일", "기술/AI", "직접 입력"]
VIEWPOINTS = ["콘텐츠 기획자", "브랜드 마케터", "일반 시청자", "잠재 고객", "시장 분석가", "교육자", "바이럴 편집자"]
DETAIL_LEVELS = ["핵심만", "표준", "디테일", "매우 디테일"]
FIDELITY_LEVELS = ["원문 충실", "원문+해석 균형", "재가공 중심"]
INFERENCE_LEVELS = ["보수적", "중간", "공격적"]

BAD_TITLES = [
    "직접 입력한 영상 스크립트",
    "manual input",
    "youtube 영상",
    "untitled",
    "직접 입력",
]

KOREAN_STOPWORDS = set([
    "그리고", "그런데", "그래서", "하지만", "저는", "우리는", "여러분", "이거", "저거", "그거",
    "정말", "진짜", "약간", "되게", "너무", "오늘", "영상", "이번", "계속", "바로", "이제",
    "것", "수", "때", "좀", "더", "왜", "어떻게", "이런", "그런", "저런", "합니다", "있습니다",
    "있고", "있는", "하면", "해서", "하는", "제가", "우리", "여기", "거죠", "거예요", "겁니다",
    "아주", "하나", "같은", "정도", "사람", "사람들", "부분", "대한", "통해", "관련", "모든",
])

DOMAIN_HINTS = {
    "시장/투자": ["코인", "비트코인", "주식", "시장", "투자", "가격", "섹터", "2차전지", "배터리", "급등", "하락"],
    "영상/마케팅": ["영상", "촬영", "편집", "마케팅", "브랜드", "광고", "콘텐츠", "유튜브", "전환", "CTA"],
    "기술/AI": ["ai", "인공지능", "기술", "개발", "앱", "서비스", "툴", "자동화", "모델"],
    "교육/노하우": ["방법", "노하우", "배우", "강의", "튜토리얼", "체크리스트", "공부", "설명"],
    "사건/논쟁": ["노조", "회사", "직원", "시민", "공장", "사건", "논란", "갈등", "반발", "요구", "법정", "기증", "주차장"],
    "트렌드/이슈": ["요즘", "논란", "이슈", "트렌드", "화제", "사람들", "커뮤니티", "밈"],
}

EVENT_TOKENS = ["처음", "시작", "어느 날", "그런데", "하지만", "이후", "결국", "나중에", "현재", "당시", "그때", "먼저", "마침내"]
CONFLICT_TOKENS = ["노조", "회사", "직원", "시민", "반발", "갈등", "요구", "조건", "상종", "법정", "문제", "위험", "리스크", "하지만", "반대로"]
EVIDENCE_TOKENS = ["근거", "수치", "%", "데이터", "조사", "연구", "사례", "예를", "보면", "기증", "주차장", "법정", "요구", "조건"]
CLAIM_TOKENS = ["핵심", "문제", "이유", "결국", "사실", "중요", "다릅니다", "아닙니다", "하지만", "놓치", "실수", "반대로"]


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_column(cur, table_name, column_name, column_type):
    cur.execute(f"PRAGMA table_info({table_name})")
    existing = [row[1] for row in cur.fetchall()]
    if column_name not in existing:
        cur.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")


def init_tables():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS youtube_video_analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT,
            url TEXT,
            title TEXT,
            channel_name TEXT,
            transcript TEXT,
            summary TEXT,
            hook_point TEXT,
            structure_note TEXT,
            visual_note TEXT,
            eafi_application TEXT,
            keywords TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS benchmark_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            channel_name TEXT NOT NULL,
            url TEXT,
            category TEXT,
            reference_reason TEXT,
            priority TEXT,
            notes TEXT,
            created_at TEXT NOT NULL
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS content_references (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            channel_id INTEGER,
            title TEXT NOT NULL,
            url TEXT,
            hook_point TEXT,
            structure_note TEXT,
            visual_note TEXT,
            eafi_application TEXT,
            lead_potential_score INTEGER DEFAULT 3,
            visual_score INTEGER DEFAULT 3,
            hook_score INTEGER DEFAULT 3,
            seo_score INTEGER DEFAULT 3,
            conversion_score INTEGER DEFAULT 3,
            total_score INTEGER DEFAULT 15,
            status TEXT DEFAULT '수집',
            created_at TEXT NOT NULL
        )
    """)

    extra_columns = {
        "key_claim": "TEXT",
        "source_type": "TEXT",
        "analysis_memo": "TEXT",
        "interpretation_conditions": "TEXT",
        "source_domain": "TEXT",
        "source_kind": "TEXT",
        "interpretation_goal": "TEXT",
        "viewpoint": "TEXT",
        "detail_level": "TEXT",
        "fidelity_level": "TEXT",
        "inference_level": "TEXT",
        "clean_transcript": "TEXT",
        "source_chunks": "TEXT",
        "source_index": "TEXT",
        "original_topic": "TEXT",
        "primary_claim": "TEXT",
        "sub_claims": "TEXT",
        "evidence_points": "TEXT",
        "context_background": "TEXT",
        "event_timeline": "TEXT",
        "actor_map": "TEXT",
        "cause_effect_chain": "TEXT",
        "audience_pain": "TEXT",
        "hidden_assumption": "TEXT",
        "contradiction_or_tension": "TEXT",
        "emotional_trigger": "TEXT",
        "viral_hook_logic": "TEXT",
        "narrative_structure": "TEXT",
        "reusable_structure": "TEXT",
        "risk_notes": "TEXT",
        "cardnews_seed": "TEXT",
        "source_grounded_qa": "TEXT",
        "interpretation_report": "TEXT",
    }
    for col, col_type in extra_columns.items():
        ensure_column(cur, "youtube_video_analyses", col, col_type)

    conn.commit()
    conn.close()


def clean(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def shorten(text, max_len=180):
    text = re.sub(r"\s+", " ", clean(text)).strip()
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def compact_lines(text):
    return "\n".join([line.strip() for line in clean(text).splitlines() if line.strip()])


def is_bad_title(title):
    lowered = clean(title).lower()
    return not lowered or any(bad.lower() in lowered for bad in BAD_TITLES)


def normalize_source_text(text):
    text = clean(text)
    text = re.sub(r"(?im)^\s*(title|url|source|link|영상 제목|제목)\s*[:：]\s*.*$", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\[[0-9:.\-\s]+\]", " ", text)
    text = re.sub(r"\([0-9:.\-\s]+\)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def get_video_id(url):
    url = clean(url)
    parsed = urlparse(url)
    host = parsed.netloc.lower().replace("www.", "")
    if host == "youtu.be":
        return parsed.path.strip("/").split("/")[0]
    if "youtube.com" in host:
        qs = parse_qs(parsed.query)
        if qs.get("v"):
            return qs["v"][0]
        match = re.search(r"/(shorts|embed|live)/([^/?#]+)", parsed.path)
        if match:
            return match.group(2)
    if re.match(r"^[a-zA-Z0-9_-]{11}$", url):
        return url
    return ""


def fetch_oembed(url):
    try:
        res = requests.get(
            "https://www.youtube.com/oembed",
            params={"url": url, "format": "json"},
            headers=HEADERS,
            timeout=15,
        )
        res.raise_for_status()
        data = res.json()
        return clean(data.get("title"), "YouTube 영상"), clean(data.get("author_name"), "YouTube")
    except Exception:
        return "YouTube 영상", "YouTube"


def list_available_transcripts(video_id):
    ytt_api = YouTubeTranscriptApi()
    transcript_list = ytt_api.list(video_id)
    rows = []
    for transcript in transcript_list:
        rows.append({
            "language": getattr(transcript, "language", ""),
            "language_code": getattr(transcript, "language_code", ""),
            "is_generated": getattr(transcript, "is_generated", ""),
            "is_translatable": getattr(transcript, "is_translatable", ""),
        })
    return rows


def fetched_transcript_to_text(fetched):
    rows = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else fetched
    parts = []
    for row in rows:
        if isinstance(row, dict):
            text = row.get("text", "")
        else:
            text = getattr(row, "text", "")
        text = clean(text).replace("\n", " ")
        if text:
            parts.append(text)
    return re.sub(r"\s+", " ", " ".join(parts)).strip()


def fetch_transcript(video_id, languages):
    languages = languages or ["ko", "en"]
    ytt_api = YouTubeTranscriptApi()
    debug = {"method": "", "available_transcripts": [], "error_stage": "", "error_message": ""}

    try:
        debug["method"] = "YouTubeTranscriptApi().fetch(video_id, languages=...)"
        fetched = ytt_api.fetch(video_id, languages=languages)
        text = fetched_transcript_to_text(fetched)
        if text:
            return text, debug
    except Exception as first_error:
        debug["error_stage"] = "direct_fetch_failed"
        debug["error_message"] = repr(first_error)

    try:
        debug["method"] = "YouTubeTranscriptApi().list(video_id) fallback"
        transcript_list = ytt_api.list(video_id)
        debug["available_transcripts"] = [
            {
                "language": getattr(t, "language", ""),
                "language_code": getattr(t, "language_code", ""),
                "is_generated": getattr(t, "is_generated", ""),
                "is_translatable": getattr(t, "is_translatable", ""),
            }
            for t in transcript_list
        ]
        transcript = None
        try:
            transcript = transcript_list.find_transcript(languages)
        except Exception:
            pass
        if transcript is None:
            try:
                transcript = transcript_list.find_generated_transcript(languages)
            except Exception:
                pass
        if transcript is None:
            available_codes = [item["language_code"] for item in debug["available_transcripts"] if item.get("language_code")]
            if not available_codes:
                raise ValueError("사용 가능한 자막 목록이 비어 있습니다.")
            transcript = transcript_list.find_transcript([available_codes[0]])
        text = fetched_transcript_to_text(transcript.fetch())
        if not text:
            raise ValueError("자막 객체는 가져왔지만 text 필드가 비어 있습니다.")
        return text, debug
    except Exception as fallback_error:
        debug["error_stage"] = "fallback_failed"
        debug["error_message"] = repr(fallback_error)
        raise


def split_sentences(text):
    text = normalize_source_text(text)
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=다)\s+|(?<=요)\s+|(?<=죠)\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 10]


def extract_keywords(text, topn=20):
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", normalize_source_text(text))
    freq = {}
    for word in words:
        w = word.lower().strip()
        if w in KOREAN_STOPWORDS or len(w) < 2:
            continue
        if re.match(r"^[0-9]+$", w):
            continue
        freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:topn]]


def score_sentence(sentence, keywords, index, tokens=None):
    tokens = tokens or []
    score = sum(1 for kw in keywords if kw in sentence.lower())
    score += 4 if any(token in sentence for token in tokens) else 0
    score += 3 if any(token in sentence for token in CLAIM_TOKENS) else 0
    score += 2 if any(token in sentence for token in CONFLICT_TOKENS) else 0
    score += max(0, 2.2 - index * 0.018)
    return score


def pick_sentences(text, keywords, limit=10, tokens=None, exclude_opening_background=False):
    sentences = split_sentences(text)
    scored = []
    for idx, sentence in enumerate(sentences):
        if exclude_opening_background and idx < 2 and not any(t in sentence for t in CLAIM_TOKENS + CONFLICT_TOKENS):
            continue
        scored.append((score_sentence(sentence, keywords, idx, tokens), sentence))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for score, s in scored[:limit] if score > 0] or sentences[:limit]


def build_chunks(text, max_chars=750):
    sentences = split_sentences(text)
    chunks = []
    current = []
    size = 0
    chunk_id = 1
    for sentence in sentences:
        if size + len(sentence) > max_chars and current:
            joined = " ".join(current)
            chunks.append({"id": f"S{chunk_id}", "text": joined})
            chunk_id += 1
            current = []
            size = 0
        current.append(sentence)
        size += len(sentence)
    if current:
        chunks.append({"id": f"S{chunk_id}", "text": " ".join(current)})
    return chunks


def cite_sentence(sentence, chunks):
    for chunk in chunks:
        if sentence[:30] and sentence[:30] in chunk["text"]:
            return f"{shorten(sentence, 170)} [{chunk['id']}]"
    return shorten(sentence, 170)


def cite_list(sentences, chunks, limit=5):
    return [cite_sentence(s, chunks) for s in sentences[:limit] if clean(s)]


def detect_domain(title, transcript, selected):
    if selected not in ["자동 감지", "직접 입력"]:
        return selected
    text = f"{title} {transcript[:2500]}".lower()
    scores = {}
    for domain, hints in DOMAIN_HINTS.items():
        scores[domain] = sum(1 for hint in hints if hint.lower() in text)
    top = max(scores.items(), key=lambda x: x[1])
    return top[0] if top[1] > 0 else "트렌드/이슈"


def detect_source_kind(domain, transcript):
    text = transcript[:4000]
    if domain == "사건/논쟁" or sum(1 for t in CONFLICT_TOKENS if t in text) >= 3:
        return "사건형"
    if any(t in text for t in ["방법", "단계", "따라", "먼저", "체크"]):
        return "튜토리얼/노하우형"
    if any(t in text for t in ["비교", "장점", "단점", "후기", "리뷰"]):
        return "리뷰/비교형"
    if domain == "시장/투자":
        return "시장분석형"
    return "이슈해설형"


def find_sentences_with(text, tokens, limit=5):
    sentences = split_sentences(text)
    picked = []
    for sentence in sentences:
        if any(token in sentence for token in tokens):
            picked.append(sentence)
        if len(picked) >= limit:
            break
    return picked


def infer_original_topic(title, keywords, domain, source_kind, transcript):
    title = clean(title)
    if not is_bad_title(title):
        return shorten(title, 90)
    conflict_keywords = [kw for kw in keywords if kw not in ["아름다운", "하나", "정말", "이야기"]]
    if source_kind == "사건형" and conflict_keywords:
        return f"{', '.join(conflict_keywords[:4])}을 둘러싼 사건과 갈등"
    if keywords:
        return f"{', '.join(keywords[:4])} 중심의 {domain} 콘텐츠"
    return f"{domain} 원본 콘텐츠"


def make_actor_map(transcript, chunks):
    actor_candidates = ["회사", "직원", "노조", "시민", "안양시", "공장", "대표", "고객", "정부", "투자자", "브랜드", "제작자", "소비자"]
    result = []
    for actor in actor_candidates:
        sentences = find_sentences_with(transcript, [actor], limit=3)
        if sentences:
            result.append({
                "actor": actor,
                "role_or_position": cite_sentence(sentences[0], chunks),
                "related_quotes": cite_list(sentences, chunks, 3),
            })
    if not result:
        result.append({"actor": "원본 화자/시청자", "role_or_position": "원본에서 명확한 등장 주체가 적게 드러납니다", "related_quotes": []})
    return result[:8]


def make_timeline(transcript, chunks, source_kind):
    tokens = EVENT_TOKENS + ["기증", "만들", "요구", "반발", "들어섰", "망하", "닫", "문", "이용"]
    sentences = find_sentences_with(transcript, tokens, limit=8)
    if not sentences:
        sentences = pick_sentences(transcript, extract_keywords(transcript), limit=5)
    timeline = []
    for idx, sentence in enumerate(sentences[:7], start=1):
        timeline.append({"step": idx, "event": cite_sentence(sentence, chunks)})
    return timeline


def extract_fact_cards(transcript, chunks, keywords):
    sentences = pick_sentences(transcript, keywords, limit=8, tokens=EVIDENCE_TOKENS, exclude_opening_background=True)
    cards = []
    for idx, sentence in enumerate(sentences[:6], start=1):
        cards.append({"fact": shorten(sentence, 150), "source": cite_sentence(sentence, chunks)})
    return cards


def build_conflict_axis(domain, source_kind, actor_map, transcript):
    text = transcript[:3500]
    if source_kind == "사건형":
        if "노조" in text or "직원" in text:
            return "공익적 결과 또는 기업의 결정과 내부 구성원의 생존 불안이 충돌하는 구조"
        if "시민" in text and "회사" in text:
            return "지역사회가 얻은 이익과 기업/이해관계자의 선택이 충돌하는 구조"
        return "겉으로 보이는 미담과 그 뒤에 남은 이해관계가 충돌하는 구조"
    if domain == "시장/투자":
        return "상승 기대감과 실제 근거/리스크 확인 사이의 긴장 구조"
    if domain == "영상/마케팅":
        return "보기 좋은 결과물과 실제 전환 성과 사이의 간극"
    return "사람들이 보는 결론과 실제로 확인해야 할 기준 사이의 간극"


def build_hidden_assumption(domain, source_kind, transcript):
    if source_kind == "사건형":
        return "겉으로 아름답거나 선해 보이는 결과라면, 그 과정도 모두 순탄했을 것이라는 착각"
    if domain == "시장/투자":
        return "가격이 움직이면 이유도 명확할 것이라는 착각"
    if domain == "영상/마케팅":
        return "보기 좋으면 성과도 따라올 것이라는 착각"
    if domain == "교육/노하우":
        return "정보를 많이 알면 실행도 쉬워질 것이라는 착각"
    return "화제가 되는 주제라면 중요한 이유도 이미 충분히 설명됐을 것이라는 착각"


def build_audience_pain(domain, source_kind, conditions):
    if source_kind == "사건형":
        pain = "시청자는 자극적인 결론이나 미담만 먼저 기억하지만, 그 뒤에 있는 주체들의 이해관계와 갈등의 흐름을 함께 보지 못하기 쉽습니다"
    elif domain == "시장/투자":
        pain = "시청자는 가격과 결론을 먼저 보지만, 실제로는 왜 움직이는지와 어떤 기준으로 판단해야 하는지를 놓치기 쉽습니다"
    elif domain == "영상/마케팅":
        pain = "시청자는 결과물의 퀄리티를 먼저 보지만, 실제 성과를 만드는 기획 구조와 전환 흐름을 놓치기 쉽습니다"
    elif domain == "교육/노하우":
        pain = "시청자는 방법을 많이 접하지만, 무엇부터 적용해야 하는지와 어떤 기준으로 판단해야 하는지를 놓치기 쉽습니다"
    else:
        pain = "시청자는 결론과 자극적인 포인트를 먼저 보지만, 왜 중요한지와 무엇을 확인해야 하는지를 놓치기 쉽습니다"
    if conditions.get("emphasis"):
        pain += f" 특히 {conditions['emphasis']} 관점이 중요합니다."
    if conditions.get("avoid"):
        pain += f" 단, {conditions['avoid']} 관점은 제외해야 합니다."
    return pain


def build_reusable_structure(source_kind, domain):
    if source_kind == "사건형":
        return "겉으로 알려진 결과를 먼저 보여주고, 그 뒤에 숨은 주체와 이해관계를 드러낸 뒤, 마지막에 독자가 다시 생각할 질문으로 닫는 구조"
    if source_kind == "튜토리얼/노하우형":
        return "문제 상황 → 흔한 실수 → 단계별 기준 → 적용 예시 → 체크리스트 구조"
    if source_kind == "시장분석형":
        return "현재 관심 → 움직인 이유 → 사람들이 놓친 기준 → 리스크 → 다음 확인 포인트 구조"
    return "초반에 질문을 던지고, 중반에서 놓친 기준을 보여준 뒤, 마지막에 적용 가능한 체크포인트로 정리하는 구조"


def build_cardnews_seed(original_topic, source_kind, domain, primary_claim, audience_pain, conflict_axis, timeline, fact_cards, chunks):
    if source_kind == "사건형":
        angles = [
            f"{original_topic} 뒤에 숨은 진짜 갈등",
            f"아름다운 결과 뒤에 남은 불편한 질문",
            f"사람들이 미담만 보고 놓친 것",
        ]
        slide_roles = ["겉으로 알려진 결과", "숨은 배경", "등장 주체", "갈등 축", "아이러니", "질문/CTA"]
    else:
        angles = [
            f"{original_topic}에서 사람들이 놓치는 것",
            f"{original_topic}을 보기 전에 확인할 기준",
            f"{original_topic}이 반응을 만드는 방식",
        ]
        slide_roles = ["훅", "맥락", "문제", "근거", "판단 기준", "행동 유도"]
    return {
        "angle_candidates": angles,
        "problem_candidates": [audience_pain, conflict_axis],
        "slide_roles": slide_roles,
        "timeline_seeds": timeline[:6],
        "fact_seeds": fact_cards[:6],
        "primary_claim": primary_claim,
    }


def build_source_qa(analysis):
    return [
        {
            "question": "이 원본은 한 문장으로 무엇인가?",
            "answer": analysis["original_topic"],
            "basis": analysis["primary_claim"],
        },
        {
            "question": "카드뉴스로 만들 때 가장 먼저 보여줄 포인트는?",
            "answer": analysis["contradiction_or_tension"],
            "basis": analysis["viral_hook_logic"],
        },
        {
            "question": "독자가 놓치기 쉬운 부분은?",
            "answer": analysis["audience_pain"],
            "basis": analysis["hidden_assumption"],
        },
    ]


def interpret_source(title, channel_name, transcript, conditions):
    clean_transcript = normalize_source_text(transcript)
    chunks = build_chunks(clean_transcript)
    keywords = extract_keywords(clean_transcript)
    domain = detect_domain(title, clean_transcript, conditions["source_domain"])
    source_kind = detect_source_kind(domain, clean_transcript)
    original_topic = infer_original_topic(title, keywords, domain, source_kind, clean_transcript)

    claim_candidates = pick_sentences(clean_transcript, keywords, limit=8, tokens=CLAIM_TOKENS + CONFLICT_TOKENS, exclude_opening_background=True)
    primary_claim_raw = claim_candidates[0] if claim_candidates else f"{original_topic}에 대한 핵심 관점을 다룹니다"
    primary_claim = cite_sentence(primary_claim_raw, chunks)

    sub_claims = cite_list(claim_candidates[1:5], chunks, 4)
    fact_cards = extract_fact_cards(clean_transcript, chunks, keywords)
    evidence_points = [card["source"] for card in fact_cards]
    timeline = make_timeline(clean_transcript, chunks, source_kind)
    actor_map = make_actor_map(clean_transcript, chunks)
    conflict_axis = build_conflict_axis(domain, source_kind, actor_map, clean_transcript)
    hidden_assumption = build_hidden_assumption(domain, source_kind, clean_transcript)
    audience_pain = build_audience_pain(domain, source_kind, conditions)
    cause_effect = [item["event"] for item in timeline[:5]]

    risk_sentences = find_sentences_with(clean_transcript, ["주의", "위험", "리스크", "아닙니다", "하지만", "반대로", "조심", "법정", "망하"], 5)
    risk_notes = cite_list(risk_sentences, chunks, 5) or ["원문에서 단정하기 어려운 부분은 카드뉴스에서 과장하지 않는 편이 안전합니다"]
    if conditions.get("avoid"):
        risk_notes.append(f"제외 관점: {conditions['avoid']}")

    narrative_structure = "사건형" if source_kind == "사건형" else "해설형"
    if source_kind == "사건형":
        narrative_structure = "결과 제시 → 과거 배경 → 이해관계자 등장 → 갈등/요구 → 현재의 아이러니 → 질문"
        emotional_trigger = "미담 뒤에 다른 이야기가 있었다는 반전감, 누가 옳은지 다시 판단하고 싶은 궁금증, 놓치고 있었다는 불안감"
        viral_hook_logic = f"겉으로는 긍정적인 결과를 먼저 보여준 뒤, 그 뒤에 숨은 갈등을 꺼내는 반전형 후킹. 핵심 근거: {primary_claim}"
    else:
        narrative_structure = "후킹 질문 → 배경 설명 → 핵심 인사이트 → 적용 방식 → 정리/CTA"
        emotional_trigger = "놓치고 있었다는 불안감, 지금 확인해야 한다는 긴급감, 기준을 얻었다는 안도감"
        viral_hook_logic = f"초반에 질문/불안/반전을 만들고, 이후 {domain} 독자가 놓친 기준을 제시하는 방식"

    reusable_structure = build_reusable_structure(source_kind, domain)
    summary_count = 3 if conditions["detail_level"] == "핵심만" else 5 if conditions["detail_level"] == "표준" else 7
    summary_sentences = claim_candidates[:summary_count] if claim_candidates else pick_sentences(clean_transcript, keywords, limit=summary_count)
    summary = "\n".join([f"- {cite_sentence(s, chunks)}" for s in summary_sentences])

    context_background = f"분야: {domain}. 원본 유형: {source_kind}. 관점: {conditions['viewpoint']}. 원문 충실도: {conditions['fidelity_level']}. 추론 허용도: {conditions['inference_level']}."
    if conditions.get("memo"):
        context_background += f" 메모: {conditions['memo']}"

    cardnews_seed = build_cardnews_seed(original_topic, source_kind, domain, primary_claim, audience_pain, conflict_axis, timeline, fact_cards, chunks)

    source_index = {
        "total_chunks": len(chunks),
        "top_keywords": keywords[:12],
        "domain": domain,
        "source_kind": source_kind,
        "chunk_preview": chunks[:5],
    }

    analysis = {
        "summary": summary,
        "key_claim": primary_claim,
        "hook_point": cite_sentence(split_sentences(clean_transcript)[0], chunks) if split_sentences(clean_transcript) else original_topic,
        "structure_note": narrative_structure,
        "visual_note": "원본 주제 카드뉴스 메뉴에서 이미지 비율, 스타일, 카피 포함 여부를 선택해 재가공",
        "eafi_application": f"{original_topic} 원본 해석 데이터를 바탕으로 원본 주제 카드뉴스 메뉴에서 카드뉴스 설계 가능",
        "keywords": ", ".join(keywords),
        "source_domain": domain,
        "source_kind": source_kind,
        "clean_transcript": clean_transcript,
        "source_chunks": json.dumps(chunks, ensure_ascii=False),
        "source_index": json.dumps(source_index, ensure_ascii=False, indent=2),
        "original_topic": original_topic,
        "primary_claim": primary_claim,
        "sub_claims": json.dumps(sub_claims, ensure_ascii=False),
        "evidence_points": json.dumps(evidence_points, ensure_ascii=False),
        "context_background": context_background,
        "event_timeline": json.dumps(timeline, ensure_ascii=False),
        "actor_map": json.dumps(actor_map, ensure_ascii=False),
        "cause_effect_chain": json.dumps(cause_effect, ensure_ascii=False),
        "audience_pain": audience_pain,
        "hidden_assumption": hidden_assumption,
        "contradiction_or_tension": conflict_axis,
        "emotional_trigger": emotional_trigger,
        "viral_hook_logic": viral_hook_logic,
        "narrative_structure": narrative_structure,
        "reusable_structure": reusable_structure,
        "risk_notes": json.dumps(risk_notes, ensure_ascii=False),
        "cardnews_seed": json.dumps(cardnews_seed, ensure_ascii=False, indent=2),
    }
    analysis["source_grounded_qa"] = json.dumps(build_source_qa(analysis), ensure_ascii=False, indent=2)
    interpretation_report = {
        "conditions": conditions,
        "source_index": source_index,
        "original_topic": original_topic,
        "primary_claim": primary_claim,
        "source_kind": source_kind,
        "domain": domain,
        "actor_map": actor_map,
        "event_timeline": timeline,
        "fact_cards": fact_cards,
        "audience_pain": audience_pain,
        "hidden_assumption": hidden_assumption,
        "contradiction_or_tension": conflict_axis,
        "emotional_trigger": emotional_trigger,
        "viral_hook_logic": viral_hook_logic,
        "reusable_structure": reusable_structure,
        "cardnews_seed": cardnews_seed,
    }
    analysis["interpretation_report"] = json.dumps(interpretation_report, ensure_ascii=False, indent=2)
    return analysis


def save_analysis(video_id, url, title, channel_name, transcript, analysis, conditions, source_type="YouTube"):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO youtube_video_analyses
        (video_id, url, title, channel_name, transcript, summary, hook_point, structure_note, visual_note,
         eafi_application, keywords, key_claim, source_type, analysis_memo, interpretation_conditions,
         source_domain, source_kind, interpretation_goal, viewpoint, detail_level, fidelity_level, inference_level,
         clean_transcript, source_chunks, source_index, original_topic, primary_claim, sub_claims, evidence_points,
         context_background, event_timeline, actor_map, cause_effect_chain, audience_pain, hidden_assumption,
         contradiction_or_tension, emotional_trigger, viral_hook_logic, narrative_structure, reusable_structure,
         risk_notes, cardnews_seed, source_grounded_qa, interpretation_report, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        video_id, url, title, channel_name, transcript, analysis["summary"], analysis["hook_point"],
        analysis["structure_note"], analysis["visual_note"], analysis["eafi_application"], analysis["keywords"],
        analysis["key_claim"], source_type, conditions.get("memo", ""), json.dumps(conditions, ensure_ascii=False),
        analysis["source_domain"], analysis["source_kind"], conditions["interpretation_goal"], conditions["viewpoint"],
        conditions["detail_level"], conditions["fidelity_level"], conditions["inference_level"], analysis["clean_transcript"],
        analysis["source_chunks"], analysis["source_index"], analysis["original_topic"], analysis["primary_claim"],
        analysis["sub_claims"], analysis["evidence_points"], analysis["context_background"], analysis["event_timeline"],
        analysis["actor_map"], analysis["cause_effect_chain"], analysis["audience_pain"], analysis["hidden_assumption"],
        analysis["contradiction_or_tension"], analysis["emotional_trigger"], analysis["viral_hook_logic"],
        analysis["narrative_structure"], analysis["reusable_structure"], analysis["risk_notes"], analysis["cardnews_seed"],
        analysis["source_grounded_qa"], analysis["interpretation_report"], datetime.now().isoformat(timespec="seconds"),
    ))
    conn.commit()
    conn.close()


def convert_to_reference(url, title, channel_name, analysis, scores, conditions):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO benchmark_channels
        (platform, channel_name, url, category, reference_reason, priority, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "YouTube", channel_name, url, "원본 해석 데이터", "NotebookLM식 소스 기반 원본 해석", "A",
        f"분야: {analysis['source_domain']} / 유형: {analysis['source_kind']} / 목적: {conditions['interpretation_goal']} / 키워드: {analysis['keywords']}",
        datetime.now().isoformat(timespec="seconds"),
    ))
    channel_id = cur.lastrowid
    total_score = sum(scores.values())
    structure_pack = (
        f"원본 주제:\n{analysis['original_topic']}\n\n"
        f"원본 유형:\n{analysis['source_kind']}\n\n"
        f"핵심 주장:\n{analysis['primary_claim']}\n\n"
        f"등장 주체:\n{analysis['actor_map']}\n\n"
        f"사건/전개 타임라인:\n{analysis['event_timeline']}\n\n"
        f"독자 문제:\n{analysis['audience_pain']}\n\n"
        f"긴장 구조:\n{analysis['contradiction_or_tension']}\n\n"
        f"재사용 구조:\n{analysis['reusable_structure']}\n\n"
        f"카드뉴스 씨앗:\n{analysis['cardnews_seed']}\n\n"
        f"해석 리포트:\n{analysis['interpretation_report']}"
    )
    cur.execute("""
        INSERT INTO content_references
        (channel_id, title, url, hook_point, structure_note, visual_note, eafi_application,
         lead_potential_score, visual_score, hook_score, seo_score, conversion_score, total_score, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        channel_id, clean(title, analysis["original_topic"]), url, analysis["hook_point"], structure_pack, analysis["visual_note"],
        analysis["eafi_application"], scores["lead"], scores["visual"], scores["hook"], scores["seo"],
        scores["conversion"], total_score, "원본 해석", datetime.now().isoformat(timespec="seconds"),
    ))
    conn.commit()
    conn.close()


def load_recent_analyses():
    conn = connect_db()
    try:
        df = pd.read_sql_query("""
            SELECT id, video_id, title, channel_name, source_domain, source_kind, interpretation_goal,
                   original_topic, primary_claim, audience_pain, keywords, created_at
            FROM youtube_video_analyses
            ORDER BY id DESC LIMIT 30
        """, conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def build_interpretation_conditions():
    st.markdown("### 원본 해석 조건")
    c1, c2, c3 = st.columns(3)
    with c1:
        interpretation_goal = st.selectbox("해석 목적", INTERPRETATION_GOALS, index=0)
        source_domain = st.selectbox("원본 분야", SOURCE_DOMAINS, index=0)
    with c2:
        viewpoint = st.selectbox("해석 관점", VIEWPOINTS, index=0)
        detail_level = st.selectbox("디테일 수준", DETAIL_LEVELS, index=2)
    with c3:
        fidelity_level = st.selectbox("원문 충실도", FIDELITY_LEVELS, index=1)
        inference_level = st.selectbox("추론 허용도", INFERENCE_LEVELS, index=1)

    c4, c5 = st.columns(2)
    with c4:
        emphasis = st.text_input("강조할 해석 관점", placeholder="예: 사건의 아이러니, 갈등 축, 독자가 놓친 사실, 후킹 방식")
    with c5:
        avoid = st.text_input("제외할 해석 관점", placeholder="예: 과한 투자 조언, 원문 밖 단정, 브랜드명 과다 노출")

    memo = st.text_input("분석 메모", placeholder="선택 입력: 왜 수집했는지, 나중에 어떤 카드뉴스로 쓸지 기록")

    return {
        "interpretation_goal": interpretation_goal,
        "source_domain": source_domain,
        "viewpoint": viewpoint,
        "detail_level": detail_level,
        "fidelity_level": fidelity_level,
        "inference_level": inference_level,
        "emphasis": emphasis,
        "avoid": avoid,
        "memo": memo,
    }


def build_payload_from_transcript(video_id, normalized_url, title, channel_name, transcript, scores, conditions, debug=None, source_type="YouTube"):
    analysis = interpret_source(title, channel_name, transcript, conditions)
    return {
        "video_id": video_id,
        "url": normalized_url,
        "title": title,
        "channel_name": channel_name,
        "transcript": transcript,
        "analysis": analysis,
        "scores": scores,
        "debug": debug or {},
        "source_type": source_type,
        "conditions": conditions,
    }


def render_json_list(label, value):
    try:
        items = json.loads(value) if isinstance(value, str) else value
    except Exception:
        items = [value]
    st.markdown(f"#### {label}")
    if isinstance(items, dict):
        st.json(items)
    elif isinstance(items, list):
        if items and isinstance(items[0], dict):
            st.dataframe(pd.DataFrame(items), use_container_width=True, hide_index=True)
        else:
            for item in items:
                st.write(f"- {item}")
    else:
        st.write(items)


def render_payload(payload):
    analysis = payload["analysis"]
    st.markdown("### NotebookLM식 원본 해석 결과")
    st.write(f"**제목:** {payload['title'] or analysis['original_topic']}")
    st.write(f"**채널:** {payload['channel_name']}")
    st.write(f"**video_id:** {payload['video_id']}")
    st.write(f"**자막 길이:** {len(payload['transcript']):,}자")
    st.write(f"**감지 분야:** {analysis['source_domain']}")
    st.write(f"**원본 유형:** {analysis['source_kind']}")
    st.write(f"**키워드:** {analysis['keywords']}")

    with st.expander("적용된 원본 해석 조건", expanded=True):
        st.json(payload["conditions"])

    if payload.get("debug"):
        with st.expander("진단 로그 보기"):
            st.json(payload["debug"])

    st.markdown("#### 원본 주제")
    st.text_area("original_topic", value=analysis["original_topic"], height=70)
    st.markdown("#### 핵심 주장")
    st.text_area("primary_claim", value=analysis["primary_claim"], height=90)
    st.markdown("#### 핵심 요약")
    st.text_area("summary", value=analysis["summary"], height=170)
    st.markdown("#### 독자 문제")
    st.text_area("audience_pain", value=analysis["audience_pain"], height=100)
    st.markdown("#### 숨은 전제")
    st.text_area("hidden_assumption", value=analysis["hidden_assumption"], height=80)
    st.markdown("#### 긴장/대립 구조")
    st.text_area("contradiction_or_tension", value=analysis["contradiction_or_tension"], height=80)
    st.markdown("#### 감정 트리거")
    st.text_area("emotional_trigger", value=analysis["emotional_trigger"], height=80)
    st.markdown("#### 바이럴 후킹 로직")
    st.text_area("viral_hook_logic", value=analysis["viral_hook_logic"], height=100)
    st.markdown("#### 전개 구조")
    st.text_area("narrative_structure", value=analysis["narrative_structure"], height=80)
    st.markdown("#### 재사용 가능한 구조")
    st.text_area("reusable_structure", value=analysis["reusable_structure"], height=100)

    render_json_list("등장 주체", analysis["actor_map"])
    render_json_list("사건/전개 타임라인", analysis["event_timeline"])
    render_json_list("보조 주장", analysis["sub_claims"])
    render_json_list("근거 포인트", analysis["evidence_points"])
    render_json_list("원인 → 결과 체인", analysis["cause_effect_chain"])
    render_json_list("주의/리스크", analysis["risk_notes"])
    render_json_list("소스 기반 Q&A", analysis["source_grounded_qa"])

    with st.expander("카드뉴스 재가공 씨앗 데이터", expanded=True):
        try:
            st.json(json.loads(analysis["cardnews_seed"]))
        except Exception:
            st.write(analysis["cardnews_seed"])

    with st.expander("소스 청크 보기"):
        try:
            st.dataframe(pd.DataFrame(json.loads(analysis["source_chunks"])), use_container_width=True, hide_index=True)
        except Exception:
            st.write(analysis["source_chunks"])

    with st.expander("전체 해석 리포트 JSON"):
        st.code(analysis["interpretation_report"])

    with st.expander("정제된 전체 자막 보기"):
        st.text_area("Clean Transcript", value=analysis["clean_transcript"], height=340)

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("원본 해석 결과 저장"):
            save_analysis(
                payload["video_id"], payload["url"], payload["title"], payload["channel_name"],
                payload["transcript"], payload["analysis"], payload["conditions"], payload.get("source_type", "YouTube")
            )
            st.success("원본 해석 결과를 저장했습니다. 원본 주제 카드뉴스 메뉴에서 사용할 수 있습니다.")
    with col_b:
        if st.button("참고 콘텐츠 DB로 저장"):
            save_analysis(
                payload["video_id"], payload["url"], payload["title"], payload["channel_name"],
                payload["transcript"], payload["analysis"], payload["conditions"], payload.get("source_type", "YouTube")
            )
            convert_to_reference(payload["url"], payload["title"], payload["channel_name"], payload["analysis"], payload["scores"], payload["conditions"])
            st.success("원본 해석 결과를 참고 콘텐츠 DB로 저장했습니다.")
    with col_c:
        if st.button("초기화"):
            st.session_state.pop("yt_analysis_payload", None)
            st.rerun()


def main():
    st.set_page_config(page_title="YouTube 영상 내용 분석", page_icon="🎬", layout="wide")
    init_tables()

    st.title("🎬 YouTube 영상 내용 분석")
    st.caption("NotebookLM처럼 원문을 청크로 나누고, 소스 근거를 붙여 주제·사건·갈등·근거·카드뉴스 씨앗을 추출합니다.")

    conditions = build_interpretation_conditions()

    st.markdown("### 수집/분석 방식")
    mode = st.radio("분석 방식", ["YouTube 링크로 자막 가져오기", "자막/스크립트 직접 붙여넣기"], horizontal=True)

    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        lead = st.slider("리드 가능성", 1, 5, 4)
    with c2:
        visual = st.slider("이미지화", 1, 5, 4)
    with c3:
        hook = st.slider("후킹", 1, 5, 4)
    with c4:
        seo = st.slider("SEO", 1, 5, 4)
    with c5:
        conversion = st.slider("전환", 1, 5, 4)
    scores = {"lead": lead, "visual": visual, "hook": hook, "seo": seo, "conversion": conversion}

    if mode == "YouTube 링크로 자막 가져오기":
        url = st.text_input("YouTube URL 또는 video_id", placeholder="https://www.youtube.com/watch?v=... 또는 https://youtube.com/shorts/...")
        langs = st.multiselect("자막 우선순위", ["ko", "en", "ja", "es", "de", "fr"], default=["ko", "en"])

        if st.button("자막 가져와서 NotebookLM식 원본 해석", type="primary"):
            video_id = get_video_id(url)
            if not video_id:
                st.error("YouTube video_id를 찾지 못했습니다. URL을 확인하세요.")
                return
            normalized_url = f"https://www.youtube.com/watch?v={video_id}"
            try:
                title, channel_name = fetch_oembed(normalized_url)
                transcript, debug = fetch_transcript(video_id, langs)
                st.session_state["yt_analysis_payload"] = build_payload_from_transcript(
                    video_id, normalized_url, title, channel_name, transcript, scores, conditions, debug, "YouTube"
                )
                st.success("자막 수집과 원본 해석을 완료했습니다.")
            except Exception as e:
                st.error(f"분석 실패: {e}")
                with st.expander("에러 상세 보기"):
                    st.code(traceback.format_exc())
                st.info("자막이 없거나 YouTube가 서버 접근을 막은 경우일 수 있습니다. 아래 '자막/스크립트 직접 붙여넣기' 방식으로 우회할 수 있습니다.")

        if url:
            video_id = get_video_id(url)
            if st.button("사용 가능한 자막 목록만 확인"):
                if not video_id:
                    st.error("video_id를 찾지 못했습니다.")
                else:
                    try:
                        rows = list_available_transcripts(video_id)
                        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
                    except Exception as e:
                        st.error(f"자막 목록 확인 실패: {e}")
                        with st.expander("에러 상세 보기"):
                            st.code(traceback.format_exc())
    else:
        manual_url = st.text_input("원본 YouTube URL 또는 video_id", placeholder="선택 입력")
        manual_title = st.text_input("영상 제목", value="")
        manual_channel = st.text_input("채널명", value="Manual Input")
        transcript = st.text_area("자막/스크립트 붙여넣기", height=360, placeholder="YouTube 자막, Whisper 전사, NotebookLM 요약 전 원문 등을 붙여넣으세요.")
        if st.button("붙여넣은 스크립트 NotebookLM식 원본 해석", type="primary"):
            if len(clean(transcript)) < 80:
                st.error("분석할 스크립트가 너무 짧습니다. 최소 80자 이상 붙여넣으세요.")
            else:
                video_id = get_video_id(manual_url) or "manual"
                normalized_url = f"https://www.youtube.com/watch?v={video_id}" if video_id != "manual" else clean(manual_url, "manual")
                title = clean(manual_title, "")
                st.session_state["yt_analysis_payload"] = build_payload_from_transcript(
                    video_id, normalized_url, title, manual_channel, transcript, scores, conditions,
                    {"method": "manual_paste", "transcript_length": len(transcript)}, "Manual"
                )
                st.success("붙여넣은 스크립트를 원본 해석했습니다.")

    payload = st.session_state.get("yt_analysis_payload")
    if payload:
        st.markdown("---")
        render_payload(payload)

    st.markdown("---")
    st.markdown("### 최근 원본 해석 기록")
    recent = load_recent_analyses()
    if recent.empty:
        st.info("아직 원본 해석 기록이 없습니다.")
    else:
        st.dataframe(recent, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
