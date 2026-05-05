import re
import sqlite3
from pathlib import Path
from datetime import datetime
from urllib.parse import urlparse

import pandas as pd
import requests
import streamlit as st
from bs4 import BeautifulSoup

DB_PATH = Path("eafi_benchmark.db")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
}


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_tables():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS collected_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_type TEXT NOT NULL,
            source_name TEXT,
            title TEXT NOT NULL,
            url TEXT,
            published_at TEXT,
            summary TEXT,
            raw_source TEXT,
            status TEXT DEFAULT '수집',
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
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
        """
    )
    cur.execute(
        """
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
        """
    )
    conn.commit()
    conn.close()


def clean(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    return text or fallback


def normalize_url(url):
    url = url.strip()
    if not url:
        return ""
    if not url.startswith("http://") and not url.startswith("https://"):
        url = "https://" + url
    return url


def detect_platform(url):
    host = urlparse(url).netloc.lower()
    if "youtube.com" in host or "youtu.be" in host:
        return "YouTube"
    if "instagram.com" in host:
        return "Instagram"
    if "tiktok.com" in host:
        return "TikTok"
    if "blog.naver.com" in host or "naver.com" in host:
        return "Naver"
    if "threads.net" in host:
        return "Threads"
    if "x.com" in host or "twitter.com" in host:
        return "X"
    return "Website"


def get_meta_content(soup, *selectors):
    for selector in selectors:
        tag = soup.select_one(selector)
        if tag:
            value = tag.get("content") or tag.get_text(" ", strip=True)
            if value:
                return value.strip()
    return ""


def fetch_youtube_oembed(url):
    endpoint = "https://www.youtube.com/oembed"
    res = requests.get(endpoint, params={"url": url, "format": "json"}, headers=HEADERS, timeout=15)
    res.raise_for_status()
    data = res.json()
    title = clean(data.get("title"), "YouTube 콘텐츠")
    author = clean(data.get("author_name"), "YouTube")
    return {
        "platform": "YouTube",
        "source_name": author,
        "title": title,
        "summary": f"YouTube 콘텐츠. 채널: {author}",
        "raw_source": url,
    }


def fetch_generic_metadata(url):
    res = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
    res.raise_for_status()
    soup = BeautifulSoup(res.text, "html.parser")

    title = get_meta_content(
        soup,
        'meta[property="og:title"]',
        'meta[name="twitter:title"]',
        "title",
        "h1",
    )
    desc = get_meta_content(
        soup,
        'meta[property="og:description"]',
        'meta[name="description"]',
        'meta[name="twitter:description"]',
    )
    site_name = get_meta_content(soup, 'meta[property="og:site_name"]')

    parsed = urlparse(res.url)
    platform = detect_platform(res.url)
    source_name = clean(site_name, parsed.netloc.replace("www.", ""))

    return {
        "platform": platform,
        "source_name": source_name,
        "title": clean(title, res.url),
        "summary": clean(desc, "자동 설명을 찾지 못했습니다. 원문을 확인해 후킹/구조를 보완하세요."),
        "raw_source": res.url,
    }


def fetch_url_metadata(url):
    url = normalize_url(url)
    platform = detect_platform(url)
    if platform == "YouTube":
        try:
            return fetch_youtube_oembed(url)
        except Exception:
            # Shorts나 일부 URL은 oEmbed가 실패할 수 있어 일반 메타로 재시도합니다.
            return fetch_generic_metadata(url)
    return fetch_generic_metadata(url)


def save_collected_item(item):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO collected_items
        (source_type, source_name, title, url, published_at, summary, raw_source, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item["platform"],
            item["source_name"],
            item["title"],
            item["url"],
            item.get("published_at", ""),
            item["summary"],
            item["raw_source"],
            "수집",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    item_id = cur.lastrowid
    conn.commit()
    conn.close()
    return item_id


def convert_item_to_reference(item, base_score=3):
    conn = connect_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO benchmark_channels
        (platform, channel_name, url, category, reference_reason, priority, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item["platform"],
            item["source_name"],
            item["raw_source"],
            "URL 자동 수집",
            "링크 기반 자동 원본 데이터 수집",
            "B",
            "URL 자동 수집 페이지에서 생성",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    channel_id = cur.lastrowid

    total_score = base_score * 5
    title = clean(item["title"], "Untitled")
    summary = clean(item["summary"])

    cur.execute(
        """
        INSERT INTO content_references
        (channel_id, title, url, hook_point, structure_note, visual_note, eafi_application,
         lead_potential_score, visual_score, hook_score, seo_score, conversion_score, total_score, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            channel_id,
            title,
            item["url"],
            title,
            summary[:700],
            "원본 페이지의 썸네일, 화면 구성, 제목 구조를 참고해 카드뉴스 이미지 방향으로 재해석",
            f"{title}을 eaf: 관점의 카드뉴스 주제로 변환",
            base_score,
            base_score,
            base_score,
            base_score,
            base_score,
            total_score,
            "수집",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )

    conn.commit()
    conn.close()


