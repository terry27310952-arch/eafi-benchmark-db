import json
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
CONTENT_GOALS = ["원본 내용 깊이 분석", "카드뉴스 원천 데이터화", "바이럴 후킹 추출", "교육형 요약", "이슈/트렌드 재가공"]
PLATFORM_FOCUS = ["인스타 카드뉴스", "유튜브 커뮤니티", "블로그", "쓰레드", "틱톡/숏폼", "범용"]
ANALYSIS_DEPTH = ["핵심만", "구조 분석", "세부 근거까지", "전환 관점", "후킹/바이럴 관점"]
IMAGE_RATIOS = ["1:1", "16:9", "9:16", "4:3"]
IMAGE_STYLES = [
    "깔끔한 인포그래픽",
    "실사 시네마틱",
    "3D 애니메이션",
    "2D 일러스트",
    "웹툰/만화형",
    "미니멀 타이포그래피",
    "뉴스 에디토리얼",
    "데이터 대시보드",
    "프리미엄 브랜드룩",
    "AI 혼합 콜라주",
]

CTA_PRESETS = {
    "저장 유도": "이 기준은 저장해두고 다시 확인해보세요",
    "댓글 유도": "여러분은 이 흐름을 어떻게 보고 계신가요? 댓글로 남겨주세요",
    "공유 유도": "이 주제가 필요한 분에게 공유해보세요",
    "팔로우 유도": "비슷한 분석을 계속 보고 싶다면 팔로우해두세요",
    "DM 문의": "이런 카드뉴스 제작이 필요하다면 DM으로 문의해주세요",
    "직접 입력": "",
}

ANGLE_PRESETS = {
    "자동 생성": "__AUTO__",
    "문제폭로형": "사람들이 놓치고 있는 문제를 먼저 드러내는 카드뉴스",
    "오해반박형": "흔히 믿는 착각을 반박하는 카드뉴스",
    "체크리스트형": "보기 전에 반드시 확인해야 할 기준을 정리하는 카드뉴스",
    "전후비교형": "Before와 After를 비교해 차이를 보여주는 카드뉴스",
    "바이럴 후킹형": "사람들이 멈춰서 볼 만한 질문으로 시작하는 카드뉴스",
    "직접 입력": "",
}

PROBLEM_PRESETS = {
    "자동 추출": "__AUTO__",
    "목적 불명확": "콘텐츠의 목적이 인지도, 신뢰, 문의 중 어디에 있는지 정리되지 않은 상태",
    "타깃 불명확": "누구에게 말하는 콘텐츠인지 흐려져 메시지와 장면 선택이 모두 애매해진 상태",
    "전환 경로 부재": "콘텐츠를 본 뒤 시청자가 무엇을 해야 하는지 명확하지 않은 상태",
    "정보 과잉": "정보는 많지만 무엇을 기준으로 판단해야 하는지 흐려진 상태",
    "실행 기준 부재": "좋은 말은 많지만 실제로 무엇부터 해야 하는지 정리되지 않은 상태",
    "레퍼런스 복붙": "겉모습은 따라 했지만 반응을 만든 구조는 읽지 못한 상태",
    "직접 입력": "",
}

TARGET_PRESETS = {
    "브랜드/마케팅 담당자": "영상 제작을 검토 중인 브랜드/마케팅 담당자",
    "스타트업 대표/팀장": "브랜드 신뢰도를 빠르게 쌓아야 하는 스타트업 대표/팀장",
    "제품 브랜드 담당자": "제품의 장점을 콘텐츠로 설득해야 하는 브랜드 담당자",
    "콘텐츠 제작자": "유튜브와 숏폼을 꾸준히 운영해야 하는 콘텐츠 제작자",
    "일반 시청자": "해당 주제에 관심 있는 일반 시청자",
    "투자/시장 관심층": "시장 흐름과 이슈를 빠르게 파악하려는 사람",
    "직접 입력": "",
}

VISUAL_STYLES = {
    "깔끔한 인포그래픽": "clean editorial infographic, organized icons, clear hierarchy, generous whitespace",
    "실사 시네마틱": "cinematic realistic photography, premium lighting, shallow depth of field, natural objects",
    "3D 애니메이션": "stylized 3D animation, soft lighting, polished commercial render, expressive composition",
    "2D 일러스트": "modern flat 2D illustration, clean shapes, balanced composition, editorial feel",
    "웹툰/만화형": "Korean webtoon inspired illustration, dynamic panels, expressive characters, clean linework",
    "미니멀 타이포그래피": "minimal typography poster style, strong layout, negative space, bold graphic rhythm",
    "뉴스 에디토리얼": "news editorial visual, headline layout, data panels, reportage mood",
    "데이터 대시보드": "data dashboard design, charts, UI cards, analytical visual system",
    "프리미엄 브랜드룩": "premium brand campaign visual, black and warm gray palette, elegant composition",
    "AI 혼합 콜라주": "AI mixed media collage, realistic elements with graphic overlays, modern editorial texture",
}

