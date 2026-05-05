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
SOURCE_DOMAINS = ["자동 감지", "영상/마케팅", "시장/투자", "기업/주식", "사건/논쟁", "트렌드/이슈", "교육/노하우", "라이프스타일", "기술/AI", "직접 입력"]
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
    "화면", "현재", "당장", "과연", "여러분의", "박제되어", "가리고", "있을까요",
])
DOMAIN_HINTS = {
    "시장/투자": ["코인", "비트코인", "주식", "시장", "투자", "가격", "차트", "급등", "급락", "상승", "하락"],
    "기업/주식": ["주가", "시총", "상장", "고점", "저점", "실적", "매출", "영업손실", "전환사채", "공시", "배터리", "리튬", "2차전지"],
    "영상/마케팅": ["영상", "촬영", "편집", "마케팅", "브랜드", "광고", "콘텐츠", "유튜브", "전환", "CTA"],
    "기술/AI": ["ai", "인공지능", "기술", "개발", "앱", "서비스", "툴", "자동화", "모델"],
    "교육/노하우": ["방법", "노하우", "강의", "튜토리얼", "체크리스트", "공부", "설명"],
    "사건/논쟁": ["노조", "회사", "직원", "시민", "공장", "사건", "논란", "갈등", "반발", "요구", "법정", "기증", "주차장", "파업", "성과급"],
    "트렌드/이슈": ["요즘", "논란", "이슈", "트렌드", "화제", "커뮤니티", "밈"],
}

RESULT_TOKENS = ["폭락", "급락", "하락", "무너", "몰락", "붕괴", "떨어", "빠졌", "상승", "급등", "올랐", "커졌", "확산", "논란", "문제", "위기", "전환", "바뀌"]
EXPECTATION_TOKENS = ["기대", "미래", "성장", "스토리", "전망", "호재", "비전", "사업", "개발", "투자", "가능성", "약속", "꿈", "계획", "수혜", "테마"]
REALITY_TOKENS = ["실적", "매출", "영업", "적자", "손실", "부채", "현금", "공시", "자금", "전환사채", "유상증자", "비용", "리스크", "위험", "문제", "지연", "실패", "논란", "검증", "현실"]
CONFLICT_TOKENS = ["하지만", "그런데", "반면", "문제는", "그러나", "결국", "다만", "반대로", "충돌", "갈등", "요구", "반발", "대신", "대립"]
STAKEHOLDER_TOKENS = ["투자자", "주주", "개미", "회사", "경영진", "직원", "노조", "정부", "소비자", "시민", "고객", "시장", "기관", "외국인"]
NUM_PATTERN = re.compile(r"\d+(?:[,.]\d+)?\s*(?:만원|천원|원|조|억|%|배|년|개월|명|개|건|위|달러|USDT)?")


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
        "source_grounded_qa": "TEXT", "interpretation_report": "TEXT", "focus_question": "TEXT", "focus_keywords": "TEXT",
        "main_topic_sentence": "TEXT", "dedup_report": "TEXT", "interpretation_slots": "TEXT", "event_type": "TEXT",
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


def shorten(text, max_len=170):
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
        freq[token] = freq.get(token, 0) + 5
    return [w for w, _ in sorted(freq.items(), key=lambda x: x[1], reverse=True)[:topn]]


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


def has_any(text, words):
    return any(word in clean(text) for word in words)


def score_sentence(sentence, tokens):
    score = 0
    score += sum(3 for token in tokens if token in sentence)
    score += min(5, len(NUM_PATTERN.findall(sentence)))
    return score


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
            transcript = transcript_list.find_transcript([available_codes[0]])
        text = fetched_transcript_to_text(transcript.fetch())
        if not text:
            raise ValueError("자막 객체는 가져왔지만 text 필드가 비어 있습니다.")
        return text, debug
    except Exception as fallback_error:
        debug["error_stage"] = "fallback_failed"
        debug["error_message"] = repr(fallback_error)
        raise