def load_recent_collected():
    conn = connect_db()
    df = pd.read_sql_query("SELECT * FROM collected_items ORDER BY id DESC LIMIT 50", conn)
    conn.close()
    return df


def main():
    st.set_page_config(page_title="URL 자동 수집", page_icon="🔗", layout="wide")
    init_tables()

    st.title("🔗 URL 자동 수집")
    st.caption("링크만 붙여넣으면 제목, 설명, 플랫폼, 채널/사이트명을 자동으로 가져와 원본 데이터로 저장합니다.")

    urls_text = st.text_area(
        "수집할 URL",
        placeholder="https://www.youtube.com/watch?v=...\nhttps://example.com/article",
        height=160,
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        auto_reference = st.checkbox("참고 콘텐츠 DB로 바로 변환", value=True)
    with col2:
        base_score = st.slider("기본 점수", min_value=1, max_value=5, value=3)
    with col3:
        dedupe_hint = st.checkbox("중복 URL은 건너뛰기", value=True)

    if st.button("URL 자동 수집 시작", type="primary"):
        raw_urls = [line.strip() for line in urls_text.splitlines() if line.strip()]
        if not raw_urls:
            st.error("URL을 1개 이상 입력하세요.")
            return

        conn = connect_db()
        existing_urls = set()
        if dedupe_hint:
            try:
                existing_df = pd.read_sql_query("SELECT url, raw_source FROM collected_items", conn)
                existing_urls = set(existing_df["url"].dropna().tolist()) | set(existing_df["raw_source"].dropna().tolist())
            except Exception:
                existing_urls = set()
        conn.close()

        results = []
        for raw_url in raw_urls:
            url = normalize_url(raw_url)
            if dedupe_hint and url in existing_urls:
                results.append({"url": url, "status": "중복 건너뜀"})
                continue
            try:
                meta = fetch_url_metadata(url)
                item = {
                    "platform": meta["platform"],
                    "source_name": meta["source_name"],
                    "title": meta["title"],
                    "url": url,
                    "summary": meta["summary"],
                    "raw_source": meta["raw_source"],
                }
                item_id = save_collected_item(item)
                if auto_reference:
                    convert_item_to_reference(item, base_score=base_score)
                item["id"] = item_id
                item["status"] = "저장 완료"
                results.append(item)
            except Exception as e:
                results.append({"url": url, "status": f"실패: {e}"})

        st.markdown("### 수집 결과")
        st.dataframe(pd.DataFrame(results), use_container_width=True, hide_index=True)

    st.markdown("---")
    st.markdown("### 최근 수집 데이터")
    recent = load_recent_collected()
    if recent.empty:
        st.info("아직 수집된 데이터가 없습니다.")
    else:
        st.dataframe(recent, use_container_width=True, hide_index=True)

    st.info("Instagram, TikTok, Threads 일부 링크는 플랫폼 차단 때문에 제목/설명이 비어 있을 수 있습니다. 이 경우에도 URL은 저장되며, 카드뉴스 설계 단계에서 직접 보완하면 됩니다.")


if __name__ == "__main__":
    main()
