import sqlite3
from pathlib import Path
from datetime import datetime

import pandas as pd
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")

TEMPLATE_OPTIONS = ["문제폭로형", "오해반박형", "전후비교형", "체크리스트형", "케이스분석형", "교육노하우형"]
VISUAL_STYLES = ["브랜드 캐릭터 중심", "실사 오피스 시네마틱", "인포그래픽 중심", "전후 비교형", "제품/포트폴리오 중심", "혼합형"]
TONE_LEVELS = ["담백", "명확", "강한 후킹", "자극적"]

INTRO_HOOK_PRESETS = {
    "편집 퀄리티 착각": {
        "hook": "이건 편집 퀄리티 문제가 아닙니다",
        "body": "많은 분들이 편집 퀄리티부터 손봅니다\n그런데 문의가 늘지 않는다면\n문제는 다른 곳에 있을 수 있습니다",
        "problem": "편집보다 먼저 목적, 타깃, 메시지, CTA가 정리되지 않은 상태",
    },
    "영상미 착각": {
        "hook": "예쁜 영상인데\n왜 문의는 없을까요?",
        "body": "영상미가 좋아도\n누구를 설득하고 어디서 전환될지 없으면\n결과는 생각보다 조용합니다",
        "problem": "영상미는 있지만 고객을 움직이는 설득 흐름이 부족한 상태",
    },
    "문의 부재": {
        "hook": "영상은 나갔는데\n문의가 없다면",
        "body": "조회수나 반응보다 먼저 봐야 할 건\n이 영상이 어떤 행동으로 이어지게 설계됐는지입니다",
        "problem": "시청 이후 문의, 상담, 구매 등 다음 행동으로 이어지는 경로가 불명확한 상태",
    },
    "기획 부재": {
        "hook": "문제는 촬영 현장이 아니라\n기획서에서 시작됩니다",
        "body": "후반 작업에서 터지는 수정과 혼란은\n대부분 처음 방향성이 흐릴 때 생깁니다",
        "problem": "제작 전에 목적과 메시지 구조가 정리되지 않아 후반 수정이 반복되는 상태",
    },
    "타깃 불명확": {
        "hook": "누구에게 말하는 영상인지\n흐리면 전부 흐려집니다",
        "body": "타깃이 흐리면\n카피도, 장면도, 편집 리듬도\n결국 애매해집니다",
        "problem": "영상이 설득해야 할 고객군이 명확하지 않아 메시지가 넓고 약해지는 상태",
    },
    "CTA 부재": {
        "hook": "좋은 영상인데\n다음 행동이 없습니다",
        "body": "고객이 영상을 본 뒤\n무엇을 해야 하는지 모르면\n좋은 인상만 남기고 끝납니다",
        "problem": "영상 이후 문의, 상담, 구매, 저장 등 행동 유도가 설계되지 않은 상태",
    },
    "제작비 누수": {
        "hook": "제작비가 새는 지점은\n촬영장이 아닐 수 있습니다",
        "body": "방향이 흐린 상태로 시작하면\n수정, 재촬영, 재편집이 반복되며\n비용이 조용히 늘어납니다",
        "problem": "초반 기획 부재로 수정과 재작업이 반복되며 시간과 비용이 증가하는 상태",
    },
    "레퍼런스 복붙": {
        "hook": "레퍼런스를 따라 했는데\n왜 우리 영상은 안 먹힐까요?",
        "body": "좋은 레퍼런스의 핵심은\n색감이나 컷이 아니라\n시청자를 설득하는 순서에 있습니다",
        "problem": "레퍼런스의 겉모습만 따라 하고 브랜드의 목적과 고객 흐름은 반영하지 못한 상태",
    },
    "조회수 착각": {
        "hook": "조회수가 높으면\n좋은 영상일까요?",
        "body": "브랜드 영상에서 중요한 건\n많이 본 숫자보다\n누가 보고 어떤 행동을 했는지입니다",
        "problem": "조회수 중심으로 판단해 실제 문의와 상담 전환 구조를 놓치는 상태",
    },
    "콘텐츠 운영 병목": {
        "hook": "콘텐츠를 계속 올리는데\n브랜드가 쌓이지 않는다면",
        "body": "문제는 업로드 횟수가 아니라\n각 콘텐츠가 어떤 역할로 고객을 움직이는지\n정리되지 않은 데 있을 수 있습니다",
        "problem": "콘텐츠별 역할과 누적 구조가 없어 운영량 대비 브랜드 자산이 쌓이지 않는 상태",
    },
    "직접 입력": {
        "hook": "직접 입력",
        "body": "직접 입력",
        "problem": "직접 입력",
    },
}