RATIO_PROMPTS = {
    "1:1": "square 1:1 composition",
    "16:9": "wide 16:9 horizontal composition",
    "9:16": "vertical 9:16 mobile story composition",
    "4:3": "classic 4:3 editorial composition",
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
    dfs = []
    try:
        refs = pd.read_sql_query("""
            SELECT r.id, 'content_reference' AS source_table, c.platform, c.channel_name, c.category, r.title, r.url,
                   r.hook_point, r.structure_note, r.visual_note, r.eafi_application,
                   r.total_score, r.status, r.created_at
            FROM content_references r
            LEFT JOIN benchmark_channels c ON r.channel_id = c.id
            ORDER BY r.id DESC
        """, conn)
        dfs.append(refs)
    except Exception:
        pass

    try:
        yt = pd.read_sql_query("""
            SELECT id, 'youtube_analysis' AS source_table, 'YouTube' AS platform, channel_name, '영상 분석' AS category,
                   title, url, hook_point, structure_note, visual_note, eafi_application,
                   20 AS total_score, '영상 분석' AS status, created_at,
                   summary, keywords, transcript
            FROM youtube_video_analyses
            ORDER BY id DESC
        """, conn)
        dfs.append(yt)
    except Exception:
        pass
    conn.close()

    if not dfs:
        return pd.DataFrame()
    df = pd.concat(dfs, ignore_index=True, sort=False)
    return df.sort_values("created_at", ascending=False, na_position="last")


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


def shorten(text, max_len=90):
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


def select_from_dict_like(label, options, key, default=None, height=80):
    labels = list(options.keys())
    index = labels.index(default) if default in labels else 0
    selected = st.selectbox(label, labels, index=index, key=f"{key}_select")
    if selected == "직접 입력":
        return st.text_area(f"{label} 직접 입력", height=height, key=f"{key}_custom"), selected
    return options[selected], selected


def analyze_source(row, selected_topic_type, context):
    title = strip_raw_labels(row.get("title"))
    hook = strip_raw_labels(row.get("hook_point"))
    structure = strip_raw_labels(row.get("structure_note"))
    application = strip_raw_labels(row.get("eafi_application"))
    summary = strip_raw_labels(row.get("summary"))
    keywords = strip_raw_labels(row.get("keywords"))
    transcript = strip_raw_labels(row.get("transcript"))
    source_text = " ".join([title, hook, structure, application, summary, keywords, transcript[:1200]])

    topic_type = detect_topic_type(source_text) if selected_topic_type == "자동 감지" else selected_topic_type
    topic = shorten(title or application or hook or "원본 주제", 54)

    if context["content_goal"] == "바이럴 후킹 추출":
        angle = f"{topic}이 사람들을 멈추게 만드는 이유"
    elif context["content_goal"] == "교육형 요약":
        angle = f"{topic}을 이해하기 전 알아야 할 기준"
    elif context["content_goal"] == "이슈/트렌드 재가공":
        angle = f"{topic}에서 지금 봐야 할 흐름"
    elif context["content_goal"] == "원본 내용 깊이 분석":
        angle = f"{topic}의 핵심을 깊게 보는 법"
    else:
        angle = f"{topic}에서 먼저 봐야 할 것"

    if topic_type == "시장/투자":
        claim = f"{topic}에 시장의 관심이 다시 모이는 흐름을 다룹니다"
        audience_problem = "많은 사람은 방향보다 가격만 먼저 보고, 왜 움직이는지에 대한 판단 기준을 놓치기 쉽습니다"
        checklist = ["왜 지금 관심이 모이는가", "실제로 바뀐 지표가 있는가", "기대감과 현실 사이의 간격은 어느 정도인가", "다음 판단 기준은 무엇인가"]
    elif topic_type == "브랜드/마케팅":
        claim = f"{topic}이 성과로 이어지는 구조를 다룹니다"
        audience_problem = "보기 좋은 결과물만 보다가 실제 행동으로 이어지는 흐름을 놓치기 쉽습니다"
        checklist = ["누구에게 말하는가", "무엇을 기억하게 할 것인가", "어떤 감정을 만들 것인가", "다음 행동은 무엇인가"]
    elif topic_type == "교육/노하우":
        claim = f"{topic}을 더 쉽게 이해하는 기준을 다룹니다"
        audience_problem = "방법은 많지만 무엇부터 봐야 하는지 정리되지 않아 실행이 어려워집니다"
        checklist = ["먼저 알아야 할 개념", "흔히 하는 착각", "실제로 적용할 순서", "마지막 체크포인트"]
    else:
        claim = f"{topic}에 대한 관심이 커지는 흐름을 다룹니다"
        audience_problem = "사람들은 결론만 먼저 보다가 왜 중요한지, 무엇을 확인해야 하는지 놓치기 쉽습니다"
        checklist = ["왜 관심이 커졌는가", "사람들이 놓치는 지점은 무엇인가", "진짜 봐야 할 기준은 무엇인가", "다음에 확인할 것은 무엇인가"]

    if context["analysis_depth"] == "세부 근거까지" and summary:
        claim = f"{claim}\n근거 요약: {shorten(summary, 160)}"
    if context["analysis_depth"] == "후킹/바이럴 관점":
        audience_problem = "사람들이 왜 멈춰서 보는지보다 제목과 결론만 따라가려는 상태"
    if context["target_audience"]:
        audience_problem = f"{context['target_audience']} 기준으로 보면, {audience_problem}"
    if context["emphasis"]:
        audience_problem += f" 특히 {context['emphasis']} 관점이 중요합니다."
    if context["avoid"]:
        audience_problem += f" 다만 {context['avoid']} 관점은 제외합니다."

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
        "keywords": keywords,
    }


