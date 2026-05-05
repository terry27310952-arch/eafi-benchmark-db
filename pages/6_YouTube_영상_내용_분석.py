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
    "원본 내용 정밀 해석",
    "카드뉴스 재가공용 해석",
    "벤치마크 구조 추출",
    "바이럴 후킹 구조 분석",
    "교육형 요약 재료화",
    "브랜드/eaf 전환 관점 해석",
]
SOURCE_DOMAINS = ["자동 감지", "영상/마케팅", "시장/투자", "트렌드/이슈", "교육/노하우", "라이프스타일", "기술/AI", "직접 입력"]
VIEWPOINTS = ["콘텐츠 기획자", "브랜드 마케터", "일반 시청자", "잠재 고객", "시장 분석가", "교육자", "바이럴 편집자"]
DETAIL_LEVELS = ["핵심만", "표준", "디테일", "매우 디테일"]
FIDELITY_LEVELS = ["원문 충실", "원문+해석 균형", "재가공 중심"]
INFERENCE_LEVELS = ["보수적", "중간", "공격적"]

KOREAN_STOPWORDS = set([
    "그리고", "그런데", "그래서", "하지만", "저는", "우리는", "여러분", "이거", "저거", "그거",
    "정말", "진짜", "약간", "되게", "너무", "오늘", "영상", "이번", "계속", "바로", "이제",
    "것", "수", "때", "좀", "더", "왜", "어떻게", "이런", "그런", "저런", "합니다", "있습니다",
    "있고", "있는", "하면", "해서", "하는", "제가", "우리", "여기", "거죠", "거예요", "겁니다",
])


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
        "interpretation_goal": "TEXT",
        "viewpoint": "TEXT",
        "detail_level": "TEXT",
        "fidelity_level": "TEXT",
        "inference_level": "TEXT",
        "original_topic": "TEXT",
        "primary_claim": "TEXT",
        "sub_claims": "TEXT",
        "evidence_points": "TEXT",
        "context_background": "TEXT",
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
    text = re.sub(r"\s+", " ", clean(text))
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=다)\s+|(?<=요)\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 12]


def extract_keywords(text, topn=16):
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", text)
    freq = {}
    for word in words:
        w = word.lower().strip()
        if w in KOREAN_STOPWORDS or len(w) < 2:
            continue
        freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:topn]]


def score_sentence(sentence, keywords, index):
    score = sum(1 for kw in keywords if kw in sentence.lower())
    score += 3 if any(token in sentence for token in ["문제", "이유", "중요", "핵심", "방법", "먼저", "결국", "하지만", "그래서", "실수", "차이", "놓치"]) else 0
    score += 2 if any(token in sentence for token in ["반드시", "절대", "사실", "진짜", "오히려", "대부분", "많은 사람"]) else 0
    score += max(0, 2.5 - index * 0.02)
    return score


def pick_sentences(text, keywords, limit=10):
    sentences = split_sentences(text)
    scored = [(score_sentence(s, keywords, idx), s) for idx, s in enumerate(sentences)]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for score, s in scored[:limit] if score > 0] or sentences[:limit]


def detect_domain(title, transcript, selected):
    if selected not in ["자동 감지", "직접 입력"]:
        return selected
    text = f"{title} {transcript[:2000]}".lower()
    if any(w in text for w in ["코인", "비트코인", "주식", "시장", "투자", "가격", "섹터", "2차전지", "배터리"]):
        return "시장/투자"
    if any(w in text for w in ["영상", "촬영", "편집", "마케팅", "브랜드", "광고", "콘텐츠", "유튜브"]):
        return "영상/마케팅"
    if any(w in text for w in ["ai", "인공지능", "기술", "개발", "앱", "서비스", "툴"]):
        return "기술/AI"
    if any(w in text for w in ["방법", "노하우", "배우", "강의", "튜토리얼", "체크리스트"]):
        return "교육/노하우"
    if any(w in text for w in ["요즘", "논란", "이슈", "트렌드", "화제", "사람들"]):
        return "트렌드/이슈"
    return "트렌드/이슈"


