import re
import sqlite3
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

KOREAN_STOPWORDS = set([
    "그리고", "그런데", "그래서", "하지만", "저는", "우리는", "여러분", "이거", "저거", "그거",
    "정말", "진짜", "약간", "되게", "너무", "오늘", "영상", "이번", "계속", "바로", "이제",
    "것", "수", "때", "좀", "더", "왜", "어떻게", "이런", "그런", "저런", "합니다", "있습니다",
])


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


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
    conn.commit()
    conn.close()


def clean(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def get_video_id(url):
    url = url.strip()
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


def fetch_transcript(video_id, languages):
    transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
    transcript = None

    for lang in languages:
        try:
            transcript = transcript_list.find_transcript([lang])
            break
        except Exception:
            pass

    if transcript is None:
        try:
            transcript = transcript_list.find_generated_transcript(languages)
        except Exception:
            available = [t.language_code for t in transcript_list]
            if available:
                transcript = transcript_list.find_transcript([available[0]])
            else:
                raise ValueError("사용 가능한 자막을 찾지 못했습니다.")

    rows = transcript.fetch()
    text = " ".join([clean(row.get("text", "")).replace("\n", " ") for row in rows])
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_sentences(text):
    text = re.sub(r"\s+", " ", clean(text))
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=다)\s+|(?<=요)\s+", text)
    return [p.strip() for p in parts if len(p.strip()) > 12]


def extract_keywords(text, topn=12):
    words = re.findall(r"[가-힣A-Za-z0-9]{2,}", text)
    freq = {}
    for word in words:
        w = word.lower().strip()
        if w in KOREAN_STOPWORDS or len(w) < 2:
            continue
        freq[w] = freq.get(w, 0) + 1
    sorted_words = sorted(freq.items(), key=lambda x: x[1], reverse=True)
    return [w for w, _ in sorted_words[:topn]]


def pick_sentences(text, keywords, limit=5):
    sentences = split_sentences(text)
    scored = []
    for sentence in sentences:
        score = sum(1 for kw in keywords if kw in sentence.lower())
        score += 1 if any(token in sentence for token in ["문제", "이유", "중요", "핵심", "방법", "먼저", "결국", "하지만", "그래서"]) else 0
        scored.append((score, sentence))
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


def analyze_transcript(title, channel_name, transcript):
    keywords = extract_keywords(transcript)
    key_sentences = pick_sentences(transcript, keywords, limit=6)
    summary = "\n".join([f"- {s[:180]}" for s in key_sentences[:5]])

    hook_candidates = [s for s in split_sentences(transcript)[:20] if len(s) < 140]
    hook_point = hook_candidates[0] if hook_candidates else title
    if len(hook_point) > 120:
        hook_point = title

    structure_note = infer_structure(transcript)
    visual_note = "원본 영상의 썸네일, 도입부 화면, 주요 예시 장면, 전환 장면을 카드뉴스 이미지 구조로 재해석"
    keyword_text = ", ".join(keywords)

    eafi_application = f"{title}의 핵심 흐름을 eaf: 관점에서 '영상 제작 전 반드시 봐야 할 구조' 카드뉴스로 변환"

    return {
        "summary": summary,
        "hook_point": hook_point,
        "structure_note": structure_note,
        "visual_note": visual_note,
        "eafi_application": eafi_application,
        "keywords": keyword_text,
    }


def save_analysis(video_id, url, title, channel_name, transcript, analysis):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO youtube_video_analyses
        (video_id, url, title, channel_name, transcript, summary, hook_point, structure_note, visual_note, eafi_application, keywords, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        video_id, url, title, channel_name, transcript, analysis["summary"], analysis["hook_point"],
        analysis["structure_note"], analysis["visual_note"], analysis["eafi_application"], analysis["keywords"],
        datetime.now().isoformat(timespec="seconds"),
    ))
    analysis_id = cur.lastrowid
    conn.commit()
    conn.close()
    return analysis_id


