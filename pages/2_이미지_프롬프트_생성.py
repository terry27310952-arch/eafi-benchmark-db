import sqlite3
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")

STYLE_PRESETS = {
    "EAFi 기본 고급 B2B": {
        "style": "premium B2B commercial visual, cinematic realism, clean composition, high-end brand film mood, refined lighting, modern Korean production studio atmosphere",
        "negative": "no text, no watermark, no logo distortion, no low quality, no cartoon, no messy layout, no extra fingers, no broken hands",
    },
    "AI 영상 제작사 무드": {
        "style": "futuristic AI video production studio, cinematic realistic lighting, sleek screens, storyboard wall, generative video interface, premium agency mood",
        "negative": "no readable UI text, no watermark, no distorted screens, no cheap stock photo look, no messy background",
    },
    "브랜드필름 시네마틱": {
        "style": "cinematic brand film frame, realistic photography, elegant depth of field, premium product campaign mood, sophisticated light and shadow",
        "negative": "no text, no watermark, no overexposed face, no plastic skin, no fake 3D render look",
    },
    "카드뉴스용 인포그래픽": {
        "style": "clean editorial infographic background, premium minimal layout, modern visual metaphor, clear subject separation, high readability, commercial design mood",
        "negative": "no text, no letters, no numbers, no clutter, no watermark, no cheap icon pack style",
    },
}

ASPECT_RATIOS = {
    "1:1 카드뉴스": "square 1:1 composition",
    "4:5 인스타 피드": "vertical 4:5 composition",
    "9:16 릴스/쇼츠": "vertical 9:16 composition",
    "16:9 유튜브/웹": "wide 16:9 composition",
}


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_prompt_table():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS image_prompts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            plan_id INTEGER,
            slide_no INTEGER,
            slide_copy TEXT,
            image_direction TEXT,
            prompt TEXT,
            negative_prompt TEXT,
            aspect_ratio TEXT,
            style_preset TEXT,
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
        df = pd.read_sql_query(
            """
            SELECT *
            FROM cardnews_plans
            ORDER BY id DESC
            """,
            conn,
        )
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def load_prompts():
    conn = connect_db()
    try:
        df = pd.read_sql_query(
            """
            SELECT *
            FROM image_prompts
            ORDER BY id DESC
            """,
            conn,
        )
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def build_prompt(plan, slide_no, slide_copy, image_direction, style_preset, aspect_ratio, extra_instruction):
    preset = STYLE_PRESETS[style_preset]
    ratio_text = ASPECT_RATIOS[aspect_ratio]

    base = f"""
Create a high-end visual for an EAFi card news slide.

Project topic: {plan['title']}
Target customer: {plan.get('target_customer') or 'brand and marketing decision makers'}
Slide number: {slide_no}
Slide message: {slide_copy}
Visual direction: {image_direction}

Visual style: {preset['style']}.
Composition: {ratio_text}, strong single focal point, clean negative space for Korean copy overlay, premium advertising look.
Lighting: soft cinematic lighting, refined contrast, realistic texture, professional commercial finish.
Mood: trustworthy, strategic, modern, high-value production partner.

Important: do not include any text inside the image. Leave clean space for typography overlay.
{extra_instruction}
""".strip()

    return "\n".join(line.strip() for line in base.splitlines() if line.strip())


