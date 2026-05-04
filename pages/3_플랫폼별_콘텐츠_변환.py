import sqlite3
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")

PLATFORMS = [
    "Instagram Carousel",
    "Instagram Reels",
    "YouTube Shorts",
    "Naver Blog",
    "Threads",
    "TikTok",
]


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_platform_table():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS platform_contents (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER,
            platform TEXT NOT NULL,
            title TEXT,
            content TEXT,
            cta TEXT,
            status TEXT DEFAULT '초안',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def load_plans():
    conn = connect_db()
    try:
        df = pd.read_sql_query("SELECT * FROM cardnews_plans ORDER BY id DESC", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def load_platform_contents(plan_id=None):
    conn = connect_db()
    try:
        query = "SELECT * FROM platform_contents ORDER BY id DESC"
        df = pd.read_sql_query(query, conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    if plan_id is not None and not df.empty:
        df = df[df["plan_id"] == plan_id]
    return df


def slide_list(plan):
    return [plan.get(f"slide_{i}") or "" for i in range(1, 7)]


def build_instagram_carousel(plan):
    slides = slide_list(plan)
    title = plan["title"]
    body = []
    body.append(f"[캐러셀 제목]\n{slides[0] or title}")
    for idx, slide in enumerate(slides, start=1):
        body.append(f"\n{idx}장\n{slide}")
    body.append(f"\n[캡션]\n{plan['core_problem']}\n\n{plan['main_message']}\n\n비슷한 영상이 필요하다면 {plan['cta']}")
    return title, "\n".join(body), plan["cta"]


def build_reels_script(plan):
    slides = slide_list(plan)
    title = f"{plan['title']} 릴스 대본"
    body = f"""
0~3초
{slides[0]}

3~8초
대부분 기업이 영상 제작을 시작할 때 이 부분을 놓칩니다.

8~18초
{slides[1]}
{slides[2]}

18~30초
{slides[3]}
{slides[4]}

30~40초
{slides[5]}

화면 구성
- 빠른 컷 전환
- 카드뉴스 원본 이미지 6장을 순서대로 사용
- 마지막 컷은 포트폴리오/견적 CTA

CTA
{plan['cta']}
""".strip()
    return title, body, plan["cta"]


def build_youtube_shorts(plan):
    title = f"{plan['title']} 쇼츠 대본"
    body = f"""
{plan['core_problem']}

근데 이거, 단순히 영상 퀄리티 문제가 아닙니다.

많은 브랜드가 영상 제작을 할 때
예쁜 결과물만 생각하고
정작 이 영상이 어디서 문의로 이어지는지는 설계하지 않습니다.

EAFi는 영상의 분위기보다 먼저
시청자가 어디서 멈추고
왜 문의해야 하는지를 설계합니다.

그래서 중요한 건 하나입니다.
멋진 영상이 아니라
전환되는 영상 구조입니다.

비슷한 사례가 궁금하다면 {plan['cta']}
""".strip()
    return title, body, plan["cta"]


def build_naver_blog(plan):
    slides = slide_list(plan)
    title = f"{plan['title']}｜기업 영상 제작 전 꼭 봐야 할 체크포인트"
    body = f"""
# {title}

기업 영상 제작을 고민할 때 많은 브랜드가 가장 먼저 보는 것은 결과물의 퀄리티입니다.
물론 영상은 멋져야 합니다. 하지만 실제 문의와 계약으로 이어지려면 그보다 먼저 봐야 할 것이 있습니다.

## 1. 문제 제기

{plan['core_problem']}

## 2. 왜 이 문제가 중요한가

{slides[1]}

영상 제작은 단순한 디자인 작업이 아니라, 브랜드가 고객에게 어떤 인상을 남기고 어떤 행동을 유도할지 설계하는 과정입니다.

## 3. 대부분 놓치는 지점

{slides[2]}

제작비, 수정 횟수, 일정 문제는 대부분 처음 기획 단계에서 목적과 승인 구조가 명확하지 않을 때 발생합니다.

## 4. EAFi의 접근 방식

{slides[3]}

EAFi는 AI와 실사를 결합해 고급스러운 영상을 만들되, 영상의 목적과 전환 경로를 먼저 설계합니다.

## 5. 적용 예시

{slides[4]}

브랜드 필름, 제품 영상, SNS 광고 소재, 상세페이지 영상은 각각 필요한 구도와 메시지가 다릅니다.

## 6. 정리

{plan['main_message']}

영상 제작을 고민 중이라면 포트폴리오와 견적을 먼저 확인해보는 것이 좋습니다.

문의: {plan['cta']}
""".strip()
    return title, body, plan["cta"]


def build_threads(plan):
    slides = slide_list(plan)
    title = f"{plan['title']} 쓰레드"
    body = f"""
1.
{slides[0]}

2.
기업 영상은 예쁘게 만드는 것보다 먼저, 어디서 문의로 이어질지 설계해야 합니다.

3.
{slides[2]}

4.
영상 제작비가 터지는 이유는 대부분 후반 작업이 아니라 초반 기획 부재에서 나옵니다.

5.
{plan['main_message']}

6.
비슷한 영상 구조가 필요하면 {plan['cta']}
""".strip()
    return title, body, plan["cta"]


def build_tiktok(plan):
    title = f"{plan['title']} 틱톡 훅 테스트"
    body = f"""
훅 A
{plan['core_problem']}

훅 B
기업 영상 만들 때 돈 새는 지점, 대부분 여기입니다.

훅 C
영상이 안 팔리는 이유, 퀄리티 때문만은 아닙니다.

15초 대본
기업 영상 제작할 때 많은 분들이 결과물만 봅니다.
근데 진짜 중요한 건 이 영상이 어디서 문의로 이어지는지입니다.
예쁜 영상은 많습니다.
근데 전환되는 영상은 설계가 다릅니다.
비슷한 사례가 궁금하면 {plan['cta']}
""".strip()
    return title, body, plan["cta"]


def build_content(plan, platform):
    if platform == "Instagram Carousel":
        return build_instagram_carousel(plan)
    if platform == "Instagram Reels":
        return build_reels_script(plan)
    if platform == "YouTube Shorts":
        return build_youtube_shorts(plan)
    if platform == "Naver Blog":
        return build_naver_blog(plan)
    if platform == "Threads":
        return build_threads(plan)
    if platform == "TikTok":
        return build_tiktok(plan)
    return plan["title"], "", plan["cta"]


def save_platform_content(plan_id, platform, title, content, cta):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO platform_contents
        (plan_id, platform, title, content, cta, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (plan_id, platform, title, content, cta, "초안", datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()


def export_platform_contents(plan_id=None):
    df = load_platform_contents(plan_id)
    export_dir = Path("exports")
    export_dir.mkdir(exist_ok=True)
    path = export_dir / "platform_contents.csv"
    df.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def main():
    st.set_page_config(page_title="플랫폼별 콘텐츠 변환", page_icon="🚀", layout="wide")
    init_platform_table()

    st.title("🚀 플랫폼별 콘텐츠 변환")
    st.caption("컨펌된 카드뉴스 설계안을 인스타, 쇼츠, 블로그, 쓰레드, 틱톡용 콘텐츠로 변환합니다.")

    plans = load_plans()
    if plans.empty:
        st.warning("먼저 카드뉴스 설계안을 저장하세요.")
        return

    options = {f"{row['id']} · {row['title']}": row for _, row in plans.iterrows()}
    selected_key = st.selectbox("변환할 카드뉴스 설계안", list(options.keys()))
    plan = options[selected_key]
    plan_id = int(plan["id"])

    selected_platforms = st.multiselect("변환할 플랫폼", PLATFORMS, default=PLATFORMS)

    st.markdown("---")
    st.markdown("## 변환 결과")

    outputs = []
    for platform in selected_platforms:
        title, content, cta = build_content(plan, platform)
        outputs.append((platform, title, content, cta))
        with st.container(border=True):
            st.markdown(f"### {platform}")
            st.text_input("제목", value=title, key=f"title_{platform}")
            st.text_area("콘텐츠", value=content, height=320, key=f"content_{platform}")
            st.text_input("CTA", value=cta, key=f"cta_{platform}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("선택 플랫폼 콘텐츠 저장", type="primary"):
            for platform, title, content, cta in outputs:
                save_platform_content(plan_id, platform, title, content, cta)
            st.success("플랫폼별 콘텐츠를 저장했습니다.")

    with col2:
        if st.button("저장된 플랫폼 콘텐츠 CSV 내보내기"):
            path = export_platform_contents(plan_id)
            st.success("CSV 파일을 생성했습니다.")
            with open(path, "rb") as f:
                st.download_button("platform_contents.csv 다운로드", f, file_name="platform_contents.csv", mime="text/csv")

    st.markdown("---")
    st.markdown("## 저장된 플랫폼 콘텐츠")
    saved = load_platform_contents(plan_id)
    if saved.empty:
        st.info("아직 저장된 플랫폼 콘텐츠가 없습니다.")
    else:
        st.dataframe(saved, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