def convert_to_reference(url, title, channel_name, analysis, scores):
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
        f"키워드: {analysis['keywords']}",
        datetime.now().isoformat(timespec="seconds"),
    ))
    channel_id = cur.lastrowid
    total_score = sum(scores.values())
    cur.execute("""
        INSERT INTO content_references
        (channel_id, title, url, hook_point, structure_note, visual_note, eafi_application,
         lead_potential_score, visual_score, hook_score, seo_score, conversion_score, total_score, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        channel_id,
        title,
        url,
        analysis["hook_point"],
        analysis["structure_note"] + "\n\n핵심 요약:\n" + analysis["summary"],
        analysis["visual_note"],
        analysis["eafi_application"],
        scores["lead"],
        scores["visual"],
        scores["hook"],
        scores["seo"],
        scores["conversion"],
        total_score,
        "영상 내용 분석",
        datetime.now().isoformat(timespec="seconds"),
    ))
    conn.commit()
    conn.close()


def load_recent_analyses():
    conn = connect_db()
    try:
        df = pd.read_sql_query("SELECT id, video_id, title, channel_name, summary, hook_point, structure_note, eafi_application, keywords, created_at FROM youtube_video_analyses ORDER BY id DESC LIMIT 30", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def main():
    st.set_page_config(page_title="YouTube 영상 내용 분석", page_icon="🎬", layout="wide")
    init_tables()

    st.title("🎬 YouTube 영상 내용 분석")
    st.caption("YouTube 링크에서 자막/스크립트를 가져와 영상 내용을 분석하고, 카드뉴스용 원본 데이터로 저장합니다.")

    url = st.text_input("YouTube URL 또는 video_id", placeholder="https://www.youtube.com/watch?v=... 또는 https://youtube.com/shorts/...")
    langs = st.multiselect("자막 우선순위", ["ko", "en", "ja", "es", "de", "fr"], default=["ko", "en"])

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

    if st.button("자막 가져와서 분석", type="primary"):
        video_id = get_video_id(url)
        if not video_id:
            st.error("YouTube video_id를 찾지 못했습니다. URL을 확인하세요.")
            return
        normalized_url = f"https://www.youtube.com/watch?v={video_id}"
        try:
            title, channel_name = fetch_oembed(normalized_url)
            transcript = fetch_transcript(video_id, langs)
            analysis = analyze_transcript(title, channel_name, transcript)
            st.session_state["yt_analysis_payload"] = {
                "video_id": video_id,
                "url": normalized_url,
                "title": title,
                "channel_name": channel_name,
                "transcript": transcript,
                "analysis": analysis,
                "scores": scores,
            }
        except Exception as e:
            st.error(f"분석 실패: {e}")
            st.info("자막이 비공개이거나 없는 영상은 분석이 어렵습니다. 이 경우 자막/스크립트를 직접 붙여 넣는 입력 기능을 다음 단계로 추가하는 게 좋습니다.")

    payload = st.session_state.get("yt_analysis_payload")
    if payload:
        st.markdown("---")
        st.markdown("### 분석 결과")
        st.write(f"**제목:** {payload['title']}")
        st.write(f"**채널:** {payload['channel_name']}")
        st.write(f"**video_id:** {payload['video_id']}")
        st.write(f"**키워드:** {payload['analysis']['keywords']}")
        st.markdown("#### 핵심 요약")
        st.text_area("요약", value=payload["analysis"]["summary"], height=160)
        st.markdown("#### 후킹 포인트")
        st.text_area("후킹 포인트", value=payload["analysis"]["hook_point"], height=90)
        st.markdown("#### 전개 구조")
        st.text_area("전개 구조", value=payload["analysis"]["structure_note"], height=90)
        st.markdown("#### eaf: 적용 아이디어")
        st.text_area("적용 아이디어", value=payload["analysis"]["eafi_application"], height=90)
        with st.expander("전체 자막 보기"):
            st.text_area("Transcript", value=payload["transcript"], height=320)

        col_a, col_b, col_c = st.columns(3)
        with col_a:
            if st.button("분석 결과 저장"):
                save_analysis(payload["video_id"], payload["url"], payload["title"], payload["channel_name"], payload["transcript"], payload["analysis"])
                st.success("영상 분석 결과를 저장했습니다.")
        with col_b:
            if st.button("참고 콘텐츠 DB로 저장"):
                save_analysis(payload["video_id"], payload["url"], payload["title"], payload["channel_name"], payload["transcript"], payload["analysis"])
                convert_to_reference(payload["url"], payload["title"], payload["channel_name"], payload["analysis"], payload["scores"])
                st.success("영상 분석 결과를 참고 콘텐츠 DB로 저장했습니다.")
        with col_c:
            if st.button("초기화"):
                st.session_state.pop("yt_analysis_payload", None)
                st.rerun()

    st.markdown("---")
    st.markdown("### 최근 영상 분석 기록")
    recent = load_recent_analyses()
    if recent.empty:
        st.info("아직 분석 기록이 없습니다.")
    else:
        st.dataframe(recent, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
