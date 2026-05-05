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

BAD_TITLES = ["직접 입력한 영상 스크립트", "manual input", "youtube 영상", "untitled", "직접 입력"]
NOISE_WORDS = set([
    "거대한", "무려", "동안", "정말", "진짜", "아주", "완전히", "한번", "결국", "바로", "이제",
    "대한민국", "글로벌", "같이", "가진", "버리는", "돈을", "화려한", "엄청난", "충격",
    "그리고", "그런데", "그래서", "하지만", "저는", "우리는", "여러분", "이거", "저거", "그거",
    "약간", "되게", "너무", "오늘", "영상", "이번", "계속", "것", "수", "때", "좀", "더",
    "왜", "어떻게", "이런", "그런", "저런", "합니다", "있습니다", "있고", "있는", "하면",
    "해서", "하는", "제가", "우리", "여기", "거죠", "거예요", "겁니다", "하나", "같은", "정도",
    "사람", "사람들", "부분", "대한", "통해", "관련", "모든", "제대로", "사실", "말씀",
])

DOMAIN_HINTS = {
    "시장/투자": ["코인", "비트코인", "주식", "시장", "투자", "가격", "섹터", "2차전지", "배터리", "급등", "하락"],
    "영상/마케팅": ["영상", "촬영", "편집", "마케팅", "브랜드", "광고", "콘텐츠", "유튜브", "전환", "CTA"],
    "기술/AI": ["ai", "인공지능", "기술", "개발", "앱", "서비스", "툴", "자동화", "모델"],
    "교육/노하우": ["방법", "노하우", "배우", "강의", "튜토리얼", "체크리스트", "공부", "설명"],
    "사건/논쟁": ["노조", "회사", "직원", "시민", "공장", "사건", "논란", "갈등", "반발", "요구", "법정", "기증", "주차장", "파업", "삼성", "성과급"],
    "트렌드/이슈": ["요즘", "논란", "이슈", "트렌드", "화제", "사람들", "커뮤니티", "밈"],
}

CORE_ACTORS = ["삼성", "삼성전자", "회사", "직원", "노조", "시민", "안양시", "정부", "공장", "주무부처", "경영진", "소비자"]
CLAIM_TOKENS = ["핵심", "문제", "이유", "결국", "사실", "중요", "다릅니다", "아닙니다", "하지만", "놓치", "실수", "반대로", "선언", "대답", "요구"]
EVENT_TOKENS = ["처음", "시작", "어느 날", "그런데", "하지만", "이후", "결국", "나중에", "현재", "당시", "그때", "먼저", "마침내", "갑자기", "선언", "요구", "파업"]
EVIDENCE_TOKENS = ["근거", "수치", "%", "데이터", "조사", "연구", "사례", "예를", "보면", "기증", "주차장", "법정", "요구", "조건", "15%", "45조", "93%", "70%", "5억", "플러그", "전원", "파업"]


# ---------- DB ----------

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
        "key_claim": "TEXT", "source_type": "TEXT", "analysis_memo": "TEXT", "interpretation_conditions": "TEXT",
        "source_domain": "TEXT", "source_kind": "TEXT", "interpretation_goal": "TEXT", "viewpoint": "TEXT",
        "detail_level": "TEXT", "fidelity_level": "TEXT", "inference_level": "TEXT", "clean_transcript": "TEXT",
        "source_chunks": "TEXT", "source_index": "TEXT", "original_topic": "TEXT", "primary_claim": "TEXT",
        "sub_claims": "TEXT", "evidence_points": "TEXT", "context_background": "TEXT", "event_timeline": "TEXT",
        "actor_map": "TEXT", "cause_effect_chain": "TEXT", "audience_pain": "TEXT", "hidden_assumption": "TEXT",
        "contradiction_or_tension": "TEXT", "emotional_trigger": "TEXT", "viral_hook_logic": "TEXT",
        "narrative_structure": "TEXT", "reusable_structure": "TEXT", "risk_notes": "TEXT", "cardnews_seed": "TEXT",
        "source_grounded_qa": "TEXT", "interpretation_report": "TEXT",
        "focus_question": "TEXT", "focus_keywords": "TEXT", "main_topic_sentence": "TEXT", "dedup_report": "TEXT",
        "interpretation_slots": "TEXT", "event_type": "TEXT",
    }
    for col, col_type in extra_columns.items():
        ensure_column(cur, "youtube_video_analyses", col, col_type)
    conn.commit()
    conn.close()


# ---------- Basic text utilities ----------

def clean(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def shorten(text, max_len=180):
    text = re.sub(r"\s+", " ", clean(text)).strip()
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def normalize_source_text(text):
    text = clean(text)
    text = re.sub(r"(?im)^\s*(title|url|source|link|영상 제목|제목)\s*[:：]\s*.*$", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\[[0-9:.\-\s]+\]", " ", text)
    text = re.sub(r"\([0-9:.\-\s]+\)", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_sentences(text):
    text = normalize_source_text(text)
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=다)\s+|(?<=요)\s+|(?<=죠)\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 10]


def is_bad_title(title):
    lowered = clean(title).lower()
    return not lowered or any(bad.lower() in lowered for bad in BAD_TITLES)


def tokenize_focus(text):
    raw = re.split(r"[,/\s]+", clean(text))
    return [t.strip().lower() for t in raw if len(t.strip()) > 1 and t.strip().lower() not in NOISE_WORDS]


def extract_keywords(text, topn=20, focus_tokens=None):
    focus_tokens = focus_tokens or []
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", normalize_source_text(text))
    freq = {}
    for word in words:
        w = word.lower().strip()
        if w in NOISE_WORDS or len(w) < 2 or re.match(r"^[0-9]+$", w):
            continue
        freq[w] = freq.get(w, 0) + 1
    for token in focus_tokens:
        if token:
            freq[token] = freq.get(token, 0) + 5
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:topn]]


