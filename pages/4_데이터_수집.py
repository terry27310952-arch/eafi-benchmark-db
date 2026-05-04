import re
import sqlite3
from pathlib import Path
from datetime import datetime
import xml.etree.ElementTree as ET

import pandas as pd
import requests
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")
YOUTUBE_HEADERS = {
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
    conn.commit()
    conn.close()


def save_collected_item(source_type, source_name, title, url, published_at, summary, raw_source):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO collected_items
        (source_type, source_name, title, url, published_at, summary, raw_source, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            source_type,
            source_name,
            title,
            url,
            published_at,
            summary,
            raw_source,
            "수집",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()


def load_collected_items():
    conn = connect_db()
    try:
        df = pd.read_sql_query("SELECT * FROM collected_items ORDER BY id DESC", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def normalize_youtube_input(value):
    raw = value.strip()
    if not raw:
        return ""
    if raw.startswith("@"):
        return f"https://www.youtube.com/{raw}"
    if raw.startswith("UC") and len(raw) >= 20:
        return raw
    if raw.startswith("www.youtube.com") or raw.startswith("youtube.com"):
        return f"https://{raw}"
    return raw


def extract_channel_id_from_text(text):
    patterns = [
        r'"channelId":"(UC[a-zA-Z0-9_-]{20,})"',
        r'"externalId":"(UC[a-zA-Z0-9_-]{20,})"',
        r'"browseId":"(UC[a-zA-Z0-9_-]{20,})"',
        r'<meta itemprop="channelId" content="(UC[a-zA-Z0-9_-]{20,})"',
        r'https://www\.youtube\.com/channel/(UC[a-zA-Z0-9_-]{20,})',
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None


def resolve_youtube_channel_id(value):
    raw = normalize_youtube_input(value)
    if not raw:
        raise ValueError("YouTube URL 또는 채널 ID를 입력하세요.")

    if raw.startswith("UC") and len(raw) >= 20:
        return raw, "channel_id 직접 입력"

    if "channel/" in raw:
        channel_id = raw.split("channel/")[-1].split("/")[0].split("?")[0]
        if channel_id.startswith("UC"):
            return channel_id, "/channel/ URL에서 추출"

    if "/@" in raw or raw.startswith("@"):
        if raw.startswith("@"):
            raw = f"https://www.youtube.com/{raw}"
        target_url = raw.split("?")[0].rstrip("/")
    elif "/c/" in raw or "/user/" in raw:
        target_url = raw.split("?")[0].rstrip("/")
    else:
        target_url = raw.split("?")[0].rstrip("/")

    response = requests.get(target_url, headers=YOUTUBE_HEADERS, timeout=20)
    response.raise_for_status()
    channel_id = extract_channel_id_from_text(response.text)
    if channel_id:
        return channel_id, f"페이지 HTML에서 자동 추출: {target_url}"

    rss_link_match = re.search(r'https://www\.youtube\.com/feeds/videos\.xml\?channel_id=(UC[a-zA-Z0-9_-]{20,})', response.text)
    if rss_link_match:
        return rss_link_match.group(1), f"RSS 링크에서 자동 추출: {target_url}"

    raise ValueError("channel_id를 자동으로 찾지 못했습니다. /channel/UC... URL 또는 UC... 채널 ID를 넣어주세요.")


def fetch_youtube_rss(channel_id):
    rss_url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"
    response = requests.get(rss_url, headers=YOUTUBE_HEADERS, timeout=15)
    response.raise_for_status()
    root = ET.fromstring(response.text)
    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "media": "http://search.yahoo.com/mrss/",
    }
    channel_title = root.findtext("atom:title", default="YouTube Channel", namespaces=ns)
    items = []
    for entry in root.findall("atom:entry", ns):
        title = entry.findtext("atom:title", default="", namespaces=ns)
        link_el = entry.find("atom:link", ns)
        url = link_el.attrib.get("href") if link_el is not None else ""
        published = entry.findtext("atom:published", default="", namespaces=ns)
        summary = entry.findtext("media:group/media:description", default="", namespaces=ns)
        items.append(
            {
                "source_type": "YouTube RSS",
                "source_name": channel_title,
                "title": title,
                "url": url,
                "published_at": published,
                "summary": summary,
                "raw_source": rss_url,
            }
        )
    return channel_title, items


def fetch_generic_rss(rss_url):
    response = requests.get(rss_url, headers=YOUTUBE_HEADERS, timeout=15)
    response.raise_for_status()
    root = ET.fromstring(response.text)

    items = []
    channel_title = "RSS Feed"

    if root.tag.endswith("rss"):
        channel = root.find("channel")
        if channel is not None:
            channel_title = channel.findtext("title", default="RSS Feed")
            for item in channel.findall("item"):
                items.append(
                    {
                        "source_type": "RSS",
                        "source_name": channel_title,
                        "title": item.findtext("title", default=""),
                        "url": item.findtext("link", default=""),
                        "published_at": item.findtext("pubDate", default=""),
                        "summary": item.findtext("description", default=""),
                        "raw_source": rss_url,
                    }
                )
    else:
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        channel_title = root.findtext("atom:title", default="Atom Feed", namespaces=ns)
        for entry in root.findall("atom:entry", ns):
            link_el = entry.find("atom:link", ns)
            items.append(
                {
                    "source_type": "Atom RSS",
                    "source_name": channel_title,
                    "title": entry.findtext("atom:title", default="", namespaces=ns),
                    "url": link_el.attrib.get("href") if link_el is not None else "",
                    "published_at": entry.findtext("atom:published", default="", namespaces=ns),
                    "summary": entry.findtext("atom:summary", default="", namespaces=ns),
                    "raw_source": rss_url,
                }
            )

    return channel_title, items


def convert_to_reference(item):
    conn = connect_db()
    cur = conn.cursor()

    cur.execute(
        """
        INSERT INTO benchmark_channels
        (platform, channel_name, url, category, reference_reason, priority, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            item.get("source_type") or "Collected",
            item.get("source_name") or "Collected Source",
            item.get("raw_source") or item.get("url") or "",
            "수집 데이터",
            "데이터 수집",
            "B",
            "데이터 수집 페이지에서 자동 생성",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    channel_id = cur.lastrowid

    title = item.get("title") or "Untitled"
    summary = item.get("summary") or ""
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
            item.get("url") or "",
            title,
            summary[:500],
            "원본 콘텐츠를 카드뉴스 구조로 재해석 필요",
            f"{title}을 EAFi 관점의 카드뉴스 주제로 변환",
            3,
            3,
            3,
            3,
            3,
            15,
            "수집",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )

    conn.commit()
    conn.close()


def export_collected():
    df = load_collected_items()
    export_dir = Path("exports")
    export_dir.mkdir(exist_ok=True)
    path = export_dir / "collected_items.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def main():
    st.set_page_config(page_title="데이터 수집", page_icon="🛰️", layout="wide")
    init_tables()

    st.title("🛰️ 데이터 수집")
    st.caption("YouTube RSS, 일반 RSS, 수동 URL로 벤치마크 후보를 수집합니다.")

    tab1, tab2, tab3, tab4 = st.tabs(["YouTube RSS", "일반 RSS", "수동 등록", "수집 데이터 보기"])

    with tab1:
        st.subheader("YouTube 채널 RSS 수집")
        st.write("YouTube Data API 키 없이도 채널 URL, @handle, channel_id로 최신 영상 제목과 링크를 수집합니다.")
        channel_url_or_id = st.text_input(
            "YouTube 채널 URL / @handle / channel_id",
            placeholder="@mkbhd 또는 https://www.youtube.com/@mkbhd 또는 UC...",
        )
        limit = st.slider("가져올 개수", 1, 20, 10)

        col_resolve, col_collect = st.columns(2)
        with col_resolve:
            if st.button("channel_id만 확인"):
                try:
                    channel_id, method = resolve_youtube_channel_id(channel_url_or_id)
                    st.success(f"channel_id: {channel_id}")
                    st.caption(method)
                except Exception as e:
                    st.error(f"확인 실패: {e}")

        with col_collect:
            if st.button("YouTube RSS 수집"):
                try:
                    channel_id, method = resolve_youtube_channel_id(channel_url_or_id)
                    source_name, items = fetch_youtube_rss(channel_id)
                    for item in items[:limit]:
                        save_collected_item(**item)
                    st.success(f"{source_name}에서 {min(len(items), limit)}개를 수집했습니다.")
                    st.caption(f"{method} · channel_id: {channel_id}")
                    st.dataframe(pd.DataFrame(items[:limit]), use_container_width=True, hide_index=True)
                except Exception as e:
                    st.error(f"수집 실패: {e}")
                    st.info("자동 추출이 막히면 /channel/UC... 형태의 URL 또는 UC... 채널 ID를 넣어주세요.")

    with tab2:
        st.subheader("일반 RSS 수집")
        rss_url = st.text_input("RSS URL", placeholder="https://example.com/feed")
        limit = st.slider("RSS 가져올 개수", 1, 50, 10)
        if st.button("RSS 수집"):
            try:
                source_name, items = fetch_generic_rss(rss_url)
                for item in items[:limit]:
                    save_collected_item(**item)
                st.success(f"{source_name}에서 {min(len(items), limit)}개를 수집했습니다.")
                st.dataframe(pd.DataFrame(items[:limit]), use_container_width=True, hide_index=True)
            except Exception as e:
                st.error(f"수집 실패: {e}")

    with tab3:
        st.subheader("수동 URL 등록")
        with st.form("manual_collect_form"):
            source_type = st.selectbox("소스 유형", ["YouTube", "Instagram", "TikTok", "Naver Blog", "Website", "Other"])
            source_name = st.text_input("소스명", placeholder="채널명 또는 사이트명")
            title = st.text_input("콘텐츠 제목")
            url = st.text_input("URL")
            summary = st.text_area("메모/요약", placeholder="후킹, 구조, 참고 포인트")
            submitted = st.form_submit_button("수동 데이터 저장")
        if submitted:
            if not title:
                st.error("제목은 필수입니다.")
            else:
                save_collected_item(source_type, source_name, title, url, "", summary, url)
                st.success("수동 데이터를 저장했습니다.")

    with tab4:
        st.subheader("수집 데이터 보기")
        df = load_collected_items()
        if df.empty:
            st.info("아직 수집 데이터가 없습니다.")
        else:
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.markdown("### 참고 콘텐츠 DB로 보내기")
            selected_id = st.number_input("보낼 수집 데이터 ID", min_value=1, step=1)
            if st.button("참고 콘텐츠로 변환"):
                row_df = df[df["id"] == selected_id]
                if row_df.empty:
                    st.error("해당 ID를 찾을 수 없습니다.")
                else:
                    convert_to_reference(row_df.iloc[0].to_dict())
                    st.success("참고 콘텐츠 DB로 변환했습니다.")

            if st.button("수집 데이터 CSV 내보내기"):
                path = export_collected()
                st.success("CSV 파일을 생성했습니다.")
                with open(path, "rb") as f:
                    st.download_button("collected_items.csv 다운로드", f, file_name="collected_items.csv", mime="text/csv")


if __name__ == "__main__":
    main()
