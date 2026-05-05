import json
import os
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")

OPENAI_DEFAULT_MODEL = "gpt-4o"
ANTHROPIC_DEFAULT_MODEL = "claude-3-5-sonnet-latest"

IMAGE_RATIOS = ["1:1", "16:9", "9:16", "4:3"]
IMAGE_STYLES = [
    "뉴스 에디토리얼",
    "깔끔한 인포그래픽",
    "실사 시네마틱",
    "3D 애니메이션",
    "2D 일러스트",
    "웹툰/만화형",
    "미니멀 타이포그래피",
    "데이터 대시보드",
    "프리미엄 브랜드룩",
    "AI 혼합 콜라주",
]
TONE_OPTIONS = ["강한 후킹", "자극적", "폭로형", "담백하지만 날카롭게", "커뮤니티 인기글 톤"]
PROVIDERS = ["OpenAI", "Anthropic"]

STYLE_MAP = {
    "뉴스 에디토리얼": "news editorial visual, data panels, reportage mood, strong headline layout",
    "깔끔한 인포그래픽": "clean editorial infographic, organized icons, clear hierarchy, generous whitespace",
    "실사 시네마틱": "cinematic realistic photography, premium lighting, documentary tension",
    "3D 애니메이션": "stylized 3D animation, polished commercial render, dramatic composition",
    "2D 일러스트": "modern flat 2D illustration, clean shapes, editorial storytelling",
    "웹툰/만화형": "Korean webtoon inspired illustration, dynamic panels, expressive characters",
    "미니멀 타이포그래피": "minimal typography poster style, bold layout, strong negative space",
    "데이터 대시보드": "data dashboard design, charts, UI cards, analytical visual system",
    "프리미엄 브랜드룩": "premium brand campaign visual, black and warm gray palette, elegant composition",
    "AI 혼합 콜라주": "AI mixed media collage, realistic elements with graphic overlays, modern editorial texture",
}
RATIO_MAP = {
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
    if isinstance(value, (dict, list)):
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


def strip_noise(text):
    text = clean(text)
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def load_references():
    conn = connect_db()
    frames = []
    try:
        refs = pd.read_sql_query("""
            SELECT r.id, 'content_reference' AS source_table, c.platform, c.channel_name, c.category,
                   r.title, r.url, r.hook_point, r.structure_note, r.visual_note, r.eafi_application,
                   r.total_score, r.status, r.created_at
            FROM content_references r
            LEFT JOIN benchmark_channels c ON r.channel_id = c.id
            ORDER BY r.id DESC
        """, conn)
        frames.append(refs)
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
            frames.append(yt)
    except Exception:
        pass
    conn.close()
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True, sort=False)
    required = [
        "id", "source_table", "title", "channel_name", "original_topic", "main_topic_sentence", "primary_claim",
        "summary", "transcript", "keywords", "audience_pain", "hidden_assumption", "contradiction_or_tension",
        "emotional_trigger", "viral_hook_logic", "narrative_structure", "reusable_structure", "evidence_points",
        "event_timeline", "actor_map", "source_grounded_qa", "cardnews_seed", "interpretation_slots", "source_index",
        "interpretation_report", "structure_note", "hook_point", "visual_note", "eafi_application", "created_at",
    ]
    for col in required:
        if col not in df.columns:
            df[col] = ""
    return df.sort_values("created_at", ascending=False, na_position="last")


def summarize_row_for_prompt(row, max_chars=18000):
    chunks = []
    fields = [
        ("title", get_value(row, "title")),
        ("original_topic", get_value(row, "original_topic")),
        ("main_topic_sentence", get_value(row, "main_topic_sentence")),
        ("primary_claim", get_value(row, "primary_claim")),
        ("summary", get_value(row, "summary")),
        ("audience_pain", get_value(row, "audience_pain")),
        ("hidden_assumption", get_value(row, "hidden_assumption")),
        ("contradiction_or_tension", get_value(row, "contradiction_or_tension")),
        ("emotional_trigger", get_value(row, "emotional_trigger")),
        ("viral_hook_logic", get_value(row, "viral_hook_logic")),
        ("narrative_structure", get_value(row, "narrative_structure")),
        ("reusable_structure", get_value(row, "reusable_structure")),
        ("keywords", get_value(row, "keywords")),
        ("hook_point", get_value(row, "hook_point")),
        ("structure_note", get_value(row, "structure_note")),
        ("visual_note", get_value(row, "visual_note")),
        ("eafi_application", get_value(row, "eafi_application")),
    ]
    for label, value in fields:
        if clean(value):
            chunks.append(f"[{label}]\n{strip_noise(value)}")
    for key in ["evidence_points", "event_timeline", "actor_map", "source_grounded_qa", "cardnews_seed", "interpretation_slots", "source_index", "interpretation_report"]:
        obj = safe_json(get_value(row, key), None)
        if obj:
            chunks.append(f"[{key}]\n{json.dumps(obj, ensure_ascii=False)[:5000]}")
    transcript = get_value(row, "transcript")
    if transcript:
        chunks.append(f"[raw_transcript]\n{strip_noise(transcript)[:12000]}")
    source_text = "\n\n".join(chunks)
    return source_text[:max_chars]


