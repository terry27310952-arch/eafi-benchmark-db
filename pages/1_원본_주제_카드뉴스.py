import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")

TOPIC_TYPES = ["자동 감지", "사건/논쟁", "시장/투자", "트렌드/이슈", "브랜드/마케팅", "라이프스타일", "교육/노하우", "기술/AI", "직접 입력"]
CONTENT_GOALS = ["원본 내용 깊이 분석", "카드뉴스 원천 데이터화", "바이럴 후킹 추출", "교육형 요약", "이슈/트렌드 재가공"]
PLATFORM_FOCUS = ["인스타 카드뉴스", "유튜브 커뮤니티", "블로그", "쓰레드", "틱톡/숏폼", "범용"]
ANALYSIS_DEPTH = ["핵심만", "구조 분석", "세부 근거까지", "전환 관점", "후킹/바이럴 관점"]
TEMPLATE_OPTIONS = ["자동 최적화", "문제 제기형", "체크리스트형", "전후 비교형", "교육형", "트렌드 분석형"]
TONE_LEVELS = ["담백", "명확", "강한 후킹", "자극적"]
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
    "댓글 유도": "여러분은 이 이야기를 어떻게 보시나요? 댓글로 남겨주세요",
    "공유 유도": "이 이야기가 필요한 분에게 공유해보세요",
    "팔로우 유도": "비슷한 분석을 계속 보고 싶다면 팔로우해두세요",
    "DM 문의": "이런 카드뉴스 제작이 필요하다면 DM으로 문의해주세요",
    "직접 입력": "",
}

