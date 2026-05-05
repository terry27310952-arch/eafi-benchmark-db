import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")

PLAN_TYPES = ["eaf 서비스 전환형", "벤치마크 구조만 차용"]
TEMPLATE_OPTIONS = ["문제 제기형", "오해 반박형", "전후 비교형", "체크리스트형", "레퍼런스 분석형", "교육형"]
TONE_LEVELS = ["담백", "명확", "강한 후킹", "자극적"]
VISUAL_STYLES = ["브랜드 캐릭터 중심", "실사 오피스 시네마틱", "인포그래픽 중심", "전후 비교형", "제품/포트폴리오 중심", "혼합형"]

INTRO_FRAMES = {
    "영상미 착각": {
        "hook": "예쁜 영상인데\n왜 문의는 없을까요?",
        "body": "보기 좋은 영상과\n고객을 움직이는 영상은 다릅니다\n전환은 분위기가 아니라 흐름에서 나옵니다",
        "problem": "영상미는 있지만 고객을 움직이는 설득 흐름이 부족한 상태",
    },
    "문의 부재": {
        "hook": "영상은 올라갔는데\n문의가 없다면",
        "body": "조회수보다 먼저 확인해야 할 건\n영상을 본 사람이 다음에 무엇을 해야 하는지입니다",
        "problem": "시청 이후 문의, 상담, 구매 등 다음 행동으로 이어지는 경로가 불명확한 상태",
    },
    "기획 부재": {
        "hook": "촬영보다 먼저\n기획이 무너지면 끝입니다",
        "body": "후반 작업에서 터지는 수정과 혼란은\n대부분 촬영 전에 이미 시작됩니다\n방향이 흐리면 결과물도 흔들립니다",
        "problem": "제작 전에 목적과 메시지 구조가 정리되지 않아 후반 수정이 반복되는 상태",
    },
    "타깃 불명확": {
        "hook": "누구에게 말하는 영상인지\n흐리면 전부 흐려집니다",
        "body": "타깃이 흐리면\n카피도 장면도 편집 리듬도\n결국 애매해집니다",
        "problem": "영상이 설득해야 할 고객군이 명확하지 않아 메시지가 넓고 약해지는 상태",
    },
    "제작비 누수": {
        "hook": "제작비는 촬영장에서만\n새는 게 아닙니다",
        "body": "방향이 흐린 상태로 시작하면\n수정, 재촬영, 재편집이 반복됩니다\n비용은 조용히 늘어납니다",
        "problem": "초반 기획 부재로 수정과 재작업이 반복되며 시간과 비용이 증가하는 상태",
    },
    "레퍼런스 복붙": {
        "hook": "레퍼런스를 따라 했는데\n왜 우리 영상은 안 먹힐까요?",
        "body": "좋은 레퍼런스의 핵심은\n색감이나 컷만이 아닙니다\n시청자를 설득하는 순서가 더 중요합니다",
        "problem": "레퍼런스의 겉모습만 따라 하고 브랜드의 목적과 고객 흐름은 반영하지 못한 상태",
    },
    "직접 입력": {"hook": "", "body": "", "problem": ""},
}

TARGETS = {
    "브랜드/마케팅 담당자": "영상 제작을 검토 중인 브랜드/마케팅 담당자",
    "스타트업 대표/팀장": "브랜드 신뢰도를 빠르게 쌓아야 하는 스타트업 대표/팀장",
    "제품 브랜드 담당자": "제품의 장점을 영상으로 설득해야 하는 브랜드 담당자",
    "B2B 세일즈 담당자": "문의와 상담 전환을 늘리고 싶은 B2B 세일즈 담당자",
    "콘텐츠 담당자": "유튜브와 숏폼을 꾸준히 운영해야 하는 콘텐츠 담당자",
    "직접 입력": "",
}

CTA_PRESETS = {
    "DM 포트폴리오/견적": "DM으로 포트폴리오와 견적을 받아보세요",
    "무료 진단": "지금 영상 구조가 맞는지 먼저 진단받아보세요",
    "상담 문의": "브랜드에 맞는 영상 구조가 필요하다면 상담을 남겨주세요",
    "제작 문의": "비슷한 영상 제작이 필요하다면 제작 문의를 남겨주세요",
    "직접 입력": "",
}