def save_prompts(plan_id, prompts):
    conn = connect_db()
    cur = conn.cursor()
    for item in prompts:
        cur.execute(
            """
            INSERT INTO image_prompts
            (plan_id, slide_no, slide_copy, image_direction, prompt, negative_prompt, aspect_ratio, style_preset, status, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                plan_id,
                item["slide_no"],
                item["slide_copy"],
                item["image_direction"],
                item["prompt"],
                item["negative_prompt"],
                item["aspect_ratio"],
                item["style_preset"],
                "초안",
                datetime.now().isoformat(timespec="seconds"),
            ),
        )
    conn.commit()
    conn.close()


def export_prompts(plan_id=None):
    prompts = load_prompts()
    if plan_id is not None and not prompts.empty:
        prompts = prompts[prompts["plan_id"] == plan_id]

    export_dir = Path("exports")
    export_dir.mkdir(exist_ok=True)
    path = export_dir / "image_prompts.csv"
    prompts.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def get_slide_pairs(plan):
    pairs = []
    for i in range(1, 7):
        pairs.append(
            {
                "slide_no": i,
                "slide_copy": plan.get(f"slide_{i}") or "",
                "image_direction": plan.get(f"image_{i}") or "",
            }
        )
    return pairs


def render_prompt_card(item):
    with st.container(border=True):
        st.markdown(f"### {item['slide_no']}장 이미지 프롬프트")
        st.markdown(f"**카피**  \n{item['slide_copy']}")
        st.markdown(f"**이미지 방향**  \n{item['image_direction']}")
        st.text_area("Prompt", value=item["prompt"], height=260, key=f"prompt_{item['slide_no']}")
        st.text_area("Negative Prompt", value=item["negative_prompt"], height=100, key=f"negative_{item['slide_no']}")


def main():
    st.set_page_config(page_title="이미지 프롬프트 생성", page_icon="🖼️", layout="wide")
    init_prompt_table()

    st.title("🖼️ 이미지 프롬프트 생성")
    st.caption("저장된 카드뉴스 설계안을 기반으로 장별 이미지 생성 프롬프트를 만듭니다. 이미지는 생성하지 않습니다.")

    plans = load_plans()
    if plans.empty:
        st.warning("먼저 '카드뉴스 설계안 생성' 페이지에서 설계안을 저장하세요.")
        return

    options = {f"{row['id']} · {row['title']}": row for _, row in plans.iterrows()}
    selected_key = st.selectbox("이미지 프롬프트를 만들 카드뉴스 설계안", list(options.keys()))
    plan = options[selected_key]
    plan_id = int(plan["id"])

    col1, col2, col3 = st.columns(3)
    with col1:
        style_preset = st.selectbox("스타일 프리셋", list(STYLE_PRESETS.keys()))
    with col2:
        aspect_ratio = st.selectbox("비율", list(ASPECT_RATIOS.keys()))
    with col3:
        language_mode = st.selectbox("출력 기준", ["영문 프롬프트", "한글 설명 + 영문 프롬프트"])

    extra_instruction = st.text_area(
        "추가 지시사항",
        value="Use realistic Korean business context when people or offices appear. Keep the image clean and premium.",
        height=80,
    )

    preset = STYLE_PRESETS[style_preset]
    prompts = []
    for pair in get_slide_pairs(plan):
        prompt = build_prompt(
            plan,
            pair["slide_no"],
            pair["slide_copy"],
            pair["image_direction"],
            style_preset,
            aspect_ratio,
            extra_instruction,
        )
        if language_mode == "한글 설명 + 영문 프롬프트":
            prompt = f"[한글 설명]\n{pair['image_direction']}\n\n[English Prompt]\n{prompt}"
        prompts.append(
            {
                "slide_no": pair["slide_no"],
                "slide_copy": pair["slide_copy"],
                "image_direction": pair["image_direction"],
                "prompt": prompt,
                "negative_prompt": preset["negative"],
                "aspect_ratio": aspect_ratio,
                "style_preset": style_preset,
            }
        )

    st.markdown("---")
    st.markdown("## 생성 결과")
    for item in prompts:
        render_prompt_card(item)

    col_save, col_export = st.columns(2)
    with col_save:
        if st.button("이 프롬프트 6개 저장", type="primary"):
            save_prompts(plan_id, prompts)
            st.success("이미지 프롬프트 6개를 저장했습니다.")
    with col_export:
        if st.button("저장된 프롬프트 CSV 내보내기"):
            path = export_prompts(plan_id)
            st.success("CSV 파일을 생성했습니다.")
            with open(path, "rb") as f:
                st.download_button("image_prompts.csv 다운로드", f, file_name="image_prompts.csv", mime="text/csv")

    st.markdown("---")
    st.markdown("## 저장된 이미지 프롬프트")
    saved = load_prompts()
    if saved.empty:
        st.info("아직 저장된 이미지 프롬프트가 없습니다.")
    else:
        saved = saved[saved["plan_id"] == plan_id]
        st.dataframe(saved, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