def get_secret(name):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, "")


def extract_json(text):
    text = clean(text)
    if not text:
        raise ValueError("LLM 응답이 비어 있습니다.")
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end + 1]
    return json.loads(text)


def build_llm_prompt(source_text, options):
    ratio_prompt = RATIO_MAP[options["image_ratio"]]
    style_prompt = STYLE_MAP[options["image_style"]]
    include_copy_rule = (
        "이미지 프롬프트에는 헤드카피만 렌더링 대상으로 넣고, 바디카피는 절대 이미지 텍스트로 넣지 마라."
        if options["include_image_copy"]
        else "이미지 프롬프트는 클린 이미지 전용이다. 이미지 안에 글자, 자막, 랜덤 문자, 워터마크를 절대 넣지 마라."
    )
    return f"""
너는 한국 커뮤니티 인기글 감각을 가진 카드뉴스 기획자이자 금융/이슈 폭로형 콘텐츠 에디터다.
임무는 원문에서 가장 강력하고 자극적인 메시지를 찾아 6장 카드뉴스로 재조립하는 것이다.

절대 하지 말 것:
- 원문을 순하게 요약하지 마라.
- '먼저 배경을 봐야 합니다', '문제는 여기서 시작됩니다', '근거를 다시 봐야 합니다', '핵심은 이 간극입니다' 같은 범용 문구 금지.
- 내부 분석 라벨, 필드명, 헤드카피/바디카피라는 단어를 카드 문장에 넣지 마라.
- 원문에 없는 숫자, 인물, 사건을 새로 만들지 마라.
- 투자 조언처럼 매수/매도 판단을 단정하지 마라.

반드시 할 것:
- 원문에서 가장 센 메시지 1개를 잡아라. 예: 폭락이 아니라 탈출 순서의 문제, 개미가 갇힌 구조, 미담 뒤의 갈등, 선동과 숫자 붕괴.
- 원문 속 구체 숫자, 고유명사, 비유, 충격적 표현을 우선 사용하라.
- 6장 모두 서로 다른 역할을 가져야 한다.
- 1장은 스크롤을 멈추는 한 방이어야 한다.
- 2~5장은 원문의 증거를 압축해 점점 더 세게 몰아가야 한다.
- 6장은 댓글/공유를 부르는 강한 질문이나 결론이어야 한다.
- 이미지 방향은 오브젝트, 공간, 대비, 구도, 여백을 구체적으로 써라.

사용자 옵션:
- 톤: {options['tone']}
- 타깃: {options['target']}
- 플랫폼: {options['platform']}
- 이미지 비율: {options['image_ratio']} = {ratio_prompt}
- 이미지 스타일: {options['image_style']} = {style_prompt}
- 카피 포함 여부: {options['include_image_copy']}
- 강조 관점: {options.get('emphasis') or '원문에서 가장 강한 메시지를 자동 선택'}
- 제외 관점: {options.get('avoid') or '원문 밖 단정, 투자 조언'}
- CTA: {options.get('cta') or '맥락형 자동'}

이미지 프롬프트 규칙:
- 모든 image_prompt는 영어 중심으로 작성하되, 핵심 오브젝트와 장면 방향은 명확해야 한다.
- {include_copy_rule}
- 공통 접두어에 반드시 포함: {ratio_prompt}, {style_prompt}
- 텍스트를 넣는 경우: Render only this Korean headline text if text is needed: '헤드카피'
- Do not render body copy. Do not render labels, UI field names, captions, watermark, random letters, or extra text.

출력은 오직 JSON 객체 하나만 반환하라. 마크다운 금지.
아래 스키마를 반드시 지켜라.

{{
  "title": "카드뉴스 저장 제목",
  "content_genre": "예: 금융 스캔들 폭로형 / 자본시장 괴담형 / 노하우 경고형 / 브랜드 문제제기형",
  "strongest_message": "원문에서 가장 센 한 문장",
  "angle_options": [
    {{"name": "각도명", "hook": "후킹 문장", "why_strong": "왜 센지"}},
    {{"name": "각도명", "hook": "후킹 문장", "why_strong": "왜 센지"}},
    {{"name": "각도명", "hook": "후킹 문장", "why_strong": "왜 센지"}}
  ],
  "selected_angle": "최종 선택한 각도명",
  "target_customer": "타깃 독자",
  "core_problem": "독자가 놓치고 있는 핵심 문제",
  "main_message": "카드뉴스 전체 메시지",
  "cta": "맥락에 맞는 마지막 질문 또는 행동 유도",
  "source_facts_used": ["원문에서 실제로 사용한 팩트 5~10개"],
  "cards": [
    {{
      "page": 1,
      "role": "hook",
      "headline": "2줄 이하 헤드카피",
      "body": "1~3문장 바디카피",
      "visual_direction": "한국어 장면 방향. 오브젝트/공간/대비/구도/여백 포함",
      "image_prompt": "영문 이미지 프롬프트. 헤드카피 렌더링 규칙 포함"
    }}
  ],
  "quality_check": {{
    "is_strong_enough": true,
    "avoided_generic_phrases": true,
    "uses_specific_source_facts": true,
    "notes": "자체 검수 메모"
  }}
}}

cards는 반드시 6개만 반환하라.

원문:
{source_text}
""".strip()


