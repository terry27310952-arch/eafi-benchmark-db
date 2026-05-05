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

IMAGE_RATIOS = ["1:1", "16:9", "9:16", "4:3"]
IMAGE_STYLES = [
    "깔끔한 인포그래픽",
    "실사 시네마틱",
    "3D 애니메이션",
    "2D 일러스트",
    "웹툰/만화형",
    "미니멀 타이포그래피",
    "뉴스 에디토리얼",
    "데이터 대시보드",
    "프리미엄 브랜드룩",
    "AI 혼합 콜라주",
]
CONTENT_GOALS = [
    "원본 내용 깊이 분석",
    "카드뉴스 원천 데이터화",
    "eaf 서비스 전환 소재화",
    "벤치마크 구조 추출",
    "바이럴 후킹 추출",
    "교육형 요약",
]
PLATFORM_FOCUS = ["인스타 카드뉴스", "유튜브 커뮤니티", "블로그", "쓰레드", "틱톡/숏폼", "범용"]
ANALYSIS_DEPTH = ["핵심만", "구조 분석", "세부 근거까지", "전환 관점", "후킹/바이럴 관점"]

ANGLE_PRESETS = {
    "자동 생성": "__AUTO__",
    "문제폭로형": "사람들이 놓치고 있는 문제를 먼저 드러내는 카드뉴스",
    "오해반박형": "흔히 믿는 착각을 반박하는 카드뉴스",
    "체크리스트형": "보기 전에 반드시 확인해야 할 기준을 정리하는 카드뉴스",
    "전후비교형": "Before와 After를 비교해 차이를 보여주는 카드뉴스",
    "eaf 서비스 전환형": "영상 제작 전 반드시 설계해야 할 구조를 보여주는 카드뉴스",
    "직접 입력": "",
}

PROBLEM_PRESETS = {
    "자동 추출": "__AUTO__",
    "목적 불명확": "콘텐츠의 목적이 인지도, 신뢰, 문의 중 어디에 있는지 정리되지 않은 상태",
    "타깃 불명확": "누구에게 말하는 콘텐츠인지 흐려져 메시지와 장면 선택이 모두 애매해진 상태",
    "전환 경로 부재": "콘텐츠를 본 뒤 시청자가 무엇을 해야 하는지 명확하지 않은 상태",
    "정보 과잉": "정보는 많지만 무엇을 기준으로 판단해야 하는지 흐려진 상태",
    "실행 기준 부재": "좋은 말은 많지만 실제로 무엇부터 해야 하는지 정리되지 않은 상태",
    "레퍼런스 복붙": "겉모습은 따라 했지만 반응을 만든 구조는 읽지 못한 상태",
    "직접 입력": "",
}

TARGET_PRESETS = {
    "브랜드/마케팅 담당자": "영상 제작을 검토 중인 브랜드/마케팅 담당자",
    "스타트업 대표/팀장": "브랜드 신뢰도를 빠르게 쌓아야 하는 스타트업 대표/팀장",
    "제품 브랜드 담당자": "제품의 장점을 콘텐츠로 설득해야 하는 브랜드 담당자",
    "콘텐츠 제작자": "유튜브와 숏폼을 꾸준히 운영해야 하는 콘텐츠 제작자",
    "일반 시청자": "해당 주제에 관심 있는 일반 시청자",
    "투자/시장 관심층": "시장 흐름과 이슈를 빠르게 파악하려는 사람",
    "직접 입력": "",
}

