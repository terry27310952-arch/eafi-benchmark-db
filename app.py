import sqlite3
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

APP_TITLE = "EAFi Benchmark DB MVP"
DB_PATH = Path("eafi_benchmark.db")

PLATFORMS = ["YouTube", "Instagram", "TikTok", "Naver Blog", "Pinterest", "Website", "Other"]
CHANNEL_CATEGORIES = [
    "AI 영상",
    "브랜드필름",
    "제품영상",
    "B2B 마케팅",
    "디자인/모션그래픽",
    "스타트업/비즈니스",
    "SEO 참고",
    "기타",
]
REFERENCE_REASONS = ["후킹", "디자인", "카피", "전환", "사례 구성", "이미지 톤", "SEO", "기타"]
STATUS_OPTIONS = ["수집", "검토중", "카드뉴스 후보", "컨펌", "보류", "제작완료"]


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS benchmark_channels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            platform TEXT NOT NULL,
            channel_name TEXT NOT NULL,
            url TEXT NOT NULL,
            category TEXT,
            reference_reason TEXT,
            priority TEXT DEFAULT 'B',
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
            lead_potential_score INTEGER DEFAULT 0,
            visual_score INTEGER DEFAULT 0,
            hook_score INTEGER DEFAULT 0,
            seo_score INTEGER DEFAULT 0,
            conversion_score INTEGER DEFAULT 0,
            total_score INTEGER DEFAULT 0,
            status TEXT DEFAULT '수집',
            created_at TEXT NOT NULL,
            FOREIGN KEY(channel_id) REFERENCES benchmark_channels(id)
        )
        """
    )
    conn.commit()
    conn.close()


def run_query(query, params=(), fetch=False):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(query, params)
    result = cur.fetchall() if fetch else None
    conn.commit()
    conn.close()
    return result


def add_channel(platform, channel_name, url, category, reference_reason, priority, notes):
    run_query(
        """
        INSERT INTO benchmark_channels
        (platform, channel_name, url, category, reference_reason, priority, notes, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (platform, channel_name, url, category, reference_reason, priority, notes, datetime.now().isoformat(timespec="seconds")),
    )


