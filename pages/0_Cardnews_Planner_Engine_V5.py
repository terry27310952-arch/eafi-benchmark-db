import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")

PLAN_TYPES = ["eaf 서비스 전환형", "원본 주제 카드뉴스형", "벤치마크 구조만 차용"]
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

GENERIC_PROBLEMS = {
    "시장 기대감만 보고 판단": "무엇이 움직이는지보다 얼마나 오를지만 먼저 보는 상태",
    "근거 없는 관심 급등": "관심은 커졌지만 실제 변화의 이유가 정리되지 않은 상태",
    "타이밍 착각": "시장이 움직인 뒤에야 이유를 찾는 상태",
    "정보 과잉": "뉴스와 의견은 많지만 판단 기준은 흐려진 상태",
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


# ---------- DB ----------

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


# ---------- Text utilities ----------

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


def remove_brand_overuse(text, brand="eaf:"):
    lines = [line.strip() for line in clean(text).splitlines() if line.strip()]
    cleaned = []
    for line in lines:
        line = re.sub(rf"^{re.escape(brand)}는\s*", "", line)
        line = re.sub(rf"^{re.escape(brand)}\s*[:：]\s*", "", line)
        cleaned.append(line)
    return "\n".join(cleaned)


def compact_lines(text):
    return "\n".join([line.strip() for line in clean(text).splitlines() if line.strip()])


def shorten(text, max_len=92):
    text = strip_raw_labels(text)
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def humanize(text, tone="명확", brand="eaf:"):
    text = compact_lines(strip_raw_labels(text))
    replacements = {
        "핵심 문제": "문제의 핵심",
        "전환되는 구조": "문의로 이어지는 구조",
        "진짜 병목": "정작 중요한 지점",
        "결과는 생각보다 조용합니다": "반응은 조용할 수 있습니다",
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


def sentence_case_title(text):
    text = strip_raw_labels(text)
    text = text.replace("|", " ").replace("- YouTube", "")
    return shorten(text, 54)


def detect_unrelated_to_eaf(text):
    service_words = ["영상", "촬영", "편집", "브랜드", "광고", "콘텐츠", "유튜브", "숏폼", "제작", "마케팅"]
    return not any(word in clean(text) for word in service_words)


# ---------- Source analysis layer ----------

def analyze_source(row):
    title = strip_raw_labels(row.get("title"))
    hook = strip_raw_labels(row.get("hook_point"))
    structure = strip_raw_labels(row.get("structure_note"))
    visual = strip_raw_labels(row.get("visual_note"))
    app = strip_raw_labels(row.get("eafi_application"))

    source_text = " ".join([title, hook, structure, app])
    original_topic = sentence_case_title(title or app or hook or "원본 콘텐츠")

    if any(token in source_text for token in ["2차전지", "배터리", "전기차"]):
        original_claim = "2차전지 섹터에 다시 관심이 모이는 흐름을 다룹니다"
        audience_pain = "사람들은 상승 가능성은 보지만, 왜 지금 움직이는지 판단 기준을 놓치기 쉽습니다"
        generic_angle = "2차전지 관심이 다시 올라오는 이유"
    elif any(token in source_text.lower() for token in ["bitcoin", "coin", "코인", "비트코인", "알트"]):
        original_claim = "시장 변화 속에서 투자자가 봐야 할 신호를 다룹니다"
        audience_pain = "사람들은 가격만 먼저 보다가 움직임의 이유와 리스크를 놓치기 쉽습니다"
        generic_angle = "시장이 움직일 때 먼저 확인해야 할 것"
    elif any(token in source_text for token in ["영상", "촬영", "편집", "브랜드", "콘텐츠", "유튜브"]):
        original_claim = "영상 콘텐츠가 성과로 이어지는 구조를 다룹니다"
        audience_pain = "보기 좋은 결과물에 집중하다가 목적과 전환 흐름을 놓치기 쉽습니다"
        generic_angle = "좋은 영상과 문의로 이어지는 영상의 차이"
    else:
        original_claim = f"{original_topic}에 대한 관심 포인트를 다룹니다"
        audience_pain = "사람들은 결론만 먼저 보다가 왜 중요한지, 무엇을 봐야 하는지 놓치기 쉽습니다"
        generic_angle = f"{original_topic}에서 먼저 봐야 할 것"

    transferable_structure = structure if len(structure) > 20 else "후킹 질문 → 배경 설명 → 핵심 문제 → 판단 기준 → 행동 유도"
    eaf_angle = "레퍼런스의 전개 방식을 빌려 영상 제작 전 반드시 정리해야 할 구조로 재해석"

    return {
        "original_title": title,
        "original_topic": original_topic,
        "original_claim": original_claim,
        "audience_pain": audience_pain,
        "transferable_structure": transferable_structure,
        "eaf_angle": eaf_angle,
        "generic_angle": generic_angle,
        "visual_note": visual,
        "source_is_unrelated_to_eaf": detect_unrelated_to_eaf(source_text),
    }


# ---------- UI helpers ----------

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


# ---------- Plan builders ----------

def build_service_plan(ctx):
    brand = ctx["brand"]
    tone = ctx["tone"]
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


def build_original_topic_plan(ctx):
    analysis = ctx["analysis"]
    tone = ctx["tone"]
    topic = ctx["angle"] or analysis["generic_angle"]
    problem = ctx["generic_problem"]
    cta = ctx["cta"]

    slides = [
        f"{shorten(topic, 30)}\n지금 봐야 할 건 따로 있습니다",
        analysis["original_claim"],
        f"문제는\n{shorten(problem, 88)}입니다",
        f"그래서 핵심은\n{shorten(analysis['audience_pain'], 88)}",
        "결론보다 중요한 건\n움직이는 이유와 판단 기준입니다",
        f"이 흐름을 놓치고 싶지 않다면\n{cta}",
    ]

    if ctx["template"] == "체크리스트형":
        slides = [
            f"{shorten(topic, 30)}\n보기 전에 체크할 4가지",
            "1. 왜 지금 관심이 모이는가",
            "2. 실제로 바뀐 지표가 있는가",
            "3. 기대감과 현실 사이의 간격은 어느 정도인가",
            "4. 다음 행동을 결정할 기준은 무엇인가",
            f"핵심은 결론이 아니라\n판단 기준을 갖는 것입니다\n{cta}",
        ]

    images = [
        "원본 주제를 상징하는 첫 장. 뉴스 헤드라인, 시장 그래프, 사람들이 주목하는 장면을 강한 후킹 구도로 표현.",
        "관심이 몰리는 흐름을 보여주는 장면. 검색량, 뉴스, 커뮤니티 반응이 한 화면에 정리된 느낌.",
        "잘못된 판단과 올바른 판단 기준을 나누는 인포그래픽. 빨간 경고 표시와 체크 포인트를 활용.",
        "왜 지금 움직이는지 분석하는 장면. 원인, 기대감, 리스크가 세 갈래로 정리된 보드.",
        "판단 기준을 정리한 체크리스트 카드. 핵심 지표와 다음 확인 포인트가 보이도록 구성.",
        "저장/공유/문의로 이어지는 마무리 카드. 깔끔한 여백과 강한 CTA 중심.",
    ]

    title = f"[{ctx['template']}] {shorten(topic, 46)}"
    main_message = f"{analysis['original_topic']}에서 중요한 건 결론보다 왜 지금 움직이는지 판단하는 기준입니다."
    return finalize_plan(ctx, title, main_message, slides, images)


def build_structure_only_plan(ctx):
    analysis = ctx["analysis"]
    cta = ctx["cta"]
    slides = [
        "잘 만든 콘텐츠는\n전개 순서가 다릅니다",
        "사람을 붙잡는 건\n화려한 화면보다 먼저 던지는 질문입니다",
        f"이 레퍼런스의 구조는\n{shorten(analysis['transferable_structure'], 86)}",
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


def finalize_plan(ctx, title, main_message, slides, images):
    tone = ctx["tone"]
    brand = ctx["brand"]
    slides = [humanize(remove_brand_overuse(slide, brand), tone, brand) for slide in slides]
    return {
        "title": humanize(title, tone, brand),
        "target_customer": ctx.get("target", ""),
        "core_problem": humanize(ctx.get("problem") or ctx.get("generic_problem") or "", tone, brand),
        "main_message": humanize(main_message, tone, brand),
        "cta": humanize(ctx["cta"], tone, brand),
        "common_style": COMMON_STYLE.get(ctx["visual_style"], COMMON_STYLE["혼합형"]),
        "slides": slides,
        "images": images,
    }


# ---------- State / save ----------

def update_state(plan, signature, force=False):
    if force or st.session_state.get("v5_signature") != signature or "v5_plan" not in st.session_state:
        st.session_state["v5_signature"] = signature
        st.session_state["v5_plan"] = plan
        st.session_state["v5_version"] = st.session_state.get("v5_version", 0) + 1


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
        reference_id,
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
    edited.update({
        "common_style": common_style,
        "title": title,
        "core_problem": core_problem,
        "main_message": main_message,
        "cta": cta,
        "slides": slides,
        "images": images,
    })
    return edited


def main():
    st.set_page_config(page_title="Cardnews Planner Engine V5", page_icon="🧠", layout="wide")
    init_cardnews_table()

    st.title("🧠 카드뉴스 설계 엔진 V5")
    st.caption("원본 필드 끼워넣기를 막고, 원본 분석 → 콘텐츠 목적 분기 → 카드뉴스 재구성 순서로 생성합니다.")

    refs = load_references()
    if refs.empty:
        st.warning("먼저 URL 자동 수집 또는 YouTube 영상 내용 분석에서 참고 콘텐츠를 저장하세요.")
        return

    options = {f"{row['id']} · {clean(row['title'])}": row for _, row in refs.iterrows()}
    selected_key = st.selectbox("참고 콘텐츠", list(options.keys()))
    row = options[selected_key]
    analysis = analyze_source(row)

    with st.expander("원본 분석 레이어 보기", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.write(f"**원본 제목:** {analysis['original_title']}")
            st.write(f"**원본 주제:** {analysis['original_topic']}")
            st.write(f"**원본 주장:** {analysis['original_claim']}")
        with c2:
            st.write(f"**독자 문제:** {analysis['audience_pain']}")
            st.write(f"**차용할 구조:** {analysis['transferable_structure']}")
            st.write(f"**eaf 전환 각도:** {analysis['eaf_angle']}")
        if analysis["source_is_unrelated_to_eaf"]:
            st.warning("이 원본은 영상 제작/eaf 서비스 주제와 직접 관련이 약합니다. '원본 주제 카드뉴스형' 또는 '벤치마크 구조만 차용'이 더 안전합니다.")

    st.markdown("---")
    st.markdown("### 생성 조건")
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        default_plan_idx = 1 if analysis["source_is_unrelated_to_eaf"] else 0
        plan_type = st.selectbox("콘텐츠 목적", PLAN_TYPES, index=default_plan_idx)
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
            angle_default = "좋은 영상과 문의로 이어지는 영상의 차이"
            angle = st.text_input("이번 카드뉴스의 핵심 각도", value=angle_default)
            problem, problem_label = select_from_dict("핵심 문제", SERVICE_PROBLEMS, "v5_service_problem", "전환 경로 부재")
        elif plan_type == "원본 주제 카드뉴스형":
            angle = st.text_input("이번 카드뉴스의 핵심 각도", value=analysis["generic_angle"])
            problem, problem_label = select_from_dict("핵심 문제", GENERIC_PROBLEMS, "v5_generic_problem", "시장 기대감만 보고 판단")
        else:
            angle = st.text_input("이번 카드뉴스의 핵심 각도", value="레퍼런스 구조를 콘텐츠로 바꾸는 법")
            problem = analysis["audience_pain"]
            problem_label = "원본 분석 기반"
            st.text_area("핵심 문제", value=problem, height=80, disabled=True)

    p1, p2 = st.columns(2)
    with p1:
        solution, solution_label = select_from_dict("브랜드 관점의 해결 방식", SERVICE_SOLUTIONS, "v5_solution", "전환 구조 먼저 설계")
        proof, proof_label = select_from_dict("근거 / 설명", PROOFS, "v5_proof", "문의 흐름 명확화")
    with p2:
        offer, offer_label = select_from_dict("서비스 / 제안 문장", OFFERS, "v5_offer", "브랜드/제품/유튜브 통합")
        if plan_type != "eaf 서비스 전환형":
            st.info("원본 주제형에서는 서비스 문장이 마지막 CTA에만 약하게 반영됩니다.")

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
        "generic_problem": problem,
        "solution": solution,
        "proof": proof,
        "offer": offer,
        "analysis": analysis,
    }

    if plan_type == "eaf 서비스 전환형":
        plan = build_service_plan(ctx)
    elif plan_type == "원본 주제 카드뉴스형":
        plan = build_original_topic_plan(ctx)
    else:
        plan = build_structure_only_plan(ctx)

    signature = "|".join([
        str(int(row["id"])), plan_type, template, tone, visual_style, intro_label,
        brand, target_label, cta_label, angle, problem_label, solution_label, proof_label, offer_label,
        target, cta, problem, solution, proof, offer,
    ])
    update_state(plan, signature)

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("현재 선택값으로 초안 다시 생성"):
            update_state(plan, signature, force=True)
            st.rerun()
    with col_info:
        st.info("Title:, URL:, 원본 제목 같은 필드는 카피에 그대로 들어가지 않도록 정화합니다. 이미지 방향은 공통 스타일과 장별 지시를 분리했습니다.")

    st.markdown("---")
    draft = st.session_state.get("v5_plan", plan)
    version = st.session_state.get("v5_version", 0)
    edited = render_editable(draft, version)

    if st.button("이 설계안 저장", type="primary"):
        save_plan(int(row["id"]), edited)
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