def resolve_auto_angle(value, analysis):
    if value and value != "__AUTO__":
        return value
    return analysis["angle"]


def resolve_auto_problem(value, analysis):
    if value and value != "__AUTO__":
        return value
    return analysis["audience_problem"]


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
    ratio = RATIO_PROMPTS[ctx["image_ratio"]]
    style = VISUAL_STYLES[ctx["image_style"]]
    copy_rule = (
        "include short Korean headline text with safe margins"
        if ctx["include_image_copy"] else
        "clean image only, no text, no captions, no typography, no letters, no watermark, no logo"
    )

    if template == "체크리스트형":
        ideas = [
            f"{topic}를 상징하는 강한 첫 장. 큰 제목, 핵심 오브젝트, 짧은 경고성 분위기.",
            "체크리스트 1번을 보여주는 카드. 원인 또는 배경을 한눈에 보여주는 아이콘과 짧은 구조도.",
            "체크리스트 2번을 보여주는 카드. 수치, 지표, 비교 표식이 보이는 분석형 구성.",
            "체크리스트 3번을 보여주는 카드. 사람들이 흔히 놓치는 지점을 빨간 표시로 강조.",
            "체크리스트 4번을 보여주는 카드. 다음 행동 기준을 정리한 깔끔한 보드.",
            "저장/공유/댓글 행동을 유도하는 마무리 카드. 여백 중심의 깔끔한 CTA 구성.",
        ]
    else:
        ideas = [
            f"{topic}를 상징하는 첫 장. 뉴스 헤드라인, 데이터 패널, 주목받는 오브젝트를 강한 후킹 구도로 표현.",
            "원본 주제에 관심이 몰리는 흐름을 보여주는 장면. 검색량, 뉴스, 커뮤니티 반응이 정리된 느낌.",
            "독자가 놓치기 쉬운 문제를 시각화. 잘못된 판단과 올바른 판단 기준이 대비되는 인포그래픽.",
            "원인과 배경을 분석하는 장면. 흐름을 만든 이유가 3가지 가지로 나뉘어 보이는 보드.",
            "핵심 기준을 정리한 카드. 체크포인트, 판단 기준, 다음 확인 지점이 한눈에 보이게 구성.",
            "저장, 공유, 댓글 같은 행동을 유도하는 마무리 카드. CTA가 선명한 구성.",
        ]
    return [f"{ratio}, {style}. {idea} {copy_rule}" for idea in ideas]


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
            images.append(st.text_area("장별 이미지 방향", value=image, height=110, key=f"ot_image_{idx}_{suffix}"))

    edited = dict(plan)
    edited.update({"common_style": common_style, "title": title, "core_problem": core_problem, "main_message": main_message, "cta": cta, "slides": slides, "images": images})
    return edited