def list_available_transcripts(video_id):
    ytt_api = YouTubeTranscriptApi()
    transcript_list = ytt_api.list(video_id)
    return [{"language": getattr(t, "language", ""), "language_code": getattr(t, "language_code", ""), "is_generated": getattr(t, "is_generated", ""), "is_translatable": getattr(t, "is_translatable", "")} for t in transcript_list]


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


def clean_citation(text):
    return re.sub(r"\s*\[[sS]\d+\]\s*$", "", clean(text)).strip()


def detect_domain(title, transcript, selected):
    if selected not in ["자동 감지", "직접 입력"]:
        return selected
    text = f"{title} {transcript[:5000]}".lower()
    scores = {domain: sum(1 for hint in hints if hint.lower() in text) for domain, hints in DOMAIN_HINTS.items()}
    top = max(scores.items(), key=lambda x: x[1])
    return top[0] if top[1] > 0 else "트렌드/이슈"


def pick_best(sentences, tokens, fallback=""):
    scored = [(score_sentence(s, tokens), idx, s) for idx, s in enumerate(sentences)]
    scored = [item for item in scored if item[0] > 0]
    if not scored:
        return fallback
    scored.sort(key=lambda x: (x[0], -x[1]), reverse=True)
    return scored[0][2]


def pick_many(sentences, tokens, limit=8):
    scored = [(score_sentence(s, tokens), idx, s) for idx, s in enumerate(sentences)]
    scored = [item for item in scored if item[0] > 0]
    scored.sort(key=lambda x: (x[0], -x[1]), reverse=True)
    picked, _ = dedup_sentences([s for _, _, s in scored], limit=limit)
    return picked


def extract_subject(title, keywords, transcript):
    source = title if not is_bad_title(title) else " ".join(keywords[:8])
    words = re.findall(r"[가-힣A-Za-zA-Z0-9]{2,}", source)
    filtered = [w for w in words if w.lower() not in NOISE_WORDS and not NUM_PATTERN.fullmatch(w)]
    if filtered:
        return filtered[0]
    return keywords[0] if keywords else "이 주제"


def infer_mode(domain, sentences):
    corpus = " ".join(sentences[:80])
    if domain in ["시장/투자", "기업/주식"] or has_any(corpus, ["주가", "가격", "시총", "상장", "차트", "고점", "저점", "투자자"]):
        return "market_or_company_shift"
    if has_any(corpus, ["노조", "직원", "회사", "반발", "요구", "파업", "갈등", "소송", "법원"]):
        return "stakeholder_conflict"
    if has_any(corpus, ["방법", "노하우", "체크", "순서", "단계", "해야", "하지 마"]):
        return "howto_or_warning"
    return "issue_context"


def build_context_profile(title, transcript, keywords, domain, focus_tokens, chunks):
    sentences = split_sentences(transcript)
    subject = extract_subject(title, keywords, transcript)
    mode = infer_mode(domain, sentences)
    title_sentence = title if not is_bad_title(title) else ""
    result_sentence = title_sentence or pick_best(sentences, RESULT_TOKENS + ["에서", "까지"], fallback=sentences[0] if sentences else subject)
    metric_sentence = pick_best(sentences, RESULT_TOKENS + ["만원", "천원", "%", "조", "억", "시총", "고점", "저점", "폭락", "급락"], fallback=result_sentence)
    expectation_sentence = pick_best(sentences, EXPECTATION_TOKENS, fallback="")
    reality_sentence = pick_best(sentences, REALITY_TOKENS, fallback="")
    conflict_sentence = pick_best(sentences, CONFLICT_TOKENS + REALITY_TOKENS, fallback=reality_sentence or result_sentence)
    stakeholder_sentences = pick_many(sentences, STAKEHOLDER_TOKENS, limit=7)
    evidence_sentences = pick_many(sentences, RESULT_TOKENS + EXPECTATION_TOKENS + REALITY_TOKENS + CONFLICT_TOKENS + STAKEHOLDER_TOKENS, limit=10)
    number_sentences = [s for s in sentences if NUM_PATTERN.search(s)]
    if number_sentences:
        evidence_sentences = dedup_sentences(number_sentences[:8] + evidence_sentences, limit=10)[0]

    def cited(s):
        return cite_sentence(s, chunks) if s else ""

    return {
        "subject": subject,
        "mode": mode,
        "result_signal": cited(result_sentence),
        "metric_signal": cited(metric_sentence),
        "expectation_signal": cited(expectation_sentence),
        "reality_signal": cited(reality_sentence),
        "conflict_signal": cited(conflict_sentence),
        "stakeholder_signals": [cited(s) for s in stakeholder_sentences],
        "evidence_signals": [cited(s) for s in evidence_sentences],
    }