def infer_structure(text):
    lower = text.lower()
    if any(word in lower for word in ["mistake", "wrong", "하지 마", "실수", "문제"]):
        return "문제 제기 → 흔한 착각/실수 설명 → 원인 분석 → 해결 방법 제시 → 행동 유도"
    if any(word in lower for word in ["how to", "방법", "tutorial", "step", "단계"]):
        return "상황 제시 → 단계별 방법 설명 → 예시/시연 → 체크포인트 → 정리"
    if any(word in lower for word in ["review", "비교", "versus", "vs", "before", "after"]):
        return "비교 대상 제시 → 차이 설명 → 장단점 분석 → 선택 기준 제시 → 결론"
    return "후킹 질문 → 배경 설명 → 핵심 인사이트 → 적용 방식 → 정리/CTA"


def find_sentences_with(text, tokens, limit=4):
    sentences = split_sentences(text)
    picked = []
    for sentence in sentences:
        if any(token in sentence for token in tokens):
            picked.append(sentence)
        if len(picked) >= limit:
            break
    return picked


def build_list(items, fallback, max_items=4):
    cleaned = [shorten(item, 170) for item in items if clean(item)]
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_items]


def infer_original_topic(title, keywords, domain):
    title = clean(title)
    bad_titles = ["직접 입력한 영상 스크립트", "manual input", "youtube 영상", "untitled"]
    if title and not any(bad.lower() in title.lower() for bad in bad_titles):
        return shorten(title, 80)
    if keywords:
        return f"{', '.join(keywords[:4])} 중심의 {domain} 콘텐츠"
    return f"{domain} 원본 콘텐츠"


