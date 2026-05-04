import sqlite3
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")

TEMPLATE_OPTIONS = ["문제 제기형", "오해 반박형", "전후 비교형", "체크리스트형", "레퍼런스 분석형", "교육형"]
VISUAL_STYLES = ["브랜드 캐릭터 중심", "실사 오피스 시네마틱", "인포그래픽 중심", "전후 비교형", "제품/포트폴리오 중심", "혼합형"]
TONE_LEVELS = ["담백", "명확", "강한 후킹", "자극적"]

INTRO_HOOK_PRESETS = {
    "편집 퀄리티 착각": {
        "hook": "영상이 안 먹히는 이유\n편집 때문만은 아닙니다",
        "body": "편집을 더 화려하게 바꿔도\n문의가 늘지 않는 경우가 있습니다\n문제는 화면 밖에 있을 수 있습니다",
        "problem": "편집보다 먼저 목적, 타깃, 메시지, CTA가 정리되지 않은 상태",
    },
    "영상미 착각": {
        "hook": "예쁜 영상인데\n왜 문의는 없을까요?",
        "body": "보기 좋은 영상과\n고객을 움직이는 영상은 다릅니다\n전환은 분위기가 아니라 흐름에서 나옵니다",
        "problem": "영상미는 있지만 고객을 움직이는 설득 흐름이 부족한 상태",
    },
    "문의 부재": {
        "hook": "영상은 올라갔는데\n문의가 없다면",
        "body": "조회수보다 먼저 확인해야 할 건\n영상을 본 사람이 다음에 무엇을 해야 하는지\n분명하게 보이는가입니다",
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
    "CTA 부재": {
        "hook": "좋은 영상인데\n다음 행동이 없습니다",
        "body": "고객이 영상을 본 뒤\n무엇을 해야 하는지 모르면\n좋은 인상만 남기고 끝납니다",
        "problem": "영상 이후 문의, 상담, 구매, 저장 등 행동 유도가 설계되지 않은 상태",
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
    "조회수 착각": {
        "hook": "조회수가 높으면\n좋은 영상일까요?",
        "body": "브랜드 영상에서 중요한 건\n많이 본 숫자만이 아닙니다\n누가 보고, 무엇을 했는지가 더 중요합니다",
        "problem": "조회수 중심으로 판단해 실제 문의와 상담 전환 구조를 놓치는 상태",
    },
    "콘텐츠 운영 병목": {
        "hook": "계속 올리는데\n브랜드가 쌓이지 않는다면",
        "body": "문제는 업로드 횟수가 아닐 수 있습니다\n각 콘텐츠가 어떤 역할로 고객을 움직이는지\n정리되어 있어야 합니다",
        "problem": "콘텐츠별 역할과 누적 구조가 없어 운영량 대비 브랜드 자산이 쌓이지 않는 상태",
    },
    "직접 입력": {"hook": "직접 입력", "body": "직접 입력", "problem": "직접 입력"},
}

CORE_PROBLEM_PRESETS = {
    "서론 훅 기준 자동 사용": "__INTRO_PROBLEM__",
    "벤치마크 원문 사용": "__REFERENCE_HOOK__",
    "전환 경로 부재": "영상은 있지만 문의, 상담, 구매 등 다음 행동으로 이어지는 경로가 보이지 않는 상태",
    "목적 불명확": "영상의 목적이 인지도, 신뢰, 문의 중 어디에 있는지 정리되지 않은 상태",
    "타깃 불명확": "누구에게 말하는 영상인지 흐려져 메시지와 장면 선택이 모두 애매해진 상태",
    "메시지 과밀": "하고 싶은 말이 너무 많아 고객이 기억해야 할 한 문장이 보이지 않는 상태",
    "CTA 부재": "영상을 본 뒤 고객이 무엇을 해야 하는지 명확하게 안내되지 않는 상태",
    "레퍼런스 복붙": "레퍼런스의 색감과 컷은 따라 했지만 브랜드의 목적과 고객 흐름은 반영되지 않은 상태",
    "수정 반복": "초반 방향성이 불명확해 후반 수정, 재편집, 일정 지연이 반복되는 상태",
    "제작비 누수": "기획이 흐린 상태로 제작이 시작돼 시간과 비용이 조용히 늘어나는 상태",
    "조회수 중심 판단": "조회수는 보지만 실제 문의나 상담 전환으로 이어졌는지는 확인하지 못하는 상태",
    "콘텐츠 자산화 실패": "콘텐츠를 계속 올리지만 브랜드 신뢰와 문의로 누적되지 않는 상태",
    "직접 입력": "직접 입력",
}

TARGET_PRESETS = {
    "브랜드/마케팅 담당자": "영상 제작을 검토 중인 브랜드/마케팅 담당자",
    "스타트업 대표/팀장": "브랜드 신뢰도를 빠르게 쌓아야 하는 스타트업 대표/팀장",
    "제품 브랜드 담당자": "제품의 장점을 영상으로 설득해야 하는 브랜드 담당자",
    "B2B 세일즈/영업 담당자": "문의와 상담 전환을 늘리고 싶은 B2B 세일즈 담당자",
    "유튜브/콘텐츠 담당자": "유튜브와 숏폼을 꾸준히 운영해야 하는 콘텐츠 담당자",
    "직접 입력": "직접 입력",
}

CTA_PRESETS = {
    "DM 포트폴리오/견적": "DM으로 포트폴리오와 견적을 받아보세요",
    "무료 진단 유도": "지금 영상 구조가 맞는지 먼저 진단받아보세요",
    "상담 문의": "브랜드에 맞는 영상 구조가 필요하다면 상담을 남겨주세요",
    "제작 문의": "비슷한 영상 제작이 필요하다면 제작 문의를 남겨주세요",
    "레퍼런스 요청": "우리 브랜드에 맞는 레퍼런스가 궁금하다면 DM을 남겨주세요",
    "직접 입력": "직접 입력",
}

INSIGHT_PRESETS = {
    "목적-타깃-메시지-CTA": "촬영 전에 목적, 타깃, 메시지, CTA가 정리돼야 후반 수정이 줄어듭니다",
    "영상미와 전환 분리": "영상미가 좋아도 설득 흐름이 없으면 문의로 이어지기 어렵습니다",
    "초반 기획 부재": "후반 작업의 혼란은 대부분 처음 기획이 흐릴 때 시작됩니다",
    "레퍼런스 구조 분석": "좋은 레퍼런스는 색감보다 문제 제기, 납득, 행동 유도의 순서가 선명합니다",
    "콘텐츠 운영 병목": "콘텐츠는 많이 올리는 것보다 각 콘텐츠의 역할이 분명해야 쌓입니다",
    "직접 입력": "직접 입력",
}

SOLUTION_PRESETS = {
    "전환 구조 먼저 설계": "eaf:는 분위기보다 먼저 목적, 타깃, 메시지, CTA가 이어지는 구조를 설계합니다",
    "브랜드 필름 구조화": "eaf:는 브랜드 필름을 이미지 영상이 아니라 신뢰와 문의로 이어지는 흐름으로 설계합니다",
    "제품 영상 설득 구조": "eaf:는 제품의 기능보다 고객이 왜 필요로 하는지 납득하는 순서부터 잡습니다",
    "유튜브 콘텐츠 체계화": "eaf:는 유튜브 콘텐츠를 조회수용 영상이 아니라 브랜드 자산으로 설계합니다",
    "AI 하이브리드 제작": "eaf:는 AI와 실사 제작을 결합해 속도, 비용, 완성도의 균형을 맞춥니다",
    "직접 입력": "직접 입력",
}

PROOF_PRESETS = {
    "수정 리스크 감소": "초반에 구조를 잡으면 후반 수정이 줄고 메시지의 방향도 흔들리지 않습니다",
    "문의 흐름 명확화": "고객이 무엇을 보고, 무엇을 이해하고, 무엇을 해야 하는지 분명할수록 전환이 쉬워집니다",
    "제작비 누수 방지": "방향이 흐린 영상은 수정과 재작업이 반복되며 시간과 비용을 함께 소모합니다",
    "콘텐츠 자산화": "목적이 분명한 영상은 한 번 쓰고 끝나지 않고 여러 플랫폼으로 확장됩니다",
    "레퍼런스 재해석": "좋은 레퍼런스는 그대로 베끼는 게 아니라 우리 브랜드의 목적에 맞게 다시 설계해야 합니다",
    "직접 입력": "직접 입력",
}

OFFER_PRESETS = {
    "브랜드/제품/유튜브 통합": "브랜드 필름, 제품 영상, 유튜브 콘텐츠까지 전환 구조부터 함께 설계합니다",
    "브랜드 필름": "브랜드의 철학과 강점을 고객이 이해하는 흐름으로 설계합니다",
    "제품 영상": "제품의 장점과 사용 이유를 선명하게 보여주는 영상으로 만듭니다",
    "유튜브 운영 콘텐츠": "유튜브와 숏폼 콘텐츠를 브랜드 자산으로 쌓아가는 구조로 제작합니다",
    "AI 영상 패키지": "AI 기반 비주얼과 실사 제작 감각을 결합한 하이브리드 영상 패키지를 제공합니다",
    "직접 입력": "직접 입력",
}

COPY_REPLACEMENTS = {
    "진짜 병목": "정작 중요한 지점",
    "좋은 영상인데": "보기 좋은 영상인데",
    "전환되는 구조": "문의로 이어지는 구조",
    "핵심 문제": "문제의 핵심",
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


def load_references():
    conn = connect_db()
    df = pd.read_sql_query("""
        SELECT r.id, c.platform, c.channel_name, c.category, r.title, r.url,
               r.hook_point, r.structure_note, r.visual_note, r.eafi_application,
               r.total_score, r.status, r.created_at
        FROM content_references r
        LEFT JOIN benchmark_channels c ON r.channel_id = c.id
        ORDER BY r.total_score DESC, r.id DESC
    """, conn)
    conn.close()
    return df


def load_plans():
    conn = connect_db()
    df = pd.read_sql_query("SELECT * FROM cardnews_plans ORDER BY id DESC", conn)
    conn.close()
    return df


def clean(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    if text.lower() in ["nan", "none", "null"]:
        return fallback
    return text or fallback


def shorten(text, max_len=86):
    text = clean(text)
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def compact_lines(text):
    return "\n".join([line.strip() for line in clean(text).splitlines() if line.strip()])


def polish_copy(text, tone="명확"):
    text = compact_lines(text)
    for old, new in COPY_REPLACEMENTS.items():
        text = text.replace(old, new)
    text = text.replace("합니다\n합니다", "합니다")
    text = text.replace("입니다\n입니다", "입니다")
    text = text.replace("\n\n\n", "\n\n")
    if tone == "담백":
        text = text.replace("무너지면 끝입니다", "흐려지기 쉽습니다")
        text = text.replace("계속 새게 됩니다", "확인해야 합니다")
    if tone == "자극적":
        text = text.replace("놓치기 쉽습니다", "계속 놓치게 됩니다")
        text = text.replace("어렵습니다", "어려워집니다")
    return text.strip()


def select_with_custom(label, presets, key, default_label=None, height=70):
    labels = list(presets.keys())
    default_index = labels.index(default_label) if default_label in labels else 0
    selected = st.selectbox(label, labels, index=default_index, key=f"{key}_select")
    if selected == "직접 입력":
        return st.text_area(f"{label} 직접 입력", value="", height=height, key=f"{key}_custom"), selected
    return presets[selected], selected


def select_intro_frame():
    labels = list(INTRO_HOOK_PRESETS.keys())
    selected = st.selectbox("서론 훅 관점", labels, index=1, key="cr3_intro_frame")
    preset = dict(INTRO_HOOK_PRESETS[selected])
    if selected == "직접 입력":
        preset["hook"] = st.text_area("서론 훅 직접 입력", value="", height=70, key="cr3_intro_hook")
        preset["body"] = st.text_area("서론 보조 문장 직접 입력", value="", height=90, key="cr3_intro_body")
        preset["problem"] = st.text_area("서론 기반 핵심 문제 직접 입력", value="", height=90, key="cr3_intro_problem")
    return selected, preset


def select_core_problem(row, intro):
    labels = list(CORE_PROBLEM_PRESETS.keys())
    selected = st.selectbox("핵심 문제", labels, index=0, key="cr3_core_problem_select")
    value = CORE_PROBLEM_PRESETS[selected]
    if value == "__INTRO_PROBLEM__":
        return intro["problem"], selected
    if value == "__REFERENCE_HOOK__":
        return clean(row.get("hook_point"), intro["problem"]), selected
    if selected == "직접 입력":
        return st.text_area("핵심 문제 직접 입력", value="", height=90, key="cr3_core_problem_custom"), selected
    return value, selected


def split_target_label(target):
    target = clean(target, "브랜드/마케팅 담당자")
    for token in [
        "영상 제작을 검토 중인 ",
        "브랜드 신뢰도를 빠르게 쌓아야 하는 ",
        "제품의 장점을 영상으로 설득해야 하는 ",
        "문의와 상담 전환을 늘리고 싶은 ",
        "유튜브와 숏폼을 꾸준히 운영해야 하는 ",
    ]:
        target = target.replace(token, "")
    return target.strip() or "브랜드/마케팅 담당자"


def hookify(text, tone):
    text = clean(text)
    if tone in ["담백", "명확"]:
        return text
    if tone == "강한 후킹":
        return text if any(word in text for word in ["왜", "이유", "문제", "없다면", "아닙니다"]) else f"{text}\n문제는 다른 데 있습니다"
    return text if any(word in text for word in ["왜", "문제", "끝", "없다면", "새는"]) else f"{text}\n이걸 놓치면 계속 새게 됩니다"


def build_image_direction(brand, visual_style, role):
    base = f"{brand} 브랜드 팔레트인 레드, 블랙, 웜 그레이를 사용한 1:1 카드뉴스 이미지. 공식 로고와 캐릭터 톤을 유지. "
    style_map = {
        "브랜드 캐릭터 중심": "메인 캐릭터가 빨간 캡과 빨간 폴로를 입고 등장. 개구리 엠블럼은 작은 패치로만 사용. ",
        "실사 오피스 시네마틱": "현대적인 어두운 오피스나 편집실의 시네마틱 실사 장면. ",
        "인포그래픽 중심": "고급 인포그래픽, 아이콘, 다이어그램 중심의 구성. ",
        "전후 비교형": "좌우 비교 구도. 왼쪽은 문제 상황, 오른쪽은 해결 상황. ",
        "제품/포트폴리오 중심": "노트북, 포트폴리오, 영상 플레이어, 제품 컷, 웹사이트 목업 중심. ",
        "혼합형": "실사 장면과 인포그래픽을 자연스럽게 섞은 구성. ",
    }
    role_map = {
        "hook": "서론 훅을 강하게 보여주는 첫 장. 대비가 크고 여백이 충분한 구도.",
        "problem": "문제가 발생하는 원인을 시각화. 수정, 낮은 전환, 불명확한 타깃을 세련되게 표현.",
        "analysis": "원인과 구조를 보여주는 다이어그램, 체크리스트, 흐름도 중심.",
        "compare": "비포/애프터 비교. 혼란스러운 제작과 구조화된 제작의 차이를 표현.",
        "solution": "스토리보드, 무드보드, 전환 퍼널, 편집 타임라인이 정리된 장면.",
        "cta": "포트폴리오와 견적 문의가 자연스럽게 보이는 마무리 컷.",
        "checklist": "핵심 항목이 정돈된 고급 체크리스트 UI.",
        "case": "레퍼런스를 분석하고 브랜드 방식으로 재해석하는 장면.",
    }
    return base + style_map.get(visual_style, "") + role_map.get(role, "고급 카드뉴스용 장면.")


def build_plan(ctx):
    brand = ctx["brand"]
    template = ctx["template"]
    tone = ctx["tone"]
    target_label = split_target_label(ctx["target"])
    angle = clean(ctx["angle"], "브랜드 영상이 문의로 이어지지 않는 이유")
    intro = ctx["intro"]
    problem = clean(ctx["problem"], intro["problem"])
    insight = clean(ctx["insight"])
    solution = clean(ctx["solution"])
    proof = clean(ctx["proof"])
    offer = clean(ctx["offer"])
    cta = clean(ctx["cta"])
    source_title = clean(ctx["source_title"], "벤치마크 콘텐츠")

    if template == "문제 제기형":
        slides = [
            hookify(intro["hook"], tone),
            intro["body"],
            f"문제의 핵심은\n{shorten(problem, 92)}입니다",
            f"그래서 제작 전에\n{shorten(insight, 92)}",
            f"{brand}는 이렇게 접근합니다\n{shorten(solution, 92)}",
            f"보기 좋은 영상보다\n문의로 이어지는 구조가 필요하다면\n{cta}",
        ]
        roles = ["hook", "problem", "analysis", "compare", "solution", "cta"]
    elif template == "오해 반박형":
        slides = [
            hookify(intro["hook"], tone),
            intro["body"],
            f"놓친 건 이것입니다\n{shorten(problem, 86)}",
            f"{shorten(proof, 92)}",
            f"{brand}는 결과물보다 먼저\n{shorten(solution, 92)}",
            f"{offer}\n{cta}",
        ]
        roles = ["hook", "problem", "analysis", "compare", "solution", "cta"]
    elif template == "전후 비교형":
        slides = [
            hookify("같은 영상도\n결과는 완전히 달라집니다", tone),
            f"Before\n{shorten(problem, 80)}",
            "After\n목적, 타깃, 메시지, CTA가\n한 방향으로 이어지는 영상",
            f"차이는 여기서 납니다\n{shorten(insight, 92)}",
            f"{brand}는 제작 전에\n{shorten(solution, 92)}",
            f"{offer}\n{cta}",
        ]
        roles = ["hook", "problem", "analysis", "compare", "solution", "cta"]
    elif template == "체크리스트형":
        slides = [
            hookify("영상 만들기 전\n이 4가지는 먼저 정리하세요", tone),
            "1. 목적\n이 영상이 인지도, 신뢰, 문의 중\n무엇을 만들지 정해야 합니다",
            "2. 타깃\n누구에게 말하는지 흐리면\n메시지도 같이 흐려집니다",
            "3. 메시지\n고객이 기억할 한 문장이\n먼저 필요합니다",
            "4. CTA\n영상을 본 뒤 무엇을 해야 하는지까지\n설계해야 전환이 생깁니다",
            f"이 4개가 정리되지 않았다면\n{brand}와 구조부터 잡아보세요\n{cta}",
        ]
        roles = ["hook", "checklist", "checklist", "checklist", "checklist", "cta"]
    elif template == "레퍼런스 분석형":
        slides = [
            hookify(f"{shorten(source_title, 30)}\n우리가 봐야 할 건 겉모습이 아닙니다", tone),
            f"이 레퍼런스에서 볼 건\n색감보다 전개 구조입니다\n출처: {ctx['platform']} · {ctx['channel']}",
            f"핵심 구조는\n{shorten(insight, 92)}",
            f"이걸 {target_label} 관점으로 바꾸면\n{shorten(angle, 72)}라는 주제가 됩니다",
            f"{brand}는 이 구조를\n{shorten(solution, 92)}",
            f"이런 콘텐츠 구조가 필요하다면\n{cta}",
        ]
        roles = ["case", "analysis", "analysis", "compare", "solution", "cta"]
    else:
        slides = [
            hookify(f"{angle}\n이 원리만 알면 훨씬 선명해집니다", tone),
            "영상은 장면을 나열하는 일이 아닙니다\n고객이 판단하는 순서를 설계하는 일입니다",
            f"첫 번째는 문제 인식\n{shorten(problem, 82)}",
            f"두 번째는 납득 구조\n{shorten(proof, 82)}",
            f"세 번째는 행동 유도\n{shorten(solution, 82)}",
            f"{offer}\n{cta}",
        ]
        roles = ["hook", "analysis", "problem", "analysis", "solution", "cta"]

    return {
        "title": f"[{template}] {shorten(angle, 45)}",
        "target_customer": ctx["target"],
        "core_problem": problem,
        "main_message": f"{brand}는 {target_label}에게 필요한 영상 구조를 먼저 설계합니다. 핵심은 {shorten(insight, 96)}",
        "cta": cta,
        "slides": [polish_copy(slide, tone) for slide in slides],
        "images": [build_image_direction(brand, ctx["visual_style"], role) for role in roles],
    }


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
        "초안", datetime.now().isoformat(timespec="seconds"),
    ))
    conn.commit()
    conn.close()


def update_draft_state(plan, signature, force=False):
    if force or st.session_state.get("copy_reviewed_v3_signature") != signature or "copy_reviewed_v3_plan" not in st.session_state:
        st.session_state["copy_reviewed_v3_signature"] = signature
        st.session_state["copy_reviewed_v3_plan"] = plan
        st.session_state["copy_reviewed_v3_version"] = st.session_state.get("copy_reviewed_v3_version", 0) + 1


def render_editable_plan(plan, version):
    suffix = f"v{version}"
    st.markdown("### 핵심 설계")
    title = st.text_input("저장할 주제명", value=plan["title"], key=f"cr3_title_{suffix}")
    core_problem = st.text_area("핵심 문제", value=plan["core_problem"], height=80, key=f"cr3_problem_{suffix}")
    main_message = st.text_area("메인 메시지", value=plan["main_message"], height=90, key=f"cr3_message_{suffix}")
    cta = st.text_input("CTA", value=plan["cta"], key=f"cr3_cta_{suffix}")

    st.markdown("### 6장 카드뉴스 구성 직접 수정")
    slides, images = [], []
    for idx, (copy, image) in enumerate(zip(plan["slides"], plan["images"]), start=1):
        with st.container(border=True):
            st.markdown(f"#### {idx}장")
            slides.append(st.text_area("카피", value=copy, height=130, key=f"cr3_slide_{idx}_{suffix}"))
            images.append(st.text_area("이미지 방향", value=image, height=110, key=f"cr3_image_{idx}_{suffix}"))

    edited = dict(plan)
    edited.update({"title": title, "core_problem": core_problem, "main_message": main_message, "cta": cta, "slides": slides, "images": images})
    return edited


def main():
    st.set_page_config(page_title="Cardnews Planner Copy Reviewed V3", page_icon="🧩", layout="wide")
    init_cardnews_table()

    st.title("🧩 카드뉴스 설계안 생성 Copy Reviewed V3")
    st.caption("핵심 문제까지 드롭다운으로 선택하는 버전입니다.")

    refs = load_references()
    if refs.empty:
        st.warning("먼저 메인 페이지에서 벤치마크 채널과 참고 콘텐츠를 등록하세요.")
        return

    options = {f"{row['id']} · {row['total_score']}점 · {row['title']}": row for _, row in refs.iterrows()}
    selected_key = st.selectbox("카드뉴스로 만들 참고 콘텐츠", list(options.keys()))
    row = options[selected_key]

    with st.expander("선택한 벤치마크 원본 데이터 보기"):
        st.write(f"**플랫폼:** {clean(row.get('platform'), '-')}")
        st.write(f"**채널:** {clean(row.get('channel_name'), '-')}")
        st.write(f"**제목:** {clean(row.get('title'), '-')}")
        st.write(f"**후킹 포인트:** {clean(row.get('hook_point'), '-')}")
        st.write(f"**전개 구조:** {clean(row.get('structure_note'), '-')}")
        st.write(f"**적용 아이디어:** {clean(row.get('eafi_application'), '-')}")

    st.markdown("---")
    st.markdown("### 생성 조건")
    c1, c2, c3 = st.columns(3)
    with c1:
        template = st.selectbox("콘텐츠 구조", TEMPLATE_OPTIONS)
    with c2:
        tone = st.selectbox("후킹 강도", TONE_LEVELS, index=2)
    with c3:
        visual_style = st.selectbox("이미지 스타일", VISUAL_STYLES)

    i1, i2 = st.columns(2)
    with i1:
        intro_label, intro = select_intro_frame()
    with i2:
        st.markdown("#### 선택된 서론 미리보기")
        st.write(f"**훅:** {intro['hook']}")
        st.write(f"**보조 문장:** {intro['body']}")
        st.write(f"**기본 문제:** {intro['problem']}")

    c4, c5 = st.columns(2)
    with c4:
        brand = st.text_input("브랜드명", value="eaf:")
        target, target_label = select_with_custom("타깃 고객", TARGET_PRESETS, "cr3_target", "브랜드/마케팅 담당자")
        cta, cta_label = select_with_custom("CTA", CTA_PRESETS, "cr3_cta_preset", "DM 포트폴리오/견적")
        problem, problem_label = select_core_problem(row, intro)
    with c5:
        angle = st.text_area("이번 카드뉴스의 핵심 각도", value=clean(row.get("eafi_application"), clean(row.get("title"), "기업 영상이 문의로 이어지지 않는 이유")), height=80)
        st.markdown("#### 선택된 핵심 문제 미리보기")
        st.write(problem)

    p1, p2 = st.columns(2)
    with p1:
        insight, insight_label = select_with_custom("벤치마크에서 가져올 인사이트 / 전개 구조", INSIGHT_PRESETS, "cr3_insight", "목적-타깃-메시지-CTA", height=90)
        proof, proof_label = select_with_custom("근거 / 설명", PROOF_PRESETS, "cr3_proof", "수정 리스크 감소", height=90)
    with p2:
        solution, solution_label = select_with_custom("브랜드 관점의 해결 방식", SOLUTION_PRESETS, "cr3_solution", "전환 구조 먼저 설계", height=90)
        offer, offer_label = select_with_custom("서비스 / 제안 문장", OFFER_PRESETS, "cr3_offer", "브랜드/제품/유튜브 통합", height=90)

    ctx = {
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
        "insight": insight,
        "solution": solution,
        "proof": proof,
        "offer": offer,
        "source_title": clean(row.get("title"), "벤치마크 콘텐츠"),
        "platform": clean(row.get("platform"), "플랫폼"),
        "channel": clean(row.get("channel_name"), "벤치마크 채널"),
    }

    plan = build_plan(ctx)
    signature = "|".join([
        str(int(row["id"])), template, tone, visual_style, intro_label, intro["hook"], intro["body"],
        brand, target_label, cta_label, problem_label, angle, problem, insight_label, solution_label, proof_label, offer_label,
        target, cta, insight, solution, proof, offer,
    ])
    update_draft_state(plan, signature)

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("현재 선택값으로 초안 다시 생성"):
            update_draft_state(plan, signature, force=True)
            st.rerun()
    with col_info:
        st.info("핵심 문제 드롭다운을 바꾸면 3장 이후 문제 정의와 해결 흐름이 함께 바뀝니다.")

    st.markdown("---")
    draft = st.session_state.get("copy_reviewed_v3_plan", plan)
    version = st.session_state.get("copy_reviewed_v3_version", 0)
    edited = render_editable_plan(draft, version)

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