def phrase_from_signal(signal, fallback):
    text = clean_citation(signal)
    text = re.sub(r"^하지만\s*", "", text)
    text = re.sub(r"^그런데\s*", "", text)
    return shorten(text, 95) if text else fallback


def build_dynamic_slots(original_topic, primary_claim, profile, conditions):
    subject = profile["subject"]
    mode = profile["mode"]
    result = phrase_from_signal(profile["result_signal"], f"{subject}을 둘러싼 강한 결과")
    metric = phrase_from_signal(profile["metric_signal"], result)
    expectation = phrase_from_signal(profile["expectation_signal"], "사람들이 먼저 믿었던 기대와 서사")
    reality = phrase_from_signal(profile["reality_signal"], "그 기대를 다시 검증하게 만든 현실 신호")
    conflict = phrase_from_signal(profile["conflict_signal"], "결과와 원인 사이에서 드러난 충돌 지점")

    if mode == "market_or_company_shift":
        tension = f"{expectation}와 {reality} 사이의 간극"
        audience_pain = f"시청자는 {metric}에 먼저 반응하지만, 실제 핵심은 그 결과를 만든 기대와 그 기대를 흔든 현실 신호를 함께 보는 것입니다."
        hidden = f"가격이나 숫자가 크게 움직이면 이유도 이미 명확해 보이지만, 원문은 {expectation}가 어떻게 만들어졌고 {reality}가 어떻게 드러났는지를 같이 봐야 한다는 전제를 깔고 있습니다."
        emotion = f"{metric}처럼 눈에 박히는 숫자나 결과가 충격을 만들고, 뒤이어 {reality}가 드러나면서 불안과 재판단 욕구를 자극합니다."
        viral = f"가장 강한 결과인 {metric}을 먼저 보여준 뒤, 그 결과를 만든 기대({expectation})와 현실 검증({reality})을 순서대로 공개하는 구조입니다."
        narrative = "강한 결과 제시 → 과거 기대 확인 → 현실 신호 공개 → 리스크/갈등 정리 → 판단 기준 제시 → 질문"
        reusable = "큰 결과로 시선을 멈춰 세우고, 그 결과를 만든 기대와 현실의 간극을 분해한 뒤, 마지막에 독자가 판단할 기준으로 닫는 구조"
        ending = "이건 다시 볼 기회일까요, 아직 확인해야 할 리스크일까요?"
        slide_seed = {
            "slide_1": f"{subject}\n무너진 건 숫자만이 아니었습니다",
            "slide_2": f"처음엔 이런 기대가 있었습니다. {expectation}",
            "slide_3": f"하지만 현실 신호가 따라붙었습니다. {reality}",
            "slide_4": f"시장은 여기서 다시 계산하기 시작했습니다. {conflict}",
            "slide_5": f"핵심은 가격이 아니라 간극입니다. {tension}",
            "slide_6": ending,
        }
    elif mode == "stakeholder_conflict":
        tension = f"{expectation}와 {conflict}가 부딪힌 구조"
        audience_pain = f"시청자는 누가 맞는지부터 보지만, 실제로는 각 주체가 무엇을 요구했고 무엇을 감수해야 했는지 먼저 봐야 합니다."
        hidden = f"겉으로는 한쪽의 잘잘못처럼 보이지만, 원문에는 {subject}을 둘러싼 요구와 책임의 배분 문제가 숨어 있습니다."
        emotion = f"강한 요구와 반응이 부딪히며 독자가 어느 쪽 논리가 더 설득력 있는지 판단하고 싶게 만듭니다."
        viral = f"가장 자극적인 충돌 장면을 먼저 보여주고, 그 뒤에 요구 조건과 이해관계, 현실적 비용을 차례대로 풀어내는 구조입니다."
        narrative = "충돌 장면 제시 → 요구 조건 공개 → 이해관계자 분해 → 책임/비용 대립 → 현재 쟁점 정리 → 질문"
        reusable = "한쪽 주장으로 시작하되, 상대 논리와 감수해야 할 비용을 함께 보여주며 독자가 판단하게 만드는 구조"
        ending = "당신은 어느 쪽의 논리가 더 설득력 있다고 보시나요?"
        slide_seed = {
            "slide_1": f"{subject}\n겉으로 보이는 싸움이 전부는 아닙니다",
            "slide_2": f"먼저 요구 조건을 봐야 합니다. {expectation or primary_claim}",
            "slide_3": f"갈등은 여기서 커졌습니다. {conflict}",
            "slide_4": f"각자 감수해야 할 비용이 달랐습니다. {reality}",
            "slide_5": f"핵심은 누가 맞느냐보다 무엇을 잃느냐입니다. {tension}",
            "slide_6": ending,
        }
    elif mode == "howto_or_warning":
        tension = f"사람들이 쉽게 하는 판단과 실제로 확인해야 할 기준의 차이"
        audience_pain = f"시청자는 결론이나 팁만 가져가려 하지만, 실제로는 왜 그렇게 해야 하는지와 언제 조심해야 하는지를 함께 알아야 합니다."
        hidden = f"간단한 방법처럼 보여도, 원문에는 {reality or conflict} 같은 조건이 붙어 있습니다."
        emotion = "몰랐던 기준을 발견했다는 느낌과 지금 바로 확인해야 한다는 긴급감이 생깁니다."
        viral = "많이 하는 실수나 강한 결론을 먼저 던진 뒤, 이유와 적용 기준을 단계적으로 풀어내는 구조입니다."
        narrative = "흔한 실수 제시 → 이유 설명 → 적용 조건 → 주의점 → 체크 기준 → 행동 유도"
        reusable = "일상적 문제를 먼저 던지고, 원리와 조건을 설명한 뒤, 마지막에 체크리스트로 저장하게 만드는 구조"
        ending = "이 기준을 알았다면, 다음엔 어디부터 확인하시겠어요?"
        slide_seed = {
            "slide_1": f"{subject}\n그냥 따라 하면 놓치는 게 있습니다",
            "slide_2": f"먼저 이유를 봐야 합니다. {expectation or primary_claim}",
            "slide_3": f"중요한 건 조건입니다. {reality or conflict}",
            "slide_4": f"여기서 실수가 갈립니다. {conflict}",
            "slide_5": f"정리하면 기준은 하나입니다. {tension}",
            "slide_6": ending,
        }
    else:
        tension = f"사람들이 본 결과와 실제로 확인해야 할 맥락 사이의 간극"
        audience_pain = f"시청자는 {result}라는 결론에 먼저 반응하지만, 실제로는 그 결론을 만든 배경과 이해관계를 같이 봐야 합니다."
        hidden = f"화제가 된 결과만 보면 중요한 이유가 이미 설명된 것처럼 보이지만, 원문에는 {conflict}라는 숨은 조건이 있습니다."
        emotion = "익숙한 결론 뒤에 다른 맥락이 있었다는 반전감과 다시 판단하고 싶은 궁금증이 생깁니다."
        viral = f"강한 결과({result})를 먼저 제시하고, 뒤이어 배경과 충돌 지점을 공개해 독자가 다시 보게 만드는 구조입니다."
        narrative = "결과 제시 → 배경 공개 → 이해관계자 등장 → 충돌 지점 정리 → 판단 기준 제시 → 질문"
        reusable = "결과로 후킹하고, 원인과 이해관계를 분해한 뒤, 마지막에 독자가 판단할 기준을 남기는 구조"
        ending = "이 이야기를 다시 본다면, 가장 먼저 어떤 기준을 확인해야 할까요?"
        slide_seed = {
            "slide_1": f"{subject}\n결론만 보면 놓치는 게 있습니다",
            "slide_2": f"먼저 배경을 봐야 합니다. {expectation or primary_claim}",
            "slide_3": f"문제는 여기서 시작됩니다. {conflict}",
            "slide_4": f"현실 신호도 같이 봐야 합니다. {reality}",
            "slide_5": f"핵심은 이 간극입니다. {tension}",
            "slide_6": ending,
        }

    return {
        "original_topic": original_topic,
        "main_topic_sentence": f"{original_topic}: {tension}",
        "audience_pain": audience_pain,
        "hidden_assumption": hidden,
        "contradiction_or_tension": tension,
        "emotional_trigger": emotion,
        "viral_hook_logic": viral,
        "narrative_structure": narrative,
        "reusable_structure": reusable,
        "slide_seed": slide_seed,
        "fact_roles": {
            "result_signal": profile["result_signal"],
            "metric_signal": profile["metric_signal"],
            "expectation_signal": profile["expectation_signal"],
            "reality_signal": profile["reality_signal"],
            "conflict_signal": profile["conflict_signal"],
            "stakeholder_signals": profile["stakeholder_signals"],
        },
        "context_profile": profile,
    }