def interpret_source(title, channel_name, transcript, conditions):
    keywords = extract_keywords(transcript)
    key_sentences = pick_sentences(transcript, keywords, limit=10)
    domain = detect_domain(title, transcript, conditions["source_domain"])
    original_topic = infer_original_topic(title, keywords, domain)

    opening_sentences = split_sentences(transcript)[:12]
    hook_candidates = [s for s in opening_sentences if 20 <= len(s) <= 160]
    hook_point = hook_candidates[0] if hook_candidates else (key_sentences[0] if key_sentences else original_topic)

    primary_claim = key_sentences[0] if key_sentences else f"{original_topic}에 대한 핵심 관점을 다룹니다"
    sub_claims = build_list(key_sentences[1:5], ["원본의 핵심 주장을 보조하는 근거가 추가로 필요합니다"], 4)
    evidence_points = build_list(
        find_sentences_with(transcript, ["왜냐", "근거", "수치", "%", "데이터", "조사", "연구", "사례", "예를", "보면"], 5),
        key_sentences[2:5] or ["원문에서 반복적으로 강조된 문장을 근거로 사용합니다"],
        5,
    )
    cause_effect = build_list(
        find_sentences_with(transcript, ["때문", "그래서", "결과", "그러면", "이유", "영향", "흐름"], 5),
        ["원인 → 변화 → 시청자가 확인해야 할 기준으로 재구성할 수 있습니다"],
        5,
    )
    risk_notes = build_list(
        find_sentences_with(transcript, ["주의", "위험", "리스크", "아닙니다", "하지만", "반대로", "조심"], 4),
        ["원문만으로 단정하기 어려운 부분은 카드뉴스에서 과장하지 않는 편이 안전합니다"],
        4,
    )

    if domain == "시장/투자":
        audience_pain = "시청자는 가격과 결론을 먼저 보지만, 실제로는 왜 움직이는지와 어떤 기준으로 판단해야 하는지를 놓치기 쉽습니다"
        hidden_assumption = "시장이 움직이면 이유도 명확할 것이라는 착각"
        tension = "기대감은 커지지만 실제 근거와 리스크는 동시에 확인해야 하는 긴장감"
    elif domain == "영상/마케팅":
        audience_pain = "시청자는 결과물의 퀄리티를 먼저 보지만, 실제 성과를 만드는 기획 구조와 전환 흐름을 놓치기 쉽습니다"
        hidden_assumption = "보기 좋으면 성과도 따라올 것이라는 착각"
        tension = "화려한 결과물과 실제 문의/전환 사이의 간극"
    elif domain == "교육/노하우":
        audience_pain = "시청자는 방법을 많이 접하지만, 무엇부터 적용해야 하는지와 어떤 기준으로 판단해야 하는지를 놓치기 쉽습니다"
        hidden_assumption = "정보를 많이 알수록 실행도 쉬워질 것이라는 착각"
        tension = "알고 있는 것과 실제로 실행하는 것 사이의 간극"
    else:
        audience_pain = "시청자는 결론과 자극적인 포인트를 먼저 보지만, 왜 중요한지와 무엇을 확인해야 하는지를 놓치기 쉽습니다"
        hidden_assumption = "화제가 되는 주제라면 이미 중요한 이유가 충분히 설명됐을 것이라는 착각"
        tension = "관심은 높지만 판단 기준은 아직 흐린 상태"

    if conditions.get("emphasis"):
        audience_pain += f" 특히 {conditions['emphasis']} 관점에서 이 문제가 더 두드러집니다."
    if conditions.get("avoid"):
        risk_notes.append(f"제외 관점: {conditions['avoid']}")

    emotional_trigger = "놓치고 있었다는 불안감, 지금 확인해야 한다는 긴급감, 기준을 얻었다는 안도감"
    if conditions["interpretation_goal"] == "바이럴 후킹 구조 분석":
        emotional_trigger = "궁금증, 반전 기대감, 손해 보기 싫은 심리, 남들은 모르는 기준을 알고 싶어 하는 욕구"
    elif conditions["interpretation_goal"] == "브랜드/eaf 전환 관점 해석":
        emotional_trigger = "잘 만들었는데도 성과가 나지 않는 답답함, 구조를 알면 해결될 것 같은 기대감"

    narrative_structure = infer_structure(transcript)
    reusable_structure = "도입부에서 문제를 던지고, 중반부에서 사람들이 놓친 기준을 보여준 뒤, 마지막에 적용 가능한 체크포인트로 정리하는 구조"
    viral_hook_logic = f"'{shorten(hook_point, 80)}'처럼 초반에 질문/불안/반전을 만들고, 이후 {domain} 독자가 놓친 기준을 제시하는 방식"

    summary_count = 3 if conditions["detail_level"] == "핵심만" else 5 if conditions["detail_level"] == "표준" else 7
    summary_lines = key_sentences[:summary_count]
    summary = "\n".join([f"- {shorten(s, 230)}" for s in summary_lines])

    context_background = f"분야: {domain}. 관점: {conditions['viewpoint']}. 원문 충실도: {conditions['fidelity_level']}. 추론 허용도: {conditions['inference_level']}."
    if conditions.get("memo"):
        context_background += f" 메모: {conditions['memo']}"

    cardnews_seed = {
        "angle_candidates": [
            f"{original_topic}에서 사람들이 놓치는 것",
            f"{original_topic}을 보기 전에 확인할 기준",
            f"{original_topic}이 반응을 만드는 방식",
        ],
        "problem_candidates": [audience_pain, tension, hidden_assumption],
        "slide_roles": ["훅", "맥락", "문제", "근거", "판단 기준", "행동 유도"],
        "useful_sentences": [shorten(s, 180) for s in key_sentences[:6]],
    }

    interpretation_report = {
        "conditions": conditions,
        "domain": domain,
        "original_topic": original_topic,
        "primary_claim": shorten(primary_claim, 240),
        "sub_claims": sub_claims,
        "evidence_points": evidence_points,
        "cause_effect_chain": cause_effect,
        "audience_pain": audience_pain,
        "hidden_assumption": hidden_assumption,
        "contradiction_or_tension": tension,
        "emotional_trigger": emotional_trigger,
        "viral_hook_logic": viral_hook_logic,
        "narrative_structure": narrative_structure,
        "reusable_structure": reusable_structure,
        "risk_notes": risk_notes,
        "cardnews_seed": cardnews_seed,
    }

    visual_note = "원본 주제 카드뉴스 메뉴에서 이미지 비율, 이미지 스타일, 카피 포함 여부를 선택해 재가공"
    eafi_application = f"{original_topic} 원본 해석 데이터를 바탕으로 원본 주제 카드뉴스 메뉴에서 카드뉴스 설계 가능"

    return {
        "summary": summary,
        "key_claim": shorten(primary_claim, 240),
        "hook_point": shorten(hook_point, 180),
        "structure_note": narrative_structure,
        "visual_note": visual_note,
        "eafi_application": eafi_application,
        "keywords": ", ".join(keywords),
        "source_domain": domain,
        "original_topic": original_topic,
        "primary_claim": shorten(primary_claim, 240),
        "sub_claims": json.dumps(sub_claims, ensure_ascii=False),
        "evidence_points": json.dumps(evidence_points, ensure_ascii=False),
        "context_background": context_background,
        "cause_effect_chain": json.dumps(cause_effect, ensure_ascii=False),
        "audience_pain": audience_pain,
        "hidden_assumption": hidden_assumption,
        "contradiction_or_tension": tension,
        "emotional_trigger": emotional_trigger,
        "viral_hook_logic": viral_hook_logic,
        "narrative_structure": narrative_structure,
        "reusable_structure": reusable_structure,
        "risk_notes": json.dumps(risk_notes, ensure_ascii=False),
        "cardnews_seed": json.dumps(cardnews_seed, ensure_ascii=False),
        "interpretation_report": json.dumps(interpretation_report, ensure_ascii=False, indent=2),
    }