def sentence_similarity(a, b):
    aw = set([w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", a.lower()) if w not in NOISE_WORDS])
    bw = set([w for w in re.findall(r"[가-힣A-Za-z0-9]{2,}", b.lower()) if w not in NOISE_WORDS])
    if not aw or not bw:
        return 0
    return len(aw & bw) / max(1, len(aw | bw))


def dedup_sentences(sentences, limit=8, threshold=0.42):
    picked, removed = [], []
    for sentence in sentences:
        if any(sentence_similarity(sentence, old) >= threshold for old in picked):
            removed.append(sentence)
            continue
        picked.append(sentence)
        if len(picked) >= limit:
            break
    return picked, removed


def focus_score(sentence, focus_tokens):
    if not focus_tokens:
        return 0
    s = sentence.lower()
    return sum(4 for token in focus_tokens if token and token in s)


def has_any(text, words):
    return any(word in clean(text) for word in words)


# ---------- YouTube ----------

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
        res = requests.get("https://www.youtube.com/oembed", params={"url": url, "format": "json"}, headers=HEADERS, timeout=15)
        res.raise_for_status()
        data = res.json()
        return clean(data.get("title"), "YouTube 영상"), clean(data.get("author_name"), "YouTube")
    except Exception:
        return "YouTube 영상", "YouTube"


def list_available_transcripts(video_id):
    ytt_api = YouTubeTranscriptApi()
    transcript_list = ytt_api.list(video_id)
    return [{"language": getattr(t, "language", ""), "language_code": getattr(t, "language_code", ""), "is_generated": getattr(t, "is_generated", ""), "is_translatable": getattr(t, "is_translatable", "")} for t in transcript_list]


def fetched_transcript_to_text(fetched):
    rows = fetched.to_raw_data() if hasattr(fetched, "to_raw_data") else fetched
    parts = []
    for row in rows:
        text = row.get("text", "") if isinstance(row, dict) else getattr(row, "text", "")
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
        text = fetched_transcript_to_text(ytt_api.fetch(video_id, languages=languages))
        if text:
            return text, debug
    except Exception as first_error:
        debug["error_stage"] = "direct_fetch_failed"
        debug["error_message"] = repr(first_error)
    try:
        debug["method"] = "YouTubeTranscriptApi().list(video_id) fallback"
        transcript_list = ytt_api.list(video_id)
        debug["available_transcripts"] = [{"language": getattr(t, "language", ""), "language_code": getattr(t, "language_code", ""), "is_generated": getattr(t, "is_generated", ""), "is_translatable": getattr(t, "is_translatable", "")} for t in transcript_list]
        transcript = None
        for finder in [transcript_list.find_transcript, transcript_list.find_generated_transcript]:
            try:
                transcript = finder(languages)
                break
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


# ---------- Source indexing ----------

def build_chunks(text, max_chars=750):
    sentences = split_sentences(text)
    chunks, current, size, chunk_id = [], [], 0, 1
    for sentence in sentences:
        if size + len(sentence) > max_chars and current:
            chunks.append({"id": f"S{chunk_id}", "text": " ".join(current)})
            chunk_id += 1
            current, size = [], 0
        current.append(sentence)
        size += len(sentence)
    if current:
        chunks.append({"id": f"S{chunk_id}", "text": " ".join(current)})
    return chunks


def cite_sentence(sentence, chunks):
    sentence = clean(sentence)
    for chunk in chunks:
        if sentence[:30] and sentence[:30] in chunk["text"]:
            return f"{shorten(sentence, 170)} [{chunk['id']}]"
    return shorten(sentence, 170)


def cite_list(sentences, chunks, limit=5):
    return [cite_sentence(s, chunks) for s in sentences[:limit] if clean(s)]


def detect_domain(title, transcript, selected):
    if selected not in ["자동 감지", "직접 입력"]:
        return selected
    text = f"{title} {transcript[:3000]}".lower()
    scores = {domain: sum(1 for hint in hints if hint.lower() in text) for domain, hints in DOMAIN_HINTS.items()}
    top = max(scores.items(), key=lambda x: x[1])
    return top[0] if top[1] > 0 else "트렌드/이슈"


def detect_event_type(title, transcript, keywords):
    corpus = f"{title} {transcript[:5000]} {' '.join(keywords)}"
    if has_any(corpus, ["삼성", "노조", "성과급", "파업", "플러그", "가전라인", "전원"]):
        return "samsung_labor"
    if has_any(corpus, ["안양", "삼덕", "공원", "기증", "주차장", "부지"]):
        return "park_donation"
    if has_any(corpus, ["노조", "직원", "회사", "갈등", "파업", "반발"]):
        return "labor_conflict"
    if has_any(corpus, ["소송", "법원", "법정", "재판"]):
        return "legal_conflict"
    return "general"


def detect_source_kind(domain, transcript, event_type):
    text = transcript[:5000]
    if event_type != "general" or domain == "사건/논쟁":
        return "사건형"
    if any(t in text for t in ["방법", "단계", "따라", "먼저", "체크"]):
        return "튜토리얼/노하우형"
    if any(t in text for t in ["비교", "장점", "단점", "후기", "리뷰"]):
        return "리뷰/비교형"
    if domain == "시장/투자":
        return "시장분석형"
    return "이슈해설형"


def find_sentences_with(text, tokens, limit=8, focus_tokens=None):
    focus_tokens = focus_tokens or []
    sentences = split_sentences(text)
    picked = []
    for sentence in sentences:
        if any(token in sentence for token in tokens) or focus_score(sentence, focus_tokens) > 0:
            picked.append(sentence)
    deduped, _ = dedup_sentences(picked, limit=limit)
    return deduped


def pick_scored_sentences(text, keywords, tokens=None, focus_tokens=None, limit=10):
    tokens = tokens or []
    focus_tokens = focus_tokens or []
    scored = []
    for idx, sentence in enumerate(split_sentences(text)):
        score = sum(1 for kw in keywords if kw in sentence.lower())
        score += focus_score(sentence, focus_tokens)
        score += 4 if any(token in sentence for token in tokens) else 0
        score += 2 if any(token in sentence for token in CLAIM_TOKENS) else 0
        score += max(0, 2.0 - idx * 0.015)
        scored.append((score, sentence))
    scored.sort(key=lambda x: x[0], reverse=True)
    candidates = [s for score, s in scored if score > 0]
    picked, _ = dedup_sentences(candidates, limit=limit)
    return picked


def make_actor_map(transcript, chunks, focus_tokens=None):
    result = []
    for actor in CORE_ACTORS:
        sentences = find_sentences_with(transcript, [actor], limit=3, focus_tokens=focus_tokens)
        if sentences:
            result.append({"actor": actor, "role_or_position": cite_sentence(sentences[0], chunks), "related_quotes": cite_list(sentences, chunks, 3)})
    unique, seen = [], set()
    for item in result:
        if item["actor"] in seen:
            continue
        seen.add(item["actor"])
        unique.append(item)
    if not unique:
        unique.append({"actor": "원본 화자/시청자", "role_or_position": "원본에서 명확한 등장 주체가 적게 드러납니다", "related_quotes": []})
    return unique[:7]


def make_timeline(transcript, chunks, keywords, focus_tokens=None):
    tokens = EVENT_TOKENS + ["기증", "만들", "요구", "반발", "들어섰", "망하", "닫", "문", "이용", "뽑아", "선언", "대신", "파업", "성과급", "폐쇄", "정부"]
    sentences = find_sentences_with(transcript, tokens, limit=12, focus_tokens=focus_tokens)
    if not sentences:
        sentences = pick_scored_sentences(transcript, keywords, limit=7, focus_tokens=focus_tokens)
    return [{"step": idx, "event": cite_sentence(sentence, chunks)} for idx, sentence in enumerate(sentences[:7], start=1)]


def extract_fact_cards(transcript, chunks, keywords, focus_tokens=None):
    sentences = pick_scored_sentences(transcript, keywords, limit=12, tokens=EVIDENCE_TOKENS, focus_tokens=focus_tokens)
    cards, used = [], set()
    for sentence in sentences:
        plain = shorten(sentence, 150)
        key = re.sub(r"[^가-힣A-Za-z0-9]", "", plain[:70])
        if key in used:
            continue
        used.add(key)
        cards.append({"fact": plain, "source": cite_sentence(sentence, chunks)})
        if len(cards) >= 8:
            break
    return cards


def find_first_fact(facts, tokens, fallback=""):
    for fact in facts:
        text = fact.get("source", "") if isinstance(fact, dict) else str(fact)
        if has_any(text, tokens):
            return text
    return fallback


def topic_from_source(title, event_type, keywords, facts):
    if not is_bad_title(title):
        title_clean = re.sub(r"[\"“”']", "", title).strip()
        if event_type == "samsung_labor" and len(title_clean) > 8:
            return title_clean
        if event_type != "general" and len(title_clean) > 8:
            return title_clean
    if event_type == "samsung_labor":
        return "삼성 가전라인 폐쇄 발언과 노조 성과급 갈등"
    if event_type == "park_donation":
        return "공원이라는 미담 뒤에 숨은 기부와 노사 갈등"
    if event_type == "labor_conflict":
        return "회사와 직원·노조 사이에 벌어진 갈등"
    filtered = [kw for kw in keywords if kw not in NOISE_WORDS][:4]
    return f"{', '.join(filtered)} 중심의 이야기" if filtered else "원본에 담긴 핵심 이야기"


# ---------- Dynamic slots ----------

def build_interpretation_slots(event_type, original_topic, primary_claim, facts, actor_map, conditions):
    actors = [a.get("actor", "") for a in actor_map if isinstance(a, dict)]
    actor_line = ", ".join([a for a in actors if a][:4]) or "여러 이해관계자"

    if event_type == "samsung_labor":
        demand = find_first_fact(facts, ["15%", "성과급", "영업 이익", "영업이익"], "노조는 회사 이익의 일부를 성과급으로 돌려달라고 요구했습니다")
        amount = find_first_fact(facts, ["45조"], "요구 규모는 단순한 보너스 논쟁을 넘어선 수준으로 커졌습니다")
        plug = find_first_fact(facts, ["플러그", "전원", "폐쇄", "뽑"], "회사는 생산 라인 중단까지 언급하는 강한 방식으로 맞섰습니다")
        strike = find_first_fact(facts, ["파업", "93%", "찬성"], "갈등은 파업 논의와 여론전으로 번졌습니다")
        gov = find_first_fact(facts, ["정부", "주무부처", "70%", "경쟁력"], "정부와 여론도 이 문제를 산업 경쟁력과 연결해 보기 시작했습니다")
        future = find_first_fact(facts, ["미래", "투자", "빨대", "7만"], "회사는 현재 보상보다 미래 투자가 우선이라는 논리로 맞섰습니다")
        conflict = "현재 이익을 직원에게 나눌 것인가, 미래 투자를 위해 비용을 통제할 것인가의 충돌"
        return {
            "original_topic": original_topic,
            "main_topic_sentence": f"{original_topic}: {conflict}",
            "audience_pain": "시청자는 삼성과 노조의 싸움이라는 자극적인 구도만 먼저 보지만, 실제 쟁점은 성과급 요구, 거대 숫자, 생산라인 중단 발언, 파업 여론, 미래 투자 논리가 함께 얽힌 구조입니다.",
            "hidden_assumption": "회사가 큰돈을 벌었으면 직원에게 더 많이 나눠야 한다는 전제와, 반도체·제조 경쟁력을 지키려면 지금의 현금 유출을 통제해야 한다는 전제가 정면으로 부딪힙니다.",
            "contradiction_or_tension": conflict,
            "emotional_trigger": "15%, 45조, 생산라인 플러그, 파업 찬성률처럼 숫자와 이미지가 강하게 부딪히며 ‘누가 맞는가’를 판단하고 싶게 만듭니다.",
            "viral_hook_logic": "가장 강한 장면인 생산라인 중단 발언을 먼저 제시한 뒤, 성과급 15% 요구와 45조 규모, 파업 여론, 정부·산업 경쟁력 이슈를 순서대로 공개하는 반전형 후킹입니다.",
            "narrative_structure": "충격 발언 제시 → 성과급 요구 공개 → 45조라는 숫자 확대 → 회사의 강경 대응 → 파업·정부·여론 확산 → 돈 싸움인지 생존 전략인지 질문",
            "reusable_structure": "강한 발언으로 멈춰 세우고, 요구 조건과 숫자를 보여준 뒤, 이해관계자의 논리를 충돌시켜 마지막에 독자가 판단하게 만드는 구조",
            "slide_seed": {
                "slide_1": "삼성은 왜 직원들과 정면충돌했을까요?",
                "slide_2": f"시작은 성과급이었습니다. {shorten(demand, 95)}",
                "slide_3": f"하지만 숫자는 커졌습니다. {shorten(amount, 95)}",
                "slide_4": f"회사의 대답은 차가웠습니다. {shorten(plug, 95)}",
                "slide_5": f"갈등은 회사 밖으로 번졌습니다. {shorten(strike or gov, 95)}",
                "slide_6": "이건 돈 싸움일까요, 미래 생존 전략일까요?",
            },
            "fact_roles": {"demand": demand, "amount": amount, "company_response": plug, "strike_or_public": strike, "government_or_industry": gov, "future_investment": future},
        }

    if event_type == "park_donation":
        park = find_first_fact(facts, ["공원", "주차장", "안양"], "지금은 시민들이 이용하는 평화로운 공원으로 남아 있습니다")
        donation = find_first_fact(facts, ["기증", "부지"], "이 공간은 한 기업의 부지 기증에서 시작됐습니다")
        union = find_first_fact(facts, ["노조", "반발", "직원"], "하지만 내부에서는 직원과 노조의 반발도 있었습니다")
        conflict = "시민에게 남은 공익적 결과와 내부 구성원이 느낀 생존 불안이 충돌한 구조"
        return {
            "original_topic": original_topic,
            "main_topic_sentence": f"{original_topic}: {conflict}",
            "audience_pain": "시청자는 공원이라는 아름다운 결과만 기억하기 쉽지만, 그 공간이 만들어지는 과정에 있었던 기업의 결정, 내부 구성원의 불안, 지역사회 이익을 함께 보지 못하기 쉽습니다.",
            "hidden_assumption": "좋은 결과로 남은 공간이라면 그 과정도 모두 좋은 이야기였을 것이라는 전제가 숨어 있습니다.",
            "contradiction_or_tension": conflict,
            "emotional_trigger": "평화로운 공원과 그 뒤에 있던 반발이 대비되며 미담의 뒷면을 확인하고 싶게 만듭니다.",
            "viral_hook_logic": "현재의 아름다운 공원을 먼저 보여준 뒤, 그 공간을 만든 기부와 내부 반발을 뒤늦게 공개하는 반전형 후킹입니다.",
            "narrative_structure": "현재 결과 제시 → 부지·기증 배경 → 내부 반발 등장 → 공익과 생존 불안 충돌 → 현재의 아이러니 → 질문",
            "reusable_structure": "좋은 결과를 먼저 보여주고, 그 뒤에 있었던 이해관계를 단계적으로 벗겨내며 마지막에 미담을 다시 보게 만드는 구조",
            "slide_seed": {
                "slide_1": "아름다운 공원에도 숨은 이야기가 있습니다",
                "slide_2": f"겉으로는 평화로운 공간입니다. {shorten(park, 95)}",
                "slide_3": f"하지만 시작은 기부였습니다. {shorten(donation, 95)}",
                "slide_4": f"그리고 내부에선 반발이 있었습니다. {shorten(union, 95)}",
                "slide_5": f"핵심은 이 충돌입니다. {conflict}",
                "slide_6": "미담만 보고 지나쳐도 될까요?",
            },
            "fact_roles": {"public_result": park, "donation": donation, "internal_conflict": union},
        }

    if event_type in ["labor_conflict", "legal_conflict"]:
        fact1 = facts[0].get("source", "") if facts and isinstance(facts[0], dict) else (facts[0] if facts else primary_claim)
        fact2 = facts[1].get("source", "") if len(facts) > 1 and isinstance(facts[1], dict) else (facts[1] if len(facts) > 1 else "갈등의 조건이 점점 커졌습니다")
        conflict = f"{actor_line} 사이에서 요구와 책임이 충돌하는 구조"
        return {
            "original_topic": original_topic,
            "main_topic_sentence": f"{original_topic}: {conflict}",
            "audience_pain": f"시청자는 누가 맞는지부터 판단하려 하지만, 먼저 봐야 할 것은 {actor_line}가 각각 무엇을 요구하고 무엇을 잃을 수 있었는지입니다.",
            "hidden_assumption": "한쪽이 선명하게 옳아 보이는 사건에도, 실제로는 각 주체가 감수해야 할 비용과 위험이 따로 존재합니다.",
            "contradiction_or_tension": conflict,
            "emotional_trigger": "강한 요구와 차가운 대응이 부딪히며 독자가 어느 편이 설득력 있는지 판단하고 싶게 만듭니다.",
            "viral_hook_logic": "가장 자극적인 요구나 대응을 먼저 보여주고, 이후 각 주체의 이해관계를 분해해 독자가 다시 판단하게 만드는 구조입니다.",
            "narrative_structure": "강한 장면 제시 → 요구 조건 공개 → 이해관계자 분해 → 충돌 지점 확대 → 현재 쟁점 정리 → 질문",
            "reusable_structure": "요구와 대응을 먼저 세우고, 각 주체의 손익을 비교한 뒤, 마지막에 판단 질문으로 닫는 구조",
            "slide_seed": {"slide_1": f"{original_topic}\n결론부터 보면 놓치는 게 있습니다", "slide_2": fact1, "slide_3": fact2, "slide_4": conflict, "slide_5": "이 사건은 요구와 책임이 충돌한 이야기입니다", "slide_6": "당신은 어느 쪽의 논리가 더 설득력 있나요?"},
            "fact_roles": {"fact1": fact1, "fact2": fact2},
        }

    fact1 = facts[0].get("source", "") if facts and isinstance(facts[0], dict) else (facts[0] if facts else primary_claim)
    conflict = "사람들이 보는 결론과 실제로 확인해야 할 기준 사이의 간극"
    return {
        "original_topic": original_topic,
        "main_topic_sentence": f"{original_topic}: {conflict}",
        "audience_pain": "시청자는 결론부터 소비하지만, 실제로는 어떤 근거와 전제가 그 결론을 만들었는지를 놓치기 쉽습니다.",
        "hidden_assumption": "화제가 되는 주제라면 중요한 이유도 이미 충분히 설명됐을 것이라는 착각이 숨어 있습니다.",
        "contradiction_or_tension": conflict,
        "emotional_trigger": "몰랐던 기준을 발견했다는 느낌과 지금 다시 확인해야 한다는 긴급감이 생깁니다.",
        "viral_hook_logic": "익숙한 결론을 먼저 보여준 뒤, 그 결론을 다시 보게 만드는 숨은 기준을 꺼내는 구조입니다.",
        "narrative_structure": "익숙한 결론 제시 → 놓친 전제 공개 → 근거 확인 → 판단 기준 정리 → 질문",
        "reusable_structure": "결론을 먼저 제시하고, 그 결론이 만들어진 근거와 전제를 분해해 독자가 다시 판단하게 만드는 구조",
        "slide_seed": {"slide_1": f"{original_topic}\n그냥 넘기면 놓치는 게 있습니다", "slide_2": fact1, "slide_3": conflict, "slide_4": "중요한 건 결론보다 판단 기준입니다", "slide_5": "이 기준으로 다시 보면 이야기가 달라집니다", "slide_6": "이 기준은 저장해두고 다시 확인해보세요"},
        "fact_roles": {"fact1": fact1},
    }


def build_cardnews_seed(slots, timeline, fact_cards):
    slide_seed = slots.get("slide_seed", {})
    return {
        "angle_candidates": [slots.get("original_topic", ""), slots.get("main_topic_sentence", "")],
        "problem_candidates": [slots.get("audience_pain", ""), slots.get("contradiction_or_tension", "")],
        "slide_roles": list(slide_seed.keys()),
        "slide_seed": slide_seed,
        "timeline_seeds": timeline[:6],
        "fact_seeds": fact_cards[:8],
        "fact_roles": slots.get("fact_roles", {}),
    }


def build_source_qa(analysis):
    return [
        {"question": "이 원본은 한 문장으로 무엇인가?", "answer": analysis["main_topic_sentence"], "basis": analysis["primary_claim"]},
        {"question": "카드뉴스로 만들 때 가장 먼저 보여줄 포인트는?", "answer": analysis["contradiction_or_tension"], "basis": analysis["viral_hook_logic"]},
        {"question": "독자가 놓치기 쉬운 부분은?", "answer": analysis["audience_pain"], "basis": analysis["hidden_assumption"]},
    ]


def interpret_source(title, channel_name, transcript, conditions):
    clean_transcript = normalize_source_text(transcript)
    chunks = build_chunks(clean_transcript)
    focus_tokens = tokenize_focus(" ".join([conditions.get("focus_question", ""), conditions.get("focus_keywords", "")]))
    keywords = extract_keywords(clean_transcript, focus_tokens=focus_tokens)
    domain = detect_domain(title, clean_transcript, conditions["source_domain"])
    event_type = detect_event_type(title, clean_transcript, keywords)
    source_kind = detect_source_kind(domain, clean_transcript, event_type)
    actor_map = make_actor_map(clean_transcript, chunks, focus_tokens)
    fact_cards = extract_fact_cards(clean_transcript, chunks, keywords, focus_tokens)
    timeline = make_timeline(clean_transcript, chunks, keywords, focus_tokens)

    original_topic = topic_from_source(title, event_type, keywords, fact_cards)
    claim_candidates = pick_scored_sentences(clean_transcript, keywords, limit=12, tokens=CLAIM_TOKENS + EVIDENCE_TOKENS, focus_tokens=focus_tokens)
    primary_claim_raw = claim_candidates[0] if claim_candidates else original_topic
    primary_claim = cite_sentence(primary_claim_raw, chunks)

    slots = build_interpretation_slots(event_type, original_topic, primary_claim, fact_cards, actor_map, conditions)
    original_topic = slots["original_topic"]
    main_topic_sentence = slots["main_topic_sentence"]

    sub_claims, dup_sub = dedup_sentences(claim_candidates[1:], limit=4)
    sub_claims_cited = cite_list(sub_claims, chunks, 4)
    evidence_points = [card["source"] for card in fact_cards]
    cause_effect = [item["event"] for item in timeline[:5]]
    risk_sentences = find_sentences_with(clean_transcript, ["주의", "위험", "리스크", "아닙니다", "하지만", "반대로", "조심", "법정", "망하", "위험", "폐쇄"], 6, focus_tokens)
    risk_notes = cite_list(risk_sentences, chunks, 5) or ["원문에서 단정하기 어려운 부분은 카드뉴스에서 과장하지 않는 편이 안전합니다"]
    if conditions.get("avoid"):
        risk_notes.append(f"제외 관점: {conditions['avoid']}")

    summary_sentences, dup_summary = dedup_sentences(claim_candidates, limit=7 if conditions["detail_level"] in ["디테일", "매우 디테일"] else 5)
    if not summary_sentences:
        summary_sentences = [card.get("source", "") for card in fact_cards[:5]]
    summary = "\n".join([f"- {cite_sentence(s, chunks) if '[' not in s else s}" for s in summary_sentences if clean(s)])

    source_index = {"total_chunks": len(chunks), "top_keywords": keywords[:12], "focus_tokens": focus_tokens, "domain": domain, "source_kind": source_kind, "event_type": event_type, "chunk_preview": chunks[:5]}
    dedup_report = {"removed_from_sub_claims": [shorten(s, 120) for s in dup_sub[:6]], "removed_from_summary": [shorten(s, 120) for s in dup_summary[:6]]}
    cardnews_seed = build_cardnews_seed(slots, timeline, fact_cards)
    context_background = f"분야: {domain}. 원본 유형: {source_kind}. 사건 유형: {event_type}. 관점: {conditions['viewpoint']}. 원문 충실도: {conditions['fidelity_level']}. 추론 허용도: {conditions['inference_level']}."
    if conditions.get("memo"):
        context_background += f" 메모: {conditions['memo']}"

    analysis = {
        "summary": summary,
        "key_claim": primary_claim,
        "hook_point": cite_sentence(split_sentences(clean_transcript)[0], chunks) if split_sentences(clean_transcript) else original_topic,
        "structure_note": slots["narrative_structure"],
        "visual_note": "원본 주제 카드뉴스 메뉴에서 이미지 비율, 스타일, 카피 포함 여부를 선택해 재가공",
        "eafi_application": f"{main_topic_sentence} 원본 해석 데이터를 바탕으로 원본 주제 카드뉴스 메뉴에서 카드뉴스 설계 가능",
        "keywords": ", ".join(keywords),
        "source_domain": domain,
        "source_kind": source_kind,
        "event_type": event_type,
        "clean_transcript": clean_transcript,
        "source_chunks": json.dumps(chunks, ensure_ascii=False),
        "source_index": json.dumps(source_index, ensure_ascii=False, indent=2),
        "original_topic": original_topic,
        "main_topic_sentence": main_topic_sentence,
        "primary_claim": primary_claim,
        "sub_claims": json.dumps(sub_claims_cited, ensure_ascii=False),
        "evidence_points": json.dumps(evidence_points, ensure_ascii=False),
        "context_background": context_background,
        "event_timeline": json.dumps(timeline, ensure_ascii=False),
        "actor_map": json.dumps(actor_map, ensure_ascii=False),
        "cause_effect_chain": json.dumps(cause_effect, ensure_ascii=False),
        "audience_pain": slots["audience_pain"],
        "hidden_assumption": slots["hidden_assumption"],
        "contradiction_or_tension": slots["contradiction_or_tension"],
        "emotional_trigger": slots["emotional_trigger"],
        "viral_hook_logic": slots["viral_hook_logic"],
        "narrative_structure": slots["narrative_structure"],
        "reusable_structure": slots["reusable_structure"],
        "risk_notes": json.dumps(risk_notes, ensure_ascii=False),
        "cardnews_seed": json.dumps(cardnews_seed, ensure_ascii=False, indent=2),
        "interpretation_slots": json.dumps(slots, ensure_ascii=False, indent=2),
        "dedup_report": json.dumps(dedup_report, ensure_ascii=False, indent=2),
    }
    analysis["source_grounded_qa"] = json.dumps(build_source_qa(analysis), ensure_ascii=False, indent=2)
    interpretation_report = {"conditions": conditions, "source_index": source_index, "dedup_report": dedup_report, "interpretation_slots": slots, "actor_map": actor_map, "event_timeline": timeline, "fact_cards": fact_cards, "cardnews_seed": cardnews_seed}
    analysis["interpretation_report"] = json.dumps(interpretation_report, ensure_ascii=False, indent=2)
    return analysis


# ---------- Save / reference ----------

def save_analysis(video_id, url, title, channel_name, transcript, analysis, conditions, source_type="YouTube"):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO youtube_video_analyses
        (video_id, url, title, channel_name, transcript, summary, hook_point, structure_note, visual_note,
         eafi_application, keywords, key_claim, source_type, analysis_memo, interpretation_conditions,
         source_domain, source_kind, event_type, interpretation_goal, viewpoint, detail_level, fidelity_level, inference_level,
         clean_transcript, source_chunks, source_index, original_topic, primary_claim, sub_claims, evidence_points,
         context_background, event_timeline, actor_map, cause_effect_chain, audience_pain, hidden_assumption,
         contradiction_or_tension, emotional_trigger, viral_hook_logic, narrative_structure, reusable_structure,
         risk_notes, cardnews_seed, source_grounded_qa, interpretation_report, focus_question, focus_keywords,
         main_topic_sentence, dedup_report, interpretation_slots, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        video_id, url, title, channel_name, transcript, analysis["summary"], analysis["hook_point"], analysis["structure_note"],
        analysis["visual_note"], analysis["eafi_application"], analysis["keywords"], analysis["key_claim"], source_type,
        conditions.get("memo", ""), json.dumps(conditions, ensure_ascii=False), analysis["source_domain"], analysis["source_kind"],
        analysis["event_type"], conditions["interpretation_goal"], conditions["viewpoint"], conditions["detail_level"],
        conditions["fidelity_level"], conditions["inference_level"], analysis["clean_transcript"], analysis["source_chunks"],
        analysis["source_index"], analysis["original_topic"], analysis["primary_claim"], analysis["sub_claims"],
        analysis["evidence_points"], analysis["context_background"], analysis["event_timeline"], analysis["actor_map"],
        analysis["cause_effect_chain"], analysis["audience_pain"], analysis["hidden_assumption"], analysis["contradiction_or_tension"],
        analysis["emotional_trigger"], analysis["viral_hook_logic"], analysis["narrative_structure"], analysis["reusable_structure"],
        analysis["risk_notes"], analysis["cardnews_seed"], analysis["source_grounded_qa"], analysis["interpretation_report"],
        conditions.get("focus_question", ""), conditions.get("focus_keywords", ""), analysis["main_topic_sentence"],
        analysis["dedup_report"], analysis["interpretation_slots"], datetime.now().isoformat(timespec="seconds"),
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
    """, ("YouTube", channel_name, url, "원본 해석 데이터", "동적 슬롯 기반 원본 해석", "A", f"분야: {analysis['source_domain']} / 유형: {analysis['source_kind']} / 사건: {analysis['event_type']} / 키워드: {analysis['keywords']}", datetime.now().isoformat(timespec="seconds")))
    channel_id = cur.lastrowid
    total_score = sum(scores.values())
    structure_pack = f"원본 주제:\n{analysis['original_topic']}\n\n메인 토픽:\n{analysis['main_topic_sentence']}\n\n해석 슬롯:\n{analysis['interpretation_slots']}\n\n카드뉴스 씨앗:\n{analysis['cardnews_seed']}\n\n해석 리포트:\n{analysis['interpretation_report']}"
    cur.execute("""
        INSERT INTO content_references
        (channel_id, title, url, hook_point, structure_note, visual_note, eafi_application,
         lead_potential_score, visual_score, hook_score, seo_score, conversion_score, total_score, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (channel_id, clean(title, analysis["original_topic"]), url, analysis["hook_point"], structure_pack, analysis["visual_note"], analysis["eafi_application"], scores["lead"], scores["visual"], scores["hook"], scores["seo"], scores["conversion"], total_score, "원본 해석", datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()


def load_recent_analyses():
    conn = connect_db()
    try:
        df = pd.read_sql_query("""
            SELECT id, video_id, title, channel_name, source_domain, source_kind, event_type, interpretation_goal,
                   original_topic, main_topic_sentence, primary_claim, audience_pain, keywords, created_at
            FROM youtube_video_analyses
            ORDER BY id DESC LIMIT 30
        """, conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


# ---------- UI ----------

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
        focus_question = st.text_input("해석 질문", placeholder="예: 이 영상에서 삼성과 노조가 충돌한 핵심 이유는 무엇인가?")
        emphasis = st.text_input("강조할 해석 관점", placeholder="예: 성과급 요구, 미래 투자, 파업 여론, 산업 경쟁력")
    with c5:
        focus_keywords = st.text_input("중심 키워드", placeholder="예: 삼성, 노조, 성과급, 파업, 공장, 플러그")
        avoid = st.text_input("제외할 해석 관점", placeholder="예: 원문 밖 단정, 과한 정치 해석")
    memo = st.text_input("분석 메모", placeholder="선택 입력: 왜 수집했는지, 나중에 어떤 카드뉴스로 쓸지 기록")
    return {"interpretation_goal": interpretation_goal, "source_domain": source_domain, "viewpoint": viewpoint, "detail_level": detail_level, "fidelity_level": fidelity_level, "inference_level": inference_level, "focus_question": focus_question, "focus_keywords": focus_keywords, "emphasis": emphasis, "avoid": avoid, "memo": memo}


def build_payload_from_transcript(video_id, normalized_url, title, channel_name, transcript, scores, conditions, debug=None, source_type="YouTube"):
    analysis = interpret_source(title, channel_name, transcript, conditions)
    return {"video_id": video_id, "url": normalized_url, "title": title, "channel_name": channel_name, "transcript": transcript, "analysis": analysis, "scores": scores, "debug": debug or {}, "source_type": source_type, "conditions": conditions}


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
    st.write(f"**원본 유형:** {analysis['source_kind']} / {analysis['event_type']}")
    st.write(f"**키워드:** {analysis['keywords']}")

    with st.expander("적용된 원본 해석 조건", expanded=True):
        st.json(payload["conditions"])
    if payload.get("debug"):
        with st.expander("진단 로그 보기"):
            st.json(payload["debug"])

    st.markdown("#### 원본 주제")
    st.text_area("original_topic", value=analysis["original_topic"], height=70)
    st.markdown("#### 메인 토픽 문장")
    st.text_area("main_topic_sentence", value=analysis["main_topic_sentence"], height=90)
    st.markdown("#### 핵심 주장")
    st.text_area("primary_claim", value=analysis["primary_claim"], height=90)
    st.markdown("#### 독자 문제")
    st.text_area("audience_pain", value=analysis["audience_pain"], height=115)
    st.markdown("#### 숨은 전제")
    st.text_area("hidden_assumption", value=analysis["hidden_assumption"], height=95)
    st.markdown("#### 긴장/대립 구조")
    st.text_area("contradiction_or_tension", value=analysis["contradiction_or_tension"], height=90)
    st.markdown("#### 감정 트리거")
    st.text_area("emotional_trigger", value=analysis["emotional_trigger"], height=95)
    st.markdown("#### 바이럴 후킹 로직")
    st.text_area("viral_hook_logic", value=analysis["viral_hook_logic"], height=115)
    st.markdown("#### 전개 구조")
    st.text_area("narrative_structure", value=analysis["narrative_structure"], height=90)
    st.markdown("#### 재사용 가능한 구조")
    st.text_area("reusable_structure", value=analysis["reusable_structure"], height=105)
    st.markdown("#### 핵심 요약")
    st.text_area("summary", value=analysis["summary"], height=170)

    render_json_list("동적 해석 슬롯", analysis["interpretation_slots"])
    render_json_list("등장 주체", analysis["actor_map"])
    render_json_list("사건/전개 타임라인", analysis["event_timeline"])
    render_json_list("근거 포인트", analysis["evidence_points"])
    render_json_list("카드뉴스 씨앗 데이터", analysis["cardnews_seed"])
    render_json_list("소스 기반 Q&A", analysis["source_grounded_qa"])

    with st.expander("중복 제거 리포트"):
        st.code(analysis["dedup_report"])
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
            save_analysis(payload["video_id"], payload["url"], payload["title"], payload["channel_name"], payload["transcript"], payload["analysis"], payload["conditions"], payload.get("source_type", "YouTube"))
            st.success("원본 해석 결과를 저장했습니다. 원본 주제 카드뉴스 메뉴에서 사용할 수 있습니다.")
    with col_b:
        if st.button("참고 콘텐츠 DB로 저장"):
            save_analysis(payload["video_id"], payload["url"], payload["title"], payload["channel_name"], payload["transcript"], payload["analysis"], payload["conditions"], payload.get("source_type", "YouTube"))
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
    st.caption("원문 스크립트에서 사건 유형을 감지하고, 독자문제·숨은전제·긴장구조·후킹로직·전개구조를 원본별로 자동 생성합니다.")
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
                st.session_state["yt_analysis_payload"] = build_payload_from_transcript(video_id, normalized_url, title, channel_name, transcript, scores, conditions, debug, "YouTube")
                st.success("자막 수집과 원본 해석을 완료했습니다.")
            except Exception as e:
                st.error(f"분석 실패: {e}")
                with st.expander("에러 상세 보기"):
                    st.code(traceback.format_exc())
                st.info("자막이 없거나 YouTube가 서버 접근을 막은 경우일 수 있습니다. 아래 직접 붙여넣기 방식으로 우회할 수 있습니다.")
        if url:
            video_id = get_video_id(url)
            if st.button("사용 가능한 자막 목록만 확인"):
                if not video_id:
                    st.error("video_id를 찾지 못했습니다.")
                else:
                    try:
                        st.dataframe(pd.DataFrame(list_available_transcripts(video_id)), use_container_width=True, hide_index=True)
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
                st.session_state["yt_analysis_payload"] = build_payload_from_transcript(video_id, normalized_url, title, manual_channel, transcript, scores, conditions, {"method": "manual_paste", "transcript_length": len(transcript)}, "Manual")
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