SERVICE_PROBLEMS = {
    "전환 경로 부재": "영상은 있지만 문의, 상담, 구매 등 다음 행동으로 이어지는 경로가 보이지 않는 상태",
    "목적 불명확": "영상의 목적이 인지도, 신뢰, 문의 중 어디에 있는지 정리되지 않은 상태",
    "타깃 불명확": "누구에게 말하는 영상인지 흐려져 메시지와 장면 선택이 모두 애매해진 상태",
    "메시지 과밀": "하고 싶은 말이 너무 많아 고객이 기억해야 할 한 문장이 보이지 않는 상태",
    "CTA 부재": "영상을 본 뒤 고객이 무엇을 해야 하는지 명확하게 안내되지 않는 상태",
    "수정 반복": "초반 방향성이 불명확해 후반 수정, 재편집, 일정 지연이 반복되는 상태",
    "제작비 누수": "기획이 흐린 상태로 제작이 시작돼 시간과 비용이 조용히 늘어나는 상태",
    "직접 입력": "",
}

SERVICE_SOLUTIONS = {
    "전환 구조 먼저 설계": "분위기보다 먼저 목적, 타깃, 메시지, CTA가 이어지는 구조를 설계합니다",
    "브랜드 필름 구조화": "브랜드 필름을 이미지 영상이 아니라 신뢰와 문의로 이어지는 흐름으로 설계합니다",
    "제품 영상 설득 구조": "제품의 기능보다 고객이 왜 필요로 하는지 납득하는 순서부터 잡습니다",
    "유튜브 콘텐츠 체계화": "유튜브 콘텐츠를 조회수용 영상이 아니라 브랜드 자산으로 설계합니다",
    "AI 하이브리드 제작": "AI와 실사 제작을 결합해 속도, 비용, 완성도의 균형을 맞춥니다",
    "직접 입력": "",
}

PROOFS = {
    "수정 리스크 감소": "초반에 구조를 잡으면 후반 수정이 줄고 메시지의 방향도 흔들리지 않습니다",
    "문의 흐름 명확화": "고객이 무엇을 보고, 무엇을 이해하고, 무엇을 해야 하는지 분명할수록 전환이 쉬워집니다",
    "제작비 누수 방지": "방향이 흐린 영상은 수정과 재작업이 반복되며 시간과 비용을 함께 소모합니다",
    "콘텐츠 자산화": "목적이 분명한 영상은 한 번 쓰고 끝나지 않고 여러 플랫폼으로 확장됩니다",
    "직접 입력": "",
}

OFFERS = {
    "브랜드/제품/유튜브 통합": "브랜드 필름, 제품 영상, 유튜브 콘텐츠까지 전환 구조부터 함께 설계합니다",
    "브랜드 필름": "브랜드의 철학과 강점을 고객이 이해하는 흐름으로 설계합니다",
    "제품 영상": "제품의 장점과 사용 이유를 선명하게 보여주는 영상으로 만듭니다",
    "유튜브 운영 콘텐츠": "유튜브와 숏폼 콘텐츠를 브랜드 자산으로 쌓아가는 구조로 제작합니다",
    "AI 영상 패키지": "AI 기반 비주얼과 실사 제작 감각을 결합한 하이브리드 영상 패키지를 제공합니다",
    "직접 입력": "",
}

BENCHMARK_STRUCTURES = {
    "후킹 질문형": "후킹 질문 → 문제 상황 → 놓친 지점 → 해결 구조 → CTA",
    "오해 반박형": "흔한 오해 → 반박 → 진짜 원인 → 해결 방식 → CTA",
    "체크리스트형": "큰 질문 → 체크포인트 1 → 체크포인트 2 → 체크포인트 3 → CTA",
    "전후 비교형": "Before → 문제 원인 → After → 차이를 만든 구조 → CTA",
    "케이스 분석형": "사례 소개 → 잘된 이유 → 차용할 구조 → 우리식 적용 → CTA",
    "직접 입력": "",
}