def save_analysis(video_id, url, title, channel_name, transcript, analysis, conditions, source_type="YouTube"):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO youtube_video_analyses
        (video_id, url, title, channel_name, transcript, summary, hook_point, structure_note, visual_note,
         eafi_application, keywords, key_claim, source_type, analysis_memo, interpretation_conditions,
         source_domain, interpretation_goal, viewpoint, detail_level, fidelity_level, inference_level,
         original_topic, primary_claim, sub_claims, evidence_points, context_background, cause_effect_chain,
         audience_pain, hidden_assumption, contradiction_or_tension, emotional_trigger, viral_hook_logic,
         narrative_structure, reusable_structure, risk_notes, cardnews_seed, interpretation_report, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        video_id, url, title, channel_name, transcript, analysis["summary"], analysis["hook_point"],
        analysis["structure_note"], analysis["visual_note"], analysis["eafi_application"], analysis["keywords"],
        analysis["key_claim"], source_type, conditions.get("memo", ""), json.dumps(conditions, ensure_ascii=False),
        analysis["source_domain"], conditions["interpretation_goal"], conditions["viewpoint"], conditions["detail_level"],
        conditions["fidelity_level"], conditions["inference_level"], analysis["original_topic"], analysis["primary_claim"],
        analysis["sub_claims"], analysis["evidence_points"], analysis["context_background"], analysis["cause_effect_chain"],
        analysis["audience_pain"], analysis["hidden_assumption"], analysis["contradiction_or_tension"],
        analysis["emotional_trigger"], analysis["viral_hook_logic"], analysis["narrative_structure"],
        analysis["reusable_structure"], analysis["risk_notes"], analysis["cardnews_seed"], analysis["interpretation_report"],
        datetime.now().isoformat(timespec="seconds"),
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
        "YouTube", channel_name, url, "원본 해석 데이터", "자막 기반 원본 해석", "A",
        f"분야: {analysis['source_domain']} / 목적: {conditions['interpretation_goal']} / 키워드: {analysis['keywords']}",
        datetime.now().isoformat(timespec="seconds"),
    ))
    channel_id = cur.lastrowid
    total_score = sum(scores.values())
    structure_pack = (
        f"원본 주제:\n{analysis['original_topic']}\n\n"
        f"핵심 주장:\n{analysis['primary_claim']}\n\n"
        f"독자 문제:\n{analysis['audience_pain']}\n\n"
        f"전개 구조:\n{analysis['narrative_structure']}\n\n"
        f"재사용 구조:\n{analysis['reusable_structure']}\n\n"
        f"핵심 요약:\n{analysis['summary']}\n\n"
        f"해석 리포트:\n{analysis['interpretation_report']}"
    )
    cur.execute("""
        INSERT INTO content_references
        (channel_id, title, url, hook_point, structure_note, visual_note, eafi_application,
         lead_potential_score, visual_score, hook_score, seo_score, conversion_score, total_score, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        channel_id, title, url, analysis["hook_point"], structure_pack, analysis["visual_note"],
        analysis["eafi_application"], scores["lead"], scores["visual"], scores["hook"], scores["seo"],
        scores["conversion"], total_score, "원본 해석", datetime.now().isoformat(timespec="seconds"),
    ))
    conn.commit()
    conn.close()


def load_recent_analyses():
    conn = connect_db()
    try:
        df = pd.read_sql_query("""
            SELECT id, video_id, title, channel_name, source_domain, interpretation_goal, original_topic,
                   primary_claim, audience_pain, keywords, created_at
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
        interpretation_goal = st.selectbox("해석 목적", INTERPRETATION_GOALS, index=1)
        source_domain = st.selectbox("원본 분야", SOURCE_DOMAINS, index=0)
    with c2:
        viewpoint = st.selectbox("해석 관점", VIEWPOINTS, index=0)
        detail_level = st.selectbox("디테일 수준", DETAIL_LEVELS, index=1)
    with c3:
        fidelity_level = st.selectbox("원문 충실도", FIDELITY_LEVELS, index=1)
        inference_level = st.selectbox("추론 허용도", INFERENCE_LEVELS, index=1)

    c4, c5 = st.columns(2)
    with c4:
        emphasis = st.text_input("강조할 해석 관점", placeholder="예: 전환 구조, 후킹 방식, 시장 판단 기준, 독자 불안")
    with c5:
        avoid = st.text_input("제외할 해석 관점", placeholder="예: 과한 투자 조언, 브랜드명 과다 노출, 원문 밖 단정")

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
    else:
        for item in items:
            st.write(f"- {item}")


def render_payload(payload):
    analysis = payload["analysis"]
    st.markdown("### 원본 해석 결과")
    st.write(f"**제목:** {payload['title']}")
    st.write(f"**채널:** {payload['channel_name']}")
    st.write(f"**video_id:** {payload['video_id']}")
    st.write(f"**자막 길이:** {len(payload['transcript']):,}자")
    st.write(f"**감지 분야:** {analysis['source_domain']}")
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
    st.text_area("audience_pain", value=analysis["audience_pain"], height=110)
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

    render_json_list("보조 주장", analysis["sub_claims"])
    render_json_list("근거 포인트", analysis["evidence_points"])
    render_json_list("원인 → 결과 체인", analysis["cause_effect_chain"])
    render_json_list("주의/리스크", analysis["risk_notes"])

    with st.expander("카드뉴스 재가공 씨앗 데이터"):
        try:
            st.json(json.loads(analysis["cardnews_seed"]))
        except Exception:
            st.write(analysis["cardnews_seed"])

    with st.expander("전체 해석 리포트 JSON"):
        st.code(analysis["interpretation_report"])

    with st.expander("전체 자막 보기"):
        st.text_area("Transcript", value=payload["transcript"], height=340)

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
    st.caption("자막/스크립트를 수집한 뒤 원본 해석기로 주제, 주장, 근거, 독자 문제, 후킹 구조, 재가공 씨앗을 추출합니다.")

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

        if st.button("자막 가져와서 원본 해석", type="primary"):
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
        if st.button("붙여넣은 스크립트 원본 해석", type="primary"):
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