def call_openai(prompt, model, temperature, max_tokens):
    api_key = get_secret("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY가 없습니다. Streamlit Secrets 또는 환경변수에 추가하세요.")
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You produce strict JSON only. You are an elite Korean editorial cardnews strategist."},
            {"role": "user", "content": prompt},
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
        "response_format": {"type": "json_object"},
    }
    res = requests.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json=payload,
        timeout=90,
    )
    if res.status_code >= 400:
        raise RuntimeError(f"OpenAI API 오류 {res.status_code}: {res.text[:1000]}")
    data = res.json()
    return data["choices"][0]["message"]["content"]


def call_anthropic(prompt, model, temperature, max_tokens):
    api_key = get_secret("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY가 없습니다. Streamlit Secrets 또는 환경변수에 추가하세요.")
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "system": "You produce strict JSON only. You are an elite Korean editorial cardnews strategist.",
        "messages": [{"role": "user", "content": prompt}],
    }
    res = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        json=payload,
        timeout=90,
    )
    if res.status_code >= 400:
        raise RuntimeError(f"Anthropic API 오류 {res.status_code}: {res.text[:1000]}")
    data = res.json()
    return "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")


def normalize_plan(plan, options):
    cards = plan.get("cards", [])
    if not isinstance(cards, list):
        cards = []
    cards = cards[:6]
    while len(cards) < 6:
        idx = len(cards) + 1
        cards.append({
            "page": idx,
            "role": "manual_fill",
            "headline": f"{idx}장 헤드카피를 확인하세요",
            "body": "LLM 응답에서 이 장의 내용이 누락됐습니다. 원문을 기준으로 직접 보완하세요.",
            "visual_direction": "구체적인 오브젝트, 배경, 대비, 구도, 여백을 포함한 카드뉴스 장면.",
            "image_prompt": f"{RATIO_MAP[options['image_ratio']]}, {STYLE_MAP[options['image_style']]}. Clean editorial cardnews image. No random text.",
        })
    plan["cards"] = cards
    for key in ["title", "content_genre", "strongest_message", "selected_angle", "target_customer", "core_problem", "main_message", "cta"]:
        plan[key] = clean(plan.get(key), "")
    if not plan["title"]:
        plan["title"] = clean(plan.get("strongest_message"), "LLM 카드뉴스 초안")[:80]
    return plan


def card_to_slide(card):
    headline = clean(card.get("headline"))
    body = clean(card.get("body"))
    return f"{headline}\n\n{body}" if body else headline


def card_to_image(card):
    return f"장면 방향:\n{clean(card.get('visual_direction'))}\n\n이미지 생성 프롬프트:\n{clean(card.get('image_prompt'))}"