COMMON_STYLE = {
    "브랜드 캐릭터 중심": "eaf: 레드, 블랙, 웜 그레이 기반. 공식 로고와 빨간 캡/빨간 폴로의 메인 캐릭터 톤 유지. 개구리 엠블럼은 작은 패치로만 사용.",
    "실사 오피스 시네마틱": "eaf: 레드, 블랙, 웜 그레이 기반. 어두운 오피스/편집실의 시네마틱 실사 톤. 로고는 작게만 노출.",
    "인포그래픽 중심": "eaf: 레드, 블랙, 웜 그레이 기반. 여백이 넓은 고급 인포그래픽. 로고와 캐릭터는 보조 요소로만 사용.",
    "전후 비교형": "eaf: 레드, 블랙, 웜 그레이 기반. 좌우 비교 구도. 문제와 해결의 대비가 한눈에 보이도록 구성.",
    "제품/포트폴리오 중심": "eaf: 레드, 블랙, 웜 그레이 기반. 노트북, 포트폴리오, 영상 플레이어, 웹사이트 목업 중심.",
    "혼합형": "eaf: 레드, 블랙, 웜 그레이 기반. 실사 장면과 인포그래픽을 자연스럽게 섞은 카드뉴스 톤.",
}


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_cardnews_table():
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