KOREAN_STOPWORDS = set([
    "그리고", "그런데", "그래서", "하지만", "저는", "우리는", "여러분", "이거", "저거", "그거",
    "정말", "진짜", "약간", "되게", "너무", "오늘", "영상", "이번", "계속", "바로", "이제",
    "것", "수", "때", "좀", "더", "왜", "어떻게", "이런", "그런", "저런", "합니다", "있습니다",
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
        "analysis_conditions": "TEXT",
        "image_ratio": "TEXT",
        "image_style": "TEXT",
        "include_image_copy": "TEXT",
        "cardnews_angle": "TEXT",
        "core_problem": "TEXT",
        "target_audience": "TEXT",
        "content_goal": "TEXT",
        "platform_focus": "TEXT",
        "analysis_depth": "TEXT",
        "slide_outline": "TEXT",
        "image_prompt_guide": "TEXT",
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


def compact_lines(text):
    return "\n".join([line.strip() for line in clean(text).splitlines() if line.strip()])


def shorten(text, max_len=160):
    text = re.sub(r"\s+", " ", clean(text)).strip()
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


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


def extract_keywords(text, topn=14):
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
    score += 2 if any(token in sentence for token in ["문제", "이유", "중요", "핵심", "방법", "먼저", "결국", "하지만", "그래서", "실수", "차이"]) else 0
    score += max(0, 2.5 - index * 0.025)
    return score


def pick_sentences(text, keywords, limit=7):
    sentences = split_sentences(text)
    scored = [(score_sentence(s, keywords, idx), s) for idx, s in enumerate(sentences)]
    scored.sort(key=lambda x: x[0], reverse=True)
    return [s for score, s in scored[:limit] if score > 0] or sentences[:limit]


def infer_structure(text):
    lower = text.lower()
    if any(word in lower for word in ["mistake", "wrong", "하지 마", "실수", "문제"]):
        return "문제 제기 → 흔한 착각/실수 설명 → 원인 분석 → 해결 방법 제시 → 행동 유도"
    if any(word in lower for word in ["how to", "방법", "tutorial", "step", "단계"]):
        return "상황 제시 → 단계별 방법 설명 → 예시/시연 → 체크포인트 → 정리"
    if any(word in lower for word in ["review", "비교", "versus", "vs", "before", "after"]):
        return "비교 대상 제시 → 차이 설명 → 장단점 분석 → 선택 기준 제시 → 결론"
    return "후킹 질문 → 배경 설명 → 핵심 인사이트 → 적용 방식 → 정리/CTA"


def infer_cardnews_angle(title, context, key_sentences):
    selected = context.get("cardnews_angle", "__AUTO__")
    if selected and selected != "__AUTO__":
        return selected
    if context.get("content_goal") == "eaf 서비스 전환 소재화":
        return "이 콘텐츠에서 배울 수 있는 영상 제작 전환 구조"
    if context.get("analysis_depth") == "후킹/바이럴 관점":
        return f"{title}이 시청자를 붙잡는 방식"
    if key_sentences:
        return f"{shorten(title, 34)}에서 먼저 봐야 할 것"
    return f"{title} 핵심 분석"


def infer_core_problem(context, key_sentences):
    selected = context.get("core_problem", "__AUTO__")
    if selected and selected != "__AUTO__":
        return selected
    candidates = [s for s in key_sentences if any(token in s for token in ["문제", "실수", "하지만", "없", "어렵", "못", "차이"])]
    if candidates:
        return shorten(candidates[0], 120)
    if context.get("content_goal") == "eaf 서비스 전환 소재화":
        return "좋은 콘텐츠를 봐도 실제 우리 브랜드의 전환 구조로 바꾸지 못하는 상태"
    return "정보는 있지만 무엇을 기준으로 판단하고 실행해야 하는지 정리되지 않은 상태"


def build_slide_outline(title, analysis, context):
    angle = analysis["cardnews_angle"]
    problem = analysis["core_problem"]
    summary_lines = [line.replace("- ", "").strip() for line in analysis["summary"].splitlines() if line.strip()]
    s1 = summary_lines[0] if len(summary_lines) > 0 else analysis["key_claim"]
    s2 = summary_lines[1] if len(summary_lines) > 1 else analysis["audience_insight"]
    s3 = summary_lines[2] if len(summary_lines) > 2 else analysis["structure_note"]

    return [
        {"slide": 1, "role": "hook", "copy": f"{shorten(angle, 34)}\n지금 봐야 할 건 따로 있습니다"},
        {"slide": 2, "role": "context", "copy": shorten(s1, 120)},
        {"slide": 3, "role": "problem", "copy": f"문제는\n{shorten(problem, 110)}입니다"},
        {"slide": 4, "role": "insight", "copy": f"핵심은\n{shorten(s2, 110)}"},
        {"slide": 5, "role": "structure", "copy": f"전개 구조는\n{shorten(analysis['structure_note'], 110)}"},
        {"slide": 6, "role": "action", "copy": f"이 기준을 저장해두고\n다시 확인해보세요"},
    ]


def build_image_prompt_guide(slide_outline, context):
    ratio = context["image_ratio"]
    style = context["image_style"]
    include_copy = context["include_image_copy"]

    style_map = {
        "깔끔한 인포그래픽": "clean editorial infographic, organized icons, clear hierarchy, generous whitespace",
        "실사 시네마틱": "cinematic realistic photography, premium lighting, shallow depth of field, natural objects",
        "3D 애니메이션": "stylized 3D animation, soft lighting, polished commercial render, expressive composition",
        "2D 일러스트": "modern flat 2D illustration, clean shapes, balanced composition, editorial feel",
        "웹툰/만화형": "Korean webtoon inspired illustration, dynamic panels, expressive characters, clean linework",
        "미니멀 타이포그래피": "minimal typography poster style, strong layout, negative space, bold graphic rhythm",
        "뉴스 에디토리얼": "news editorial visual, headline layout, data panels, reportage mood",
        "데이터 대시보드": "data dashboard design, charts, UI cards, analytical visual system",
        "프리미엄 브랜드룩": "premium brand campaign visual, black and warm gray palette, elegant composition",
        "AI 혼합 콜라주": "AI mixed media collage, realistic elements with graphic overlays, modern editorial texture",
    }
    ratio_map = {
        "1:1": "square 1:1 composition",
        "16:9": "wide 16:9 horizontal composition",
        "9:16": "vertical 9:16 mobile story composition",
        "4:3": "classic 4:3 editorial composition",
    }
    copy_rule = (
        "include short Korean headline text with enough safe margin" if include_copy
        else "clean image only, no text, no captions, no typography, no letters, no watermark, no logo"
    )

    prompts = []
    for item in slide_outline:
        prompts.append({
            "slide": item["slide"],
            "role": item["role"],
            "prompt": f"{ratio_map[ratio]}, {style_map[style]}, slide role: {item['role']}, visual idea based on: {item['copy']}, {copy_rule}",
        })
    return prompts


def analyze_transcript(title, channel_name, transcript, context):
    keywords = extract_keywords(transcript)
    key_sentences = pick_sentences(transcript, keywords, limit=7)
    summary = "\n".join([f"- {shorten(s, 220)}" for s in key_sentences[:5]])

    opening_sentences = split_sentences(transcript)[:12]
    hook_candidates = [s for s in opening_sentences if 20 <= len(s) <= 160]
    hook_point = hook_candidates[0] if hook_candidates else title
    structure_note = infer_structure(transcript)
    key_claim = key_sentences[0] if key_sentences else hook_point
    cardnews_angle = infer_cardnews_angle(title, context, key_sentences)
    core_problem = infer_core_problem(context, key_sentences)
    audience_insight = f"타깃은 '{context['target_audience']}'이며, 이 콘텐츠는 '{context['content_goal']}' 목적으로 재가공됩니다. 핵심은 원문 내용을 그대로 요약하는 것이 아니라 {context['platform_focus']}에 맞는 판단 기준으로 바꾸는 것입니다."

    if context.get("emphasis"):
        audience_insight += f" 강조 관점: {context['emphasis']}."
    if context.get("avoid"):
        audience_insight += f" 제외할 관점: {context['avoid']}."

    visual_note = (
        f"이미지 비율 {context['image_ratio']}, 스타일 {context['image_style']}. "
        f"이미지 내 카피/텍스트 포함: {'포함' if context['include_image_copy'] else '미포함, 클린 이미지'}"
    )
    eafi_application = f"{title}의 핵심 내용을 {context['platform_focus']}용 카드뉴스 구조로 재가공. 각도: {cardnews_angle}"
    keyword_text = ", ".join(keywords)

    analysis = {
        "summary": summary,
        "key_claim": shorten(key_claim, 240),
        "hook_point": shorten(hook_point, 180),
        "structure_note": structure_note,
        "cardnews_angle": cardnews_angle,
        "core_problem": core_problem,
        "audience_insight": audience_insight,
        "visual_note": visual_note,
        "eafi_application": eafi_application,
        "keywords": keyword_text,
    }
    slide_outline = build_slide_outline(title, analysis, context)
    image_prompt_guide = build_image_prompt_guide(slide_outline, context)
    analysis["slide_outline"] = slide_outline
    analysis["image_prompt_guide"] = image_prompt_guide
    return analysis


def save_analysis(video_id, url, title, channel_name, transcript, analysis, context):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO youtube_video_analyses
        (video_id, url, title, channel_name, transcript, summary, hook_point, structure_note, visual_note, eafi_application, keywords,
         analysis_conditions, image_ratio, image_style, include_image_copy, cardnews_angle, core_problem, target_audience,
         content_goal, platform_focus, analysis_depth, slide_outline, image_prompt_guide, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        video_id, url, title, channel_name, transcript, analysis["summary"], analysis["hook_point"],
        analysis["structure_note"], analysis["visual_note"], analysis["eafi_application"], analysis["keywords"],
        json.dumps(context, ensure_ascii=False), context["image_ratio"], context["image_style"], str(context["include_image_copy"]),
        analysis["cardnews_angle"], analysis["core_problem"], context["target_audience"], context["content_goal"],
        context["platform_focus"], context["analysis_depth"], json.dumps(analysis["slide_outline"], ensure_ascii=False),
        json.dumps(analysis["image_prompt_guide"], ensure_ascii=False), datetime.now().isoformat(timespec="seconds"),
    ))
    analysis_id = cur.lastrowid
    conn.commit()
    conn.close()
    return analysis_id


def convert_to_reference(url, title, channel_name, analysis, scores, context):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO benchmark_channels
        (platform, channel_name, url, category, reference_reason, priority, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        "YouTube",
        channel_name,
        url,
        "영상 내용 분석",
        "자막 기반 영상 내용 분석",
        "A",
        f"목적: {context['content_goal']} / 비율: {context['image_ratio']} / 스타일: {context['image_style']} / 키워드: {analysis['keywords']}",
        datetime.now().isoformat(timespec="seconds"),
    ))
    channel_id = cur.lastrowid
    total_score = sum(scores.values())
    structure_pack = (
        f"분석 조건:\n{json.dumps(context, ensure_ascii=False)}\n\n"
        f"전개 구조:\n{analysis['structure_note']}\n\n"
        f"핵심 요약:\n{analysis['summary']}\n\n"
        f"6장 구성:\n{json.dumps(analysis['slide_outline'], ensure_ascii=False)}"
    )
    cur.execute("""
        INSERT INTO content_references
        (channel_id, title, url, hook_point, structure_note, visual_note, eafi_application,
         lead_potential_score, visual_score, hook_score, seo_score, conversion_score, total_score, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        channel_id, title, url, analysis["hook_point"], structure_pack, analysis["visual_note"], analysis["eafi_application"],
        scores["lead"], scores["visual"], scores["hook"], scores["seo"], scores["conversion"], total_score,
        "영상 내용 분석", datetime.now().isoformat(timespec="seconds"),
    ))
    conn.commit()
    conn.close()


def load_recent_analyses():
    conn = connect_db()
    try:
        df = pd.read_sql_query("""
            SELECT id, video_id, title, channel_name, content_goal, platform_focus, image_ratio, image_style,
                   include_image_copy, cardnews_angle, core_problem, keywords, created_at
            FROM youtube_video_analyses
            ORDER BY id DESC LIMIT 30
        """, conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def select_preset(label, options, key, default=None, height=80):
    labels = list(options.keys())
    index = labels.index(default) if default in labels else 0
    selected = st.selectbox(label, labels, index=index, key=f"{key}_select")
    value = options[selected]
    if selected == "직접 입력":
        value = st.text_area(f"{label} 직접 입력", height=height, key=f"{key}_custom")
    return value, selected


def build_analysis_context():
    st.markdown("### 분석 조건")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        content_goal = st.selectbox("콘텐츠 목적", CONTENT_GOALS, index=1)
    with c2:
        platform_focus = st.selectbox("플랫폼/사용처", PLATFORM_FOCUS, index=0)
    with c3:
        analysis_depth = st.selectbox("분석 깊이", ANALYSIS_DEPTH, index=1)
    with c4:
        target_value, target_label = select_preset("타깃 독자", TARGET_PRESETS, "yt_target", "브랜드/마케팅 담당자")

    c5, c6 = st.columns(2)
    with c5:
        angle_value, angle_label = select_preset("카드뉴스 핵심 각도", ANGLE_PRESETS, "yt_angle", "자동 생성")
        problem_value, problem_label = select_preset("핵심 문제", PROBLEM_PRESETS, "yt_problem", "자동 추출")
    with c6:
        emphasis = st.text_input("강조할 관점", placeholder="예: 전환 구조, 비용 누수, 레퍼런스 차용 방식")
        avoid = st.text_input("제외할 관점", placeholder="예: 과한 투자 조언, 원문 그대로 요약, 브랜드명 과다 노출")

    st.markdown("### 이미지 생성 조건")
    i1, i2, i3 = st.columns(3)
    with i1:
        image_ratio = st.selectbox("이미지 비율", IMAGE_RATIOS, index=0)
    with i2:
        image_style = st.selectbox("이미지 스타일", IMAGE_STYLES, index=0)
    with i3:
        include_image_copy = st.checkbox("이미지 안에 카피/텍스트 넣기", value=True)
        st.caption("끄면 프롬프트에 no text / no captions / no watermark 조건이 들어갑니다.")

    return {
        "content_goal": content_goal,
        "platform_focus": platform_focus,
        "analysis_depth": analysis_depth,
        "target_audience": target_value,
        "target_label": target_label,
        "cardnews_angle": angle_value,
        "angle_label": angle_label,
        "core_problem": problem_value,
        "problem_label": problem_label,
        "emphasis": emphasis,
        "avoid": avoid,
        "image_ratio": image_ratio,
        "image_style": image_style,
        "include_image_copy": include_image_copy,
    }


def build_payload_from_transcript(video_id, normalized_url, title, channel_name, transcript, scores, context, debug=None):
    analysis = analyze_transcript(title, channel_name, transcript, context)
    return {
        "video_id": video_id,
        "url": normalized_url,
        "title": title,
        "channel_name": channel_name,
        "transcript": transcript,
        "analysis": analysis,
        "scores": scores,
        "context": context,
        "debug": debug or {},
    }


def render_payload(payload):
    st.markdown("### 분석 결과")
    st.write(f"**제목:** {payload['title']}")
    st.write(f"**채널:** {payload['channel_name']}")
    st.write(f"**video_id:** {payload['video_id']}")
    st.write(f"**자막 길이:** {len(payload['transcript']):,}자")
    st.write(f"**키워드:** {payload['analysis']['keywords']}")

    with st.expander("적용된 분석/이미지 조건", expanded=True):
        st.json(payload["context"])

    if payload.get("debug"):
        with st.expander("진단 로그 보기"):
            st.json(payload["debug"])

    st.markdown("#### 핵심 분석")
    st.text_area("핵심 요약", value=payload["analysis"]["summary"], height=170)
    st.text_area("핵심 주장", value=payload["analysis"]["key_claim"], height=90)
    st.text_area("카드뉴스 핵심 각도", value=payload["analysis"]["cardnews_angle"], height=70)
    st.text_area("핵심 문제", value=payload["analysis"]["core_problem"], height=90)
    st.text_area("타깃 인사이트", value=payload["analysis"]["audience_insight"], height=120)
    st.text_area("전개 구조", value=payload["analysis"]["structure_note"], height=90)

    st.markdown("#### 6장 카드뉴스 구성")
    slide_df = pd.DataFrame(payload["analysis"]["slide_outline"])
    st.dataframe(slide_df, use_container_width=True, hide_index=True)

    st.markdown("#### 이미지 프롬프트 가이드")
    prompt_df = pd.DataFrame(payload["analysis"]["image_prompt_guide"])
    st.dataframe(prompt_df, use_container_width=True, hide_index=True)

    with st.expander("전체 자막 보기"):
        st.text_area("Transcript", value=payload["transcript"], height=340)

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        if st.button("분석 결과 저장"):
            save_analysis(payload["video_id"], payload["url"], payload["title"], payload["channel_name"], payload["transcript"], payload["analysis"], payload["context"])
            st.success("영상 분석 결과를 저장했습니다.")
    with col_b:
        if st.button("참고 콘텐츠 DB로 저장"):
            save_analysis(payload["video_id"], payload["url"], payload["title"], payload["channel_name"], payload["transcript"], payload["analysis"], payload["context"])
            convert_to_reference(payload["url"], payload["title"], payload["channel_name"], payload["analysis"], payload["scores"], payload["context"])
            st.success("영상 분석 결과를 참고 콘텐츠 DB로 저장했습니다.")
    with col_c:
        if st.button("초기화"):
            st.session_state.pop("yt_analysis_payload", None)
            st.rerun()


def main():
    st.set_page_config(page_title="YouTube 영상 내용 분석", page_icon="🎬", layout="wide")
    init_tables()

    st.title("🎬 YouTube 영상 내용 분석")
    st.caption("YouTube 자막/스크립트를 분석해 카드뉴스 제작용 원천 데이터, 6장 구성, 이미지 프롬프트 조건까지 생성합니다.")

    context = build_analysis_context()

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

        if st.button("자막 가져와서 분석", type="primary"):
            video_id = get_video_id(url)
            if not video_id:
                st.error("YouTube video_id를 찾지 못했습니다. URL을 확인하세요.")
                return
            normalized_url = f"https://www.youtube.com/watch?v={video_id}"
            try:
                title, channel_name = fetch_oembed(normalized_url)
                transcript, debug = fetch_transcript(video_id, langs)
                st.session_state["yt_analysis_payload"] = build_payload_from_transcript(
                    video_id, normalized_url, title, channel_name, transcript, scores, context, debug
                )
                st.success("자막 수집과 분석을 완료했습니다.")
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
        manual_title = st.text_input("영상 제목", value="직접 입력한 영상 스크립트")
        manual_channel = st.text_input("채널명", value="Manual Input")
        transcript = st.text_area("자막/스크립트 붙여넣기", height=360, placeholder="YouTube 자막, Whisper 전사, NotebookLM 요약 전 원문 등을 붙여넣으세요.")
        if st.button("붙여넣은 스크립트 분석", type="primary"):
            if len(clean(transcript)) < 80:
                st.error("분석할 스크립트가 너무 짧습니다. 최소 80자 이상 붙여넣으세요.")
            else:
                video_id = get_video_id(manual_url) or "manual"
                normalized_url = f"https://www.youtube.com/watch?v={video_id}" if video_id != "manual" else clean(manual_url, "manual")
                st.session_state["yt_analysis_payload"] = build_payload_from_transcript(
                    video_id, normalized_url, manual_title, manual_channel, transcript, scores, context,
                    {"method": "manual_paste", "transcript_length": len(transcript)},
                )
                st.success("붙여넣은 스크립트를 분석했습니다.")

    payload = st.session_state.get("yt_analysis_payload")
    if payload:
        st.markdown("---")
        render_payload(payload)

    st.markdown("---")
    st.markdown("### 최근 영상 분석 기록")
    recent = load_recent_analyses()
    if recent.empty:
        st.info("아직 분석 기록이 없습니다.")
    else:
        st.dataframe(recent, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
