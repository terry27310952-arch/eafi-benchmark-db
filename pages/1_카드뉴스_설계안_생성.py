import sqlite3
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_cardnews_table():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS cardnews_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_id INTEGER,
            title TEXT NOT NULL,
            target_customer TEXT,
            core_problem TEXT,
            main_message TEXT,
            cta TEXT,
            slide_1 TEXT,
            slide_2 TEXT,
            slide_3 TEXT,
            slide_4 TEXT,
            slide_5 TEXT,
            slide_6 TEXT,
            image_1 TEXT,
            image_2 TEXT,
            image_3 TEXT,
            image_4 TEXT,
            image_5 TEXT,
            image_6 TEXT,
            status TEXT DEFAULT '초안',
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def load_references():
    conn = connect_db()
    df = pd.read_sql_query(
        """
        SELECT r.id, c.platform, c.channel_name, c.category, r.title, r.url,
               r.hook_point, r.structure_note, r.visual_note, r.eafi_application,
               r.total_score, r.status, r.created_at
        FROM content_references r
        LEFT JOIN benchmark_channels c ON r.channel_id = c.id
        ORDER BY r.total_score DESC, r.id DESC
        """,
        conn,
    )
    conn.close()
    return df


def load_plans():
    conn = connect_db()
    df = pd.read_sql_query(
        """
        SELECT *
        FROM cardnews_plans
        ORDER BY id DESC
        """,
        conn,
    )
    conn.close()
    return df


def build_cardnews_plan(row, target_customer, cta):
    title = row.get("eafi_application") or row.get("title") or "EAFi 카드뉴스"
    hook = row.get("hook_point") or "영상 제작에서 가장 크게 놓치는 문제"
    structure = row.get("structure_note") or "문제 제기 → 원인 분석 → 해결 방식 → 실행 제안"
    visual = row.get("visual_note") or "비포/애프터 비교, 제작 프로세스, 체크리스트형 그래픽"
    application = row.get("eafi_application") or title

    return {
        "title": title,
        "target_customer": target_customer,
        "core_problem": hook,
        "main_message": f"{application}을 통해 단순히 멋진 영상이 아니라 문의로 이어지는 제작 구조를 보여준다.",
        "cta": cta,
        "slides": [
            f"{hook}",
            "많은 기업이 영상 제작을 시작할 때 결과물보다 먼저 놓치는 것이 있습니다. 바로 제작 목적과 전환 경로입니다.",
            f"벤치마크 구조: {structure}",
            "EAFi는 영상의 예쁨보다 먼저 고객이 어떤 장면에서 멈추고, 어떤 이유로 문의하는지 설계합니다.",
            f"적용 방향: {application}",
            f"비슷한 영상이 필요하다면 {cta}",
        ],
        "images": [
            "강한 문제 제기를 보여주는 기업 담당자 또는 브랜드 회의 장면. 어두운 배경, 화면에는 복잡한 영상 제작 체크리스트.",
            "영상 제작 비용과 수정 요청이 늘어나는 과정을 보여주는 인포그래픽형 이미지. 텍스트 없이 그래프와 아이콘 중심.",
            f"벤치마크 콘텐츠의 전개 구조를 시각화한 카드형 다이어그램. 핵심 참고 요소: {visual}",
            "EAFi 팀이 스토리보드, AI 영상 컷, 브랜드 무드보드를 한 화면에서 정리하는 고급 프로덕션 워크스테이션 장면.",
            "비포/애프터 비교 구도. 왼쪽은 평범한 브랜드 영상, 오른쪽은 전환을 고려한 시네마틱 AI 하이브리드 영상 콘셉트.",
            "깔끔한 CTA 마무리 컷. 포트폴리오 화면과 견적 문의 버튼이 보이는 프리미엄 웹사이트 목업.",
        ],
    }


def save_plan(reference_id, plan):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO cardnews_plans
        (reference_id, title, target_customer, core_problem, main_message, cta,
         slide_1, slide_2, slide_3, slide_4, slide_5, slide_6,
         image_1, image_2, image_3, image_4, image_5, image_6, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            reference_id,
            plan["title"],
            plan["target_customer"],
            plan["core_problem"],
            plan["main_message"],
            plan["cta"],
            plan["slides"][0],
            plan["slides"][1],
            plan["slides"][2],
            plan["slides"][3],
            plan["slides"][4],
            plan["slides"][5],
            plan["images"][0],
            plan["images"][1],
            plan["images"][2],
            plan["images"][3],
            plan["images"][4],
            plan["images"][5],
            "초안",
            datetime.now().isoformat(timespec="seconds"),
        ),
    )
    conn.commit()
    conn.close()


def render_plan(plan):
    st.markdown("### 핵심 설계")
    st.write(f"**주제:** {plan['title']}")
    st.write(f"**타깃:** {plan['target_customer']}")
    st.write(f"**핵심 문제:** {plan['core_problem']}")
    st.write(f"**메인 메시지:** {plan['main_message']}")
    st.write(f"**CTA:** {plan['cta']}")

    st.markdown("### 6장 카드뉴스 구성")
    for idx, (copy, image) in enumerate(zip(plan["slides"], plan["images"]), start=1):
        with st.container(border=True):
            st.markdown(f"#### {idx}장")
            st.markdown(f"**카피**  \n{copy}")
            st.markdown(f"**이미지 방향**  \n{image}")


def main():
    st.set_page_config(page_title="카드뉴스 설계안 생성", page_icon="🧩", layout="wide")
    init_cardnews_table()

    st.title("🧩 카드뉴스 설계안 생성")
    st.caption("참고 콘텐츠 후보를 6장 카드뉴스 원본 구조로 변환합니다.")

    refs = load_references()
    if refs.empty:
        st.warning("먼저 메인 페이지에서 벤치마크 채널과 참고 콘텐츠를 등록하세요.")
        return

    options = {
        f"{row['id']} · {row['total_score']}점 · {row['title']}": row
        for _, row in refs.iterrows()
    }

    selected_key = st.selectbox("카드뉴스로 만들 참고 콘텐츠", list(options.keys()))
    row = options[selected_key]

    col1, col2 = st.columns(2)
    with col1:
        target_customer = st.text_input("타깃 고객", value="영상 제작을 고민하는 브랜드/마케팅 담당자")
    with col2:
        cta = st.text_input("CTA", value="DM으로 포트폴리오와 견적을 받아보세요")

    plan = build_cardnews_plan(row, target_customer, cta)
    render_plan(plan)

    if st.button("이 설계안 저장", type="primary"):
        save_plan(int(row["id"]), plan)
        st.success("카드뉴스 설계안을 저장했습니다.")

    st.markdown("---")
    st.markdown("### 저장된 카드뉴스 설계안")
    plans = load_plans()
    if plans.empty:
        st.info("아직 저장된 설계안이 없습니다.")
    else:
        st.dataframe(plans, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