def main():
    st.set_page_config(page_title="원본 주제 카드뉴스", page_icon="📰", layout="wide")
    init_table()

    st.title("📰 원본 주제 카드뉴스")
    st.caption("YouTube 분석 데이터나 참고 콘텐츠를 카드뉴스로 재가공합니다. 이미지 비율, 스타일, 카피 포함 여부까지 여기서 설정합니다.")

    refs = load_references()
    if refs.empty:
        st.warning("먼저 YouTube 영상 내용 분석에서 분석 결과를 저장하세요.")
        return

    options = {f"{row['source_table']} · {row['id']} · {clean(row['title'])}": row for _, row in refs.iterrows()}
    selected_key = st.selectbox("원본 콘텐츠 선택", list(options.keys()))
    row = options[selected_key]

    st.markdown("---")
    st.markdown("### 콘텐츠 분석 조건")
    c1, c2, c3 = st.columns(3)
    with c1:
        topic_type_select = st.selectbox("주제 유형", TOPIC_TYPES, index=0)
        content_goal = st.selectbox("콘텐츠 목적", CONTENT_GOALS, index=1)
    with c2:
        template = st.selectbox("콘텐츠 구조", TEMPLATE_OPTIONS, index=0)
        platform_focus = st.selectbox("플랫폼/사용처", PLATFORM_FOCUS, index=0)
    with c3:
        tone = st.selectbox("후킹 강도", TONE_LEVELS, index=2)
        analysis_depth = st.selectbox("분석 깊이", ANALYSIS_DEPTH, index=1)

    c4, c5 = st.columns(2)
    with c4:
        target_value, target_label = select_from_dict_like("타깃 독자", TARGET_PRESETS, "ot_target", "일반 시청자")
        angle_value, angle_label = select_from_dict_like("카드뉴스 핵심 각도", ANGLE_PRESETS, "ot_angle", "자동 생성")
        problem_value, problem_label = select_from_dict_like("핵심 문제", PROBLEM_PRESETS, "ot_problem_preset", "자동 추출")
    with c5:
        emphasis = st.text_input("강조할 관점", placeholder="예: 전환 구조, 비용 누수, 판단 기준, 바이럴 후킹")
        avoid = st.text_input("제외할 관점", placeholder="예: 과한 투자 조언, 원문 그대로 요약, 브랜드명 과다 노출")
        cta, cta_label = select_from_dict_like("CTA", CTA_PRESETS, "ot_cta_preset", "저장 유도")

    st.markdown("### 이미지 생성 조건")
    i1, i2, i3 = st.columns(3)
    with i1:
        image_ratio = st.selectbox("이미지 비율", IMAGE_RATIOS, index=0)
    with i2:
        image_style = st.selectbox("이미지 스타일", IMAGE_STYLES, index=0)
    with i3:
        include_image_copy = st.checkbox("이미지 안에 카피/텍스트 넣기", value=True)
        st.caption("끄면 no text / no captions / no watermark 조건이 들어갑니다.")

    base_context = {
        "content_goal": content_goal,
        "platform_focus": platform_focus,
        "analysis_depth": analysis_depth,
        "target_audience": target_value,
        "emphasis": emphasis,
        "avoid": avoid,
    }
    analysis = analyze_source(row, topic_type_select, base_context)
    if topic_type_select == "직접 입력":
        analysis["topic_type"] = st.text_input("주제 유형 직접 입력", value="사용자 정의")

    angle = resolve_auto_angle(angle_value, analysis)
    problem = resolve_auto_problem(problem_value, analysis)
    common_style = f"{RATIO_PROMPTS[image_ratio]}, {VISUAL_STYLES[image_style]}. 플랫폼: {platform_focus}."
    if include_image_copy:
        common_style += " 이미지 안에 짧은 한글 헤드라인을 넣을 수 있음. 안전 여백 확보."
    else:
        common_style += " clean image only, no text, no captions, no typography, no letters, no watermark, no logo."

    with st.expander("원본 분석 결과", expanded=True):
        st.write(f"**감지된 주제 유형:** {analysis['topic_type']}")
        st.write(f"**원본 주제:** {analysis['topic']}")
        st.write(f"**핵심 주장:** {analysis['claim']}")
        st.write(f"**독자 문제:** {analysis['audience_problem']}")
        st.write(f"**차용할 전개 구조:** {analysis['structure']}")
        if analysis.get("keywords"):
            st.write(f"**키워드:** {analysis['keywords']}")

    ctx = {
        "analysis": analysis,
        "template": template,
        "tone": tone,
        "topic_type": analysis["topic_type"],
        "angle": angle,
        "problem": problem,
        "cta": cta,
        "common_style": common_style,
        "image_ratio": image_ratio,
        "image_style": image_style,
        "include_image_copy": include_image_copy,
    }
    plan = build_plan(ctx)

    signature = "|".join([
        str(int(row["id"])), clean(row.get("source_table")), analysis["topic_type"], content_goal, platform_focus,
        analysis_depth, template, tone, target_label, angle_label, problem_label, image_ratio, image_style,
        str(include_image_copy), angle, problem, cta, emphasis, avoid,
    ])
    update_state(plan, signature)

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("현재 선택값으로 초안 다시 생성"):
            update_state(plan, signature, force=True)
            st.rerun()
    with col_info:
        st.info("카드뉴스 제작 조건은 이 메뉴에서 설정합니다. YouTube 분석 메뉴는 원문 수집/분석 저장만 담당합니다.")

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


if __name__ == "__main__":
    main()
