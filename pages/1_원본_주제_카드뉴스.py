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
    "자동 맥락형 엔딩": "__AUTO_CONTEXT__",
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

RATIO_PROMPTS = {
    "1:1": "square 1:1 composition",
    "16:9": "wide 16:9 horizontal composition",
    "9:16": "vertical 9:16 mobile story composition",
    "4:3": "classic 4:3 editorial composition",
}

GENERIC_CTA_LEAKS = ["__AUTO_CONTEXT__", "이 기준은 저장해두고 다시 확인해보세요", "저장해두고 다시 확인해보세요", "이 기준이 필요했다면"]
LABEL_WORDS = ["헤드카피", "바디카피", "카피", "장면 방향", "이미지 생성 프롬프트"]


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
    for label in LABEL_WORDS:
        text = re.sub(rf"(?im)^\s*{re.escape(label)}\s*$", "", text)
        text = re.sub(rf"(?im)^\s*{re.escape(label)}\s*[:：]\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def normalize_sentence(text):
    text = strip_meta(text)
    text = re.sub(r"^[\-•\d\.\s]+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def shorten(text, max_len=110):
    text = strip_meta(text)
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def split_source_sentences(text):
    text = strip_meta(text)
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=다)\s+|(?<=요)\s+|(?<=죠)\s+", text)
    return [normalize_sentence(p) for p in parts if len(normalize_sentence(p)) > 12]


def compact_lines(text):
    return "\n".join([line.strip() for line in clean(text).splitlines() if line.strip()])


def has_any(text, words):
    return any(word in clean(text) for word in words)


def polish(text, tone="명확"):
    text = compact_lines(text)
    replacements = {
        "합니다입니다": "합니다",
        "쉽습니다입니다": "쉽습니다",
        "중요합니다입니다": "중요합니다",
        "진짜": "정말",
        "없으면": "없다면",
        "~": "",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if tone == "담백":
        text = text.replace("놓치면 안 됩니다", "확인해볼 필요가 있습니다")
    elif tone == "자극적":
        text = text.replace("봐야 합니다", "놓치면 안 됩니다")
    return text.strip()


def make_card(headline, body=""):
    return {"headline": compact_lines(headline), "body": compact_lines(body)}


def combine_card(card):
    headline = compact_lines(card.get("headline", ""))
    body = compact_lines(card.get("body", ""))
    return f"{headline}\n\n{body}" if body else headline


def selected_cta_is_generic(cta):
    cta = clean(cta)
    return not cta or any(leak in cta for leak in GENERIC_CTA_LEAKS)


def contextual_ending(analysis, selected_cta):
    custom = clean(selected_cta)
    if custom and not selected_cta_is_generic(custom):
        return custom
    event_type = analysis.get("event_type", "general")
    if event_type == "samsung_labor":
        return "당신은 이 갈등을 직원 보상 문제로 보시나요, 회사의 생존 전략으로 보시나요?"
    if event_type == "park_donation":
        return "이 이야기는 미담일까요, 아니면 우리가 늦게 본 갈등의 기록일까요?"
    if event_type in ["labor_conflict", "legal_conflict"]:
        return "당신은 어느 쪽의 논리가 더 설득력 있다고 보시나요?"
    if analysis.get("topic_type") == "시장/투자":
        return "지금 봐야 할 건 가격이 아니라, 그 가격을 움직인 이유입니다."
    return "이 이야기를 다시 본다면, 가장 먼저 어떤 기준을 확인해야 할까요?"


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
    required = [
        "source_kind", "event_type", "original_topic", "main_topic_sentence", "primary_claim", "actor_map",
        "event_timeline", "cardnews_seed", "interpretation_slots", "contradiction_or_tension",
        "hidden_assumption", "emotional_trigger", "viral_hook_logic", "reusable_structure",
        "source_grounded_qa", "evidence_points", "cause_effect_chain", "audience_pain", "keywords",
        "summary", "transcript", "interpretation_report",
    ]
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
    transcript = split_source_sentences(get_value(row, "transcript"))[:100]
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
        if len(result) >= 40:
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
        "interpretation_slots": slots,
        "keywords": get_value(row, "keywords"),
    }


def fact_text(facts, tokens, fallback):
    for fact in facts:
        if has_any(fact, tokens):
            return normalize_sentence(fact)
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


def build_samsung_cards(a, selected_cta):
    facts = a["facts"]
    demand_raw = fact_text(facts, ["15%", "성과급", "영업 이익", "영업이익"], "노조는 회사가 벌어들인 이익 일부를 성과급으로 돌려달라고 요구했습니다")
    amount_raw = fact_text(facts, ["45조"], "요구 규모가 거대한 숫자로 읽히면서 논쟁은 단순한 보너스 문제를 넘어섰습니다")
    response_raw = fact_text(facts, ["플러그", "전원", "폐쇄", "가전라인"], "회사는 생산라인 중단까지 거론하는 강경한 방식으로 맞섰습니다")
    outside_raw = fact_text(facts, ["파업", "93%", "찬성", "정부", "주무부처", "70%", "경쟁력"], "갈등은 파업과 여론전, 산업 경쟁력 논쟁으로 번졌습니다")
    close = contextual_ending(a, selected_cta)
    return [
        make_card("삼성은 왜\n가전라인 폐쇄까지 꺼냈을까요?", "겉으로는 노사 갈등처럼 보이지만, 안쪽에는 성과급과 미래 투자라는 더 큰 충돌이 있었습니다."),
        make_card("출발점은 성과급이었습니다", f"노조의 요구는 단순한 격려금이 아니었습니다. {shorten(demand_raw, 92)}"),
        make_card("문제는 숫자가 너무 컸다는 겁니다", f"회사가 보기엔 이 요구가 미래 투자 재원을 흔드는 문제로 보였습니다. {shorten(amount_raw, 92)}"),
        make_card("삼성은 양보 대신\n강경한 경고를 택했습니다", f"회사는 더 이상 단순 협상으로 볼 수 없다고 판단했습니다. {shorten(response_raw, 92)}"),
        make_card("갈등은 회사 밖으로 번졌습니다", f"이제 쟁점은 직원 보상을 넘어 파업, 여론, 산업 경쟁력 문제로 커졌습니다. {shorten(outside_raw, 92)}"),
        make_card("결국 질문은 하나입니다", close),
    ]


def build_park_cards(a, selected_cta):
    facts = a["facts"]
    park = fact_text(facts, ["공원", "주차장", "시민"], "지금은 시민들이 이용하는 평화로운 공간으로 남아 있습니다")
    donation = fact_text(facts, ["기증", "부지"], "이 공간은 기업의 부지 기증에서 시작됐습니다")
    union = fact_text(facts, ["노조", "반발", "직원"], "하지만 내부에서는 직원과 노조의 반발도 있었습니다")
    close = contextual_ending(a, selected_cta)
    return [
        make_card("아름다운 공원에도\n숨은 이야기가 있습니다", "지금 보이는 풍경만으로는 이 공간이 지나온 갈등을 다 설명할 수 없습니다."),
        make_card("지금은 평화로운 공간입니다", shorten(park, 105)),
        make_card("하지만 시작은 기부였습니다", shorten(donation, 105)),
        make_card("그 과정이 모두\n평화롭진 않았습니다", shorten(union, 105)),
        make_card("핵심은 결과와 과정의 충돌입니다", shorten(a["conflict"], 105)),
        make_card("이 이야기를 다시 본다면", close),
    ]


def build_general_event_cards(a, selected_cta):
    facts = a["facts"]
    close = contextual_ending(a, selected_cta)
    fact1 = facts[0] if facts else a["primary_claim"]
    fact2 = facts[1] if len(facts) > 1 else a["conflict"]
    fact3 = facts[2] if len(facts) > 2 else a["hidden_assumption"]
    return [
        make_card(f"{shorten(a['topic'], 28)}\n결론만으로는 부족합니다", "이 사건은 결과보다 그 결과가 만들어진 조건을 먼저 봐야 합니다."),
        make_card("먼저 봐야 할 단서", shorten(fact1, 105)),
        make_card("이해관계는 여기서 갈립니다", shorten(a["conflict"], 105)),
        make_card("핵심은 요구와 대응입니다", shorten(fact2, 105)),
        make_card("놓치면 안 되는 전제", shorten(fact3, 105)),
        make_card("마지막 질문", close),
    ]


def build_slot_based_event_plan(ctx):
    a = ctx["analysis"]
    cta = ctx["cta"]
    if a["event_type"] == "samsung_labor":
        cards = build_samsung_cards(a, cta)
        directions = [
            "삼성 반도체 또는 가전 생산라인을 배경으로 회사와 직원이 대치하는 뉴스형 첫 장.",
            "성과급 요구와 영업이익 15% 같은 숫자가 크게 보이는 계산서형 인포그래픽.",
            "45조처럼 거대한 숫자가 화면을 압도하고 양쪽 이해관계자가 충돌하는 장면.",
            "생산라인 전원 스위치 또는 플러그를 상징적으로 보여주는 긴장감 있는 장면.",
            "파업 투표, 정부 브리핑, 산업 경쟁력 뉴스가 겹치는 다층 콜라주.",
            "돈다발과 반도체 웨이퍼가 양쪽에 놓이고 중앙에 질문이 남는 마무리 장면.",
        ]
    elif a["event_type"] == "park_donation":
        cards = build_park_cards(a, cta)
        directions = [
            "평화로운 도심 공원 위에 과거 공장 실루엣이 희미하게 겹쳐진 첫 장.",
            "공원과 지하 주차장, 시민의 일상이 보이는 밝은 장면.",
            "오래된 공장 부지 지도와 기증 문서를 겹쳐 보여주는 자료형 장면.",
            "회사, 직원, 노조, 시민이 관계도로 연결된 장면.",
            "미담과 갈등이 좌우로 갈라지는 비교형 인포그래픽.",
            "공원 벤치 위에 질문 하나가 남는 조용한 마무리 장면.",
        ]
    else:
        cards = build_general_event_cards(a, cta)
        directions = [
            "사건의 가장 강한 장면을 크게 보여주는 뉴스형 첫 장.",
            "첫 번째 단서가 되는 숫자나 발언을 자료처럼 보여주는 장면.",
            "이해관계자들이 서로 다른 위치에 놓인 관계도 장면.",
            "갈등의 축을 좌우 대비로 보여주는 장면.",
            "독자가 놓친 전제를 돋보기로 찾아내는 장면.",
            "질문을 남기는 여백 중심의 마무리 카드.",
        ]
    prompts = build_prompts(ctx, directions, cards)
    return finalize_plan(ctx, f"[사건형] {shorten(a['topic'], 44)}", a["audience_problem"], cards, directions, prompts)


def build_generic_plan(ctx):
    a = ctx["analysis"]
    facts = a["facts"]
    close = contextual_ending(a, ctx["cta"])
    topic = a["topic"]
    fact1 = facts[0] if facts else a["primary_claim"]
    cards = [
        make_card(f"{shorten(topic, 28)}\n먼저 봐야 할 기준이 있습니다", "결론보다 중요한 건 이 이야기를 움직인 조건입니다."),
        make_card("핵심 단서", shorten(fact1, 105)),
        make_card("사람들이 놓치는 지점", shorten(a["audience_problem"], 105)),
        make_card("판단 기준", shorten(a["conflict"], 105)),
        make_card("정리하면", shorten(a["reusable_structure"], 105)),
        make_card("마지막 질문", close),
    ]
    directions = [
        "원본 주제를 상징하는 첫 장. 큰 오브젝트와 짧은 문장으로 초반 주목도를 만드는 구성.",
        "핵심 단서를 보여주는 장면. 자료와 메시지가 명확히 연결되게 구성.",
        "독자가 놓치기 쉬운 문제를 시각화. 잘못된 판단과 올바른 판단 기준을 대비.",
        "판단 기준을 분석하는 장면. 원인, 배경, 체크포인트를 3갈래로 정리.",
        "재사용 가능한 구조를 보여주는 카드. 흐름도가 한눈에 보이게 구성.",
        "질문을 남기는 여백 중심의 마무리 카드.",
    ]
    prompts = build_prompts(ctx, directions, cards)
    return finalize_plan(ctx, f"[원본 주제] {shorten(topic, 44)}", a["audience_problem"], cards, directions, prompts)


def copy_text_for_image(card):
    headline = strip_meta(card.get("headline", ""))
    body = strip_meta(card.get("body", ""))
    headline = re.sub(r"\s+", " ", headline.replace("\n", " ")).strip()
    body = re.sub(r"\s+", " ", body.replace("\n", " ")).strip()
    for label in LABEL_WORDS:
        headline = headline.replace(label, "")
        body = body.replace(label, "")
    return shorten(headline, 44), shorten(body, 90)


def build_prompts(ctx, directions, cards):
    ratio = RATIO_PROMPTS[ctx["image_ratio"]]
    style = VISUAL_STYLES[ctx["image_style"]]
    prompts = []
    for idx, direction in enumerate(directions, start=1):
        headline, body = copy_text_for_image(cards[idx - 1])
        if ctx["include_image_copy"]:
            copy_rule = (
                f"Render only this Korean headline text if text is needed: '{headline}'. "
                "Do not render body copy. Do not render the labels '헤드카피', '바디카피', '카피', 'Copy intent', or any field name. "
                "Use the body copy only as conceptual context for the visual composition."
            )
        else:
            copy_rule = "clean image only, no text, no captions, no typography, no letters, no watermark, no logo"
        prompts.append(f"{ratio}, {style}. {direction} Body context for composition only: {body}. {copy_rule}")
    return prompts


def finalize_plan(ctx, title, main_message, cards, directions, prompts):
    tone = ctx["tone"]
    cards = [{"headline": polish(c.get("headline", ""), tone), "body": polish(c.get("body", ""), tone)} for c in cards]
    slides = [combine_card(card) for card in cards]
    return {
        "title": polish(title, tone),
        "target_customer": ctx["topic_type"],
        "core_problem": polish(ctx.get("problem") or main_message, tone),
        "main_message": polish(main_message, tone),
        "cta": contextual_ending(ctx["analysis"], ctx["cta"]),
        "common_style": ctx["common_style"],
        "cards": cards,
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


def ensure_cards(plan):
    if plan.get("cards"):
        return plan["cards"]
    cards = []
    for slide in plan.get("slides", ["", "", "", "", "", ""]):
        parts = [p.strip() for p in clean(slide).split("\n\n")]
        headline = parts[0] if parts else ""
        body = "\n\n".join(parts[1:]) if len(parts) > 1 else ""
        cards.append(make_card(headline, body))
    return cards[:6]


def render_editable(plan, version):
    suffix = f"v{version}"
    st.markdown("### 공통 이미지 스타일")
    common_style = st.text_area("공통 스타일", value=plan["common_style"], height=90, key=f"ot_common_{suffix}")
    st.markdown("### 핵심 설계")
    title = st.text_input("저장할 주제명", value=plan["title"], key=f"ot_title_{suffix}")
    core_problem = st.text_area("핵심 문제", value=plan["core_problem"], height=80, key=f"ot_problem_{suffix}")
    main_message = st.text_area("메인 메시지", value=plan["main_message"], height=90, key=f"ot_message_{suffix}")
    cta = st.text_input("맥락형 엔딩/CTA", value=plan["cta"], key=f"ot_cta_{suffix}")
    st.markdown("### 6장 카드뉴스 구성 직접 수정")
    cards = ensure_cards(plan)
    edited_cards, directions, prompts = [], [], []
    for idx in range(6):
        card = cards[idx] if idx < len(cards) else make_card("", "")
        with st.container(border=True):
            st.markdown(f"#### {idx + 1}장")
            headline = st.text_area("헤드카피", value=card.get("headline", ""), height=80, key=f"ot_headline_{idx}_{suffix}")
            body = st.text_area("바디카피", value=card.get("body", ""), height=110, key=f"ot_body_{idx}_{suffix}")
            direction = st.text_area("장면 방향", value=plan["directions"][idx], height=90, key=f"ot_direction_{idx}_{suffix}")
            prompt = st.text_area("이미지 생성 프롬프트", value=plan["prompts"][idx], height=130, key=f"ot_prompt_{idx}_{suffix}")
            edited_cards.append(make_card(headline, body))
            directions.append(direction)
            prompts.append(prompt)
    slides = [combine_card(card) for card in edited_cards]
    edited = dict(plan)
    edited.update({
        "common_style": common_style,
        "title": title,
        "core_problem": core_problem,
        "main_message": main_message,
        "cta": cta,
        "cards": edited_cards,
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
    st.caption("헤드카피와 바디카피를 입력창으로 분리하고, 이미지 프롬프트에는 실제 헤드라인만 전달합니다.")
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
        cta, cta_label = select_from_dict_like("엔딩/CTA", CTA_PRESETS, "ot_cta_preset", "자동 맥락형 엔딩")

    st.markdown("### 이미지 생성 조건")
    i1, i2, i3 = st.columns(3)
    with i1:
        image_ratio = st.selectbox("이미지 비율", IMAGE_RATIOS, index=0)
    with i2:
        image_style = st.selectbox("이미지 스타일", IMAGE_STYLES, index=0)
    with i3:
        include_image_copy = st.checkbox("이미지 안에 헤드카피만 넣기", value=True)
        st.caption("바디카피와 '헤드카피/바디카피' 라벨은 이미지 프롬프트에 렌더링 대상으로 들어가지 않습니다.")

    base_context = {"content_goal": content_goal, "platform_focus": platform_focus, "analysis_depth": analysis_depth, "target_audience": target_value, "emphasis": emphasis, "avoid": avoid}
    analysis = analyze_source(row, topic_type_select, base_context)
    if topic_type_select == "직접 입력":
        analysis["topic_type"] = st.text_input("주제 유형 직접 입력", value="사용자 정의")

    effective_template = "문제 제기형" if template == "자동 최적화" else template
    angle = resolve_auto_angle(angle_value, analysis)
    problem = resolve_auto_problem(problem_value, analysis)
    common_style = f"비율: {image_ratio} / 스타일: {image_style} / 사용처: {platform_focus}."
    common_style += " 이미지 안에는 짧은 헤드카피만 포함. 바디카피는 디자인 참고용." if include_image_copy else " 텍스트 없는 클린 이미지. no text, no captions, no typography, no letters, no watermark, no logo."

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
        st.info("이미지 프롬프트에는 '헤드카피/바디카피' 라벨이 들어가지 않고, 렌더링 대상은 짧은 헤드카피로 제한됩니다.")

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