def save_plan(reference_id, plan):
    cards = plan["cards"]
    slides = [card_to_slide(card) for card in cards]
    images = [card_to_image(card) for card in cards]
    conn = connect_db()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO cardnews_plans
        (reference_id, title, target_customer, core_problem, main_message, cta,
         slide_1, slide_2, slide_3, slide_4, slide_5, slide_6,
         image_1, image_2, image_3, image_4, image_5, image_6, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        reference_id, plan["title"], plan.get("target_customer", ""), plan.get("core_problem", ""), plan.get("main_message", ""), plan.get("cta", ""),
        slides[0], slides[1], slides[2], slides[3], slides[4], slides[5],
        images[0], images[1], images[2], images[3], images[4], images[5],
        "LLM 초안", datetime.now().isoformat(timespec="seconds"),
    ))
    conn.commit()
    conn.close()


def render_plan_editor(plan):
    st.markdown("### LLM 진단")
    c1, c2 = st.columns(2)
    with c1:
        title = st.text_input("저장 제목", value=plan.get("title", ""))
        content_genre = st.text_input("콘텐츠 장르", value=plan.get("content_genre", ""))
        selected_angle = st.text_input("선택 각도", value=plan.get("selected_angle", ""))
    with c2:
        strongest_message = st.text_area("가장 강한 메시지", value=plan.get("strongest_message", ""), height=80)
        cta = st.text_area("CTA / 마지막 질문", value=plan.get("cta", ""), height=80)
    core_problem = st.text_area("핵심 문제", value=plan.get("core_problem", ""), height=80)
    main_message = st.text_area("메인 메시지", value=plan.get("main_message", ""), height=80)

    st.markdown("#### 각도 후보")
    angles = plan.get("angle_options", [])
    if isinstance(angles, list) and angles:
        st.dataframe(pd.DataFrame(angles), use_container_width=True, hide_index=True)

    st.markdown("#### 사용된 원문 팩트")
    facts = plan.get("source_facts_used", [])
    if isinstance(facts, list):
        for fact in facts:
            st.write(f"- {fact}")

    edited_cards = []
    st.markdown("### 6장 카드뉴스 직접 수정")
    for idx, card in enumerate(plan.get("cards", [])[:6]):
        with st.container(border=True):
            st.markdown(f"#### {idx + 1}장")
            role = st.text_input("역할", value=clean(card.get("role", "")), key=f"llm_role_{idx}")
            headline = st.text_area("헤드카피", value=clean(card.get("headline", "")), height=75, key=f"llm_head_{idx}")
            body = st.text_area("바디카피", value=clean(card.get("body", "")), height=115, key=f"llm_body_{idx}")
            visual_direction = st.text_area("장면 방향", value=clean(card.get("visual_direction", "")), height=110, key=f"llm_visual_{idx}")
            image_prompt = st.text_area("이미지 생성 프롬프트", value=clean(card.get("image_prompt", "")), height=145, key=f"llm_prompt_{idx}")
            edited_cards.append({
                "page": idx + 1,
                "role": role,
                "headline": headline,
                "body": body,
                "visual_direction": visual_direction,
                "image_prompt": image_prompt,
            })

    edited = dict(plan)
    edited.update({
        "title": title,
        "content_genre": content_genre,
        "selected_angle": selected_angle,
        "strongest_message": strongest_message,
        "core_problem": core_problem,
        "main_message": main_message,
        "cta": cta,
        "cards": edited_cards,
    })
    return edited