def build_actor_map(profile):
    rows = []
    for signal in profile.get("stakeholder_signals", [])[:7]:
        plain = clean_citation(signal)
        actor = "이해관계자"
        for token in STAKEHOLDER_TOKENS:
            if token in plain:
                actor = token
                break
        rows.append({"actor": actor, "role_or_position": signal, "related_quotes": [signal]})
    if not rows:
        rows = [{"actor": profile.get("subject", "원본 주체"), "role_or_position": profile.get("result_signal", "원본의 중심 주체"), "related_quotes": [profile.get("result_signal", "")]}]
    return rows


def build_timeline(profile):
    items = []
    ordered = [
        ("결과", profile.get("result_signal", "")),
        ("기대", profile.get("expectation_signal", "")),
        ("현실", profile.get("reality_signal", "")),
        ("충돌", profile.get("conflict_signal", "")),
    ]
    seen = set()
    for label, signal in ordered:
        if not signal:
            continue
        key = clean_citation(signal)[:50]
        if key in seen:
            continue
        seen.add(key)
        items.append({"step": len(items) + 1, "event": f"{label}: {signal}"})
    for signal in profile.get("evidence_signals", [])[:6]:
        key = clean_citation(signal)[:50]
        if key in seen:
            continue
        seen.add(key)
        items.append({"step": len(items) + 1, "event": signal})
        if len(items) >= 8:
            break
    return items


