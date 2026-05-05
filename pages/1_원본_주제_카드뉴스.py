import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")

TEMPLATE_OPTIONS = ["자동 최적화", "문제 제기형", "체크리스트형", "전후 비교형", "교육형", "트렌드 분석형"]
TONE_LEVELS = ["담백", "명확", "강한 후킹", "자극적"]
TOPIC_TYPES = ["자동 감지", "사건/논쟁", "시장/투자", "트렌드/이슈", "브랜드/마케팅", "라이프스타일", "교육/노하우", "기술/AI", "직접 입력"]
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
    "댓글 유도": "여러분은 이 이야기를 어떻게 보시나요? 댓글로 남겨주세요",
    "공유 유도": "이 이야기가 필요한 분에게 공유해보세요",
    "팔로우 유도": "비슷한 분석을 계속 보고 싶다면 팔로우해두세요",
    "DM 문의": "이런 카드뉴스 제작이 필요하다면 DM으로 문의해주세요",
    "직접 입력": "",
}

ANGLE_PRESETS = {
    "자동 생성": "__AUTO__",
    "사건의 뒷면": "겉으로 알려진 결과 뒤에 숨은 갈등을 보여주는 카드뉴스",
    "문제폭로형": "사람들이 놓치고 있는 문제를 먼저 드러내는 카드뉴스",
    "오해반박형": "흔히 믿는 착각을 반박하는 카드뉴스",
    "체크리스트형": "보기 전에 반드시 확인해야 할 기준을 정리하는 카드뉴스",
    "전후비교형": "Before와 After를 비교해 차이를 보여주는 카드뉴스",
    "바이럴 후킹형": "사람들이 멈춰서 볼 만한 질문으로 시작하는 카드뉴스",
    "직접 입력": "",
}

PROBLEM_PRESETS = {
    "자동 추출": "__AUTO__",
    "숨은 갈등": "겉으로 보이는 결과만 보고 그 뒤에 있는 갈등과 이해관계를 놓치는 상태",
    "목적 불명확": "콘텐츠의 목적이 인지도, 신뢰, 문의 중 어디에 있는지 정리되지 않은 상태",
    "타깃 불명확": "누구에게 말하는 콘텐츠인지 흐려져 메시지와 장면 선택이 모두 애매해진 상태",
    "전환 경로 부재": "콘텐츠를 본 뒤 시청자가 무엇을 해야 하는지 명확하지 않은 상태",
    "정보 과잉": "정보는 많지만 무엇을 기준으로 판단해야 하는지 흐려진 상태",
    "실행 기준 부재": "좋은 말은 많지만 실제로 무엇부터 해야 하는지 정리되지 않은 상태",
    "레퍼런스 복붙": "겉모습은 따라 했지만 반응을 만든 구조는 읽지 못한 상태",
    "직접 입력": "",
}

TARGET_PRESETS = {
    "일반 시청자": "해당 주제에 관심 있는 일반 시청자",
    "브랜드/마케팅 담당자": "영상 제작을 검토 중인 브랜드/마케팅 담당자",
    "스타트업 대표/팀장": "브랜드 신뢰도를 빠르게 쌓아야 하는 스타트업 대표/팀장",
    "제품 브랜드 담당자": "제품의 장점을 콘텐츠로 설득해야 하는 브랜드 담당자",
    "콘텐츠 제작자": "유튜브와 숏폼을 꾸준히 운영해야 하는 콘텐츠 제작자",
    "투자/시장 관심층": "시장 흐름과 이슈를 빠르게 파악하려는 사람",
    "직접 입력": "",
}