TARGET_PRESETS = {
    "브랜드/마케팅 담당자": "영상 제작을 고민하는 브랜드/마케팅 담당자",
    "스타트업 대표/팀장": "브랜드 인지도와 신뢰도를 빠르게 만들고 싶은 스타트업 대표/팀장",
    "제품 브랜드 담당자": "제품의 장점은 있지만 영상으로 설득하기 어려운 제품 브랜드 담당자",
    "B2B 세일즈/영업 담당자": "문의와 상담 전환을 늘리고 싶은 B2B 세일즈/영업 담당자",
    "유튜브/콘텐츠 담당자": "유튜브와 숏폼 콘텐츠를 꾸준히 운영해야 하는 콘텐츠 담당자",
    "직접 입력": "직접 입력",
}

CTA_PRESETS = {
    "DM 포트폴리오/견적": "DM으로 포트폴리오와 견적을 받아보세요",
    "무료 진단 유도": "지금 만든 영상 구조가 맞는지 무료로 진단받아보세요",
    "상담 문의": "브랜드에 맞는 영상 구조가 필요하다면 상담을 남겨주세요",
    "제작 문의": "비슷한 영상 제작이 필요하다면 제작 문의를 남겨주세요",
    "레퍼런스 요청": "우리 브랜드에 맞는 레퍼런스를 받아보고 싶다면 DM을 남겨주세요",
    "직접 입력": "직접 입력",
}

INSIGHT_PRESETS = {
    "목적-타깃-메시지-CTA": "촬영 전에 목적, 타깃, 메시지, CTA가 정리되지 않으면 후반 작업에서 수정이 반복됩니다",
    "영상미와 전환 분리": "영상미가 좋아도 누구를 설득하고 어디서 전환될지 설계되지 않으면 문의로 이어지기 어렵습니다",
    "초반 기획 부재": "후반 작업에서 터지는 문제의 대부분은 처음 기획 단계에서 이미 시작됩니다",
    "레퍼런스 구조 분석": "좋은 레퍼런스는 겉모습보다 문제 제기, 납득, 행동 유도 순서가 선명합니다",
    "콘텐츠 운영 병목": "꾸준히 올리는 것보다 중요한 건 각 콘텐츠가 어떤 역할로 고객을 움직이는지 정리하는 것입니다",
    "직접 입력": "직접 입력",
}

SOLUTION_PRESETS = {
    "전환 구조 먼저 설계": "eaf:는 영상의 분위기보다 목적, 타깃, 메시지, CTA가 이어지는 전환 구조를 먼저 설계합니다",
    "브랜드 필름 구조화": "eaf:는 브랜드 필름을 단순 이미지 영상이 아니라 신뢰와 문의로 이어지는 흐름으로 설계합니다",
    "제품 영상 설득 구조": "eaf:는 제품의 기능보다 고객이 왜 필요로 하는지 납득하는 순서부터 설계합니다",
    "유튜브 콘텐츠 체계화": "eaf:는 유튜브 콘텐츠를 조회수용 영상이 아니라 브랜드 인지도와 상담으로 이어지는 자산으로 설계합니다",
    "AI 하이브리드 제작": "eaf:는 AI와 실사 제작을 결합해 속도, 비용, 완성도를 함께 고려한 제작 구조를 만듭니다",
    "직접 입력": "직접 입력",
}

PROOF_PRESETS = {
    "수정 리스크 감소": "기획 단계에서 구조가 정리되면 후반 수정이 줄고, 메시지와 행동 유도가 일관되게 이어집니다",
    "문의 흐름 명확화": "고객이 무엇을 보고, 무엇을 이해하고, 어떤 행동을 해야 하는지 분명할수록 문의 전환이 쉬워집니다",
    "제작비 누수 방지": "방향성이 불명확한 영상은 수정과 재작업이 반복되면서 시간과 비용이 함께 늘어납니다",
    "콘텐츠 자산화": "목적이 분명한 영상은 한 번 쓰고 끝나는 결과물이 아니라 여러 플랫폼으로 확장되는 콘텐츠 자산이 됩니다",
    "레퍼런스 재해석": "잘 만든 레퍼런스의 핵심은 톤앤매너보다 시청자가 납득하는 순서에 있습니다",
    "직접 입력": "직접 입력",
}