def load_plans():
    conn = connect_db()
    try:
        df = pd.read_sql_query("SELECT * FROM cardnews_plans ORDER BY id DESC LIMIT 50", conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df


def clean(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    if text.lower() in ["nan", "none", "null"]:
        return fallback
    return text or fallback


def compact_lines(text):
    return "\n".join([line.strip() for line in clean(text).splitlines() if line.strip()])


def shorten(text, max_len=92):
    text = re.sub(r"https?://\S+", "", clean(text))
    text = re.sub(r"(?im)^\s*(title|url|source|link|영상 제목|제목)\s*[:：]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def remove_brand_overuse(text, brand="eaf:"):
    lines = [line.strip() for line in clean(text).splitlines() if line.strip()]
    cleaned = []
    for line in lines:
        line = re.sub(rf"^{re.escape(brand)}는\s*", "", line)
        line = re.sub(rf"^{re.escape(brand)}\s*[:：]\s*", "", line)
        cleaned.append(line)
    return "\n".join(cleaned)


def humanize(text, tone="명확", brand="eaf:"):
    text = compact_lines(shorten(line, 200) for line in clean(text).splitlines())
    replacements = {
        "핵심 문제": "문제의 핵심",
        "전환되는 구조": "문의로 이어지는 구조",
        "진짜 병목": "정작 중요한 지점",
        "없으면": "없다면",
        "합니다입니다": "합니다",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if tone == "담백":
        text = text.replace("끝입니다", "흔들리기 쉽습니다")
        text = text.replace("계속 새게 됩니다", "확인해야 합니다")
    elif tone == "자극적":
        text = text.replace("놓치기 쉽습니다", "계속 놓치게 됩니다")
        text = text.replace("어렵습니다", "어려워집니다")
    return text.strip()


def select_from_dict(label, options, key, default=None, height=80):
    labels = list(options.keys())
    index = labels.index(default) if default in labels else 0
    selected = st.selectbox(label, labels, index=index, key=f"{key}_select")
    if selected == "직접 입력":
        return st.text_area(f"{label} 직접 입력", height=height, key=f"{key}_custom"), selected
    return options[selected], selected


def select_intro():
    label = st.selectbox("서론 훅 관점", list(INTRO_FRAMES.keys()), index=0, key="v5_intro")
    frame = dict(INTRO_FRAMES[label])
    if label == "직접 입력":
        frame["hook"] = st.text_area("서론 훅 직접 입력", height=70, key="v5_intro_hook")
        frame["body"] = st.text_area("서론 보조 문장 직접 입력", height=90, key="v5_intro_body")
        frame["problem"] = st.text_area("서론 기반 문제 직접 입력", height=90, key="v5_intro_problem")
    return label, frame


def split_target_label(target):
    target = clean(target, "브랜드/마케팅 담당자")
    for token in ["영상 제작을 검토 중인 ", "브랜드 신뢰도를 빠르게 쌓아야 하는 ", "제품의 장점을 영상으로 설득해야 하는 ", "문의와 상담 전환을 늘리고 싶은 ", "유튜브와 숏폼을 꾸준히 운영해야 하는 "]:
        target = target.replace(token, "")
    return target.strip() or "브랜드/마케팅 담당자"


def finalize_plan(ctx, title, main_message, slides, images):
    tone = ctx["tone"]
    brand = ctx["brand"]
    slides = [humanize(remove_brand_overuse(slide, brand), tone, brand) for slide in slides]
    return {
        "title": humanize(title, tone, brand),
        "target_customer": ctx.get("target", ""),
        "core_problem": humanize(ctx.get("problem") or "", tone, brand),
        "main_message": humanize(main_message, tone, brand),
        "cta": humanize(ctx["cta"], tone, brand),
        "common_style": COMMON_STYLE.get(ctx["visual_style"], COMMON_STYLE["혼합형"]),
        "slides": slides,
        "images": images,
    }


def build_service_plan(ctx):
    brand = ctx["brand"]
    target_label = split_target_label(ctx["target"])
    intro = ctx["intro"]
    problem = ctx["problem"]
    solution = ctx["solution"]
    proof = ctx["proof"]
    offer = ctx["offer"]
    cta = ctx["cta"]

    slides = [
        intro["hook"],
        intro["body"],
        f"문제의 핵심은\n{shorten(problem, 88)}입니다",
        f"그래서 제작 전에\n{shorten(proof, 88)}",
        f"우리는 이렇게 접근합니다\n{shorten(solution, 88)}",
        f"{shorten(offer, 72)}\n{cta}",
    ]

    if ctx["template"] == "전후 비교형":
        slides = [
            "같은 영상도\n결과는 완전히 달라집니다",
            f"Before\n{shorten(problem, 78)}",
            "After\n목적, 타깃, 메시지, CTA가\n한 방향으로 이어지는 영상",
            f"차이는 여기서 납니다\n{shorten(proof, 84)}",
            f"우리는 제작 전에\n{shorten(solution, 84)}",
            f"{shorten(offer, 72)}\n{cta}",
        ]
    elif ctx["template"] == "체크리스트형":
        slides = [
            "영상 만들기 전\n이 4가지는 먼저 정리하세요",
            "1. 목적\n인지도, 신뢰, 문의 중\n무엇을 만들지 정해야 합니다",
            "2. 타깃\n누구에게 말하는지 흐리면\n메시지도 같이 흐려집니다",
            "3. 메시지\n고객이 기억할 한 문장이\n먼저 필요합니다",
            "4. CTA\n영상을 본 뒤 무엇을 해야 하는지까지\n설계해야 전환이 생깁니다",
            f"구조부터 잡고 싶다면\n{cta}",
        ]

    images = [
        "문제 제기용 첫 장. 고민하는 담당자, 멈춰 있는 성과 그래프, 어두운 회의실을 대비감 있게 표현.",
        "보기 좋은 영상 화면과 낮은 문의 지표가 함께 보이는 장면. 겉보기 성과와 실제 전환의 간극을 표현.",
        "문제 정의 보드. 목적, 타깃, 메시지, CTA 중 비어 있는 부분이 빨간 표시로 드러나는 인포그래픽.",
        "제작 전 체크리스트와 후반 수정 요청이 대비되는 장면. 혼란과 정리의 차이가 보이게 구성.",
        "스토리보드, 무드보드, 전환 퍼널, 편집 타임라인이 한 화면에 정리된 전략 워크스페이스.",
        "노트북에 포트폴리오 화면이 열려 있고 DM/상담 문의 흐름이 자연스럽게 보이는 마무리 장면.",
    ]

    title = f"[{ctx['template']}] {shorten(ctx['angle'], 46)}"
    main_message = f"{brand}는 {target_label}에게 필요한 영상 구조를 먼저 설계합니다. 핵심은 결과물이 아니라 고객의 다음 행동입니다."
    return finalize_plan(ctx, title, main_message, slides, images)


def build_structure_only_plan(ctx):
    structure = ctx["benchmark_structure"]
    cta = ctx["cta"]
    slides = [
        "잘 만든 콘텐츠는\n전개 순서가 다릅니다",
        "사람을 붙잡는 건\n화려한 화면보다 먼저 던지는 질문입니다",
        f"이 구조의 핵심은\n{shorten(structure, 86)}",
        "그 구조를 그대로 베끼는 게 아니라\n우리 브랜드의 목적에 맞게 바꿔야 합니다",
        "핵심은 톤앤매너가 아니라\n문제 제기, 납득, 행동 유도의 순서입니다",
        f"이런 콘텐츠 구조가 필요하다면\n{cta}",
    ]
    images = [
        "여러 레퍼런스 썸네일을 분석하는 장면. 겉모습보다 구조를 보는 느낌.",
        "도입부 훅이 시청자를 붙잡는 과정을 시각화한 인포그래픽.",
        "문제 제기, 납득, 행동 유도 흐름이 연결된 구조도.",
        "레퍼런스 복붙과 브랜드 맞춤 재해석을 비교하는 좌우 구도.",
        "카피, 스토리보드, CTA가 하나의 흐름으로 정리된 전략 보드.",
        "eaf: 포트폴리오와 상담 CTA가 보이는 깔끔한 마무리 장면.",
    ]
    title = f"[{ctx['template']}] 레퍼런스 구조를 콘텐츠로 바꾸는 법"
    main_message = "좋은 레퍼런스는 그대로 따라 하는 게 아니라 구조를 읽고 브랜드 목적에 맞게 다시 설계해야 합니다."
    return finalize_plan(ctx, title, main_message, slides, images)


def update_state(plan, signature, force=False):
    if force or st.session_state.get("v5_signature") != signature or "v5_plan" not in st.session_state:
        st.session_state["v5_signature"] = signature
        st.session_state["v5_plan"] = plan
        st.session_state["v5_version"] = st.session_state.get("v5_version", 0) + 1


def save_plan(plan):
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cardnews_plans
        (reference_id, title, target_customer, core_problem, main_message, cta,
         slide_1, slide_2, slide_3, slide_4, slide_5, slide_6,
         image_1, image_2, image_3, image_4, image_5, image_6, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        None,
        plan["title"],
        plan["target_customer"],
        plan["core_problem"],
        plan["main_message"],
        plan["cta"],
        plan["slides"][0], plan["slides"][1], plan["slides"][2], plan["slides"][3], plan["slides"][4], plan["slides"][5],
        plan["images"][0], plan["images"][1], plan["images"][2], plan["images"][3], plan["images"][4], plan["images"][5],
        "초안",
        datetime.now().isoformat(timespec="seconds"),
    ))
    conn.commit()
    conn.close()


def render_editable(plan, version):
    suffix = f"v{version}"
    st.markdown("### 공통 이미지 스타일")
    common_style = st.text_area("공통 스타일", value=plan["common_style"], height=90, key=f"v5_common_{suffix}")

    st.markdown("### 핵심 설계")
    title = st.text_input("저장할 주제명", value=plan["title"], key=f"v5_title_{suffix}")
    core_problem = st.text_area("핵심 문제", value=plan["core_problem"], height=80, key=f"v5_problem_{suffix}")
    main_message = st.text_area("메인 메시지", value=plan["main_message"], height=90, key=f"v5_message_{suffix}")
    cta = st.text_input("CTA", value=plan["cta"], key=f"v5_cta_{suffix}")

    st.markdown("### 6장 카드뉴스 구성 직접 수정")
    slides, images = [], []
    for idx, (copy, image) in enumerate(zip(plan["slides"], plan["images"]), start=1):
        with st.container(border=True):
            st.markdown(f"#### {idx}장")
            slides.append(st.text_area("카피", value=copy, height=120, key=f"v5_slide_{idx}_{suffix}"))
            images.append(st.text_area("장별 이미지 방향", value=image, height=100, key=f"v5_image_{idx}_{suffix}"))

    edited = dict(plan)
    edited.update({"common_style": common_style, "title": title, "core_problem": core_problem, "main_message": main_message, "cta": cta, "slides": slides, "images": images})
    return edited


def main():
    st.set_page_config(page_title="Cardnews Planner Engine V5", page_icon="🧠", layout="wide")
    init_cardnews_table()

    st.title("🧠 카드뉴스 설계 엔진 V5")
    st.caption("참고 콘텐츠 선택 없이 eaf 서비스 전환형과 벤치마크 구조 차용을 바로 생성합니다.")

    st.markdown("### 생성 조건")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        plan_type = st.selectbox("콘텐츠 목적", PLAN_TYPES, index=0)
    with c2:
        template = st.selectbox("콘텐츠 구조", TEMPLATE_OPTIONS, index=0)
    with c3:
        tone = st.selectbox("후킹 강도", TONE_LEVELS, index=2)
    with c4:
        visual_style = st.selectbox("이미지 스타일", VISUAL_STYLES, index=0)

    i1, i2 = st.columns(2)
    with i1:
        intro_label, intro = select_intro()
    with i2:
        st.markdown("#### 서론 미리보기")
        st.write(intro["hook"])
        st.caption(intro["body"])

    c5, c6 = st.columns(2)
    with c5:
        brand = st.text_input("브랜드명", value="eaf:")
        target, target_label = select_from_dict("타깃 고객", TARGETS, "v5_target", "브랜드/마케팅 담당자")
        cta, cta_label = select_from_dict("CTA", CTA_PRESETS, "v5_cta_preset", "DM 포트폴리오/견적")
    with c6:
        if plan_type == "eaf 서비스 전환형":
            angle = st.text_input("이번 카드뉴스의 핵심 각도", value="좋은 영상과 문의로 이어지는 영상의 차이")
            problem, problem_label = select_from_dict("핵심 문제", SERVICE_PROBLEMS, "v5_service_problem", "전환 경로 부재")
            benchmark_structure = ""
        else:
            angle = st.text_input("이번 카드뉴스의 핵심 각도", value="레퍼런스 구조를 콘텐츠로 바꾸는 법")
            benchmark_structure, problem_label = select_from_dict("차용할 벤치마크 구조", BENCHMARK_STRUCTURES, "v5_benchmark_structure", "후킹 질문형")
            problem = "겉모습을 따라 하기보다 반응을 만든 전개 순서를 읽어야 하는 상황"

    p1, p2 = st.columns(2)
    with p1:
        solution, solution_label = select_from_dict("브랜드 관점의 해결 방식", SERVICE_SOLUTIONS, "v5_solution", "전환 구조 먼저 설계")
        proof, proof_label = select_from_dict("근거 / 설명", PROOFS, "v5_proof", "문의 흐름 명확화")
    with p2:
        offer, offer_label = select_from_dict("서비스 / 제안 문장", OFFERS, "v5_offer", "브랜드/제품/유튜브 통합")
        if plan_type == "벤치마크 구조만 차용":
            st.info("이 모드는 참고 콘텐츠 선택 없이 전개 구조만 선택해 eaf 콘텐츠로 변환합니다.")

    ctx = {
        "plan_type": plan_type,
        "template": template,
        "tone": tone,
        "visual_style": visual_style,
        "intro_label": intro_label,
        "intro": intro,
        "brand": brand,
        "target": target,
        "cta": cta,
        "angle": angle,
        "problem": problem,
        "benchmark_structure": benchmark_structure,
        "solution": solution,
        "proof": proof,
        "offer": offer,
    }

    plan = build_service_plan(ctx) if plan_type == "eaf 서비스 전환형" else build_structure_only_plan(ctx)

    signature = "|".join([plan_type, template, tone, visual_style, intro_label, brand, target_label, cta_label, angle, problem_label, benchmark_structure, solution_label, proof_label, offer_label, target, cta, problem, solution, proof, offer])
    update_state(plan, signature)

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("현재 선택값으로 초안 다시 생성"):
            update_state(plan, signature, force=True)
            st.rerun()
    with col_info:
        st.info("V5 내부의 참고 콘텐츠 선택 항목을 제거했습니다. 원본 주제 카드뉴스는 별도 메뉴에서 그대로 사용합니다.")

    st.markdown("---")
    draft = st.session_state.get("v5_plan", plan)
    version = st.session_state.get("v5_version", 0)
    edited = render_editable(draft, version)

    if st.button("이 설계안 저장", type="primary"):
        save_plan(edited)
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
