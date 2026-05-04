import sqlite3
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")

TEMPLATE_OPTIONS = [
    "문제폭로형",
    "오해반박형",
    "전후비교형",
    "체크리스트형",
    "케이스분석형",
    "교육노하우형",
]

VISUAL_STYLES = [
    "브랜드 캐릭터 중심",
    "실사 오피스 시네마틱",
    "인포그래픽 중심",
    "전후 비교형",
    "제품/포트폴리오 중심",
    "혼합형",
]

TONE_LEVELS = {
    "담백": 0,
    "명확": 1,
    "강한 후킹": 2,
    "자극적": 3,
}


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


def clean(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    if text.lower() in ["nan", "none", "null"]:
        return fallback
    return text or fallback


def shorten(text, max_len=80):
    text = clean(text)
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rstrip() + "…"


def compact_lines(text):
    lines = [line.strip() for line in clean(text).splitlines()]
    return "\n".join([line for line in lines if line])


def normalize_korean_copy(text):
    text = compact_lines(text)
    replacements = {
        "진짜 병목을 놓칩니다": "정작 중요한 지점을 놓치기 쉽습니다",
        "핵심 문제는 ": "문제의 핵심은 ",
        "비슷한 구조의 콘텐츠가 필요하다면": "이런 구조의 콘텐츠가 필요하다면",
        "필요하다면 DM": "필요하다면\nDM",
        "많은 사람이 편집 퀄리티만 고칩니다": "많은 분들이 편집 퀄리티부터 손봅니다",
        "고객이 납득하고 움직이는 흐름": "고객이 이해하고 움직이는 흐름",
        "고객의 판단 순서": "고객이 판단하는 순서",
        "결과물의 분위기보다 전환 구조를 먼저 설계한다": "결과물의 분위기보다 전환 구조를 먼저 설계합니다",
        "핵심 인사이트:": "핵심은",
        "를 위해": "에게 필요한",
        "가 결과물만": "는 결과물만",
        "담당자가 결과물만": "담당자는 결과물만",
        "담당자가는": "담당자는",
        "고객 행동까지 설계된 영상": "고객의 다음 행동까지 설계된 영상",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)

    # 너무 개발자스러운 접속어 정리
    text = text.replace("입니다\n입니다", "입니다")
    text = text.replace("합니다\n합니다", "합니다")
    text = text.replace("\n\n\n", "\n\n")
    return text.strip()


def split_target_label(target):
    target = clean(target, "브랜드/마케팅 담당자")
    for token in ["영상 제작을 고민하는 ", "영상을 고민하는 ", "콘텐츠 제작을 고민하는 "]:
        target = target.replace(token, "")
    return target.strip() or "브랜드/마케팅 담당자"


def review_slide_copy(slide, tone_level):
    slide = normalize_korean_copy(slide)
    lines = slide.splitlines()

    # 카드뉴스 문장은 너무 긴 한 줄보다 짧은 호흡이 좋다.
    refined = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if len(line) > 42 and " " in line:
            # 마침표 없는 긴 설명문을 부드럽게 2줄로 분리
            chunks = line.split(" ")
            mid = max(1, len(chunks) // 2)
            left = " ".join(chunks[:mid]).strip()
            right = " ".join(chunks[mid:]).strip()
            if len(left) >= 10 and len(right) >= 10:
                refined.extend([left, right])
            else:
                refined.append(line)
        else:
            refined.append(line)

    text = "\n".join(refined)

    if tone_level == "자극적":
        text = text.replace("놓치기 쉽습니다", "계속 놓치게 됩니다")
        text = text.replace("중요합니다", "여기서 갈립니다")
    elif tone_level == "담백":
        text = text.replace("진짜", "")
        text = text.replace("계속 새는 지점입니다", "확인해야 할 지점입니다")

    return compact_lines(text)


def review_plan_copy(plan, ctx):
    reviewed = dict(plan)
    reviewed["title"] = normalize_korean_copy(reviewed["title"])
    reviewed["core_problem"] = normalize_korean_copy(reviewed["core_problem"])
    reviewed["main_message"] = normalize_korean_copy(reviewed["main_message"])
    reviewed["cta"] = normalize_korean_copy(reviewed["cta"])
    reviewed["slides"] = [review_slide_copy(slide, ctx["tone_level"]) for slide in reviewed["slides"]]
    return reviewed


def build_context(row, inputs):
    source_title = clean(row.get("title"), "벤치마크 콘텐츠")
    hook_point = clean(row.get("hook_point"), source_title)
    structure_note = clean(row.get("structure_note"), "문제 제기 → 원인 분석 → 해결 방식 → 실행 제안")
    visual_note = clean(row.get("visual_note"), "브랜드 톤에 맞는 실사/인포그래픽 혼합 구성")
    application = clean(row.get("eafi_application"), source_title)
    channel_name = clean(row.get("channel_name"), "벤치마크 채널")
    platform = clean(row.get("platform"), "플랫폼")

    content_angle = clean(inputs.get("content_angle"), application)
    core_problem = clean(inputs.get("core_problem"), hook_point)
    insight = clean(inputs.get("insight"), structure_note)
    solution = clean(inputs.get("solution"), f"{inputs['brand_name']}는 결과물의 분위기보다 목적, 타깃, 메시지, 전환 흐름을 먼저 설계합니다")
    proof = clean(inputs.get("proof"), "기획 단계에서 구조를 잡으면 수정 횟수와 제작 리스크를 줄일 수 있습니다")
    offer = clean(inputs.get("offer"), "브랜드 필름, 제품 영상, 유튜브 콘텐츠까지 전환 구조를 기준으로 설계")

    return {
        "source_title": source_title,
        "hook_point": hook_point,
        "structure_note": structure_note,
        "visual_note": visual_note,
        "application": application,
        "channel_name": channel_name,
        "platform": platform,
        "content_angle": content_angle,
        "core_problem": core_problem,
        "insight": insight,
        "solution": solution,
        "proof": proof,
        "offer": offer,
        "target_customer": inputs["target_customer"],
        "target_label": split_target_label(inputs["target_customer"]),
        "cta": inputs["cta"],
        "brand_name": inputs["brand_name"],
        "visual_style": inputs["visual_style"],
        "tone_level": inputs["tone_level"],
    }


def hookify(text, tone_level):
    text = clean(text)
    if tone_level in ["담백", "명확"]:
        return text
    if tone_level == "강한 후킹":
        return text if any(word in text for word in ["왜", "이유", "문제", "진짜"]) else f"{text}\n문제는 다른 데 있습니다"
    return text if any(word in text for word in ["왜", "망", "큰일", "문제", "진짜"]) else f"{text}\n이걸 놓치면 계속 새게 됩니다"


def build_image_direction(ctx, slide_no, role):
    brand = ctx["brand_name"]
    visual_style = ctx["visual_style"]
    base = f"{brand} 브랜드 팔레트인 레드, 블랙, 웜 그레이를 사용한 1:1 카드뉴스 이미지. 공식 로고와 캐릭터 톤을 유지. "

    if visual_style == "브랜드 캐릭터 중심":
        character = "메인 캐릭터가 빨간 캡과 빨간 폴로를 입고 등장. 개구리 엠블럼은 모자/옷의 작은 패치로만 사용. "
    elif visual_style == "실사 오피스 시네마틱":
        character = "현대적인 어두운 오피스/편집실의 시네마틱 실사 장면. 필요한 경우 메인 캐릭터를 자연스럽게 배치. "
    elif visual_style == "인포그래픽 중심":
        character = "텍스트 없이도 이해되는 고급 인포그래픽, 아이콘, 다이어그램 중심. 메인 캐릭터는 작게 보조 요소로만 배치. "
    elif visual_style == "전후 비교형":
        character = "좌우 비교 구도. 왼쪽은 문제 상황, 오른쪽은 정리된 해결 상황. 메인 캐릭터는 해결 쪽에 자연스럽게 배치. "
    elif visual_style == "제품/포트폴리오 중심":
        character = "노트북, 포트폴리오, 영상 플레이어, 제품 컷, 브랜드 웹사이트 목업 중심. 캐릭터는 신뢰감을 주는 보조 인물로 배치. "
    else:
        character = "실사 장면과 인포그래픽을 혼합하고, 메인 캐릭터를 핵심 시선 유도 요소로 배치. "

    role_map = {
        "hook": "강한 문제 제기 장면. 보는 사람이 멈추도록 큰 대비와 여백을 확보.",
        "problem": "문제가 발생하는 원인을 시각화. 복잡한 수정, 낮은 전환, 불명확한 타깃 같은 신호를 세련되게 표현.",
        "analysis": "원인과 구조를 보여주는 다이어그램/체크리스트/흐름도 중심의 장면.",
        "compare": "비포/애프터 비교. 혼란스러운 제작과 구조화된 제작의 차이를 명확히 표현.",
        "solution": "브랜드가 해결 구조를 설계하는 장면. 스토리보드, 무드보드, 전환 퍼널, 편집 타임라인이 정리되어 있음.",
        "cta": "프리미엄 포트폴리오/견적 문의 장면. 노트북 웹사이트 목업과 CTA가 자연스럽게 보이는 마무리 컷.",
        "case": "벤치마크 콘텐츠를 분석하는 장면. 원본 레퍼런스에서 배운 구조를 브랜드 방식으로 재해석하는 느낌.",
        "checklist": "체크리스트형 카드. 핵심 항목이 시각적으로 정돈된 고급 UI/보드 구성.",
    }
    return base + character + role_map.get(role, "고급스럽고 명확한 카드뉴스용 장면.")


def build_plan_by_template(ctx, template_name):
    brand = ctx["brand_name"]
    angle = ctx["content_angle"]
    problem = ctx["core_problem"]
    insight = ctx["insight"]
    solution = ctx["solution"]
    proof = ctx["proof"]
    offer = ctx["offer"]
    cta = ctx["cta"]
    target_label = ctx["target_label"]
    source_title = ctx["source_title"]
    tone_level = ctx["tone_level"]

    if template_name == "문제폭로형":
        slides = [
            hookify(f"{angle}\n문제는 겉으로 보이는 곳에 있지 않습니다", tone_level),
            f"{target_label}가 영상 결과물만 먼저 보면\n정작 중요한 구조를 놓치기 쉽습니다\n문제의 핵심은 {shorten(problem, 55)}입니다",
            f"대부분 여기서부터 꼬입니다\n{shorten(insight, 95)}",
            "먼저 봐야 할 건\n무엇을 만들지가 아닙니다\n왜 만들고, 누구를 움직일지입니다",
            f"{brand}는 이렇게 설계합니다\n{shorten(solution, 95)}",
            f"멋진 결과물보다\n전환되는 구조가 필요하다면\n{cta}",
        ]
        roles = ["hook", "problem", "analysis", "compare", "solution", "cta"]

    elif template_name == "오해반박형":
        slides = [
            hookify("이건 편집 퀄리티 문제가 아닙니다", tone_level),
            "많은 분들이 편집 퀄리티부터 손봅니다\n그런데 문의가 늘지 않는다면\n문제는 다른 곳에 있을 수 있습니다",
            f"놓친 건 이것입니다\n{shorten(problem, 85)}",
            "영상은 예쁘게 보이는 순간보다\n고객이 이해하고 움직이는 흐름이 더 중요합니다",
            f"{brand}는 분위기보다 구조를 먼저 잡습니다\n{shorten(solution, 85)}",
            f"{offer}\n필요하다면\n{cta}",
        ]
        roles = ["hook", "problem", "analysis", "compare", "solution", "cta"]

    elif template_name == "전후비교형":
        slides = [
            hookify("같은 영상도\n결과가 갈리는 이유", tone_level),
            f"기획 없이 만들면\n수정은 늘고 메시지는 흐려집니다\n{shorten(problem, 65)}",
            "구조를 잡고 만들면\n목적, 타깃, 메시지, CTA가\n한 방향으로 이어집니다",
            "Before\n예쁜데 문의가 없는 영상\nAfter\n고객의 다음 행동까지 설계된 영상",
            f"{brand}는 제작 전에\n이 흐름을 먼저 설계합니다\n{shorten(insight, 80)}",
            f"{offer}\n{cta}",
        ]
        roles = ["hook", "problem", "analysis", "compare", "solution", "cta"]

    elif template_name == "체크리스트형":
        slides = [
            hookify("영상 만들기 전\n이 4개는 먼저 정리하세요", tone_level),
            "1. 목적\n이 영상이 인지도, 신뢰, 문의 중\n무엇을 만들지 정해야 합니다",
            "2. 타깃\n누구에게 말하는 영상인지 흐리면\n메시지도 같이 흐려집니다",
            "3. 메시지\n고객이 기억해야 할 한 문장이\n먼저 필요합니다",
            "4. CTA\n영상을 본 뒤 무엇을 해야 하는지까지\n설계해야 전환이 생깁니다",
            f"이 4개가 정리되지 않았다면\n{brand}와 구조부터 잡아보세요\n{cta}",
        ]
        roles = ["hook", "checklist", "checklist", "checklist", "checklist", "cta"]

    elif template_name == "케이스분석형":
        slides = [
            hookify(f"{shorten(source_title, 30)}\n우리가 봐야 할 건 조회수만이 아닙니다", tone_level),
            f"이 레퍼런스에서 볼 건\n겉모습보다 전개 구조입니다\n출처: {ctx['platform']} · {ctx['channel_name']}",
            f"핵심 구조\n{shorten(insight, 105)}",
            f"이걸 {target_label} 관점으로 바꾸면\n{shorten(angle, 65)}라는 주제가 됩니다",
            f"{brand} 적용 방식\n{shorten(solution, 95)}",
            f"이런 구조의 콘텐츠가 필요하다면\n{cta}",
        ]
        roles = ["case", "analysis", "analysis", "compare", "solution", "cta"]

    else:  # 교육노하우형
        slides = [
            hookify(f"{angle}\n이 원리만 알면 훨씬 선명해집니다", tone_level),
            "영상은 장면을 나열하는 일이 아닙니다\n고객이 판단하는 순서를 설계하는 일입니다",
            f"첫 번째는 문제 인식\n{shorten(problem, 80)}",
            f"두 번째는 납득 구조\n{shorten(proof, 80)}",
            f"세 번째는 행동 유도\n{shorten(solution, 80)}",
            f"{offer}\n{cta}",
        ]
        roles = ["hook", "analysis", "problem", "analysis", "solution", "cta"]

    images = [build_image_direction(ctx, idx + 1, role) for idx, role in enumerate(roles)]
    title = f"[{template_name}] {shorten(angle, 45)}"
    main_message = f"{brand}는 {target_label}에게 필요한 전환 구조를 먼저 설계합니다. 핵심은 {shorten(insight, 100)}"

    return {
        "title": title,
        "target_customer": ctx["target_customer"],
        "core_problem": problem,
        "main_message": main_message,
        "cta": cta,
        "slides": slides,
        "images": images,
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


def render_source_preview(row):
    with st.expander("선택한 벤치마크 원본 데이터 보기", expanded=False):
        st.write(f"**플랫폼:** {clean(row.get('platform'), '-')}")
        st.write(f"**채널:** {clean(row.get('channel_name'), '-')}")
        st.write(f"**제목:** {clean(row.get('title'), '-')}")
        st.write(f"**후킹 포인트:** {clean(row.get('hook_point'), '-')}")
        st.write(f"**전개 구조:** {clean(row.get('structure_note'), '-')}")
        st.write(f"**이미지 참고:** {clean(row.get('visual_note'), '-')}")
        st.write(f"**적용 아이디어:** {clean(row.get('eafi_application'), '-')}")


def update_draft_state(plan, selector_signature, force=False):
    previous_signature = st.session_state.get("planner_selector_signature")
    if force or previous_signature != selector_signature or "planner_plan" not in st.session_state:
        st.session_state["planner_selector_signature"] = selector_signature
        st.session_state["planner_plan"] = plan
        st.session_state["planner_plan_version"] = st.session_state.get("planner_plan_version", 0) + 1


def render_editable_plan(plan, version):
    st.markdown("### 핵심 설계")
    key_suffix = f"v{version}"
    title = st.text_input("저장할 주제명", value=plan["title"], key=f"plan_title_{key_suffix}")
    core_problem = st.text_area("핵심 문제", value=plan["core_problem"], height=80, key=f"plan_core_problem_{key_suffix}")
    main_message = st.text_area("메인 메시지", value=plan["main_message"], height=90, key=f"plan_main_message_{key_suffix}")
    cta = st.text_input("CTA", value=plan["cta"], key=f"plan_cta_{key_suffix}")

    st.markdown("### 6장 카드뉴스 구성 직접 수정")
    edited_slides = []
    edited_images = []
    for idx, (copy, image) in enumerate(zip(plan["slides"], plan["images"]), start=1):
        with st.container(border=True):
            st.markdown(f"#### {idx}장")
            edited_copy = st.text_area("카피", value=copy, height=130, key=f"slide_copy_{idx}_{key_suffix}")
            edited_image = st.text_area("이미지 방향", value=image, height=110, key=f"slide_image_{idx}_{key_suffix}")
            edited_slides.append(edited_copy)
            edited_images.append(edited_image)

    edited_plan = dict(plan)
    edited_plan["title"] = title
    edited_plan["core_problem"] = core_problem
    edited_plan["main_message"] = main_message
    edited_plan["cta"] = cta
    edited_plan["slides"] = edited_slides
    edited_plan["images"] = edited_images
    return edited_plan


def main():
    st.set_page_config(page_title="카드뉴스 설계안 생성", page_icon="🧩", layout="wide")
    init_cardnews_table()

    st.title("🧩 카드뉴스 설계안 생성")
    st.caption("벤치마크 데이터를 고정 문구가 아니라, 선택한 콘텐츠 각도와 템플릿에 맞춰 6장 카드뉴스로 변환합니다.")

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
    render_source_preview(row)

    st.markdown("---")
    st.markdown("### 생성 조건")

    col1, col2, col3, col4 = st.columns(4)
    with col1:
        template_name = st.selectbox("콘텐츠 구조", TEMPLATE_OPTIONS, index=0)
    with col2:
        tone_level = st.selectbox("후킹 강도", list(TONE_LEVELS.keys()), index=2)
    with col3:
        visual_style = st.selectbox("이미지 스타일", VISUAL_STYLES, index=0)
    with col4:
        auto_review = st.checkbox("한국어 카피 자동 검수", value=True)

    col5, col6 = st.columns(2)
    with col5:
        brand_name = st.text_input("브랜드명", value="eaf:")
        target_customer = st.text_input("타깃 고객", value="영상 제작을 고민하는 브랜드/마케팅 담당자")
        cta = st.text_input("CTA", value="DM으로 포트폴리오와 견적을 받아보세요")
    with col6:
        content_angle = st.text_area(
            "이번 카드뉴스의 핵심 각도",
            value=clean(row.get("eafi_application"), clean(row.get("title"), "기업 영상이 문의로 이어지지 않는 이유")),
            height=80,
        )
        core_problem = st.text_area(
            "핵심 문제",
            value=clean(row.get("hook_point"), "결과물 퀄리티만 보고 전환 구조를 놓치는 문제"),
            height=80,
        )

    insight = st.text_area(
        "벤치마크에서 가져올 인사이트 / 전개 구조",
        value=clean(row.get("structure_note"), "문제 제기 → 원인 분석 → 해결 방식 → 실행 제안"),
        height=90,
    )
    solution = st.text_area(
        "브랜드 관점의 해결 방식",
        value=f"{brand_name}는 영상의 분위기보다 목적, 타깃, 메시지, CTA가 이어지는 전환 구조를 먼저 설계합니다",
        height=80,
    )
    proof = st.text_area(
        "근거/설명",
        value="기획 단계에서 구조가 정리되면 후반 수정이 줄고, 메시지와 행동 유도가 일관되게 이어집니다",
        height=80,
    )
    offer = st.text_area(
        "서비스/제안 문장",
        value="브랜드 필름, 제품 영상, 유튜브 콘텐츠까지 문의로 이어지는 구조부터 함께 설계",
        height=70,
    )

    inputs = {
        "template_name": template_name,
        "tone_level": tone_level,
        "visual_style": visual_style,
        "brand_name": brand_name,
        "target_customer": target_customer,
        "cta": cta,
        "content_angle": content_angle,
        "core_problem": core_problem,
        "insight": insight,
        "solution": solution,
        "proof": proof,
        "offer": offer,
    }

    ctx = build_context(row, inputs)
    generated_plan = build_plan_by_template(ctx, template_name)
    if auto_review:
        generated_plan = review_plan_copy(generated_plan, ctx)

    selector_signature = f"{int(row['id'])}|{template_name}|{tone_level}|{visual_style}|{auto_review}"
    update_draft_state(generated_plan, selector_signature)

    col_refresh, col_note = st.columns([1, 3])
    with col_refresh:
        if st.button("현재 입력값으로 초안 다시 생성", type="secondary"):
            update_draft_state(generated_plan, selector_signature, force=True)
            st.rerun()
    with col_note:
        st.info("드롭다운을 바꾸면 아래 초안이 자동 갱신됩니다. 핵심 각도/문제/근거를 수정한 뒤에는 왼쪽 버튼으로 다시 생성하세요. 자동 검수는 어색한 조사, 개발자식 문장, 과하게 딱딱한 표현을 한 번 더 정리합니다.")

    st.markdown("---")
    draft_plan = st.session_state.get("planner_plan", generated_plan)
    version = st.session_state.get("planner_plan_version", 0)
    edited_plan = render_editable_plan(draft_plan, version)

    if st.button("이 설계안 저장", type="primary"):
        save_plan(int(row["id"]), edited_plan)
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
