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
IMAGE_STYLES = ["깔끔한 인포그래픽", "실사 시네마틱", "3D 애니메이션", "2D 일러스트", "웹툰/만화형", "미니멀 타이포그래피", "뉴스 에디토리얼", "데이터 대시보드", "프리미엄 브랜드룩", "AI 혼합 콜라주"]

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
    "사건의 뒷면": "사건의 뒷면",
    "문제폭로형": "문제폭로형",
    "오해반박형": "오해반박형",
    "체크리스트형": "체크리스트형",
    "전후비교형": "전후비교형",
    "바이럴 후킹형": "바이럴 후킹형",
    "직접 입력": "",
}

PROBLEM_PRESETS = {
    "자동 추출": "__AUTO__",
    "숨은 갈등": "겉으로 보이는 결과만 보고 그 뒤에 있는 갈등과 이해관계를 놓치는 상태",
    "목적 불명확": "콘텐츠의 목적이 인지도, 신뢰, 문의 중 어디에 있는지 정리되지 않은 상태",
    "정보 과잉": "정보는 많지만 무엇을 기준으로 판단해야 하는지 흐려진 상태",
    "직접 입력": "",
}

TARGET_PRESETS = {
    "일반 시청자": "해당 주제에 관심 있는 일반 시청자",
    "브랜드/마케팅 담당자": "영상 제작을 검토 중인 브랜드/마케팅 담당자",
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

RATIO_PROMPTS = {"1:1": "square 1:1 composition", "16:9": "wide 16:9 horizontal composition", "9:16": "vertical 9:16 mobile story composition", "4:3": "classic 4:3 editorial composition"}
COPY_LEAKS = ["첫 번째 단서", "결론만 보면", "과정이 중요한 이야기입니다", "겉으로 보이는 결과", "사람들이 놓치기 쉬운 건"]


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
        return clean(row.get(key, default), default)
    except Exception:
        try:
            return clean(row[key], default)
        except Exception:
            return default


def strip_meta(text):
    text = clean(text)
    text = re.sub(r"(?im)^\s*(title|url|source|link|영상 제목|제목)\s*[:：]\s*", "", text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\[[sS]?\d+\]", "", text)
    text = re.sub(r"[\"“”']", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def shorten(text, max_len=95):
    text = strip_meta(text)
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def compact_lines(text):
    return "\n".join([line.strip() for line in clean(text).splitlines() if line.strip()])


def normalize_sentence(text):
    text = strip_meta(text)
    text = re.sub(r"^[\-•\d\.\s]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def split_source_sentences(text):
    text = strip_meta(text)
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=다)\s+|(?<=요)\s+|(?<=죠)\s+", text)
    return [normalize_sentence(p) for p in parts if len(normalize_sentence(p)) > 12]


def has_any(text, words):
    return any(word in clean(text) for word in words)


def polish(text, tone="명확"):
    text = compact_lines(text)
    replacements = {"합니다입니다": "합니다", "쉽습니다입니다": "쉽습니다", "중요합니다입니다": "중요합니다", "진짜": "정말", "없으면": "없다면"}
    for old, new in replacements.items():
        text = text.replace(old, new)
    if tone == "담백":
        text = text.replace("놓치면 안 됩니다", "확인해볼 필요가 있습니다")
    elif tone == "자극적":
        text = text.replace("봐야 합니다", "놓치면 안 됩니다")
    return text.strip()


def select_from_dict_like(label, options, key, default=None, height=80):
    labels = list(options.keys())
    index = labels.index(default) if default in labels else 0
    selected = st.selectbox(label, labels, index=index, key=f"{key}_select")
    if selected == "직접 입력":
        return st.text_area(f"{label} 직접 입력", height=height, key=f"{key}_custom"), selected
    return options[selected], selected


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
    required = ["source_kind", "event_type", "original_topic", "main_topic_sentence", "primary_claim", "actor_map", "event_timeline", "cardnews_seed", "interpretation_slots", "contradiction_or_tension", "hidden_assumption", "emotional_trigger", "viral_hook_logic", "reusable_structure", "source_grounded_qa", "evidence_points", "cause_effect_chain", "audience_pain", "keywords", "summary", "transcript", "interpretation_report"]
    for col in required:
        if col not in df.columns:
            df[col] = ""
    return df.sort_values("created_at", ascending=False, na_position="last")


def load_plans():
    conn = connect_db()
    df = pd.read_sql_query("SELECT * FROM cardnews_plans ORDER BY id DESC LIMIT 50", conn)
    conn.close()
    return df


def flatten_item(item):
    if isinstance(item, dict):
        return normalize_sentence(item.get("event") or item.get("source") or item.get("fact") or item.get("answer") or item.get("basis") or "")
    return normalize_sentence(item)


def collect_fact_pool(row):
    timeline = safe_json(get_value(row, "event_timeline"), [])
    evidence = safe_json(get_value(row, "evidence_points"), [])
    cause = safe_json(get_value(row, "cause_effect_chain"), [])
    qa = safe_json(get_value(row, "source_grounded_qa"), [])
    seed = safe_json(get_value(row, "cardnews_seed"), {})
    slots = safe_json(get_value(row, "interpretation_slots"), {})
    fact_seeds = seed.get("fact_seeds", []) if isinstance(seed, dict) else []
    timeline_seeds = seed.get("timeline_seeds", []) if isinstance(seed, dict) else []
    fact_roles = list((slots.get("fact_roles", {}) if isinstance(slots, dict) else {}).values())
    summary = split_source_sentences(get_value(row, "summary"))
    transcript = split_source_sentences(get_value(row, "transcript"))[:80]
    raw_items = []
    for group in [fact_roles, fact_seeds, evidence, timeline_seeds, timeline, cause, summary, qa, transcript]:
        if isinstance(group, list):
            raw_items.extend(group)
    result, seen = [], set()
    for item in raw_items:
        value = flatten_item(item)
        if not value:
            continue
        key = re.sub(r"[^가-힣A-Za-z0-9]", "", value[:75])
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= 35:
            break
    return result


def actor_names(actor_map):
    names = []
    if isinstance(actor_map, list):
        for item in actor_map:
            if isinstance(item, dict):
                name = clean(item.get("actor"))
                if name and name not in names:
                    names.append(name)
    return names[:6]


def classify_event(facts, actors, title, event_type_from_analysis=""):
    if event_type_from_analysis:
        return event_type_from_analysis
    corpus = " ".join(facts + actors + [title])
    if has_any(corpus, ["삼성", "노조", "성과급", "파업", "플러그", "가전라인", "폐쇄"]):
        return "samsung_labor"
    if has_any(corpus, ["공원", "기증", "주차장", "안양", "부지"]):
        return "park_donation"
    if has_any(corpus, ["노조", "직원", "회사", "파업", "갈등"]):
        return "labor_conflict"
    return "general"


def infer_topic(row, facts, actors, slots):
    for key in ["original_topic", "main_topic_sentence"]:
        val = normalize_sentence(slots.get(key, "")) if isinstance(slots, dict) else ""
        if val:
            return shorten(val, 80)
    for key in ["main_topic_sentence", "original_topic", "title"]:
        val = normalize_sentence(get_value(row, key))
        if val and not val.lower().startswith("youtube"):
            return shorten(val, 80)
    if has_any(" ".join(facts + actors), ["삼성", "노조", "성과급"]):
        return "삼성과 노조가 충돌한 성과급·파업 갈등"
    return "원본에 숨은 사건과 갈등"


def analyze_source(row, selected_topic_type, context):
    slots = safe_json(get_value(row, "interpretation_slots"), {})
    seed = safe_json(get_value(row, "cardnews_seed"), {})
    actor_map = safe_json(get_value(row, "actor_map"), [])
    actors = actor_names(actor_map)
    facts = collect_fact_pool(row)
    event_type = classify_event(facts, actors, get_value(row, "title"), get_value(row, "event_type"))
    source_kind = get_value(row, "source_kind") or ("사건형" if event_type != "general" else "이슈해설형")
    topic = infer_topic(row, facts, actors, slots)

    def slot_or_db(slot_key, db_key, fallback=""):
        if isinstance(slots, dict) and normalize_sentence(slots.get(slot_key, "")):
            return normalize_sentence(slots.get(slot_key, ""))
        return normalize_sentence(get_value(row, db_key)) or fallback

    primary_claim = slot_or_db("primary_claim", "primary_claim", facts[0] if facts else f"{topic}은 결과보다 과정이 중요한 이야기입니다")
    audience_pain = slot_or_db("audience_pain", "audience_pain", "사람들은 결론만 먼저 보지만, 사건을 만든 주체와 이해관계는 놓치기 쉽습니다")
    conflict = slot_or_db("contradiction_or_tension", "contradiction_or_tension", "겉으로 보이는 결과와 그 뒤에 숨은 이해관계가 충돌하는 구조")
    hidden = slot_or_db("hidden_assumption", "hidden_assumption", "선명한 결론에도 여러 주체의 손익이 숨어 있을 수 있다는 점")
    emotion = slot_or_db("emotional_trigger", "emotional_trigger", "몰랐던 뒷이야기를 알게 되는 반전감과 다시 판단하고 싶은 궁금증")
    viral = slot_or_db("viral_hook_logic", "viral_hook_logic", "가장 강한 장면을 먼저 보여주고 뒤에 숨은 이해관계를 공개하는 반전형 후킹")
    reusable = slot_or_db("reusable_structure", "reusable_structure", "결과를 먼저 보여주고 숨은 배경과 이해관계를 드러낸 뒤 질문으로 닫는 구조")
    narrative = slot_or_db("narrative_structure", "narrative_structure", "강한 장면 제시 → 배경 공개 → 이해관계자 분해 → 갈등 확대 → 질문")

    if selected_topic_type == "자동 감지":
        topic_type = "사건/논쟁" if source_kind == "사건형" or event_type != "general" else "트렌드/이슈"
    else:
        topic_type = selected_topic_type

    slide_seed = {}
    if isinstance(slots, dict) and isinstance(slots.get("slide_seed"), dict):
        slide_seed = slots.get("slide_seed")
    elif isinstance(seed, dict) and isinstance(seed.get("slide_seed"), dict):
        slide_seed = seed.get("slide_seed")

    return {
        "source_table": get_value(row, "source_table"),
        "source_kind": source_kind,
        "event_type": event_type,
        "topic_type": topic_type,
        "topic": topic,
        "primary_claim": primary_claim,
        "claim": primary_claim,
        "audience_problem": audience_pain,
        "conflict": conflict,
        "hidden_assumption": hidden,
        "emotional_trigger": emotion,
        "viral_hook_logic": viral,
        "narrative_structure": narrative,
        "reusable_structure": reusable,
        "actor_map": actor_map,
        "actor_names": actors,
        "facts": facts,
        "slide_seed": slide_seed,
        "interpretation_slots": slots,
        "keywords": get_value(row, "keywords"),
    }


def fact_text(facts, tokens, fallback):
    for fact in facts:
        if has_any(fact, tokens):
            return fact
    return fallback


def resolve_auto_angle(value, analysis):
    if value and value != "__AUTO__" and value not in ["사건의 뒷면", "문제폭로형", "오해반박형", "체크리스트형", "전후비교형", "바이럴 후킹형"]:
        return value
    if analysis["event_type"] == "samsung_labor":
        return "삼성은 왜 직원들과 정면충돌했을까"
    if analysis["event_type"] == "park_donation":
        return "아름다운 결과 뒤에 숨은 갈등"
    return f"{analysis['topic']}의 진짜 쟁점"


def resolve_auto_problem(value, analysis):
    if value and value != "__AUTO__" and "카드뉴스" not in value:
        return value
    return analysis["audience_problem"]


def seed_is_bad(text):
    text = clean(text)
    return not text or any(leak in text for leak in COPY_LEAKS) or len(text) > 140


def get_seed_slide(slide_seed, idx, fallback):
    if isinstance(slide_seed, dict):
        val = slide_seed.get(f"slide_{idx}") or slide_seed.get(str(idx))
        if val and not seed_is_bad(val):
            return normalize_sentence(val)
    return fallback


def build_samsung_slides(a, cta):
    facts = a["facts"]
    has_15 = has_any(" ".join(facts), ["15%", "영업 이익", "영업이익"])
    has_45 = has_any(" ".join(facts), ["45조"])
    has_plug = has_any(" ".join(facts), ["플러그", "전원", "폐쇄", "가전라인"])
    has_strike = has_any(" ".join(facts), ["파업", "93%", "찬성"])
    has_gov = has_any(" ".join(facts), ["정부", "주무부처", "70%", "경쟁력"])

    demand = "노조는 영업이익 15% 배분을 요구했습니다" if has_15 else shorten(fact_text(facts, ["성과급", "영업 이익", "영업이익"], "성과급 요구가 갈등의 출발점이었습니다"), 82)
    amount = "요구 규모는 45조라는 숫자까지 커졌습니다" if has_45 else shorten(fact_text(facts, ["45조", "숫자", "규모"], "숫자가 커지면서 단순한 보너스 논쟁을 넘어섰습니다"), 82)
    response = "가전 생산라인 전원까지 언급하며 맞섰습니다" if has_plug else shorten(fact_text(facts, ["플러그", "전원", "폐쇄", "대답"], "회사는 강경한 방식으로 대응했습니다"), 82)
    outside = "파업, 정부, 산업 경쟁력 이슈까지 겹쳤습니다" if (has_strike or has_gov) else shorten(fact_text(facts, ["파업", "정부", "경쟁력", "여론"], "갈등은 회사 밖의 여론전으로 번졌습니다"), 82)

    return [
        "삼성은 왜\n가전라인 폐쇄까지 꺼냈을까요?",
        f"출발점은 성과급이었습니다\n{demand}",
        f"숫자는 여기서 커졌습니다\n{amount}",
        f"삼성의 대답은 강경했습니다\n{response}",
        f"이제 사내 갈등이 아니었습니다\n{outside}",
        f"이건 직원 몫의 돈일까요\n회사의 생존 비용일까요?\n{cta}",
    ]


def build_park_slides(a, cta):
    facts = a["facts"]
    park = shorten(fact_text(facts, ["공원", "주차장", "시민"], "지금은 시민들이 이용하는 평화로운 공간입니다"), 82)
    donation = shorten(fact_text(facts, ["기증", "부지"], "이 공간은 기업의 부지 기증에서 시작됐습니다"), 82)
    union = shorten(fact_text(facts, ["노조", "반발", "직원"], "하지만 내부에서는 직원과 노조의 반발도 있었습니다"), 82)
    return [
        "아름다운 공원에도\n숨은 이야기가 있습니다",
        f"지금은 평화로운 공간입니다\n{park}",
        f"하지만 시작은 기부였습니다\n{donation}",
        f"그 과정이 모두 평화롭진 않았습니다\n{union}",
        f"핵심은 이 충돌입니다\n{shorten(a['conflict'], 86)}",
        f"미담만 보고 지나쳐도 될까요?\n{cta}",
    ]


def build_slot_based_event_plan(ctx):
    a = ctx["analysis"]
    cta = ctx["cta"]
    facts = a["facts"]
    seed = a.get("slide_seed", {})

    if a["event_type"] == "samsung_labor":
        slides = build_samsung_slides(a, cta)
        directions = [
            "삼성 반도체 또는 가전 생산라인을 배경으로 회사와 직원이 대치하는 뉴스형 첫 장.",
            "성과급 요구와 영업이익 15% 같은 숫자가 크게 보이는 계산서형 인포그래픽.",
            "45조처럼 거대한 숫자가 화면을 압도하고 양쪽 이해관계자가 충돌하는 장면.",
            "생산라인 전원 스위치 또는 플러그를 상징적으로 보여주는 긴장감 있는 장면.",
            "파업 투표, 정부 브리핑, 산업 경쟁력 뉴스가 겹치는 다층 콜라주.",
            "돈다발과 반도체 웨이퍼가 양쪽에 놓이고 중앙에 질문이 남는 마무리 장면.",
        ]
    elif a["event_type"] == "park_donation":
        slides = build_park_slides(a, cta)
        directions = [
            "평화로운 도심 공원 위에 과거 공장 실루엣이 희미하게 겹쳐진 첫 장.",
            "공원과 지하 주차장, 시민의 일상이 보이는 밝은 장면.",
            "오래된 공장 부지 지도와 기증 문서를 겹쳐 보여주는 자료형 장면.",
            "회사, 직원, 노조, 시민이 관계도로 연결된 장면.",
            "미담과 갈등이 좌우로 갈라지는 비교형 인포그래픽.",
            "공원 벤치 위에 질문 하나가 남는 조용한 마무리 장면.",
        ]
    else:
        slides = [
            get_seed_slide(seed, 1, f"{shorten(a['topic'], 28)}\n결론만으로는 부족합니다"),
            get_seed_slide(seed, 2, f"먼저 봐야 할 단서\n{shorten(facts[0] if facts else a['primary_claim'], 88)}"),
            get_seed_slide(seed, 3, f"여기서 이해관계가 갈립니다\n{shorten(a['conflict'], 88)}"),
            get_seed_slide(seed, 4, f"핵심은 요구와 대응입니다\n{shorten(facts[1] if len(facts) > 1 else a['hidden_assumption'], 88)}"),
            get_seed_slide(seed, 5, f"놓치면 안 되는 전제\n{shorten(a['hidden_assumption'], 88)}"),
            get_seed_slide(seed, 6, f"당신은 이 사건을\n어떻게 보시나요?\n{cta}"),
        ]
        directions = [
            "사건의 가장 강한 장면을 크게 보여주는 뉴스형 첫 장.",
            "첫 번째 단서가 되는 숫자나 발언을 자료처럼 보여주는 장면.",
            "이해관계자들이 서로 다른 위치에 놓인 관계도 장면.",
            "갈등의 축을 좌우 대비로 보여주는 장면.",
            "독자가 놓친 전제를 돋보기로 찾아내는 장면.",
            "질문을 남기는 여백 중심의 마무리 카드.",
        ]
    prompts = build_prompts(ctx, directions, slides)
    return finalize_plan(ctx, f"[사건형] {shorten(a['topic'], 44)}", a["audience_problem"], slides, directions, prompts)


def build_generic_plan(ctx):
    a = ctx["analysis"]
    facts = a["facts"]
    cta = ctx["cta"]
    topic = a["topic"]
    slides = [
        f"{shorten(topic, 28)}\n먼저 봐야 할 기준이 있습니다",
        f"핵심 단서\n{shorten(facts[0] if facts else a['primary_claim'], 92)}",
        f"사람들이 놓치는 건\n{shorten(a['audience_problem'], 92)}",
        f"판단 기준은\n{shorten(a['conflict'], 92)}",
        f"정리하면\n{shorten(a['reusable_structure'], 92)}",
        f"이 기준이 필요했다면\n{cta}",
    ]
    directions = [
        "원본 주제를 상징하는 첫 장. 큰 오브젝트와 짧은 문장으로 초반 주목도를 만드는 구성.",
        "핵심 단서를 보여주는 장면. 자료와 메시지가 명확히 연결되게 구성.",
        "독자가 놓치기 쉬운 문제를 시각화. 잘못된 판단과 올바른 판단 기준을 대비.",
        "판단 기준을 분석하는 장면. 원인, 배경, 체크포인트를 3갈래로 정리.",
        "재사용 가능한 구조를 보여주는 카드. 흐름도가 한눈에 보이게 구성.",
        "저장, 공유, 댓글 같은 행동을 유도하는 마무리 카드.",
    ]
    prompts = build_prompts(ctx, directions, slides)
    return finalize_plan(ctx, f"[원본 주제] {shorten(topic, 44)}", a["audience_problem"], slides, directions, prompts)


def build_prompts(ctx, directions, slides):
    ratio = RATIO_PROMPTS[ctx["image_ratio"]]
    style = VISUAL_STYLES[ctx["image_style"]]
    copy_rule = "include a short Korean headline, safe margins, clean readable text" if ctx["include_image_copy"] else "clean image only, no text, no captions, no typography, no letters, no watermark, no logo"
    prompts = []
    for idx, direction in enumerate(directions, start=1):
        copy_hint = shorten(slides[idx - 1].replace("\n", " / "), 90)
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
    if ctx["analysis"]["source_kind"] == "사건형" or ctx["analysis"]["event_type"] != "general":
        return build_slot_based_event_plan(ctx)
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
    edited.update({"common_style": common_style, "title": title, "core_problem": core_problem, "main_message": main_message, "cta": cta, "slides": slides, "directions": directions, "prompts": prompts, "images": [f"장면 방향:\n{directions[i]}\n\n이미지 생성 프롬프트:\n{prompts[i]}" for i in range(6)]})
    return edited


def main():
    st.set_page_config(page_title="원본 주제 카드뉴스", page_icon="📰", layout="wide")
    init_table()
    st.title("📰 원본 주제 카드뉴스")
    st.caption("영상내용분석의 해석 슬롯을 쓰되, 최종 카피는 카드뉴스용 문장으로 다시 씁니다.")
    refs = load_references()
    if refs.empty:
        st.warning("먼저 YouTube 영상 내용 분석에서 원본 해석 결과를 저장하세요.")
        return

    options = {f"{get_value(row, 'source_table')} · {row['id']} · {get_value(row, 'main_topic_sentence') or get_value(row, 'original_topic') or get_value(row, 'title')}": row for _, row in refs.iterrows()}
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
        emphasis = st.text_input("강조할 관점", placeholder="예: 사건의 아이러니, 갈등 축, 숫자, 당사자 이해관계")
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

    base_context = {"content_goal": content_goal, "platform_focus": platform_focus, "analysis_depth": analysis_depth, "target_audience": target_value, "emphasis": emphasis, "avoid": avoid}
    analysis = analyze_source(row, topic_type_select, base_context)
    if topic_type_select == "직접 입력":
        analysis["topic_type"] = st.text_input("주제 유형 직접 입력", value="사용자 정의")

    effective_template = "문제 제기형" if template == "자동 최적화" else template
    angle = resolve_auto_angle(angle_value, analysis)
    problem = resolve_auto_problem(problem_value, analysis)
    common_style = f"비율: {image_ratio} / 스타일: {image_style} / 사용처: {platform_focus}."
    common_style += " 이미지 안에 짧은 한글 헤드라인 포함 가능. 안전 여백 확보." if include_image_copy else " 텍스트 없는 클린 이미지. no text, no captions, no typography, no letters, no watermark, no logo."

    with st.expander("원본 분석 결과", expanded=True):
        st.write(f"**감지된 주제 유형:** {analysis['topic_type']}")
        st.write(f"**원본 유형:** {analysis['source_kind']} / {analysis['event_type']}")
        st.write(f"**원본 주제:** {analysis['topic']}")
        st.write(f"**핵심 주장:** {analysis['primary_claim']}")
        st.write(f"**독자 문제:** {analysis['audience_problem']}")
        st.write(f"**숨은 전제:** {analysis['hidden_assumption']}")
        st.write(f"**갈등/긴장 구조:** {analysis['conflict']}")
        st.write(f"**감정 트리거:** {analysis['emotional_trigger']}")
        st.write(f"**바이럴 후킹 로직:** {analysis['viral_hook_logic']}")
        st.write(f"**전개 구조:** {analysis['narrative_structure']}")
        st.write(f"**재사용 가능한 구조:** {analysis['reusable_structure']}")
        if analysis.get("facts"):
            st.write("**사용할 핵심 팩트:**")
            for fact in analysis["facts"][:8]:
                st.write(f"- {fact}")

    ctx = {"analysis": analysis, "template": effective_template, "tone": tone, "topic_type": analysis["topic_type"], "angle": angle, "problem": problem, "cta": cta, "common_style": common_style, "image_ratio": image_ratio, "image_style": image_style, "include_image_copy": include_image_copy}
    plan = build_plan(ctx)
    signature = "|".join([str(int(row["id"])), get_value(row, "source_table"), analysis["topic"], analysis["event_type"], effective_template, tone, image_ratio, image_style, str(include_image_copy), angle, problem, cta, emphasis, avoid])
    update_state(plan, signature)

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("현재 선택값으로 초안 다시 생성"):
            update_state(plan, signature, force=True)
            st.rerun()
    with col_info:
        st.info("이제 원본의 해석 슬롯은 참고하되, 최종 카드 카피는 사건별 카피라이터 레이어에서 다시 정리합니다.")

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
