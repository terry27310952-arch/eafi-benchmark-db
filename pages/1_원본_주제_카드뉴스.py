import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")

TEMPLATE_OPTIONS = ["문제 제기형", "체크리스트형", "전후 비교형", "교육형", "트렌드 분석형"]
TONE_LEVELS = ["담백", "명확", "강한 후킹", "자극적"]
TOPIC_TYPES = ["자동 감지", "시장/투자", "트렌드/이슈", "브랜드/마케팅", "라이프스타일", "교육/노하우", "직접 입력"]
CTA_PRESETS = {
    "저장 유도": "이 기준은 저장해두고 다시 확인해보세요",
    "댓글 유도": "여러분은 이 흐름을 어떻게 보고 계신가요? 댓글로 남겨주세요",
    "공유 유도": "이 주제가 필요한 분에게 공유해보세요",
    "팔로우 유도": "비슷한 분석을 계속 보고 싶다면 팔로우해두세요",
    "DM 문의": "이런 카드뉴스 제작이 필요하다면 DM으로 문의해주세요",
    "직접 입력": "",
}

VISUAL_STYLES = {
    "깔끔한 인포그래픽": "1:1 카드뉴스. 넓은 여백, 선명한 타이포, 정리된 아이콘과 다이어그램 중심.",
    "뉴스/이슈형": "1:1 카드뉴스. 뉴스 헤드라인, 데이터 패널, 시장 반응, 타임라인을 활용한 에디토리얼 스타일.",
    "프리미엄 브랜드형": "1:1 카드뉴스. 블랙, 화이트, 웜 그레이 기반의 고급 브랜드 매거진 톤.",
    "데이터 분석형": "1:1 카드뉴스. 그래프, 지표, 비교표, 체크포인트가 중심인 분석형 디자인.",
    "커뮤니티 바이럴형": "1:1 카드뉴스. 짧은 훅, 큰 타이포, 강한 대비, 공유 욕구가 생기는 구성.",
}


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_table():
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
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
    """)
    conn.commit()
    conn.close()


def load_references():
    conn = connect_db()
    df = pd.read_sql_query("""
        SELECT r.id, c.platform, c.channel_name, c.category, r.title, r.url,
               r.hook_point, r.structure_note, r.visual_note, r.eafi_application,
               r.total_score, r.status, r.created_at
        FROM content_references r
        LEFT JOIN benchmark_channels c ON r.channel_id = c.id
        ORDER BY r.id DESC
    """, conn)
    conn.close()
    return df


def load_plans():
    conn = connect_db()
    df = pd.read_sql_query("SELECT * FROM cardnews_plans ORDER BY id DESC LIMIT 50", conn)
    conn.close()
    return df


def clean(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    if text.lower() in ["nan", "none", "null"]:
        return fallback
    return text or fallback


def strip_raw_labels(text):
    text = clean(text)
    text = re.sub(r"(?im)^\s*(title|url|source|link|영상 제목|제목)\s*[:：]\s*", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"www\.\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def compact_lines(text):
    return "\n".join([line.strip() for line in clean(text).splitlines() if line.strip()])


def shorten(text, max_len=86):
    text = strip_raw_labels(text)
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def polish(text, tone="명확"):
    text = compact_lines(strip_raw_labels(text))
    replacements = {
        "핵심 문제": "문제의 핵심",
        "진짜": "정말",
        "결과는 생각보다 조용합니다": "반응은 조용할 수 있습니다",
        "없으면": "없다면",
        "합니다입니다": "합니다",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if tone == "담백":
        text = text.replace("큰일납니다", "주의가 필요합니다")
        text = text.replace("놓치면 안 됩니다", "확인해볼 필요가 있습니다")
    elif tone == "자극적":
        text = text.replace("봐야 합니다", "놓치면 안 됩니다")
        text = text.replace("확인해야 합니다", "반드시 확인해야 합니다")
    return text.strip()


def detect_topic_type(text):
    t = clean(text).lower()
    if any(w in t for w in ["2차전지", "배터리", "전기차", "코인", "비트코인", "주식", "시장", "투자", "가격", "섹터"]):
        return "시장/투자"
    if any(w in t for w in ["트렌드", "이슈", "논란", "요즘", "급등", "관심", "바이럴"]):
        return "트렌드/이슈"
    if any(w in t for w in ["브랜드", "마케팅", "광고", "콘텐츠", "유튜브", "영상", "제작"]):
        return "브랜드/마케팅"
    if any(w in t for w in ["방법", "노하우", "강의", "배우", "체크리스트"]):
        return "교육/노하우"
    return "트렌드/이슈"


def analyze_source(row, selected_topic_type):
    title = strip_raw_labels(row.get("title"))
    hook = strip_raw_labels(row.get("hook_point"))
    structure = strip_raw_labels(row.get("structure_note"))
    application = strip_raw_labels(row.get("eafi_application"))
    source_text = " ".join([title, hook, structure, application])

    topic_type = detect_topic_type(source_text) if selected_topic_type == "자동 감지" else selected_topic_type
    topic = shorten(title or application or hook or "원본 주제", 54)

    if topic_type == "시장/투자":
        claim = f"{topic}에 시장의 관심이 다시 모이는 흐름을 다룹니다"
        audience_problem = "많은 사람은 방향보다 가격만 먼저 보고, 왜 움직이는지에 대한 판단 기준을 놓치기 쉽습니다"
        angle = f"{topic}에서 지금 먼저 봐야 할 것"
        checklist = ["왜 지금 관심이 모이는가", "실제로 바뀐 지표가 있는가", "기대감과 현실 사이의 간격은 어느 정도인가", "다음 판단 기준은 무엇인가"]
    elif topic_type == "브랜드/마케팅":
        claim = f"{topic}이 성과로 이어지는 구조를 다룹니다"
        audience_problem = "보기 좋은 결과물만 보다가 실제 행동으로 이어지는 흐름을 놓치기 쉽습니다"
        angle = f"{topic}이 결과로 이어지려면 먼저 봐야 할 것"
        checklist = ["누구에게 말하는가", "무엇을 기억하게 할 것인가", "어떤 감정을 만들 것인가", "다음 행동은 무엇인가"]
    elif topic_type == "교육/노하우":
        claim = f"{topic}을 더 쉽게 이해하는 기준을 다룹니다"
        audience_problem = "방법은 많지만 무엇부터 봐야 하는지 정리되지 않아 실행이 어려워집니다"
        angle = f"{topic}을 이해하기 전 확인할 기준"
        checklist = ["먼저 알아야 할 개념", "흔히 하는 착각", "실제로 적용할 순서", "마지막 체크포인트"]
    else:
        claim = f"{topic}에 대한 관심이 커지는 흐름을 다룹니다"
        audience_problem = "사람들은 결론만 먼저 보다가 왜 중요한지, 무엇을 확인해야 하는지 놓치기 쉽습니다"
        angle = f"{topic}에서 지금 봐야 할 것"
        checklist = ["왜 관심이 커졌는가", "사람들이 놓치는 지점은 무엇인가", "진짜 봐야 할 기준은 무엇인가", "다음에 확인할 것은 무엇인가"]

    if len(structure) < 20:
        structure = "후킹 질문 → 배경 설명 → 문제 정의 → 판단 기준 → 정리/CTA"

    return {
        "topic_type": topic_type,
        "topic": topic,
        "claim": claim,
        "audience_problem": audience_problem,
        "angle": angle,
        "structure": structure,
        "checklist": checklist,
        "source_text": source_text,
    }


def build_plan(ctx):
    analysis = ctx["analysis"]
    template = ctx["template"]
    tone = ctx["tone"]
    angle = ctx["angle"] or analysis["angle"]
    problem = ctx["problem"] or analysis["audience_problem"]
    cta = ctx["cta"]
    topic = analysis["topic"]

    if template == "체크리스트형":
        items = analysis["checklist"]
        slides = [
            f"{shorten(angle, 30)}\n보기 전에 체크할 4가지",
            f"1. {items[0]}",
            f"2. {items[1]}",
            f"3. {items[2]}",
            f"4. {items[3]}",
            f"결론보다 중요한 건\n판단 기준을 갖는 것입니다\n{cta}",
        ]
    elif template == "전후 비교형":
        slides = [
            f"{shorten(topic, 30)}\n반응이 갈리는 이유",
            f"Before\n결론부터 보고 따라가는 상태",
            f"After\n왜 움직이는지 기준을 먼저 보는 상태",
            f"차이는 여기서 납니다\n{shorten(problem, 82)}",
            f"그래서 봐야 할 건\n{shorten(analysis['structure'], 82)}",
            f"이 흐름이 중요하다고 느꼈다면\n{cta}",
        ]
    elif template == "교육형":
        slides = [
            f"{shorten(angle, 30)}\n이 원리부터 보면 쉽습니다",
            analysis["claim"],
            f"첫 번째는 문제 인식\n{shorten(problem, 82)}",
            f"두 번째는 판단 기준\n{shorten(analysis['structure'], 82)}",
            "세 번째는 적용입니다\n정보를 그대로 믿기보다\n내 상황에 맞게 다시 봐야 합니다",
            f"이 기준은 저장해두고\n다시 확인해보세요\n{cta}",
        ]
    elif template == "트렌드 분석형":
        slides = [
            f"{shorten(topic, 30)}\n왜 지금 다시 보일까요?",
            analysis["claim"],
            f"관심이 커질수록\n{shorten(problem, 82)}",
            "중요한 건 분위기가 아니라\n그 흐름을 만든 이유입니다",
            f"지금 볼 기준은\n{shorten(analysis['structure'], 82)}",
            f"다음 흐름도 놓치고 싶지 않다면\n{cta}",
        ]
    else:
        slides = [
            f"{shorten(angle, 30)}\n지금 봐야 할 건 따로 있습니다",
            analysis["claim"],
            f"문제는\n{shorten(problem, 82)}입니다",
            "결론보다 중요한 건\n왜 움직이는지 보는 기준입니다",
            f"핵심 흐름은\n{shorten(analysis['structure'], 82)}",
            f"이 기준이 필요했다면\n{cta}",
        ]

    images = build_images(ctx, template)
    slides = [polish(slide, tone) for slide in slides]
    return {
        "title": f"[원본 주제] {shorten(angle, 48)}",
        "target_customer": ctx["topic_type"],
        "core_problem": polish(problem, tone),
        "main_message": polish(f"{topic}에서 중요한 건 결론보다 왜 지금 중요한지 판단하는 기준입니다", tone),
        "cta": polish(cta, tone),
        "common_style": ctx["common_style"],
        "slides": slides,
        "images": images,
    }


def build_images(ctx, template):
    topic = ctx["analysis"]["topic"]
    if template == "체크리스트형":
        return [
            f"{topic}를 상징하는 강한 첫 장. 큰 제목, 핵심 오브젝트, 짧은 경고성 분위기.",
            "체크리스트 1번을 보여주는 카드. 원인 또는 배경을 한눈에 보여주는 아이콘과 짧은 구조도.",
            "체크리스트 2번을 보여주는 카드. 수치, 지표, 비교 표식이 보이는 분석형 구성.",
            "체크리스트 3번을 보여주는 카드. 사람들이 흔히 놓치는 지점을 빨간 표시로 강조.",
            "체크리스트 4번을 보여주는 카드. 다음 행동 기준을 정리한 깔끔한 보드.",
            "저장/공유/댓글 행동을 유도하는 마무리 카드. 여백 중심의 깔끔한 CTA 구성.",
        ]
    return [
        f"{topic}를 상징하는 첫 장. 뉴스 헤드라인, 데이터 패널, 주목받는 오브젝트를 강한 후킹 구도로 표현.",
        "원본 주제에 관심이 몰리는 흐름을 보여주는 장면. 검색량, 뉴스, 커뮤니티 반응이 정리된 느낌.",
        "독자가 놓치기 쉬운 문제를 시각화. 잘못된 판단과 올바른 판단 기준이 대비되는 인포그래픽.",
        "원인과 배경을 분석하는 장면. 흐름을 만든 이유가 3가지 가지로 나뉘어 보이는 보드.",
        "핵심 기준을 정리한 카드. 체크포인트, 판단 기준, 다음 확인 지점이 한눈에 보이게 구성.",
        "저장, 공유, 댓글 같은 행동을 유도하는 마무리 카드. CTA가 선명한 구성.",
    ]


def save_plan(reference_id, plan):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cardnews_plans
        (reference_id, title, target_customer, core_problem, main_message, cta,
         slide_1, slide_2, slide_3, slide_4, slide_5, slide_6,
         image_1, image_2, image_3, image_4, image_5, image_6, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        reference_id, plan["title"], plan["target_customer"], plan["core_problem"], plan["main_message"], plan["cta"],
        plan["slides"][0], plan["slides"][1], plan["slides"][2], plan["slides"][3], plan["slides"][4], plan["slides"][5],
        plan["images"][0], plan["images"][1], plan["images"][2], plan["images"][3], plan["images"][4], plan["images"][5],
        "원본 주제", datetime.now().isoformat(timespec="seconds"),
    ))
    conn.commit()
    conn.close()


def update_state(plan, signature, force=False):
    if force or st.session_state.get("original_topic_signature") != signature or "original_topic_plan" not in st.session_state:
        st.session_state["original_topic_signature"] = signature
        st.session_state["original_topic_plan"] = plan
        st.session_state["original_topic_version"] = st.session_state.get("original_topic_version", 0) + 1


def render_editable(plan, version):
    suffix = f"v{version}"
    st.markdown("### 공통 이미지 스타일")
    common_style = st.text_area("공통 스타일", value=plan["common_style"], height=90, key=f"ot_common_{suffix}")

    st.markdown("### 핵심 설계")
    title = st.text_input("저장할 주제명", value=plan["title"], key=f"ot_title_{suffix}")
    core_problem = st.text_area("핵심 문제", value=plan["core_problem"], height=80, key=f"ot_problem_{suffix}")
    main_message = st.text_area("메인 메시지", value=plan["main_message"], height=90, key=f"ot_message_{suffix}")
    cta = st.text_input("CTA", value=plan["cta"], key=f"ot_cta_{suffix}")

    st.markdown("### 6장 카드뉴스 구성 직접 수정")
    slides, images = [], []
    for idx, (copy, image) in enumerate(zip(plan["slides"], plan["images"]), start=1):
        with st.container(border=True):
            st.markdown(f"#### {idx}장")
            slides.append(st.text_area("카피", value=copy, height=120, key=f"ot_slide_{idx}_{suffix}"))
            images.append(st.text_area("장별 이미지 방향", value=image, height=100, key=f"ot_image_{idx}_{suffix}"))

    edited = dict(plan)
    edited.update({"common_style": common_style, "title": title, "core_problem": core_problem, "main_message": main_message, "cta": cta, "slides": slides, "images": images})
    return edited


def main():
    st.set_page_config(page_title="원본 주제 카드뉴스", page_icon="📰", layout="wide")
    init_table()

    st.title("📰 원본 주제 카드뉴스")
    st.caption("수집한 링크/영상의 주제 자체를 카드뉴스로 재가공합니다. eaf 서비스 영업 카피와 분리된 메뉴입니다.")

    refs = load_references()
    if refs.empty:
        st.warning("먼저 URL 자동 수집 또는 YouTube 영상 내용 분석에서 참고 콘텐츠를 저장하세요.")
        return

    options = {f"{row['id']} · {clean(row['title'])}": row for _, row in refs.iterrows()}
    selected_key = st.selectbox("원본 콘텐츠 선택", list(options.keys()))
    row = options[selected_key]

    st.markdown("---")
    st.markdown("### 생성 조건")
    c1, c2, c3 = st.columns(3)
    with c1:
        topic_type_select = st.selectbox("주제 유형", TOPIC_TYPES, index=0)
    with c2:
        template = st.selectbox("콘텐츠 구조", TEMPLATE_OPTIONS, index=0)
    with c3:
        tone = st.selectbox("후킹 강도", TONE_LEVELS, index=2)

    analysis = analyze_source(row, topic_type_select)
    if topic_type_select == "직접 입력":
        analysis["topic_type"] = st.text_input("주제 유형 직접 입력", value="사용자 정의")

    with st.expander("원본 분석 결과", expanded=True):
        st.write(f"**감지된 주제 유형:** {analysis['topic_type']}")
        st.write(f"**원본 주제:** {analysis['topic']}")
        st.write(f"**핵심 주장:** {analysis['claim']}")
        st.write(f"**독자 문제:** {analysis['audience_problem']}")
        st.write(f"**차용할 전개 구조:** {analysis['structure']}")

    c4, c5 = st.columns(2)
    with c4:
        angle = st.text_input("카드뉴스 핵심 각도", value=analysis["angle"])
        problem = st.text_area("핵심 문제", value=analysis["audience_problem"], height=80)
    with c5:
        cta, cta_label = select_cta = select_from_dict_like("CTA", CTA_PRESETS, "ot_cta_preset", "저장 유도")
        visual_label = st.selectbox("이미지 스타일", list(VISUAL_STYLES.keys()), index=0)
        common_style = st.text_area("공통 이미지 스타일", value=VISUAL_STYLES[visual_label], height=80)

    ctx = {
        "analysis": analysis,
        "template": template,
        "tone": tone,
        "topic_type": analysis["topic_type"],
        "angle": angle,
        "problem": problem,
        "cta": cta,
        "common_style": common_style,
    }
    plan = build_plan(ctx)

    signature = "|".join([str(int(row["id"])), analysis["topic_type"], template, tone, angle, problem, cta, common_style])
    update_state(plan, signature)

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("현재 선택값으로 초안 다시 생성"):
            update_state(plan, signature, force=True)
            st.rerun()
    with col_info:
        st.info("이 메뉴는 원본 주제 자체를 카드뉴스로 만듭니다. eaf 서비스 전환 카피는 넣지 않습니다.")

    st.markdown("---")
    draft = st.session_state.get("original_topic_plan", plan)
    version = st.session_state.get("original_topic_version", 0)
    edited = render_editable(draft, version)

    if st.button("이 설계안 저장", type="primary"):
        save_plan(int(row["id"]), edited)
        st.success("원본 주제 카드뉴스 설계안을 저장했습니다.")

    st.markdown("---")
    st.markdown("### 최근 저장된 카드뉴스")
    plans = load_plans()
    if plans.empty:
        st.info("아직 저장된 카드뉴스가 없습니다.")
    else:
        st.dataframe(plans, use_container_width=True, hide_index=True)


def select_from_dict_like(label, options, key, default=None):
    labels = list(options.keys())
    index = labels.index(default) if default in labels else 0
    selected = st.selectbox(label, labels, index=index, key=f"{key}_select")
    if selected == "직접 입력":
        return st.text_area(f"{label} 직접 입력", height=80, key=f"{key}_custom"), selected
    return options[selected], selected


if __name__ == "__main__":
    main()