VISUAL_STYLES = {
    "깔끔한 인포그래픽": "clean editorial infographic, organized icons, clear hierarchy, generous whitespace",
    "실사 시네마틱": "cinematic realistic photography, premium lighting, natural texture, documentary mood",
    "3D 애니메이션": "stylized 3D animation, soft lighting, polished commercial render, expressive composition",
    "2D 일러스트": "modern flat 2D illustration, clean shapes, balanced editorial composition",
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

BAD_TOPIC_FRAGMENTS = [
    "원본 해석 데이터",
    "원본 주제 카드뉴스",
    "카드뉴스 메뉴",
    "직접 입력한 영상 스크립트",
    "youtube 영상",
    "untitled",
    "manual input",
]

TEMPLATE_LEAKS = [
    "관심이 커지는 흐름을 다룹니다",
    "지금 봐야 할 건 따로 있습니다",
    "카드뉴스",
    "원본 해석 데이터를 바탕으로",
    "해당 주제에 관심 있는 일반 시청자 기준으로 보면",
]


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


def clean(value, fallback=""):
    if value is None:
        return fallback
    text = str(value).strip()
    if text.lower() in ["nan", "none", "null"]:
        return fallback
    return text or fallback


def strip_meta(text):
    text = clean(text)
    text = re.sub(r"(?im)^\s*(title|url|source|link|영상 제목|제목)\s*[:：]\s*", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\[[sS]?\d+\]", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def strip_citations(text):
    return re.sub(r"\s*\[[sS]?\d+\]", "", clean(text)).strip()


def shorten(text, max_len=90):
    text = strip_meta(text)
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def compact_lines(text):
    return "\n".join([line.strip() for line in clean(text).splitlines() if line.strip()])


def safe_json(value, fallback=None):
    if fallback is None:
        fallback = []
    if value is None:
        return fallback
    if isinstance(value, (list, dict)):
        return value
    text = clean(value)
    if not text:
        return fallback
    try:
        return json.loads(text)
    except Exception:
        return fallback


def get_value(row, key, default=""):
    try:
        value = row.get(key, default)
    except Exception:
        try:
            value = row[key]
        except Exception:
            value = default
    return clean(value, default)


def topic_is_bad(topic):
    t = clean(topic).lower()
    if not t:
        return True
    if any(fragment.lower() in t for fragment in BAD_TOPIC_FRAGMENTS):
        return True
    if t.count(",") >= 4 and "사건" not in t and "갈등" not in t:
        return True
    if len(t) < 4:
        return True
    return False


def extract_embedded_title(*texts):
    for text in texts:
        raw = clean(text)
        match = re.search(r"Title\s*[:：]\s*[\"“']?(.{8,120}?)[\"”']?(?:\n|$)", raw, flags=re.I)
        if match:
            title = strip_meta(match.group(1))
            if title:
                return title
    return ""


def remove_template_leaks(text):
    text = clean(text)
    for leak in TEMPLATE_LEAKS:
        text = text.replace(leak, "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def polish(text, tone="명확"):
    text = compact_lines(text)
    replacements = {
        "핵심 문제": "문제의 핵심",
        "진짜": "정말",
        "없으면": "없다면",
        "합니다입니다": "합니다",
        "쉽습니다입니다": "쉽습니다",
        "중요합니다입니다": "중요합니다",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    text = remove_template_leaks(text)
    if tone == "담백":
        text = text.replace("놓치면 안 됩니다", "확인해볼 필요가 있습니다")
    elif tone == "자극적":
        text = text.replace("봐야 합니다", "놓치면 안 됩니다")
        text = text.replace("확인해야 합니다", "반드시 확인해야 합니다")
    return text.strip()


def select_from_dict_like(label, options, key, default=None, height=80):
    labels = list(options.keys())
    index = labels.index(default) if default in labels else 0
    selected = st.selectbox(label, labels, index=index, key=f"{key}_select")
    if selected == "직접 입력":
        return st.text_area(f"{label} 직접 입력", height=height, key=f"{key}_custom"), selected
    return options[selected], selected


def detect_topic_type(text):
    t = clean(text).lower()
    if any(w in t for w in ["노조", "회사", "직원", "시민", "공장", "사건", "갈등", "반발", "요구", "법정", "기증", "주차장"]):
        return "사건/논쟁"
    if any(w in t for w in ["2차전지", "배터리", "전기차", "코인", "비트코인", "주식", "시장", "투자", "가격", "섹터"]):
        return "시장/투자"
    if any(w in t for w in ["브랜드", "마케팅", "광고", "콘텐츠", "유튜브", "영상", "제작"]):
        return "브랜드/마케팅"
    if any(w in t for w in ["방법", "노하우", "강의", "배우", "체크리스트"]):
        return "교육/노하우"
    if any(w in t for w in ["ai", "인공지능", "기술", "개발", "앱", "툴"]):
        return "기술/AI"
    return "트렌드/이슈"


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
        yt = pd.read_sql_query("SELECT * FROM youtube_video_analyses ORDER BY id DESC", conn)
        if not yt.empty:
            yt["source_table"] = "youtube_analysis"
            yt["platform"] = "YouTube"
            yt["category"] = yt.get("source_kind", "영상 분석")
            yt["total_score"] = 20
            yt["status"] = "원본 해석"
            dfs.append(yt)
    except Exception:
        pass

    conn.close()

    if not dfs:
        return pd.DataFrame()
    df = pd.concat(dfs, ignore_index=True, sort=False)
    for col in [
        "source_kind", "original_topic", "primary_claim", "actor_map", "event_timeline", "cardnews_seed",
        "contradiction_or_tension", "hidden_assumption", "emotional_trigger", "viral_hook_logic",
        "reusable_structure", "source_grounded_qa", "evidence_points", "cause_effect_chain", "audience_pain",
        "keywords", "summary", "transcript", "interpretation_report"
    ]:
        if col not in df.columns:
            df[col] = ""
    return df.sort_values("created_at", ascending=False, na_position="last")


def load_plans():
    conn = connect_db()
    df = pd.read_sql_query("SELECT * FROM cardnews_plans ORDER BY id DESC LIMIT 50", conn)
    conn.close()
    return df


def resolve_topic(row, seed):
    title = get_value(row, "title")
    summary = get_value(row, "summary")
    transcript = get_value(row, "transcript")
    original_topic = get_value(row, "original_topic")
    embedded_title = extract_embedded_title(summary, transcript)

    candidates = []
    if original_topic:
        candidates.append(original_topic)
    if embedded_title:
        candidates.append(embedded_title)
    if title and not topic_is_bad(title):
        candidates.append(title)

    if isinstance(seed, dict):
        angles = seed.get("angle_candidates") or []
        for angle in angles:
            if angle:
                cleaned = re.sub(r"(뒤에 숨은.*|에서 사람들이.*|을 보기 전에.*|이 반응을.*)", "", strip_citations(angle)).strip()
                if cleaned:
                    candidates.append(cleaned)

    keywords = get_value(row, "keywords")
    if keywords:
        keys = [k.strip() for k in keywords.split(",") if len(k.strip()) > 1]
        if keys:
            candidates.append(f"{', '.join(keys[:3])}을 둘러싼 이야기")

    for candidate in candidates:
        candidate = strip_citations(candidate)
        if not topic_is_bad(candidate):
            return shorten(candidate, 80)
    return "원본에 숨은 이야기"


def flatten_event_text(item):
    if isinstance(item, dict):
        return strip_citations(item.get("event") or item.get("source") or item.get("text") or "")
    return strip_citations(item)


def actor_names(actor_map):
    names = []
    if isinstance(actor_map, list):
        for item in actor_map:
            if isinstance(item, dict):
                name = clean(item.get("actor"))
                if name and name not in names:
                    names.append(name)
    return names[:5]


def analyze_source(row, selected_topic_type, context):
    seed = safe_json(get_value(row, "cardnews_seed"), {})
    actor_map = safe_json(get_value(row, "actor_map"), [])
    timeline = safe_json(get_value(row, "event_timeline"), [])
    evidence = safe_json(get_value(row, "evidence_points"), [])
    cause_chain = safe_json(get_value(row, "cause_effect_chain"), [])
    qa = safe_json(get_value(row, "source_grounded_qa"), [])

    raw_text = " ".join([
        get_value(row, "title"), get_value(row, "original_topic"), get_value(row, "primary_claim"),
        get_value(row, "summary"), get_value(row, "keywords"), get_value(row, "structure_note"),
        get_value(row, "transcript")[:1600]
    ])

    source_kind = get_value(row, "source_kind") or ""
    if not source_kind:
        detected = detect_topic_type(raw_text)
        source_kind = "사건형" if detected == "사건/논쟁" else "이슈해설형"

    topic_type = detect_topic_type(raw_text) if selected_topic_type == "자동 감지" else selected_topic_type
    topic = resolve_topic(row, seed)

    primary_claim = get_value(row, "primary_claim") or get_value(row, "key_claim") or get_value(row, "hook_point")
    primary_claim = strip_citations(primary_claim)
    if not primary_claim or topic_is_bad(primary_claim):
        if evidence:
            primary_claim = flatten_event_text(evidence[0])
        elif timeline:
            primary_claim = flatten_event_text(timeline[0])
        else:
            primary_claim = f"{topic}은 겉으로 보이는 결과만으로 설명하기 어려운 이야기입니다"

    audience_pain = strip_citations(get_value(row, "audience_pain"))
    conflict = strip_citations(get_value(row, "contradiction_or_tension"))
    hidden = strip_citations(get_value(row, "hidden_assumption"))
    emotion = strip_citations(get_value(row, "emotional_trigger"))
    viral = strip_citations(get_value(row, "viral_hook_logic"))
    reusable = strip_citations(get_value(row, "reusable_structure"))

    if not audience_pain:
        if source_kind == "사건형":
            audience_pain = "사람들은 결과만 먼저 보지만, 그 뒤에 얽힌 주체와 갈등의 흐름은 놓치기 쉽습니다"
        else:
            audience_pain = "사람들은 결론만 먼저 보다가 왜 중요한지와 무엇을 확인해야 하는지를 놓치기 쉽습니다"
    if not conflict:
        conflict = "겉으로 보이는 결과와 그 뒤에 숨은 이해관계가 충돌하는 구조"
    if not hidden:
        hidden = "겉으로 좋아 보이는 결과라면 과정도 순탄했을 것이라는 착각"
    if not emotion:
        emotion = "몰랐던 뒷이야기를 알게 되는 반전감과 다시 판단하고 싶은 궁금증"
    if not viral:
        viral = "겉으로 알려진 결과를 먼저 보여준 뒤, 뒤에 숨어 있던 갈등을 꺼내는 반전형 후킹"
    if not reusable:
        reusable = "결과를 먼저 보여주고, 숨은 배경과 이해관계를 드러낸 뒤, 마지막에 독자가 다시 생각할 질문으로 닫는 구조"

    if context.get("content_goal") == "바이럴 후킹 추출":
        angle = f"{topic}이 사람들을 멈추게 만드는 이유"
    elif source_kind == "사건형":
        angle = f"{topic} 뒤에 숨은 갈등"
    elif context.get("content_goal") == "교육형 요약":
        angle = f"{topic}을 이해하기 전 알아야 할 기준"
    else:
        angle = f"{topic}에서 먼저 봐야 할 것"

    if isinstance(seed, dict) and seed.get("angle_candidates"):
        first_angle = strip_citations(seed["angle_candidates"][0])
        if first_angle and not topic_is_bad(first_angle):
            angle = first_angle

    return {
        "source_table": get_value(row, "source_table"),
        "source_kind": source_kind,
        "topic_type": topic_type,
        "topic": topic,
        "angle": angle,
        "primary_claim": primary_claim,
        "claim": primary_claim,
        "audience_problem": audience_pain,
        "conflict": conflict,
        "hidden_assumption": hidden,
        "emotional_trigger": emotion,
        "viral_hook_logic": viral,
        "reusable_structure": reusable,
        "actor_map": actor_map,
        "actor_names": actor_names(actor_map),
        "event_timeline": timeline,
        "evidence_points": evidence,
        "cause_effect_chain": cause_chain,
        "source_grounded_qa": qa,
        "cardnews_seed": seed,
        "keywords": get_value(row, "keywords"),
    }


def resolve_auto_angle(value, analysis):
    if value and value != "__AUTO__":
        # 내부 옵션 설명문은 그대로 카피에 쓰지 않고 방향성만 참고한다.
        if "카드뉴스" in value:
            if analysis["source_kind"] == "사건형":
                return f"{analysis['topic']} 뒤에 숨은 이야기"
            return analysis["angle"]
        return value
    return analysis["angle"]


def resolve_auto_problem(value, analysis):
    if value and value != "__AUTO__":
        if "카드뉴스" in value:
            return analysis["audience_problem"]
        return value
    return analysis["audience_problem"]


def timeline_text(timeline, index, fallback):
    if isinstance(timeline, list) and len(timeline) > index:
        value = flatten_event_text(timeline[index])
        if value:
            return shorten(value, 96)
    return fallback


def evidence_text(evidence, index, fallback):
    if isinstance(evidence, list) and len(evidence) > index:
        value = flatten_event_text(evidence[index])
        if value:
            return shorten(value, 96)
    return fallback


def build_event_plan(ctx):
    a = ctx["analysis"]
    tone = ctx["tone"]
    cta = ctx["cta"]
    topic = a["topic"]
    actors = a["actor_names"] or ["회사", "직원", "시민"]
    actor_line = ", ".join(actors[:4])

    first_event = timeline_text(a["event_timeline"], 0, "처음엔 평범한 이야기처럼 보였습니다")
    second_event = timeline_text(a["event_timeline"], 1, a["primary_claim"])
    evidence = evidence_text(a["evidence_points"], 0, a["primary_claim"])

    slides = [
        f"{shorten(topic, 28)}\n그 뒤에는 다른 이야기가 있었습니다",
        f"겉으로 보이는 건 결과입니다\n{first_event}",
        f"하지만 이 이야기엔\n{actor_line}가 얽혀 있었습니다",
        f"갈등은 여기서 시작됩니다\n{shorten(a['conflict'], 90)}",
        f"사람들이 놓치기 쉬운 건\n{shorten(a['hidden_assumption'], 90)}",
        f"이 이야기를 어떻게 보시나요?\n{cta}",
    ]

    if ctx["template"] == "전후 비교형":
        slides = [
            f"같은 사건도\n보는 위치에 따라 달라집니다",
            f"겉으로는\n{shorten(first_event, 86)}",
            f"안쪽으로 들어가면\n{shorten(second_event, 86)}",
            f"여기엔\n{actor_line}의 이해관계가 겹쳐 있습니다",
            f"결국 남는 질문은 이것입니다\n{shorten(a['conflict'], 86)}",
            f"당신은 이 결말을\n어떻게 보시나요?\n{cta}",
        ]
    elif ctx["template"] == "체크리스트형":
        slides = [
            f"{shorten(topic, 26)}\n보기 전에 확인할 4가지",
            f"1. 결과만 보고 있지 않은가\n{shorten(first_event, 72)}",
            f"2. 누가 얽혀 있는가\n{actor_line}",
            f"3. 갈등의 축은 무엇인가\n{shorten(a['conflict'], 76)}",
            f"4. 어떤 전제가 숨어 있는가\n{shorten(a['hidden_assumption'], 76)}",
            f"미담과 갈등은\n같은 장면에 남을 수 있습니다\n{cta}",
        ]
    elif ctx["template"] == "교육형":
        slides = [
            f"이 사건은\n결과보다 구조를 봐야 합니다",
            f"첫 번째\n{shorten(first_event, 86)}",
            f"두 번째\n{shorten(evidence, 86)}",
            f"세 번째\n{shorten(a['conflict'], 86)}",
            f"그래서 핵심은\n{shorten(a['reusable_structure'], 86)}",
            f"이 기준으로 보면\n사건이 다르게 보입니다\n{cta}",
        ]

    directions = [
        "평화로운 현재의 결과와 그 뒤에 숨은 과거의 그림자를 동시에 보여주는 첫 장. 밝은 공간 위에 희미한 갈등의 흔적을 겹쳐 배치.",
        "겉으로 알려진 결과를 설명하는 장면. 공원, 건물, 뉴스 헤드라인, 오래된 자료 사진 느낌을 조합.",
        f"등장 주체를 한눈에 보여주는 관계도. {actor_line}가 서로 다른 위치에 놓이고, 선으로 이해관계가 연결되는 구성.",
        "갈등의 축을 시각화한 장면. 한쪽은 공익 또는 결과, 다른 한쪽은 생존권/이해관계/불안을 상징하도록 대비.",
        "아이러니를 보여주는 장면. 같은 장소를 바라보는 두 시선이 좌우로 갈라져 보이게 구성.",
        "마지막 질문형 카드. 차분한 배경 위에 독자가 다시 생각하게 만드는 여백 중심의 마무리 장면.",
    ]
    prompts = build_prompts(ctx, directions, slides)

    return finalize_plan(ctx, f"[사건형] {shorten(topic, 44)}", a["audience_problem"], slides, directions, prompts)


def build_generic_plan(ctx):
    a = ctx["analysis"]
    template = ctx["template"]
    cta = ctx["cta"]
    topic = a["topic"]
    angle = ctx["angle"] or a["angle"]
    problem = ctx["problem"] or a["audience_problem"]

    if template == "체크리스트형":
        slides = [
            f"{shorten(topic, 28)}\n보기 전에 확인할 4가지",
            f"1. 왜 지금 중요한가\n{shorten(a['primary_claim'], 74)}",
            f"2. 사람들이 놓친 건 무엇인가\n{shorten(problem, 74)}",
            f"3. 어떤 기준으로 봐야 하는가\n{shorten(a['reusable_structure'], 74)}",
            f"4. 어떤 리스크를 봐야 하는가\n{shorten(a['hidden_assumption'], 74)}",
            f"이 기준은 저장해두고\n다시 확인해보세요\n{cta}",
        ]
    elif template == "전후 비교형":
        slides = [
            f"{shorten(topic, 28)}\n반응이 갈리는 이유",
            "Before\n결론부터 보고 따라가는 상태",
            f"After\n{shorten(a['reusable_structure'], 76)}",
            f"차이는 여기서 납니다\n{shorten(problem, 82)}",
            f"핵심은\n{shorten(a['primary_claim'], 82)}",
            f"이 흐름이 중요하다고 느꼈다면\n{cta}",
        ]
    elif template == "교육형":
        slides = [
            f"{shorten(topic, 28)}\n이 기준부터 보면 쉽습니다",
            f"먼저 봐야 할 건\n{shorten(a['primary_claim'], 86)}",
            f"사람들이 놓치는 건\n{shorten(problem, 86)}",
            f"다음으로 볼 건\n{shorten(a['conflict'], 86)}",
            f"정리하면\n{shorten(a['reusable_structure'], 86)}",
            f"이 기준은 저장해두고\n다시 확인해보세요\n{cta}",
        ]
    else:
        slides = [
            f"{shorten(angle, 30)}",
            f"핵심은 이것입니다\n{shorten(a['primary_claim'], 92)}",
            f"문제는\n{shorten(problem, 92)}",
            f"놓치면 안 되는 기준은\n{shorten(a['conflict'], 92)}",
            f"재사용할 수 있는 구조는\n{shorten(a['reusable_structure'], 92)}",
            f"이 기준이 필요했다면\n{cta}",
        ]

    directions = [
        "원본 주제를 상징하는 첫 장. 큰 오브젝트와 짧은 문장으로 초반 주목도를 만드는 구성.",
        "핵심 주장을 보여주는 장면. 중심 메시지와 관련 이미지가 명확히 연결되게 구성.",
        "독자가 놓치기 쉬운 문제를 시각화. 잘못된 판단과 올바른 판단 기준을 대비.",
        "핵심 기준을 분석하는 장면. 원인, 배경, 판단 포인트를 3갈래로 정리한 보드.",
        "재사용 가능한 구조를 보여주는 카드. 체크포인트와 흐름도가 한눈에 보이게 구성.",
        "저장, 공유, 댓글 같은 행동을 유도하는 마무리 카드. CTA가 선명한 여백 중심 구성.",
    ]
    prompts = build_prompts(ctx, directions, slides)

    return finalize_plan(ctx, f"[원본 주제] {shorten(angle, 44)}", problem, slides, directions, prompts)


def build_prompts(ctx, directions, slides):
    ratio = RATIO_PROMPTS[ctx["image_ratio"]]
    style = VISUAL_STYLES[ctx["image_style"]]
    copy_rule = (
        "include a short Korean headline, safe margins, clean readable text"
        if ctx["include_image_copy"] else
        "clean image only, no text, no captions, no typography, no letters, no watermark, no logo"
    )
    prompts = []
    for idx, direction in enumerate(directions, start=1):
        copy_hint = shorten(slides[idx - 1].replace("\n", " / "), 80)
        prompts.append(f"{ratio}, {style}. {direction} Copy intent: {copy_hint}. {copy_rule}")
    return prompts


def finalize_plan(ctx, title, main_message, slides, directions, prompts):
    tone = ctx["tone"]
    slides = [polish(slide, tone) for slide in slides]
    return {
        "title": polish(title, tone),
        "target_customer": ctx["topic_type"],
        "core_problem": polish(ctx.get("problem") or main_message, tone),
        "main_message": polish(main_message, tone),
        "cta": polish(ctx["cta"], tone),
        "common_style": ctx["common_style"],
        "slides": slides,
        "directions": directions,
        "prompts": prompts,
        "images": [f"장면 방향:\n{directions[i]}\n\n이미지 생성 프롬프트:\n{prompts[i]}" for i in range(6)],
    }


def build_plan(ctx):
    if ctx["analysis"]["source_kind"] == "사건형":
        return build_event_plan(ctx)
    return build_generic_plan(ctx)


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
    slides, directions, prompts = [], [], []
    for idx in range(6):
        with st.container(border=True):
            st.markdown(f"#### {idx + 1}장")
            slides.append(st.text_area("카피", value=plan["slides"][idx], height=110, key=f"ot_slide_{idx}_{suffix}"))
            directions.append(st.text_area("장면 방향", value=plan["directions"][idx], height=90, key=f"ot_direction_{idx}_{suffix}"))
            prompts.append(st.text_area("이미지 생성 프롬프트", value=plan["prompts"][idx], height=120, key=f"ot_prompt_{idx}_{suffix}"))

    edited = dict(plan)
    edited.update({
        "common_style": common_style,
        "title": title,
        "core_problem": core_problem,
        "main_message": main_message,
        "cta": cta,
        "slides": slides,
        "directions": directions,
        "prompts": prompts,
        "images": [f"장면 방향:\n{directions[i]}\n\n이미지 생성 프롬프트:\n{prompts[i]}" for i in range(6)],
    })
    return edited


def main():
    st.set_page_config(page_title="원본 주제 카드뉴스", page_icon="📰", layout="wide")
    init_table()

    st.title("📰 원본 주제 카드뉴스")
    st.caption("YouTube 원본 해석 데이터를 받아 카드뉴스로 조립합니다. 사건형은 사건 구조 전용 빌더로 생성합니다.")

    refs = load_references()
    if refs.empty:
        st.warning("먼저 YouTube 영상 내용 분석에서 원본 해석 결과를 저장하세요.")
        return

    options = {f"{get_value(row, 'source_table')} · {row['id']} · {get_value(row, 'original_topic') or get_value(row, 'title')}": row for _, row in refs.iterrows()}
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
        emphasis = st.text_input("강조할 관점", placeholder="예: 사건의 아이러니, 갈등 축, 독자가 놓친 사실, 후킹 방식")
        avoid = st.text_input("제외할 관점", placeholder="예: 과한 투자 조언, 원문 밖 단정, 브랜드명 과다 노출")
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

    if template == "자동 최적화":
        effective_template = "문제 제기형" if analysis["source_kind"] == "사건형" else "체크리스트형"
    else:
        effective_template = template

    angle = resolve_auto_angle(angle_value, analysis)
    problem = resolve_auto_problem(problem_value, analysis)

    common_style = f"비율: {image_ratio} / 스타일: {image_style} / 사용처: {platform_focus}."
    if include_image_copy:
        common_style += " 이미지 안에 짧은 한글 헤드라인 포함 가능. 안전 여백 확보."
    else:
        common_style += " 텍스트 없는 클린 이미지. no text, no captions, no typography, no letters, no watermark, no logo."

    with st.expander("원본 분석 결과", expanded=True):
        st.write(f"**감지된 주제 유형:** {analysis['topic_type']}")
        st.write(f"**원본 유형:** {analysis['source_kind']}")
        st.write(f"**원본 주제:** {analysis['topic']}")
        st.write(f"**핵심 주장:** {analysis['primary_claim']}")
        st.write(f"**독자 문제:** {analysis['audience_problem']}")
        st.write(f"**갈등/긴장 구조:** {analysis['conflict']}")
        st.write(f"**차용할 전개 구조:** {analysis['reusable_structure']}")
        if analysis.get("actor_names"):
            st.write(f"**등장 주체:** {', '.join(analysis['actor_names'])}")
        if analysis.get("keywords"):
            st.write(f"**키워드:** {analysis['keywords']}")

    ctx = {
        "analysis": analysis,
        "template": effective_template,
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
        str(int(row["id"])), get_value(row, "source_table"), analysis["topic"], analysis["source_kind"],
        analysis["topic_type"], content_goal, platform_focus, analysis_depth, effective_template, tone,
        target_label, angle_label, problem_label, image_ratio, image_style, str(include_image_copy),
        angle, problem, cta, emphasis, avoid,
    ])
    update_state(plan, signature)

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("현재 선택값으로 초안 다시 생성"):
            update_state(plan, signature, force=True)
            st.rerun()
    with col_info:
        st.info("YouTube 원본 해석기의 source_kind, event_timeline, actor_map, cardnews_seed를 우선 사용합니다. 이미지 방향과 생성 프롬프트는 분리해 표시합니다.")

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