def main():
    st.set_page_config(page_title="LLM 카드뉴스 생성기", page_icon="🧠", layout="wide")
    init_table()
    st.title("🧠 LLM 카드뉴스 생성기")
    st.caption("Python 규칙 템플릿이 아니라, LLM이 원문 장르와 가장 센 메시지를 직접 판단해 6장 카드뉴스를 만듭니다.")

    refs = load_references()
    mode = st.radio("원본 입력 방식", ["저장된 원본 선택", "직접 붙여넣기"], horizontal=True)
    reference_id = 0
    source_text = ""

    if mode == "저장된 원본 선택":
        if refs.empty:
            st.warning("저장된 원본이 없습니다. 직접 붙여넣기 방식을 사용하세요.")
        else:
            options = {
                f"{get_value(row, 'source_table')} · {row['id']} · {get_value(row, 'main_topic_sentence') or get_value(row, 'original_topic') or get_value(row, 'title')}": row
                for _, row in refs.iterrows()
            }
            selected = st.selectbox("원본 선택", list(options.keys()))
            row = options[selected]
            reference_id = int(row["id"])
            source_text = summarize_row_for_prompt(row)
            with st.expander("LLM에 전달될 원본 재료", expanded=False):
                st.text_area("Source Payload", value=source_text, height=360)
    else:
        source_text = st.text_area("원본 스크립트/기사/분석문 붙여넣기", height=420, placeholder="여기에 원문을 붙여넣으세요.")
        reference_id = 0

    st.markdown("---")
    st.markdown("### 생성 옵션")
    c1, c2, c3 = st.columns(3)
    with c1:
        provider = st.selectbox("LLM Provider", PROVIDERS, index=0)
        default_model = OPENAI_DEFAULT_MODEL if provider == "OpenAI" else ANTHROPIC_DEFAULT_MODEL
        model = st.text_input("모델명", value=default_model)
    with c2:
        tone = st.selectbox("카피 톤", TONE_OPTIONS, index=2)
        platform = st.selectbox("플랫폼", ["인스타 카드뉴스", "유튜브 커뮤니티", "블로그", "쓰레드", "틱톡/숏폼", "범용"], index=0)
    with c3:
        image_ratio = st.selectbox("이미지 비율", IMAGE_RATIOS, index=0)
        image_style = st.selectbox("이미지 스타일", IMAGE_STYLES, index=0)

    c4, c5, c6 = st.columns(3)
    with c4:
        target = st.text_input("타깃", value="한국 커뮤니티/투자 이슈에 반응하는 일반 독자")
        include_image_copy = st.checkbox("이미지에 헤드카피만 포함", value=True)
    with c5:
        emphasis = st.text_input("강조 관점", placeholder="예: 개미 피해 구조, 오너 탈출, 숫자 붕괴, 폭로형")
        avoid = st.text_input("제외 관점", value="원문 밖 단정, 매수/매도 추천, 법적 단정")
    with c6:
        temperature = st.slider("창의성", 0.0, 1.0, 0.65, 0.05)
        max_tokens = st.slider("최대 토큰", 2000, 8000, 5000, 500)

    cta = st.text_input("CTA/엔딩 방향", placeholder="비우면 맥락에 맞게 자동 생성")

    options = {
        "provider": provider,
        "model": model,
        "tone": tone,
        "platform": platform,
        "target": target,
        "image_ratio": image_ratio,
        "image_style": image_style,
        "include_image_copy": include_image_copy,
        "emphasis": emphasis,
        "avoid": avoid,
        "cta": cta,
    }

    if st.button("LLM으로 6장 카드뉴스 생성", type="primary"):
        if len(clean(source_text)) < 100:
            st.error("원본이 너무 짧습니다. 최소 100자 이상 필요합니다.")
        else:
            prompt = build_llm_prompt(source_text, options)
            with st.spinner("LLM이 원문에서 가장 센 메시지를 찾는 중..."):
                try:
                    raw = call_openai(prompt, model, temperature, max_tokens) if provider == "OpenAI" else call_anthropic(prompt, model, temperature, max_tokens)
                    plan = normalize_plan(extract_json(raw), options)
                    st.session_state["llm_cardnews_plan"] = plan
                    st.session_state["llm_cardnews_raw"] = raw
                    st.session_state["llm_cardnews_reference_id"] = reference_id
                    st.success("LLM 카드뉴스 초안을 생성했습니다.")
                except Exception as e:
                    st.error(f"생성 실패: {e}")
                    if "raw" in locals():
                        with st.expander("원본 LLM 응답"):
                            st.text(raw)

    plan = st.session_state.get("llm_cardnews_plan")
    if plan:
        st.markdown("---")
        edited = render_plan_editor(plan)
        st.session_state["llm_cardnews_plan"] = edited
        with st.expander("전체 JSON 보기"):
            st.code(json.dumps(edited, ensure_ascii=False, indent=2))
        col1, col2 = st.columns([1, 2])
        with col1:
            if st.button("이 LLM 설계안 저장", type="primary"):
                save_plan(st.session_state.get("llm_cardnews_reference_id", 0), edited)
                st.success("LLM 카드뉴스 설계안을 저장했습니다.")
        with col2:
            qc = edited.get("quality_check", {})
            if qc:
                st.info(f"자체 검수: {qc}")

    st.markdown("---")
    st.markdown("### 최근 저장된 카드뉴스")
    plans = pd.DataFrame()
    try:
        conn = connect_db()
        plans = pd.read_sql_query("SELECT * FROM cardnews_plans ORDER BY id DESC LIMIT 30", conn)
        conn.close()
    except Exception:
        pass
    if plans.empty:
        st.info("아직 저장된 카드뉴스가 없습니다.")
    else:
        st.dataframe(plans, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