def add_reference(channel_id, title, url, hook_point, structure_note, visual_note, eafi_application, lead, visual, hook, seo, conversion, status):
    total = int(lead) + int(visual) + int(hook) + int(seo) + int(conversion)
    if total >= 20 and status == "수집":
        status = "카드뉴스 후보"
    run_query(
        """
        INSERT INTO content_references
        (channel_id, title, url, hook_point, structure_note, visual_note, eafi_application,
         lead_potential_score, visual_score, hook_score, seo_score, conversion_score, total_score, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (channel_id, title, url, hook_point, structure_note, visual_note, eafi_application, int(lead), int(visual), int(hook), int(seo), int(conversion), total, status, datetime.now().isoformat(timespec="seconds")),
    )


def load_channels():
    conn = connect_db()
    df = pd.read_sql_query("SELECT * FROM benchmark_channels ORDER BY id DESC", conn)
    conn.close()
    return df


def load_references():
    conn = connect_db()
    df = pd.read_sql_query(
        """
        SELECT r.id, c.platform, c.channel_name, c.category, r.title, r.url,
               r.hook_point, r.structure_note, r.visual_note, r.eafi_application,
               r.lead_potential_score, r.visual_score, r.hook_score, r.seo_score,
               r.conversion_score, r.total_score, r.status, r.created_at
        FROM content_references r
        LEFT JOIN benchmark_channels c ON r.channel_id = c.id
        ORDER BY r.total_score DESC, r.id DESC
        """,
        conn,
    )
    conn.close()
    return df


def get_channel_options():
    df = load_channels()
    if df.empty:
        return {}
    return {f"{row['id']} · {row['platform']} · {row['channel_name']}": int(row["id"]) for _, row in df.iterrows()}


def update_reference_status(reference_id, status):
    run_query("UPDATE content_references SET status = ? WHERE id = ?", (status, reference_id))


def delete_row(table, row_id):
    if table not in {"benchmark_channels", "content_references"}:
        raise ValueError("Invalid table")
    run_query(f"DELETE FROM {table} WHERE id = ?", (row_id,))


def export_data():
    export_dir = Path("exports")
    export_dir.mkdir(exist_ok=True)
    channels_path = export_dir / "benchmark_channels.csv"
    refs_path = export_dir / "content_references.csv"
    load_channels().to_csv(channels_path, index=False, encoding="utf-8-sig")
    load_references().to_csv(refs_path, index=False, encoding="utf-8-sig")
    return channels_path, refs_path


def render_dashboard():
    refs = load_references()
    channels = load_channels()
    st.subheader("대시보드")
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("등록 채널", len(channels))
    col2.metric("참고 콘텐츠", len(refs))
    col3.metric("카드뉴스 후보", 0 if refs.empty else int((refs["status"] == "카드뉴스 후보").sum()))
    col4.metric("컨펌 콘텐츠", 0 if refs.empty else int((refs["status"] == "컨펌").sum()))
    if refs.empty:
        st.info("아직 참고 콘텐츠가 없습니다. 먼저 벤치마크 채널과 콘텐츠를 등록하세요.")
        return
    st.markdown("### 상위 후보")
    st.dataframe(refs.head(10), use_container_width=True, hide_index=True)
    platform_counts = refs["platform"].fillna("Unknown").value_counts().reset_index()
    platform_counts.columns = ["platform", "count"]
    st.bar_chart(platform_counts, x="platform", y="count")


def render_add_channel():
    st.subheader("벤치마크 채널 등록")
    with st.form("add_channel_form"):
        platform = st.selectbox("플랫폼", PLATFORMS)
        channel_name = st.text_input("채널명 / 계정명")
        url = st.text_input("채널 URL")
        category = st.selectbox("카테고리", CHANNEL_CATEGORIES)
        reference_reason = st.multiselect("참고 이유", REFERENCE_REASONS, default=["후킹"])
        priority = st.selectbox("우선순위", ["S", "A", "B", "보류"], index=2)
        notes = st.text_area("메모", placeholder="예: 첫 장 카피가 강함, B2B 전환 구조 참고")
        submitted = st.form_submit_button("채널 저장")
    if submitted:
        if not channel_name or not url:
            st.error("채널명과 URL은 필수입니다.")
        else:
            add_channel(platform, channel_name, url, category, ", ".join(reference_reason), priority, notes)
            st.success("채널을 저장했습니다.")


def render_add_reference():
    st.subheader("참고 콘텐츠 등록")
    channel_options = get_channel_options()
    if not channel_options:
        st.warning("먼저 벤치마크 채널을 등록해야 합니다.")
        return
    with st.expander("점수 기준 보기"):
        st.markdown("각 항목 0~5점입니다. 총점 20점 이상이면 자동으로 카드뉴스 후보 상태가 됩니다.")
    with st.form("add_reference_form"):
        selected = st.selectbox("연결할 벤치마크 채널", list(channel_options.keys()))
        title = st.text_input("콘텐츠 제목")
        url = st.text_input("콘텐츠 URL")
        hook_point = st.text_area("후킹 포인트")
        structure_note = st.text_area("전개 구조")
        visual_note = st.text_area("이미지/디자인 참고")
        eafi_application = st.text_area("EAFi 적용 아이디어")
        c1, c2, c3, c4, c5 = st.columns(5)
        lead = c1.slider("리드", 0, 5, 3)
        visual = c2.slider("이미지", 0, 5, 3)
        hook = c3.slider("후킹", 0, 5, 3)
        seo = c4.slider("SEO", 0, 5, 3)
        conversion = c5.slider("전환", 0, 5, 3)
        total = lead + visual + hook + seo + conversion
        st.info(f"예상 총점: {total}점 / 25점")
        status = st.selectbox("상태", STATUS_OPTIONS, index=0)
        submitted = st.form_submit_button("참고 콘텐츠 저장")
    if submitted:
        if not title:
            st.error("콘텐츠 제목은 필수입니다.")
        else:
            add_reference(channel_options[selected], title, url, hook_point, structure_note, visual_note, eafi_application, lead, visual, hook, seo, conversion, status)
            st.success("참고 콘텐츠를 저장했습니다.")


def render_candidates():
    st.subheader("카드뉴스 후보 추출")
    refs = load_references()
    if refs.empty:
        st.info("참고 콘텐츠가 없습니다.")
        return
    min_score = st.slider("최소 점수", 0, 25, 20)
    candidates = refs[refs["total_score"] >= min_score].sort_values("total_score", ascending=False)
    if candidates.empty:
        st.warning("조건에 맞는 후보가 없습니다.")
        return
    for _, row in candidates.iterrows():
        with st.container(border=True):
            st.markdown(f"### {row['title']}")
            st.caption(f"{row['platform']} · {row['channel_name']} · 총점 {row['total_score']}점 · 상태: {row['status']}")
            st.markdown(f"**후킹 포인트**  \n{row['hook_point'] or '-'}")
            st.markdown(f"**전개 구조**  \n{row['structure_note'] or '-'}")
            st.markdown(f"**이미지 참고**  \n{row['visual_note'] or '-'}")
            st.markdown(f"**EAFi 적용 아이디어**  \n{row['eafi_application'] or '-'}")
            if row["url"]:
                st.link_button("원본 보기", row["url"])


def render_tables():
    st.subheader("DB 보기 / 관리")
    tab1, tab2 = st.tabs(["벤치마크 채널", "참고 콘텐츠"])
    with tab1:
        channels = load_channels()
        st.dataframe(channels, use_container_width=True, hide_index=True)
        with st.expander("채널 삭제"):
            row_id = st.number_input("삭제할 채널 ID", min_value=1, step=1, key="delete_channel_id")
            if st.button("채널 삭제", type="secondary"):
                delete_row("benchmark_channels", int(row_id))
                st.success("삭제했습니다. 새로고침하면 반영됩니다.")
    with tab2:
        refs = load_references()
        st.dataframe(refs, use_container_width=True, hide_index=True)
        with st.expander("상태 변경"):
            ref_id = st.number_input("상태 변경할 콘텐츠 ID", min_value=1, step=1, key="status_ref_id")
            new_status = st.selectbox("새 상태", STATUS_OPTIONS, index=2, key="new_ref_status")
            if st.button("상태 변경"):
                update_reference_status(int(ref_id), new_status)
                st.success("상태를 변경했습니다. 새로고침하면 반영됩니다.")
        with st.expander("콘텐츠 삭제"):
            row_id = st.number_input("삭제할 콘텐츠 ID", min_value=1, step=1, key="delete_ref_id")
            if st.button("콘텐츠 삭제", type="secondary"):
                delete_row("content_references", int(row_id))
                st.success("삭제했습니다. 새로고침하면 반영됩니다.")


def render_export():
    st.subheader("CSV 내보내기")
    if st.button("CSV 파일 생성"):
        channels_path, refs_path = export_data()
        st.success("CSV 파일을 생성했습니다.")
        with open(channels_path, "rb") as f:
            st.download_button("benchmark_channels.csv 다운로드", f, file_name="benchmark_channels.csv", mime="text/csv")
        with open(refs_path, "rb") as f:
            st.download_button("content_references.csv 다운로드", f, file_name="content_references.csv", mime="text/csv")


def main():
    st.set_page_config(page_title=APP_TITLE, page_icon="🎬", layout="wide")
    init_db()
    st.title("🎬 EAFi Benchmark DB MVP")
    st.caption("벤치마크 채널 → 참고 콘텐츠 → 점수화 → 카드뉴스 후보 추출")
    menu = st.sidebar.radio("메뉴", ["대시보드", "벤치마크 채널 등록", "참고 콘텐츠 등록", "카드뉴스 후보 추출", "DB 보기 / 관리", "CSV 내보내기"])
    if menu == "대시보드":
        render_dashboard()
    elif menu == "벤치마크 채널 등록":
        render_add_channel()
    elif menu == "참고 콘텐츠 등록":
        render_add_reference()
    elif menu == "카드뉴스 후보 추출":
        render_candidates()
    elif menu == "DB 보기 / 관리":
        render_tables()
    elif menu == "CSV 내보내기":
        render_export()


if __name__ == "__main__":
    main()