TARGET_PRESETS = {
    "일반 시청자": "해당 주제에 관심 있는 일반 시청자",
    "브랜드/마케팅 담당자": "영상 제작을 검토 중인 브랜드/마케팅 담당자",
    "콘텐츠 제작자": "유튜브와 숏폼을 꾸준히 운영해야 하는 콘텐츠 제작자",
    "투자/시장 관심층": "시장 흐름과 이슈를 빠르게 파악하려는 사람",
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
    "정보 과잉": "정보는 많지만 무엇을 기준으로 판단해야 하는지 흐려진 상태",
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

INTERNAL_LABELS = [
    "현실 신호", "기대 신호", "결과 신호", "충돌 신호", "context_profile", "result_signal", "expectation_signal", "reality_signal", "conflict_signal"
]
BAD_HEADLINES = ["핵심 단서", "사람들이 놓치는 지점", "판단 기준", "정리하면", "마지막 질문", "먼저 봐야 할 기준"]
REPEAT_GUARD_WORDS = ["확인해야", "먼저 봐야", "다시 계산", "중요한 건", "기준", "기대", "현실"]
GENERIC_CTA_LEAKS = ["__AUTO_CONTEXT__", "이 기준은 저장해두고 다시 확인해보세요", "저장해두고 다시 확인해보세요"]
LABEL_WORDS = ["헤드카피", "바디카피", "카피", "장면 방향", "이미지 생성 프롬프트", "Copy intent"]

TOKEN_GROUPS = {
    "verification_gap": ["실적", "매출", "영업", "손실", "적자", "숫자", "이익", "재무", "분기", "보고서"],
    "financial_pressure": ["자금", "현금", "전환사채", "CB", "유상증자", "부채", "차입", "상환", "조달", "채권"],
    "execution_risk": ["공시", "지연", "계약", "사업", "생산", "공장", "인허가", "투자", "리튬", "배터리", "2차전지", "진행"],
    "market_price": ["주가", "가격", "만원", "천원", "원", "시총", "고점", "저점", "폭락", "급락", "하락", "급등", "상승"],
    "expectation": ["기대", "미래", "성장", "스토리", "전망", "호재", "수혜", "테마", "비전", "가능성"],
    "conflict": ["하지만", "그런데", "문제는", "반면", "그러나", "의심", "리스크", "위험", "논란", "갈등", "반발", "요구"],
}

NUM_RE = re.compile(r"\d+(?:[,.]\d+)?\s*(?:만원|천원|원|조|억|%|배|달러|명|개|건)?")


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
        fallback = {}
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
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\[[sS]?\d+\]", "", text)
    text = re.sub(r"[\"“”']", "", text)
    for label in LABEL_WORDS:
        text = re.sub(rf"(?im)^\s*{re.escape(label)}\s*[:：]?\s*", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def remove_internal_labels(text):
    text = strip_meta(text)
    replacements = {
        "현실 신호": "검증해야 할 숫자",
        "기대 신호": "처음의 기대",
        "결과 신호": "드러난 결과",
        "충돌 신호": "엇갈린 지점",
        "그 기대를 다시 확인하게 만든 검증해야 할 숫자": "기대를 검증해야 할 숫자",
        "그 기대를 다시 확인하게 만든": "기대를 흔든",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    for label in INTERNAL_LABELS:
        text = text.replace(label, "")
    text = re.sub(r"\s+", " ", text).strip()
    return text


def shorten(text, max_len=130):
    text = remove_internal_labels(text)
    return text if len(text) <= max_len else text[: max_len - 1].rstrip() + "…"


def compact_lines(text):
    return "\n".join([line.strip() for line in clean(text).splitlines() if line.strip()])


def has_any(text, words):
    return any(word in clean(text) for word in words)


def tokenize_sentences(text):
    text = strip_meta(text)
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=다)\s+|(?<=요)\s+|(?<=죠)\s+", text)
    return [remove_internal_labels(p) for p in parts if len(remove_internal_labels(p)) > 10]


def polish(text, tone="명확"):
    text = compact_lines(remove_internal_labels(text))
    replacements = {
        "합니다입니다": "합니다",
        "쉽습니다입니다": "쉽습니다",
        "중요합니다입니다": "중요합니다",
        "  ": " ",
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    if tone == "담백":
        text = text.replace("놓치면 안 됩니다", "확인해볼 필요가 있습니다")
    elif tone == "자극적":
        text = text.replace("봐야 합니다", "놓치면 안 됩니다")
    return text.strip()


def first_nonempty(*values, fallback=""):
    for value in values:
        if isinstance(value, str) and remove_internal_labels(value):
            return remove_internal_labels(value)
        if value:
            return value
    return fallback


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
        "source_kind", "event_type", "original_topic", "main_topic_sentence", "primary_claim",
        "actor_map", "event_timeline", "cardnews_seed", "interpretation_slots", "source_index",
        "contradiction_or_tension", "hidden_assumption", "emotional_trigger", "viral_hook_logic",
        "reusable_structure", "source_grounded_qa", "evidence_points", "cause_effect_chain",
        "audience_pain", "keywords", "summary", "transcript", "interpretation_report",
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
        return remove_internal_labels(item.get("event") or item.get("source") or item.get("fact") or item.get("answer") or item.get("basis") or "")
    return remove_internal_labels(item)


def collect_fact_pool(row):
    pools = []
    for key in ["evidence_points", "event_timeline", "cause_effect_chain", "source_grounded_qa"]:
        value = safe_json(get_value(row, key), [])
        if isinstance(value, list):
            pools.extend(value)
    for key in ["interpretation_slots", "cardnews_seed", "source_index"]:
        value = safe_json(get_value(row, key), {})
        if isinstance(value, dict):
            for sub in ["fact_roles", "context_profile", "fact_seeds", "timeline_seeds"]:
                item = value.get(sub)
                if isinstance(item, dict):
                    pools.extend(item.values())
                elif isinstance(item, list):
                    pools.extend(item)
            if isinstance(value.get("slide_seed"), dict):
                pools.extend(value["slide_seed"].values())
    pools.extend(tokenize_sentences(get_value(row, "summary"))[:20])
    pools.extend(tokenize_sentences(get_value(row, "transcript"))[:80])
    result, seen = [], set()
    for item in pools:
        value = flatten_item(item)
        if not value:
            continue
        key = re.sub(r"[^가-힣A-Za-z0-9]", "", value[:75])
        if key in seen:
            continue
        seen.add(key)
        result.append(value)
        if len(result) >= 50:
            break
    return result


def get_context_profile(row):
    candidates = []
    for key in ["interpretation_slots", "cardnews_seed", "source_index", "interpretation_report"]:
        obj = safe_json(get_value(row, key), {})
        if isinstance(obj, dict):
            candidates.append(obj.get("context_profile", {}))
            if isinstance(obj.get("fact_roles"), dict):
                candidates.append(obj["fact_roles"].get("context_profile", {}))
            if isinstance(obj.get("source_index"), dict):
                candidates.append(obj["source_index"].get("context_profile", {}))
            if isinstance(obj.get("interpretation_slots"), dict):
                candidates.append(obj["interpretation_slots"].get("context_profile", {}))
    for c in candidates:
        if isinstance(c, dict) and c:
            return {k: remove_internal_labels(v) if isinstance(v, str) else v for k, v in c.items()}
    return {}


def find_fact(facts, tokens, fallback=""):
    for fact in facts:
        if has_any(fact, tokens):
            return remove_internal_labels(fact)
    return remove_internal_labels(fallback)


def infer_subject(topic, facts):
    text = f"{topic} {' '.join(facts[:4])}"
    words = re.findall(r"[가-힣A-Za-zA-Z0-9]{2,}", text)
    banned = set(["만원에서", "천원까지", "몰락", "붕괴", "문제", "결과", "기준", "영상", "스크립트", "원본", "핵심", "주제"])
    for w in words:
        if w not in banned and not re.fullmatch(r"\d+", w):
            return w
    return "이 주제"


def normalize_mode(mode, profile, facts):
    mode = clean(mode)
    if mode in ["market_or_company_shift", "corporate_stock_collapse", "market_analysis", "시장/기업 분석형", "문맥형 시장/기업 분석"]:
        return "market_or_company_shift"
    if mode in ["stakeholder_conflict", "samsung_labor", "labor_conflict", "legal_conflict", "문맥형 이해관계 갈등", "사건형"]:
        return "stakeholder_conflict"
    if mode in ["howto_or_warning", "문맥형 노하우/경고", "튜토리얼/노하우형"]:
        return "howto_or_warning"
    corpus = " ".join([str(profile.get(k, "")) for k in ["result_signal", "metric_signal", "expectation_signal", "reality_signal", "conflict_signal"]] + facts[:10])
    if has_any(corpus, ["주가", "가격", "만원", "천원", "시총", "투자자", "실적", "전환사채", "매출", "적자", "차트"]):
        return "market_or_company_shift"
    if has_any(corpus, ["노조", "직원", "회사", "반발", "갈등", "요구", "파업", "소송", "법원"]):
        return "stakeholder_conflict"
    if has_any(corpus, ["방법", "실수", "체크", "주의", "해야", "노하우", "원리"]):
        return "howto_or_warning"
    return "issue_context"


def build_signal_pack(profile, facts, topic):
    subject = first_nonempty(profile.get("subject", ""), infer_subject(topic, facts), fallback="이 주제")
    result = first_nonempty(profile.get("result_signal", ""), find_fact(facts, TOKEN_GROUPS["market_price"] + ["논란", "몰락", "붕괴"], topic), fallback=topic)
    metric = first_nonempty(profile.get("metric_signal", ""), find_fact(facts, TOKEN_GROUPS["market_price"], result), fallback=result)
    expectation = first_nonempty(profile.get("expectation_signal", ""), find_fact(facts, TOKEN_GROUPS["expectation"], "처음엔 미래 성장성과 기대가 있었습니다"), fallback="처음엔 미래 성장성과 기대가 있었습니다")
    reality_raw = first_nonempty(profile.get("reality_signal", ""), find_fact(facts, TOKEN_GROUPS["verification_gap"] + TOKEN_GROUPS["financial_pressure"] + TOKEN_GROUPS["execution_risk"], "기대가 숫자로 검증되는 순간이 왔습니다"), fallback="기대가 숫자로 검증되는 순간이 왔습니다")
    conflict = first_nonempty(profile.get("conflict_signal", ""), find_fact(facts, TOKEN_GROUPS["conflict"], reality_raw), fallback=reality_raw)
    verification = find_fact(facts, TOKEN_GROUPS["verification_gap"], reality_raw if has_any(reality_raw, TOKEN_GROUPS["verification_gap"]) else "실적과 숫자가 기대를 따라오는지 확인해야 했습니다")
    finance = find_fact(facts, TOKEN_GROUPS["financial_pressure"], "현금, 부채, 자금 조달 같은 재무 부담도 다시 봐야 합니다")
    execution = find_fact(facts, TOKEN_GROUPS["execution_risk"], "사업 진행 속도와 공시된 리스크도 판단에 영향을 줍니다")
    repricing = find_fact(facts, TOKEN_GROUPS["conflict"] + TOKEN_GROUPS["market_price"], "시장은 미래 스토리보다 증명된 숫자를 보기 시작했습니다")
    return {
        "subject": subject,
        "result": remove_internal_labels(result),
        "metric": remove_internal_labels(metric),
        "expectation": remove_internal_labels(expectation),
        "reality_raw": remove_internal_labels(reality_raw),
        "verification_gap": remove_internal_labels(verification),
        "financial_pressure": remove_internal_labels(finance),
        "execution_risk": remove_internal_labels(execution),
        "market_repricing": remove_internal_labels(repricing),
        "conflict": remove_internal_labels(conflict),
    }


def analyze_source(row, selected_topic_type, context):
    facts = collect_fact_pool(row)
    profile = get_context_profile(row)
    slots = safe_json(get_value(row, "interpretation_slots"), {})
    topic = first_nonempty(
        slots.get("original_topic", "") if isinstance(slots, dict) else "",
        get_value(row, "original_topic"),
        get_value(row, "main_topic_sentence"),
        get_value(row, "title"),
        fallback="원본에 담긴 핵심 변화",
    )
    mode = normalize_mode(profile.get("mode") or get_value(row, "event_type"), profile, facts)
    signal_pack = build_signal_pack(profile, facts, topic)
    profile = {**profile, **signal_pack, "mode": mode}
    if selected_topic_type == "자동 감지":
        topic_type = {
            "market_or_company_shift": "시장/투자",
            "stakeholder_conflict": "사건/논쟁",
            "howto_or_warning": "교육/노하우",
            "issue_context": "트렌드/이슈",
        }.get(mode, "트렌드/이슈")
    else:
        topic_type = selected_topic_type
    return {
        "source_table": get_value(row, "source_table"),
        "event_type": mode,
        "topic_type": topic_type,
        "topic": remove_internal_labels(topic),
        "primary_claim": first_nonempty(get_value(row, "primary_claim"), signal_pack["result"], fallback=topic),
        "audience_problem": first_nonempty(get_value(row, "audience_pain"), "독자는 결과에 먼저 반응하지만, 그 결과를 만든 배경과 조건은 놓치기 쉽습니다"),
        "conflict": first_nonempty(get_value(row, "contradiction_or_tension"), signal_pack["conflict"], fallback="결과와 배경 사이의 간극"),
        "hidden_assumption": first_nonempty(get_value(row, "hidden_assumption"), "겉으로 보이는 결과가 곧 전체 이유라는 착각"),
        "emotional_trigger": first_nonempty(get_value(row, "emotional_trigger"), "강한 결과와 뒤늦게 드러난 맥락이 만드는 재판단 욕구"),
        "viral_hook_logic": first_nonempty(get_value(row, "viral_hook_logic"), "강한 결과를 먼저 보여주고, 그 뒤의 기대와 검증 과정을 순서대로 공개하는 구조"),
        "narrative_structure": first_nonempty(get_value(row, "narrative_structure"), "결과 제시 → 기대 공개 → 숫자 검증 → 재평가 → 판단 기준 → 질문"),
        "reusable_structure": first_nonempty(get_value(row, "reusable_structure"), "결과로 멈춰 세우고, 기대와 검증의 간극을 분해한 뒤 질문으로 닫는 구조"),
        "facts": facts,
        "profile": profile,
    }


def make_card(role, headline, body, visual_spec):
    return {
        "role": role,
        "headline": compact_lines(remove_internal_labels(headline)),
        "body": compact_lines(remove_internal_labels(body)),
        "visual_spec": visual_spec,
    }


def combine_card(card):
    headline = compact_lines(card.get("headline", ""))
    body = compact_lines(card.get("body", ""))
    return f"{headline}\n\n{body}" if body else headline


def value_headline(metric, subject):
    metric = remove_internal_labels(metric)
    numbers = NUM_RE.findall(metric)
    numbers = [n.strip() for n in numbers if n.strip()]
    if len(numbers) >= 2:
        return f"{numbers[0]}에서 {numbers[1]}까지\n무너진 건 가격만이 아닙니다"
    if len(numbers) == 1:
        return f"{numbers[0]}이라는 숫자\n그 자체가 경고였습니다"
    if has_any(metric, ["폭락", "급락", "하락", "무너", "몰락"]):
        return f"{subject}\n무너진 건 차트만이 아닙니다"
    return f"{subject}\n결과만 보면 놓치는 게 있습니다"


def selected_cta_is_generic(cta):
    cta = clean(cta)
    return not cta or any(leak in cta for leak in GENERIC_CTA_LEAKS)


def contextual_ending(analysis, selected_cta):
    custom = clean(selected_cta)
    if custom and not selected_cta_is_generic(custom):
        return remove_internal_labels(custom)
    mode = analysis.get("event_type", "issue_context")
    p = analysis.get("profile", {})
    if mode == "market_or_company_shift":
        return "다시 보려면 차트보다 먼저 확인해야 합니다. 이 기대가 아직 숫자로 증명되고 있는지, 아니면 시장이 이미 답을 바꾼 건지 말입니다."
    if mode == "stakeholder_conflict":
        return "이 갈등을 다시 본다면, 누가 더 크게 말했는지가 아니라 누가 어떤 비용을 감수하는지부터 봐야 합니다."
    if mode == "howto_or_warning":
        return "다음에 같은 상황을 만나면, 결론보다 조건을 먼저 확인해보세요. 적용 기준이 달라지면 결과도 달라집니다."
    return "이 이야기를 다시 본다면, 결론보다 먼저 그 결론을 만든 배경부터 확인해야 합니다."


def visual_spec(subject, role, main_object, scene, contrast, camera="정면에 가까운 카드뉴스형 구도", text_area="상단 25%에 헤드라인용 넓은 여백", brand_tone="eaf 브랜드 톤의 레드, 블랙, 웜 그레이 기반"):
    return {
        "visual_subject": subject,
        "role": role,
        "main_object": main_object,
        "scene": scene,
        "contrast": contrast,
        "camera": camera,
        "text_area": text_area,
        "brand_tone": brand_tone,
    }


def build_market_cards(analysis, cta):
    p = analysis["profile"]
    subject = p["subject"]
    metric = p["metric"]
    expectation = p["expectation"]
    verification = p["verification_gap"]
    finance = p["financial_pressure"]
    execution = p["execution_risk"]
    repricing = p["market_repricing"]
    conflict = p["conflict"]
    ending = contextual_ending(analysis, cta)
    return [
        make_card(
            "shock_result",
            value_headline(metric, subject),
            "그런데 이 이야기는 단순한 급락이 아닙니다. 먼저 봐야 할 건, 이 가격을 밀어올렸던 믿음이 무엇이었는지입니다.",
            visual_spec(subject, "shock_result", "수직으로 떨어지는 주가 차트, 금이 간 상징 오브젝트, 흩어진 투자자 영수증", "어두운 금융 뉴스룸 배경", "과거 기대감과 현재 급락을 강하게 대비", "살짝 내려다보는 정면 3D 인포그래픽 구도"),
        ),
        make_card(
            "old_belief",
            "처음엔 믿을 이유가 있었습니다",
            f"시장은 늘 미래를 먼저 가격에 반영합니다. 이때 사람들을 움직인 건 {shorten(expectation, 95)}였습니다.",
            visual_spec(subject, "old_belief", "빛나는 성장 그래프, 미래 사업을 상징하는 오브젝트, 기대감이 모이는 데이터 패널", "밝은 데이터룸 또는 미래형 산업 배경", "상승 기대와 아직 검증되지 않은 숫자를 대비"),
        ),
        make_card(
            "verification_gap",
            "문제는 숫자가 따라오지 못했다는 겁니다",
            f"기대가 커질수록 시장은 더 구체적인 증거를 요구합니다. 여기서 투자자가 확인해야 할 건 {shorten(verification, 100)}입니다.",
            visual_spec(subject, "verification_gap", "회계 보고서, 빨간 경고등, 꺾이는 그래프, 체크 표시가 들어간 리스크 문서", "차가운 회계 자료와 모니터가 놓인 분석 데스크", "성장 서사와 숫자 검증의 충돌을 대비"),
        ),
        make_card(
            "market_repricing",
            "시장은 더 이상 스토리만 보지 않았습니다",
            f"한 번 의심이 시작되면 기준은 바뀝니다. 미래 가능성보다 {shorten(finance, 65)}, 그리고 {shorten(repricing, 65)}가 먼저 보이기 시작합니다.",
            visual_spec(subject, "market_repricing", "계산기, 투자자 모니터, 재평가되는 차트, 빨간색과 회색 데이터 카드", "증권사 리서치룸 같은 차가운 공간", "기대에서 검증으로 바뀌는 시선을 표현"),
        ),
        make_card(
            "decision_standard",
            "핵심은 하락률이 아닙니다",
            f"중요한 건 이 하락이 과한 공포인지, 뒤늦은 재평가인지입니다. 가격보다 먼저 봐야 할 건 {shorten(execution, 80)}와 {shorten(conflict, 80)}입니다.",
            visual_spec(subject, "decision_standard", "저울, 두 갈래 길, 한쪽엔 미래 기대 그래프, 다른 쪽엔 차가운 실적표와 리스크 문서", "절제된 금융 인포그래픽 배경", "기회와 리스크가 동시에 놓인 판단 장면"),
        ),
        make_card(
            "final_question",
            "이건 기회일까요, 경고일까요?",
            ending,
            visual_spec(subject, "final_question", "갈림길 앞 투자자 실루엣, 한쪽은 반등 차트, 다른 쪽은 경고등이 켜진 리스크 표지판", "어두운 배경에 선택지가 선명하게 보이는 마무리 장면", "희망과 경고가 동시에 보이도록 대비"),
        ),
    ]


def build_conflict_cards(analysis, cta):
    p = analysis["profile"]
    subject = p["subject"]
    expectation = p["expectation"]
    conflict = p["conflict"]
    verification = p["verification_gap"]
    ending = contextual_ending(analysis, cta)
    return [
        make_card("conflict_hook", f"{subject}\n겉으로 보이는 싸움이 전부는 아닙니다", "처음 눈에 들어오는 건 강한 충돌 장면입니다. 하지만 갈등은 그 장면 하나로 끝나지 않습니다.", visual_spec(subject, "conflict_hook", "서로 마주 선 두 집단, 가운데 갈라진 선, 뉴스 헤드라인 패널", "긴장감 있는 뉴스룸 배경", "양쪽 입장이 동시에 보이는 대립 구도")),
        make_card("demand", "먼저 요구 조건을 봐야 합니다", f"갈등은 보통 요구에서 시작됩니다. 이 원문에서 먼저 확인할 것은 {shorten(expectation, 95)}입니다.", visual_spec(subject, "demand", "요구서, 숫자가 표시된 문서, 한쪽 이해관계자들의 손짓", "회의실 또는 협상 테이블", "요구의 명분과 비용을 대비")),
        make_card("response", "상대의 계산은 달랐습니다", f"반대편은 같은 장면을 다르게 봅니다. 여기서 부딪힌 현실적 조건은 {shorten(verification, 95)}입니다.", visual_spec(subject, "response", "차가운 계산서, 비용 그래프, 닫힌 회의실 문", "건조한 기업 회의실 배경", "감정적 요구와 냉정한 계산의 대비")),
        make_card("collision", "갈등은 여기서 커졌습니다", f"핵심은 누가 더 목소리가 큰지가 아닙니다. 진짜 충돌 지점은 {shorten(conflict, 95)}입니다.", visual_spec(subject, "collision", "충돌하는 화살표, 양쪽 주장 카드, 가운데 깨지는 선", "다층 인포그래픽 배경", "두 논리가 정면으로 부딪히는 장면")),
        make_card("cost", "결국 누군가는 비용을 냅니다", "이런 갈등은 승패보다 비용을 봐야 합니다. 누가 얻고, 누가 감수하는지가 판단의 핵심입니다.", visual_spec(subject, "cost", "비용 계산표, 손익 저울, 서로 다른 이해관계자 아이콘", "차분한 분석 보드", "이득과 손실을 한 화면에서 대비")),
        make_card("final_question", "당신은 어느 쪽이 더 설득력 있나요?", ending, visual_spec(subject, "final_question", "두 갈래 선택지와 중앙의 물음표, 양쪽 입장이 정리된 카드", "여백이 넓은 마무리 카드", "독자가 판단하게 만드는 균형 구도")),
    ]


def build_howto_cards(analysis, cta):
    p = analysis["profile"]
    subject = p["subject"]
    expectation = p["expectation"]
    verification = p["verification_gap"]
    execution = p["execution_risk"]
    ending = contextual_ending(analysis, cta)
    return [
        make_card("mistake_hook", f"{subject}\n그냥 따라 하면 놓치는 게 있습니다", "겉으로는 쉬워 보여도 결과가 갈리는 지점은 따로 있습니다.", visual_spec(subject, "mistake_hook", "잘못된 선택지와 올바른 선택지가 갈라진 체크리스트", "깔끔한 생활형 인포그래픽 배경", "흔한 실수와 올바른 기준을 대비")),
        make_card("why", "먼저 이유를 알아야 합니다", f"사람들이 흔히 믿는 건 {shorten(expectation, 90)}입니다. 하지만 이유를 모르면 적용이 흔들립니다.", visual_spec(subject, "why", "돋보기, 원리 도식, 핵심 이유가 연결된 화살표", "밝은 교육형 카드 배경", "결론보다 원리를 먼저 보여주는 구성")),
        make_card("condition", "중요한 건 조건입니다", f"실제로 달라지는 지점은 {shorten(verification, 95)}입니다. 조건을 놓치면 같은 방법도 다르게 작동합니다.", visual_spec(subject, "condition", "조건표, 온오프 스위치, 체크된 기준 카드", "정리된 체크리스트 보드", "성공 조건과 실패 조건을 대비")),
        make_card("risk", "여기서 실수가 갈립니다", f"주의해야 할 건 {shorten(execution, 95)}입니다. 팁보다 중요한 건 언제, 누구에게, 어떻게 적용되는지입니다.", visual_spec(subject, "risk", "경고 아이콘, 틀린 선택을 가리키는 빨간 표시, 올바른 경로", "미니멀한 경고 카드 배경", "안전한 선택과 위험한 선택을 대비")),
        make_card("checklist", "정리하면 조건부터 봐야 합니다", "무작정 따라 하기보다, 내 상황에서 이 조건이 맞는지 먼저 확인해야 합니다.", visual_spec(subject, "checklist", "세 가지 체크포인트가 적힌 카드, 손가락으로 첫 번째 항목을 가리키는 장면", "깔끔한 노하우 카드뉴스 배경", "저장하고 다시 보는 체크리스트 느낌")),
        make_card("final_action", "다음엔 이것부터 확인하세요", ending, visual_spec(subject, "final_action", "저장 버튼, 체크리스트, 작은 메모 카드", "밝고 정돈된 마무리 카드", "실행과 저장을 유도하는 구성")),
    ]


def build_issue_cards(analysis, cta):
    p = analysis["profile"]
    subject = p["subject"]
    result = p["result"]
    expectation = p["expectation"]
    conflict = p["conflict"]
    verification = p["verification_gap"]
    ending = contextual_ending(analysis, cta)
    return [
        make_card("result_hook", f"{subject}\n결론만 보면 놓치는 게 있습니다", f"사람들이 먼저 본 건 {shorten(result, 90)}입니다. 하지만 이 이야기는 그 장면 하나로 설명되지 않습니다.", visual_spec(subject, "result_hook", "강한 뉴스 헤드라인, 흐릿한 배경 자료, 중앙의 핵심 오브젝트", "뉴스 에디토리얼 배경", "결과와 숨은 배경을 대비")),
        make_card("background", "먼저 배경을 봐야 합니다", f"이 이야기가 커진 이유는 {shorten(expectation, 95)} 때문입니다. 겉으로 보이는 결론 전에 쌓인 맥락이 있습니다.", visual_spec(subject, "background", "오래된 자료 사진, 지도 또는 데이터 패널, 배경을 연결하는 선", "차분한 다큐멘터리형 카드 배경", "현재 결과와 과거 배경을 연결")),
        make_card("turning_point", "문제는 여기서 시작됩니다", f"분위기가 바뀐 지점은 {shorten(conflict, 95)}입니다. 여기서 단순한 이야기가 의문으로 바뀝니다.", visual_spec(subject, "turning_point", "갈라지는 선, 충돌하는 두 정보 카드, 중앙의 경고 표시", "긴장감 있는 인포그래픽 배경", "평온한 배경과 충돌 지점을 대비")),
        make_card("verification", "근거를 다시 봐야 합니다", f"원문에서 다시 확인해야 할 건 {shorten(verification, 95)}입니다. 결론보다 이 근거가 판단을 바꿉니다.", visual_spec(subject, "verification", "돋보기, 원문 자료, 체크된 사실 카드", "분석 데스크 배경", "표면적 반응과 실제 근거를 대비")),
        make_card("standard", "핵심은 이 간극입니다", f"중요한 건 누가 더 자극적으로 말했느냐가 아니라, {shorten(analysis.get('conflict'), 95)}입니다.", visual_spec(subject, "standard", "저울, 양쪽에 놓인 결과와 맥락, 가운데 벌어진 간극", "미니멀한 판단 기준 카드", "감정과 기준의 대비")),
        make_card("final_question", "이제 다르게 보이시나요?", ending, visual_spec(subject, "final_question", "빈 여백 위의 큰 질문, 뒤쪽에 희미한 자료와 주체들", "여백 중심 마무리 카드", "독자가 다시 생각하게 만드는 조용한 엔딩")),
    ]


def build_card_brief(analysis, cta):
    mode = analysis.get("event_type", "issue_context")
    if mode == "market_or_company_shift":
        return {"card_arc": "result_belief_verification_repricing_standard", "cards": build_market_cards(analysis, cta)}
    if mode == "stakeholder_conflict":
        return {"card_arc": "demand_response_cost", "cards": build_conflict_cards(analysis, cta)}
    if mode == "howto_or_warning":
        return {"card_arc": "mistake_reason_condition_risk", "cards": build_howto_cards(analysis, cta)}
    return {"card_arc": "result_context_gap", "cards": build_issue_cards(analysis, cta)}


def repeat_guard(cards, analysis, cta):
    for idx, card in enumerate(cards):
        card["headline"] = remove_internal_labels(card.get("headline", ""))
        card["body"] = remove_internal_labels(card.get("body", ""))
        if any(card["headline"].strip() == bad for bad in BAD_HEADLINES):
            card["headline"] = fallback_headline(idx, analysis)
        if idx in [1, 2] and len(strip_meta(card["body"])) < 45:
            card["body"] += " 원문에서 확인된 구체적인 배경과 조건을 함께 봐야 합니다."
        if idx == 5 and selected_cta_is_generic(card["body"]):
            card["body"] = contextual_ending(analysis, cta)
    joined = "\n".join([c["headline"] + "\n" + c["body"] for c in cards])
    if "현실 신호" in joined or "기대 신호" in joined:
        for card in cards:
            card["headline"] = remove_internal_labels(card["headline"])
            card["body"] = remove_internal_labels(card["body"])
    return cards


def fallback_headline(idx, analysis):
    mode = analysis.get("event_type", "issue_context")
    p = analysis.get("profile", {})
    subject = p.get("subject", "이 주제")
    table = {
        "market_or_company_shift": [value_headline(p.get("metric", ""), subject), "처음엔 믿을 이유가 있었습니다", "문제는 숫자가 따라오지 못했다는 겁니다", "시장은 더 이상 스토리만 보지 않았습니다", "핵심은 하락률이 아닙니다", "이건 기회일까요, 경고일까요?"],
        "stakeholder_conflict": [f"{subject}\n겉으로 보이는 싸움이 전부는 아닙니다", "먼저 요구 조건을 봐야 합니다", "상대의 계산은 달랐습니다", "갈등은 여기서 커졌습니다", "결국 누군가는 비용을 냅니다", "당신은 어느 쪽이 더 설득력 있나요?"],
        "howto_or_warning": [f"{subject}\n그냥 따라 하면 놓치는 게 있습니다", "먼저 이유를 알아야 합니다", "중요한 건 조건입니다", "여기서 실수가 갈립니다", "정리하면 조건부터 봐야 합니다", "다음엔 이것부터 확인하세요"],
        "issue_context": [f"{subject}\n결론만 보면 놓치는 게 있습니다", "먼저 배경을 봐야 합니다", "문제는 여기서 시작됩니다", "근거를 다시 봐야 합니다", "핵심은 이 간극입니다", "이제 다르게 보이시나요?"],
    }
    return table.get(mode, table["issue_context"])[min(idx, 5)]


def card_direction_from_spec(spec):
    if not isinstance(spec, dict):
        return clean(spec, "구체적인 오브젝트와 배경, 대비, 카메라 구도를 포함한 카드뉴스 장면")
    return (
        f"{spec.get('scene', '')}. "
        f"중앙 오브젝트: {spec.get('main_object', '')}. "
        f"대비: {spec.get('contrast', '')}. "
        f"카메라/구도: {spec.get('camera', '')}. "
        f"텍스트 영역: {spec.get('text_area', '')}. "
        f"브랜드 톤: {spec.get('brand_tone', '')}."
    ).strip()


def copy_text_for_image(card):
    headline = strip_meta(card.get("headline", ""))
    body = strip_meta(card.get("body", ""))
    headline = re.sub(r"\s+", " ", headline.replace("\n", " ")).strip()
    body = re.sub(r"\s+", " ", body.replace("\n", " ")).strip()
    for label in LABEL_WORDS:
        headline = headline.replace(label, "")
        body = body.replace(label, "")
    return shorten(headline, 48), shorten(body, 120)


def build_prompts(ctx, cards):
    ratio = RATIO_PROMPTS[ctx["image_ratio"]]
    style = VISUAL_STYLES[ctx["image_style"]]
    prompts, directions = [], []
    for card in cards:
        direction = card_direction_from_spec(card.get("visual_spec", {}))
        headline, body = copy_text_for_image(card)
        if ctx["include_image_copy"]:
            copy_rule = (
                f"Render only this Korean headline text if text is needed: '{headline}'. "
                "Do not render body copy. Do not render the labels '헤드카피', '바디카피', '카피', 'Copy intent', or any field name. "
                "Use the body copy only as conceptual context for the visual composition."
            )
        else:
            copy_rule = "clean image only, no text, no captions, no typography, no letters, no watermark, no logo"
        prompts.append(f"{ratio}, {style}. {direction} Body context for composition only: {body}. {copy_rule}")
        directions.append(direction)
    return directions, prompts


def finalize_plan(ctx, title, main_message, cards):
    tone = ctx["tone"]
    cards = repeat_guard(cards, ctx["analysis"], ctx["cta"])
    cards = [{**c, "headline": polish(c.get("headline", ""), tone), "body": polish(c.get("body", ""), tone)} for c in cards]
    directions, prompts = build_prompts(ctx, cards)
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
        "brief_debug": ctx.get("brief_debug", {}),
    }


def build_plan(ctx):
    brief = build_card_brief(ctx["analysis"], ctx["cta"])
    ctx["brief_debug"] = {"card_arc": brief.get("card_arc"), "mode": ctx["analysis"].get("event_type"), "profile": ctx["analysis"].get("profile", {})}
    topic = ctx["analysis"].get("topic", "원본 주제")
    return finalize_plan(ctx, f"[{ctx['analysis'].get('event_type', 'context')}] {shorten(topic, 44)}", ctx["analysis"].get("audience_problem", ""), brief["cards"])


def resolve_auto_angle(value, analysis):
    if value and value != "__AUTO__" and value not in ["사건의 뒷면", "문제폭로형", "오해반박형", "체크리스트형", "전후비교형", "바이럴 후킹형"]:
        return value
    mode = analysis.get("event_type", "issue_context")
    if mode == "market_or_company_shift":
        return "가격보다 먼저 봐야 할 기대와 숫자의 간극"
    if mode == "stakeholder_conflict":
        return "요구와 책임이 충돌한 지점"
    if mode == "howto_or_warning":
        return "사람들이 놓치는 적용 조건"
    return "결론 뒤에 숨은 맥락"


def resolve_auto_problem(value, analysis):
    if value and value != "__AUTO__" and "카드뉴스" not in value:
        return value
    return analysis.get("audience_problem", "독자는 결과를 먼저 보지만, 그 결과를 만든 배경과 조건은 놓치기 쉽습니다")


def select_from_dict_like(label, options, key, default=None, height=80):
    labels = list(options.keys())
    index = labels.index(default) if default in labels else 0
    selected = st.selectbox(label, labels, index=index, key=f"{key}_select")
    if selected == "직접 입력":
        return st.text_area(f"{label} 직접 입력", height=height, key=f"{key}_custom"), selected
    return options[selected], selected


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
        cards.append(make_card("manual", headline, body, {}))
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
        card = cards[idx] if idx < len(cards) else make_card("manual", "", "", {})
        with st.container(border=True):
            st.markdown(f"#### {idx + 1}장")
            headline = st.text_area("헤드카피", value=card.get("headline", ""), height=80, key=f"ot_headline_{idx}_{suffix}")
            body = st.text_area("바디카피", value=card.get("body", ""), height=115, key=f"ot_body_{idx}_{suffix}")
            direction = st.text_area("장면 방향", value=plan["directions"][idx], height=105, key=f"ot_direction_{idx}_{suffix}")
            prompt = st.text_area("이미지 생성 프롬프트", value=plan["prompts"][idx], height=150, key=f"ot_prompt_{idx}_{suffix}")
            edited_cards.append({**card, "headline": headline, "body": body})
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
    st.caption("내부 슬롯명 노출을 막고, 가격·기대·검증·재평가·판단 기준으로 카피를 분리합니다.")
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
        target_value, _ = select_from_dict_like("타깃 독자", TARGET_PRESETS, "ot_target", "일반 시청자")
        angle_value, _ = select_from_dict_like("카드뉴스 핵심 각도", ANGLE_PRESETS, "ot_angle", "자동 생성")
        problem_value, _ = select_from_dict_like("핵심 문제", PROBLEM_PRESETS, "ot_problem_preset", "자동 추출")
    with c5:
        emphasis = st.text_input("강조할 관점", placeholder="예: 가격 변화, 기대감, 실적, 자금 부담, 사업 진행 리스크")
        avoid = st.text_input("제외할 관점", placeholder="예: 원문 밖 단정, 매수/매도 추천")
        cta, _ = select_from_dict_like("엔딩/CTA", CTA_PRESETS, "ot_cta_preset", "자동 맥락형 엔딩")

    st.markdown("### 이미지 생성 조건")
    i1, i2, i3 = st.columns(3)
    with i1:
        image_ratio = st.selectbox("이미지 비율", IMAGE_RATIOS, index=0)
    with i2:
        image_style = st.selectbox("이미지 스타일", IMAGE_STYLES, index=0)
    with i3:
        include_image_copy = st.checkbox("이미지 안에 헤드카피만 넣기", value=True)
        st.caption("바디카피와 라벨은 렌더링 대상에서 제외됩니다.")

    base_context = {"content_goal": content_goal, "platform_focus": platform_focus, "analysis_depth": analysis_depth, "target_audience": target_value, "emphasis": emphasis, "avoid": avoid}
    analysis = analyze_source(row, topic_type_select, base_context)
    if topic_type_select == "직접 입력":
        analysis["topic_type"] = st.text_input("주제 유형 직접 입력", value="사용자 정의")

    effective_template = "문제 제기형" if template == "자동 최적화" else template
    angle = resolve_auto_angle(angle_value, analysis)
    problem = resolve_auto_problem(problem_value, analysis)
    common_style = f"비율: {image_ratio} / 스타일: {image_style} / 사용처: {platform_focus}."
    common_style += " 이미지 안에는 짧은 헤드카피만 포함. 바디카피는 디자인 참고용." if include_image_copy else " 텍스트 없는 클린 이미지. no text, no captions, no typography, no letters, no watermark, no logo."

    with st.expander("원본 분석 결과 / 사용된 문맥 신호", expanded=True):
        st.write(f"**감지된 주제 유형:** {analysis['topic_type']}")
        st.write(f"**문맥 모드:** {analysis['event_type']}")
        st.write(f"**원본 주제:** {analysis['topic']}")
        st.write(f"**핵심 주장:** {analysis['primary_claim']}")
        st.write(f"**독자 문제:** {analysis['audience_problem']}")
        st.write(f"**갈등/긴장 구조:** {analysis['conflict']}")
        st.markdown("##### signal_pack")
        st.json(analysis.get("profile", {}))
        if analysis.get("facts"):
            st.markdown("##### 사용 가능한 핵심 팩트")
            for fact in analysis["facts"][:10]:
                st.write(f"- {fact}")

    ctx = {"analysis": analysis, "template": effective_template, "tone": tone, "topic_type": analysis["topic_type"], "angle": angle, "problem": problem, "cta": cta, "common_style": common_style, "image_ratio": image_ratio, "image_style": image_style, "include_image_copy": include_image_copy}
    plan = build_plan(ctx)
    signature = "|".join([str(int(row["id"])), get_value(row, "source_table"), analysis["topic"], analysis["event_type"], effective_template, tone, image_ratio, image_style, str(include_image_copy), angle, problem, cta, emphasis, avoid, json.dumps(analysis.get("profile", {}), ensure_ascii=False)])
    update_state(plan, signature)

    col_refresh, col_info = st.columns([1, 3])
    with col_refresh:
        if st.button("현재 선택값으로 초안 다시 생성"):
            update_state(plan, signature, force=True)
            st.rerun()
    with col_info:
        st.info("'현실 신호' 같은 내부 슬롯명은 카피에서 제거하고, 3장·4장·5장을 숫자 검증/재평가/판단 기준으로 분리합니다.")

    st.markdown("---")
    draft = st.session_state.get("original_topic_plan", plan)
    version = st.session_state.get("original_topic_version", 0)
    edited = render_editable(draft, version)

    with st.expander("CardBrief 디버그"):
        st.json(edited.get("brief_debug", {}))

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