def build_cardnews_seed(slots, timeline, evidence_points):
    return {
        "angle_candidates": [slots.get("original_topic", ""), slots.get("main_topic_sentence", "")],
        "problem_candidates": [slots.get("audience_pain", ""), slots.get("contradiction_or_tension", "")],
        "slide_roles": list(slots.get("slide_seed", {}).keys()),
        "slide_seed": slots.get("slide_seed", {}),
        "timeline_seeds": timeline[:6],
        "fact_seeds": evidence_points[:8],
        "fact_roles": slots.get("fact_roles", {}),
        "context_profile": slots.get("context_profile", {}),
    }


def interpret_source(title, channel_name, transcript, conditions):
    clean_transcript = normalize_source_text(transcript)
    chunks = build_chunks(clean_transcript)
    focus_tokens = tokenize_focus(" ".join([conditions.get("focus_question", ""), conditions.get("focus_keywords", "")]))
    keywords = extract_keywords(clean_transcript, focus_tokens=focus_tokens)
    domain = detect_domain(title, clean_transcript, conditions["source_domain"])
    profile = build_context_profile(title, clean_transcript, keywords, domain, focus_tokens, chunks)
    event_type = profile["mode"]
    source_kind = {
        "market_or_company_shift": "문맥형 시장/기업 분석",
        "stakeholder_conflict": "문맥형 이해관계 갈등",
        "howto_or_warning": "문맥형 노하우/경고",
        "issue_context": "문맥형 이슈 해석",
    }.get(event_type, "문맥형 원본 해석")

    if not is_bad_title(title):
        original_topic = re.sub(r"[\"“”']", "", title).strip()
    else:
        original_topic = f"{profile['subject']}을 둘러싼 핵심 변화"

    primary_claim = profile.get("result_signal") or profile.get("metric_signal") or original_topic
    slots = build_dynamic_slots(original_topic, primary_claim, profile, conditions)
    timeline = build_timeline(profile)
    actor_map = build_actor_map(profile)
    evidence_points = profile.get("evidence_signals", [])[:10]
    sub_claims = [s for s in [profile.get("expectation_signal"), profile.get("reality_signal"), profile.get("conflict_signal")] if s]
    risk_notes = [s for s in evidence_points if has_any(s, REALITY_TOKENS + ["주의", "위험", "리스크"])] or ["원문 밖 단정은 피하고, 원문에서 확인된 결과·기대·현실 신호만 사용하세요."]
    summary_lines = [slots["main_topic_sentence"], slots["audience_pain"], slots["contradiction_or_tension"], slots["viral_hook_logic"]]
    summary = "\n".join([f"- {line}" for line in summary_lines if clean(line)])
    cardnews_seed = build_cardnews_seed(slots, timeline, evidence_points)
    source_index = {
        "total_chunks": len(chunks),
        "top_keywords": keywords[:12],
        "focus_tokens": focus_tokens,
        "domain": domain,
        "source_kind": source_kind,
        "event_type": event_type,
        "context_profile": profile,
        "chunk_preview": chunks[:5],
    }
    dedup_report = {"logic": "fixed event branch removed; generated from result/expectation/reality/conflict context slots", "removed_fixed_templates": True}
    context_background = f"분야: {domain}. 원본 유형: {source_kind}. 문맥 모드: {event_type}. 관점: {conditions['viewpoint']}. 원문 충실도: {conditions['fidelity_level']}. 추론 허용도: {conditions['inference_level']}."
    if conditions.get("memo"):
        context_background += f" 메모: {conditions['memo']}"
    analysis = {
        "summary": summary,
        "key_claim": primary_claim,
        "hook_point": profile.get("result_signal") or original_topic,
        "structure_note": slots["narrative_structure"],
        "visual_note": "원본 주제 카드뉴스 메뉴에서 이미지 비율, 스타일, 카피 포함 여부를 선택해 재가공",
        "eafi_application": f"{slots['main_topic_sentence']} 원본 해석 데이터를 바탕으로 원본 주제 카드뉴스 메뉴에서 카드뉴스 설계 가능",
        "keywords": ", ".join(keywords),
        "source_domain": domain,
        "source_kind": source_kind,
        "event_type": event_type,
        "clean_transcript": clean_transcript,
        "source_chunks": json.dumps(chunks, ensure_ascii=False),
        "source_index": json.dumps(source_index, ensure_ascii=False, indent=2),
        "original_topic": slots["original_topic"],
        "main_topic_sentence": slots["main_topic_sentence"],
        "primary_claim": primary_claim,
        "sub_claims": json.dumps(sub_claims, ensure_ascii=False),
        "evidence_points": json.dumps(evidence_points, ensure_ascii=False),
        "context_background": context_background,
        "event_timeline": json.dumps(timeline, ensure_ascii=False),
        "actor_map": json.dumps(actor_map, ensure_ascii=False),
        "cause_effect_chain": json.dumps([x["event"] for x in timeline], ensure_ascii=False),
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
    analysis["source_grounded_qa"] = json.dumps([
        {"question": "이 원본은 한 문장으로 무엇인가?", "answer": analysis["main_topic_sentence"], "basis": analysis["primary_claim"]},
        {"question": "카드뉴스로 만들 때 가장 먼저 보여줄 포인트는?", "answer": profile.get("result_signal", ""), "basis": analysis["viral_hook_logic"]},
        {"question": "독자가 놓치기 쉬운 부분은?", "answer": analysis["audience_pain"], "basis": analysis["hidden_assumption"]},
    ], ensure_ascii=False, indent=2)
    interpretation_report = {"conditions": conditions, "source_index": source_index, "dedup_report": dedup_report, "interpretation_slots": slots, "actor_map": actor_map, "event_timeline": timeline, "evidence_points": evidence_points, "cardnews_seed": cardnews_seed}
    analysis["interpretation_report"] = json.dumps(interpretation_report, ensure_ascii=False, indent=2)
    return analysis


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
    """, ("YouTube", channel_name, url, "원본 해석 데이터", "문맥 슬롯 기반 원본 해석", "A", f"분야: {analysis['source_domain']} / 유형: {analysis['source_kind']} / 문맥: {analysis['event_type']} / 키워드: {analysis['keywords']}", datetime.now().isoformat(timespec="seconds")))
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
        focus_question = st.text_input("해석 질문", placeholder="예: 이 원문에서 가장 강한 결과와 그 원인은 무엇인가?")
        emphasis = st.text_input("강조할 해석 관점", placeholder="예: 가격 변화, 기대감, 현실 신호, 리스크, 이해관계")
    with c5:
        focus_keywords = st.text_input("중심 키워드", placeholder="예: 종목명, 핵심 숫자, 사업, 실적, 리스크")
        avoid = st.text_input("제외할 해석 관점", placeholder="예: 원문 밖 단정, 매수/매도 추천")
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
    for label, key, height in [
        ("원본 주제", "original_topic", 70), ("메인 토픽 문장", "main_topic_sentence", 95), ("핵심 주장", "primary_claim", 95),
        ("독자 문제", "audience_pain", 125), ("숨은 전제", "hidden_assumption", 115), ("긴장/대립 구조", "contradiction_or_tension", 95),
        ("감정 트리거", "emotional_trigger", 115), ("바이럴 후킹 로직", "viral_hook_logic", 125),
        ("전개 구조", "narrative_structure", 95), ("재사용 가능한 구조", "reusable_structure", 115), ("핵심 요약", "summary", 170),
    ]:
        st.markdown(f"#### {label}")
        st.text_area(key, value=analysis[key], height=height)
    render_json_list("동적 해석 슬롯", analysis["interpretation_slots"])
    render_json_list("등장 주체", analysis["actor_map"])
    render_json_list("사건/전개 타임라인", analysis["event_timeline"])
    render_json_list("근거 포인트", analysis["evidence_points"])
    render_json_list("카드뉴스 씨앗 데이터", analysis["cardnews_seed"])
    render_json_list("소스 기반 Q&A", analysis["source_grounded_qa"])
    with st.expander("중복 제거/고정분기 제거 리포트"):
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
    st.caption("고정 이벤트 분기 대신, 원문에서 결과·기대·현실·갈등 신호를 추출해 문맥별 해석 슬롯을 자동 생성합니다.")
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