OFFER_PRESETS = {
    "브랜드/제품/유튜브 통합": "브랜드 필름, 제품 영상, 유튜브 콘텐츠까지 문의로 이어지는 구조부터 함께 설계",
    "브랜드 필름": "브랜드의 철학과 강점을 고객이 이해하는 흐름으로 설계하는 브랜드 필름 제작",
    "제품 영상": "제품의 장점과 사용 이유를 선명하게 보여주는 제품 영상 제작",
    "유튜브 운영 콘텐츠": "유튜브와 숏폼 콘텐츠를 브랜드 자산으로 쌓아가는 콘텐츠 제작",
    "AI 영상 패키지": "AI 기반 비주얼과 실사 제작 감각을 결합한 하이브리드 영상 패키지",
    "직접 입력": "직접 입력",
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


def shorten(text, max_len=80):
    text = clean(text)
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def compact_lines(text):
    return "\n".join([line.strip() for line in clean(text).splitlines() if line.strip()])


def select_with_custom(label, presets, key, default_label=None, height=70):
    labels = list(presets.keys())
    default_index = labels.index(default_label) if default_label in labels else 0
    selected = st.selectbox(label, labels, index=default_index, key=f"{key}_select")
    if selected == "직접 입력":
        return st.text_area(f"{label} 직접 입력", value="", height=height, key=f"{key}_custom")
    return presets[selected]


def select_intro_frame():
    labels = list(INTRO_HOOK_PRESETS.keys())
    selected = st.selectbox("서론 훅 관점", labels, index=1, key="intro_frame_select")
    preset = dict(INTRO_HOOK_PRESETS[selected])
    if selected == "직접 입력":
        preset["hook"] = st.text_area("서론 훅 직접 입력", value="", height=70, key="intro_hook_custom")
        preset["body"] = st.text_area("서론 보조 문장 직접 입력", value="", height=90, key="intro_body_custom")
        preset["problem"] = st.text_area("서론 기반 핵심 문제 직접 입력", value="", height=90, key="intro_problem_custom")
    return selected, preset


def split_target_label(target):
    target = clean(target, "브랜드/마케팅 담당자")
    for token in ["영상 제작을 고민하는 ", "브랜드 인지도와 신뢰도를 빠르게 만들고 싶은 ", "문의와 상담 전환을 늘리고 싶은 "]:
        target = target.replace(token, "")
    return target.strip() or "브랜드/마케팅 담당자"


def normalize_korean_copy(text):
    text = compact_lines(text)
    replacements = {
        "진짜 병목을 놓칩니다": "정작 중요한 지점을 놓치기 쉽습니다",
        "핵심 문제는 ": "문제의 핵심은 ",
        "비슷한 구조의 콘텐츠가 필요하다면": "이런 구조의 콘텐츠가 필요하다면",
        "고객 행동까지 설계된 영상": "고객의 다음 행동까지 설계된 영상",
        "결과물의 분위기보다 전환 구조를 먼저 설계한다": "결과물의 분위기보다 전환 구조를 먼저 설계합니다",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text.replace("\n\n\n", "\n\n").strip()


def review_slide_copy(slide, tone_level):
    text = normalize_korean_copy(slide)
    if tone_level == "자극적":
        text = text.replace("놓치기 쉽습니다", "계속 놓치게 됩니다")
    elif tone_level == "담백":
        text = text.replace("진짜", "")
    return compact_lines(text)


def review_plan_copy(plan, tone_level):
    reviewed = dict(plan)
    reviewed["title"] = normalize_korean_copy(reviewed["title"])
    reviewed["core_problem"] = normalize_korean_copy(reviewed["core_problem"])
    reviewed["main_message"] = normalize_korean_copy(reviewed["main_message"])
    reviewed["cta"] = normalize_korean_copy(reviewed["cta"])
    reviewed["slides"] = [review_slide_copy(slide, tone_level) for slide in reviewed["slides"]]
    return reviewed


def hookify(text, tone_level):
    text = clean(text)
    if tone_level in ["담백", "명확"]:
        return text
    if tone_level == "강한 후킹":
        return text if any(word in text for word in ["왜", "이유", "문제", "진짜"]) else f"{text}\n문제는 다른 데 있습니다"
    return text if any(word in text for word in ["왜", "망", "큰일", "문제", "진짜"]) else f"{text}\n이걸 놓치면 계속 새게 됩니다"


def build_image_direction(brand, visual_style, role):
    base = f"{brand} 브랜드 팔레트인 레드, 블랙, 웜 그레이를 사용한 1:1 카드뉴스 이미지. 공식 로고와 캐릭터 톤 유지. "
    style_map = {
        "브랜드 캐릭터 중심": "메인 캐릭터가 빨간 캡과 빨간 폴로를 입고 등장. 개구리 엠블럼은 작은 패치로만 사용. ",
        "실사 오피스 시네마틱": "현대적인 어두운 오피스/편집실의 시네마틱 실사 장면. ",
        "인포그래픽 중심": "고급 인포그래픽, 아이콘, 다이어그램 중심. ",
        "전후 비교형": "좌우 비교 구도. 왼쪽은 문제 상황, 오른쪽은 해결 상황. ",
        "제품/포트폴리오 중심": "노트북, 포트폴리오, 영상 플레이어, 제품 컷, 웹사이트 목업 중심. ",
        "혼합형": "실사 장면과 인포그래픽을 혼합한 구성. ",
    }
    role_map = {
        "hook": "선택한 서론 훅 관점을 강하게 보여주는 첫 장. 큰 대비와 여백 확보.",
        "problem": "문제가 발생하는 원인을 시각화. 수정, 낮은 전환, 불명확한 타깃을 세련되게 표현.",
        "analysis": "원인과 구조를 보여주는 다이어그램/체크리스트/흐름도.",
        "compare": "비포/애프터 비교. 혼란스러운 제작과 구조화된 제작의 차이를 표현.",
        "solution": "스토리보드, 무드보드, 전환 퍼널, 편집 타임라인이 정리된 장면.",
        "cta": "포트폴리오/견적 문의 장면. 노트북 웹사이트 목업과 CTA가 보이는 마무리 컷.",
        "checklist": "핵심 항목이 정돈된 고급 체크리스트 UI.",
        "case": "벤치마크 콘텐츠를 분석하고 브랜드 방식으로 재해석하는 장면.",
    }
    return base + style_map.get(visual_style, "") + role_map.get(role, "고급 카드뉴스용 장면.")


def build_plan(ctx):
    brand = ctx["brand"]
    template = ctx["template"]
    tone = ctx["tone"]
    target_label = split_target_label(ctx["target"])
    angle = ctx["angle"]
    intro = ctx["intro"]
    problem = clean(ctx["problem"], intro["problem"])
    insight = ctx["insight"]
    solution = ctx["solution"]
    proof = ctx["proof"]
    offer = ctx["offer"]
    cta = ctx["cta"]
    source_title = ctx["source_title"]

    if template == "문제폭로형":
        slides = [
            hookify(intro["hook"], tone),
            intro["body"],
            f"문제의 핵심은 이것입니다\n{shorten(problem, 90)}",
            f"대부분 여기서부터 꼬입니다\n{shorten(insight, 95)}",
            f"{brand}는 이렇게 설계합니다\n{shorten(solution, 95)}",
            f"멋진 결과물보다\n전환되는 구조가 필요하다면\n{cta}",
        ]
        roles = ["hook", "problem", "analysis", "compare", "solution", "cta"]
    elif template == "오해반박형":
        slides = [
            hookify(intro["hook"], tone),
            intro["body"],
            f"놓친 건 이것입니다\n{shorten(problem, 85)}",
            "영상은 좋아 보이는 순간보다\n고객이 이해하고 움직이는 흐름이 더 중요합니다",
            f"{brand}는 분위기보다 구조를 먼저 잡습니다\n{shorten(solution, 85)}",
            f"{offer}\n필요하다면\n{cta}",
        ]
        roles = ["hook", "problem", "analysis", "compare", "solution", "cta"]
    elif template == "전후비교형":
        slides = [
            hookify(f"같은 영상도\n결과가 갈리는 이유", tone),
            f"{intro['body']}\n{shorten(problem, 65)}",
            "구조를 잡고 만들면\n목적, 타깃, 메시지, CTA가\n한 방향으로 이어집니다",
            "Before\n겉보기엔 괜찮지만 전환이 약한 영상\nAfter\n고객의 다음 행동까지 설계된 영상",
            f"{brand}는 제작 전에\n이 흐름을 먼저 설계합니다\n{shorten(insight, 80)}",
            f"{offer}\n{cta}",
        ]
        roles = ["hook", "problem", "analysis", "compare", "solution", "cta"]
    elif template == "체크리스트형":
        slides = [
            hookify("영상 만들기 전\n이 4개는 먼저 정리하세요", tone),
            "1. 목적\n이 영상이 인지도, 신뢰, 문의 중\n무엇을 만들지 정해야 합니다",
            "2. 타깃\n누구에게 말하는 영상인지 흐리면\n메시지도 같이 흐려집니다",
            "3. 메시지\n고객이 기억해야 할 한 문장이\n먼저 필요합니다",
            "4. CTA\n영상을 본 뒤 무엇을 해야 하는지까지\n설계해야 전환이 생깁니다",
            f"이 4개가 정리되지 않았다면\n{brand}와 구조부터 잡아보세요\n{cta}",
        ]
        roles = ["hook", "checklist", "checklist", "checklist", "checklist", "cta"]
    elif template == "케이스분석형":
        slides = [
            hookify(f"{shorten(source_title, 30)}\n우리가 봐야 할 건 조회수만이 아닙니다", tone),
            f"이 레퍼런스에서 볼 건\n겉모습보다 전개 구조입니다\n출처: {ctx['platform']} · {ctx['channel']}",
            f"핵심 구조\n{shorten(insight, 105)}",
            f"이걸 {target_label} 관점으로 바꾸면\n{shorten(angle, 65)}라는 주제가 됩니다",
            f"{brand} 적용 방식\n{shorten(solution, 95)}",
            f"이런 구조의 콘텐츠가 필요하다면\n{cta}",
        ]
        roles = ["case", "analysis", "analysis", "compare", "solution", "cta"]
    else:
        slides = [
            hookify(f"{angle}\n이 원리만 알면 훨씬 선명해집니다", tone),
            "영상은 장면을 나열하는 일이 아닙니다\n고객이 판단하는 순서를 설계하는 일입니다",
            f"첫 번째는 문제 인식\n{shorten(problem, 80)}",
            f"두 번째는 납득 구조\n{shorten(proof, 80)}",
            f"세 번째는 행동 유도\n{shorten(solution, 80)}",
            f"{offer}\n{cta}",
        ]
        roles = ["hook", "analysis", "problem", "analysis", "solution", "cta"]

    plan = {
        "title": f"[{template}] {shorten(angle, 45)}",
        "target_customer": ctx["target"],
        "core_problem": problem,
        "main_message": f"{brand}는 {target_label}에게 필요한 전환 구조를 먼저 설계합니다. 핵심은 {shorten(insight, 100)}",
        "cta": cta,
        "slides": slides,
        "images": [build_image_direction(brand, ctx["visual_style"], role) for role in roles],
    }
    return review_plan_copy(plan, tone) if ctx["auto_review"] else plan


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
    if force or st.session_state.get("preset_v2_signature") != signature or "preset_v2_plan" not in st.session_state:
        st.session_state["preset_v2_signature"] = signature
        st.session_state["preset_v2_plan"] = plan
        st.session_state["preset_v2_version"] = st.session_state.get("preset_v2_version", 0) + 1


def render_editable_plan(plan, version):
    suffix = f"v{version}"
    st.markdown("### 핵심 설계")
    title = st.text_input("저장할 주제명", value=plan["title"], key=f"preset_v2_title_{suffix}")
    core_problem = st.text_area("핵심 문제", value=plan["core_problem"], height=80, key=f"preset_v2_problem_{suffix}")
    main_message = st.text_area("메인 메시지", value=plan["main_message"], height=90, key=f"preset_v2_message_{suffix}")
    cta = st.text_input("CTA", value=plan["cta"], key=f"preset_v2_cta_{suffix}")

    st.markdown("### 6장 카드뉴스 구성 직접 수정")
    slides, images = [], []
    for idx, (copy, image) in enumerate(zip(plan["slides"], plan["images"]), start=1):
        with st.container(border=True):
            st.markdown(f"#### {idx}장")
            slides.append(st.text_area("카피", value=copy, height=130, key=f"preset_v2_slide_{idx}_{suffix}"))
            images.append(st.text_area("이미지 방향", value=image, height=110, key=f"preset_v2_image_{idx}_{suffix}"))

    edited = dict(plan)
    edited.update({"title": title, "core_problem": core_problem, "main_message": main_message, "cta": cta, "slides": slides, "images": images})
    return edited


def main():
    st.set_page_config(page_title="Cardnews Planner Presets V2", page_icon="🧩", layout="wide")
    init_cardnews_table()

    st.title("🧩 카드뉴스 설계안 생성 프리셋 V2")
    st.caption("서론 훅 관점을 선택해 첫 장이 편집 퀄리티에만 갇히지 않도록 만든 버전입니다.")

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
    c1, c2, c3, c4 = st.columns(4)
    with c1:
        template = st.selectbox("콘텐츠 구조", TEMPLATE_OPTIONS)
    with c2:
        tone = st.selectbox("후킹 강도", TONE_LEVELS, index=2)
    with c3:
        visual_style = st.selectbox("이미지 스타일", VISUAL_STYLES)
    with c4:
        auto_review = st.checkbox("한국어 카피 자동 검수", value=True)

    i1, i2 = st.columns(2)
    with i1:
        intro_label, intro = select_intro_frame()
    with i2:
        st.markdown("#### 선택된 서론 미리보기")
        st.write(f"**훅:** {intro['hook']}")
        st.write(f"**보조 문장:** {intro['body']}")
        st.write(f"**기본 문제:** {intro['problem']}")

    c5, c6 = st.columns(2)
    with c5:
        brand = st.text_input("브랜드명", value="eaf:")
        target = select_with_custom("타깃 고객", TARGET_PRESETS, "target_v2", "브랜드/마케팅 담당자")
        cta = select_with_custom("CTA", CTA_PRESETS, "cta_v2", "DM 포트폴리오/견적")
    with c6:
        angle = st.text_area("이번 카드뉴스의 핵심 각도", value=clean(row.get("eafi_application"), clean(row.get("title"), "기업 영상이 문의로 이어지지 않는 이유")), height=80)
        default_problem = clean(row.get("hook_point"), intro["problem"])
        problem = st.text_area("핵심 문제", value=default_problem, height=80)

    p1, p2 = st.columns(2)
    with p1:
        insight = select_with_custom("벤치마크에서 가져올 인사이트 / 전개 구조", INSIGHT_PRESETS, "insight_v2", "목적-타깃-메시지-CTA", height=90)
        proof = select_with_custom("근거 / 설명", PROOF_PRESETS, "proof_v2", "수정 리스크 감소", height=90)
    with p2:
        solution = select_with_custom("브랜드 관점의 해결 방식", SOLUTION_PRESETS, "solution_v2", "전환 구조 먼저 설계", height=90)
        offer = select_with_custom("서비스 / 제안 문장", OFFER_PRESETS, "offer_v2", "브랜드/제품/유튜브 통합", height=90)

    ctx = {
        "template": template,
        "tone": tone,
        "visual_style": visual_style,
        "auto_review": auto_review,
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
    signature = "|".join([str(int(row["id"])), template, tone, visual_style, str(auto_review), intro_label, intro["hook"], intro["body"], brand, target, cta, angle, problem, insight, solution, proof, offer])
    update_draft_state(plan, signature)

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("현재 선택값으로 초안 다시 생성"):
            update_draft_state(plan, signature, force=True)
            st.rerun()
    with col_info:
        st.info("서론 훅 관점을 바꾸면 1~3장 흐름이 함께 바뀝니다. 필요하면 하단에서 직접 다듬고 저장하세요.")

    st.markdown("---")
    draft = st.session_state.get("preset_v2_plan", plan)
    version = st.session_state.get("preset_v2_version", 0)
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
