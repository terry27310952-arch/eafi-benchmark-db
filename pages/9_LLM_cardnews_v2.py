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
PROVIDERS = ["OpenAI", "Anthropic"]
IMAGE_RATIOS = ["1:1", "16:9", "9:16", "4:3"]
IMAGE_STYLES = ["뉴스 에디토리얼", "깔끔한 인포그래픽", "실사 시네마틱", "3D 애니메이션", "2D 일러스트", "웹툰/만화형", "데이터 대시보드", "프리미엄 브랜드룩"]
TONE_OPTIONS = ["폭로형", "커뮤니티 인기글 톤", "자극적", "강한 후킹", "담백하지만 날카롭게"]

STYLE_MAP = {
    "뉴스 에디토리얼": "news editorial visual, data panels, reportage mood, strong headline layout",
    "깔끔한 인포그래픽": "clean editorial infographic, organized icons, clear hierarchy, generous whitespace",
    "실사 시네마틱": "cinematic realistic photography, premium lighting, documentary tension",
    "3D 애니메이션": "stylized 3D animation, polished commercial render, dramatic composition",
    "2D 일러스트": "modern flat 2D illustration, clean shapes, editorial storytelling",
    "웹툰/만화형": "Korean webtoon inspired illustration, dynamic panels, expressive characters",
    "데이터 대시보드": "data dashboard design, charts, UI cards, analytical visual system",
    "프리미엄 브랜드룩": "premium brand campaign visual, black and warm gray palette, elegant composition",
}
RATIO_MAP = {"1:1": "square 1:1 composition", "16:9": "wide 16:9 horizontal composition", "9:16": "vertical 9:16 mobile story composition", "4:3": "classic 4:3 editorial composition"}

GENERIC_BAD = ["먼저 배경", "문제는 여기서", "근거를 다시", "핵심은 이 간극", "판단 기준", "다시 봐야", "중요한 건", "확인해야", "이야기는 여기서"]
LATE_PAGE_BAD = ["정리하면", "마지막 질문", "여러분은", "댓글", "어떻게 보시나요", "핵심은", "기준입니다"]


def clean(v, fallback=""):
    if v is None:
        return fallback
    s = str(v).strip()
    if s.lower() in ["nan", "none", "null"]:
        return fallback
    return s or fallback


def connect_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_table():
    conn = connect_db()
    conn.execute("""
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


def safe_json(v, fallback=None):
    fallback = {} if fallback is None else fallback
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(clean(v)) if clean(v) else fallback
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
        yt = pd.read_sql_query("SELECT * FROM youtube_video_analyses ORDER BY id DESC", conn)
        if not yt.empty:
            yt["source_table"] = "youtube_analysis"
            frames.append(yt)
    except Exception:
        pass
    try:
        refs = pd.read_sql_query("""
            SELECT r.id, 'content_reference' AS source_table, c.channel_name, r.title, r.url,
                   r.hook_point, r.structure_note, r.visual_note, r.eafi_application, r.created_at
            FROM content_references r
            LEFT JOIN benchmark_channels c ON r.channel_id = c.id
            ORDER BY r.id DESC
        """, conn)
        frames.append(refs)
    except Exception:
        pass
    conn.close()
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True, sort=False)
    for col in ["id", "source_table", "title", "original_topic", "main_topic_sentence", "primary_claim", "summary", "transcript", "keywords", "evidence_points", "event_timeline", "interpretation_slots", "source_index", "interpretation_report", "created_at"]:
        if col not in df.columns:
            df[col] = ""
    return df.sort_values("created_at", ascending=False, na_position="last")


def source_payload(row, max_chars=24000):
    parts = []
    for key in ["title", "original_topic", "main_topic_sentence", "primary_claim", "summary", "keywords", "hook_point", "structure_note", "visual_note", "eafi_application"]:
        val = get_value(row, key)
        if val:
            parts.append(f"[{key}]\n{strip_noise(val)}")
    for key in ["evidence_points", "event_timeline", "interpretation_slots", "source_index", "interpretation_report"]:
        obj = safe_json(get_value(row, key), None)
        if obj:
            parts.append(f"[{key}]\n{json.dumps(obj, ensure_ascii=False)[:6000]}")
    transcript = get_value(row, "transcript")
    if transcript:
        parts.append(f"[raw_transcript]\n{strip_noise(transcript)[:16000]}")
    return "\n\n".join(parts)[:max_chars]


def secret(name):
    try:
        if name in st.secrets:
            return st.secrets[name]
    except Exception:
        pass
    return os.getenv(name, "")


def parse_json(text):
    text = clean(text)
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fence:
        text = fence.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            text = text[start:end+1]
    return json.loads(text)


def build_prompt(source_text, opt, prior_plan=None, repair_notes=""):
    ratio = RATIO_MAP[opt["image_ratio"]]
    style = STYLE_MAP[opt["image_style"]]
    prior = ""
    if prior_plan:
        prior = f"""
[이전 초안]
{json.dumps(prior_plan, ensure_ascii=False)[:12000]}

[재작성 지시]
{repair_notes}
"""
    return f"""
너는 한국 커뮤니티에서 터지는 폭로형 카드뉴스 에디터다.
원문을 얌전하게 요약하지 말고, 가장 강한 구조적 메시지를 잡아 6장 카드뉴스로 재구성하라.

가장 중요한 규칙:
4장, 5장, 6장이 약하면 실패다.
4장은 판을 뒤집는 결정적 증거여야 한다.
5장은 가장 잔혹한 이해관계 또는 피해 구조여야 한다.
6장은 독자가 저장/공유/댓글을 하고 싶게 만드는 최종 판결이어야 한다.

4~6장 금지:
- '근거를 다시 봐야 합니다', '핵심은 이 간극입니다', '어떻게 보시나요', '판단 기준', '정리하면' 같은 말 금지.
- 평범한 요약 금지.
- 1~3장 내용 반복 금지.
- 숫자 없는 추상문 금지. 원문 숫자/고유명사/강한 비유를 최소 1개 이상 넣어라.

장별 강제 구조:
1장 hook: 원문에서 가장 자극적인 비유/피해/결과로 시작.
2장 identity_reversal: 겉으로 알려진 이미지와 실제 출발점의 반전.
3장 hype_engine: 누가/무엇이 기대를 키웠는지. 선동, 테마, 스피커, 신앙화 구조.
4장 number_collapse: 전망치/실적/회계/공시 등 숫자가 무너지는 장면. 반드시 구체 숫자 사용.
5장 trap_or_exit: 거래정지, 상폐, 오너 매도, 담보, 선순위, 개미 감금 등 가장 잔혹한 이해관계.
6장 repeat_formula: 이 사건이 반복되는 공식 또는 최종 판결. '이건 폭락이 아니라 ___의 문제였다' 급으로 끝내라.

반드시 원문에 있는 팩트만 사용하라. 법적 확정이 아닌 내용은 '의혹 구조', '본문이 지적한 구조', '정황'으로 표현하라. 투자 조언 금지.

사용자 옵션:
톤={opt['tone']}
타깃={opt['target']}
플랫폼={opt['platform']}
강조={opt.get('emphasis') or '원문에서 가장 센 메시지'}
제외={opt.get('avoid') or '원문 밖 단정, 매수/매도 추천'}
이미지={opt['image_ratio']} {ratio}, {opt['image_style']} {style}

이미지 프롬프트 규칙:
- 영어 중심, 구체 오브젝트/공간/대비/구도/텍스트 여백 포함.
- Render only this Korean headline text if text is needed: '해당 장 headline'
- Do not render body copy. Do not render labels, UI field names, captions, watermark, random letters, or extra text.

출력은 JSON 객체 하나만. 마크다운 금지.
스키마:
{{
  "title":"저장 제목",
  "content_genre":"장르",
  "strongest_message":"가장 강한 메시지",
  "selected_angle":"선택 각도",
  "target_customer":"타깃",
  "core_problem":"독자가 놓친 핵심 문제",
  "main_message":"전체 메시지",
  "cta":"마지막 질문/판결",
  "source_facts_used":["실제 사용 팩트 8개 이상"],
  "cards":[
    {{"page":1,"role":"hook","headline":"2줄 이하","body":"1~3문장","visual_direction":"한국어 장면 방향","image_prompt":"영문 프롬프트"}},
    {{"page":2,"role":"identity_reversal","headline":"","body":"","visual_direction":"","image_prompt":""}},
    {{"page":3,"role":"hype_engine","headline":"","body":"","visual_direction":"","image_prompt":""}},
    {{"page":4,"role":"number_collapse","headline":"","body":"","visual_direction":"","image_prompt":""}},
    {{"page":5,"role":"trap_or_exit","headline":"","body":"","visual_direction":"","image_prompt":""}},
    {{"page":6,"role":"repeat_formula","headline":"","body":"","visual_direction":"","image_prompt":""}}
  ],
  "quality_check":{{"late_pages_strong":true,"page4_has_specific_numbers":true,"page5_has_victim_or_exit_structure":true,"page6_has_final_verdict":true,"notes":""}}
}}

{prior}

원문:
{source_text}
""".strip()


def call_openai(prompt, model, temperature, max_tokens):
    key = secret("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY가 없습니다.")
    res = requests.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, json={"model": model, "messages": [{"role":"system", "content":"Return strict JSON only. You are a ruthless Korean editorial cardnews strategist."}, {"role":"user", "content": prompt}], "temperature": temperature, "max_tokens": max_tokens, "response_format": {"type":"json_object"}}, timeout=120)
    if res.status_code >= 400:
        raise RuntimeError(f"OpenAI API 오류 {res.status_code}: {res.text[:1000]}")
    return res.json()["choices"][0]["message"]["content"]


def call_anthropic(prompt, model, temperature, max_tokens):
    key = secret("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY가 없습니다.")
    res = requests.post("https://api.anthropic.com/v1/messages", headers={"x-api-key": key, "anthropic-version": "2023-06-01", "Content-Type": "application/json"}, json={"model": model, "max_tokens": max_tokens, "temperature": temperature, "system":"Return strict JSON only. You are a ruthless Korean editorial cardnews strategist.", "messages":[{"role":"user","content":prompt}]}, timeout=120)
    if res.status_code >= 400:
        raise RuntimeError(f"Anthropic API 오류 {res.status_code}: {res.text[:1000]}")
    return "".join(x.get("text", "") for x in res.json().get("content", []) if x.get("type") == "text")


def validate_late_pages(plan):
    notes = []
    cards = plan.get("cards", []) if isinstance(plan.get("cards"), list) else []
    if len(cards) < 6:
        notes.append("cards length < 6")
        return False, notes
    for idx in [3,4,5]:
        card = cards[idx]
        text = f"{card.get('headline','')} {card.get('body','')}"
        if any(bad in text for bad in GENERIC_BAD + LATE_PAGE_BAD):
            notes.append(f"page {idx+1} generic wording")
        if idx == 3 and not re.search(r"\d", text):
            notes.append("page 4 lacks numbers")
        if idx == 4 and not any(w in text for w in ["개미", "투자자", "오너", "매도", "담보", "상폐", "거래정지", "갇", "탈출", "피해"]):
            notes.append("page 5 lacks victim/exit/trap structure")
        if idx == 5 and not any(w in text for w in ["공식", "반복", "폭락이 아니라", "탈출", "순서", "판결", "문제였습니다", "기억"]):
            notes.append("page 6 lacks final verdict/formula")
    return len(notes) == 0, notes


def normalize_plan(plan):
    cards = plan.get("cards", []) if isinstance(plan.get("cards"), list) else []
    cards = cards[:6]
    while len(cards) < 6:
        n = len(cards) + 1
        cards.append({"page": n, "role": "missing", "headline": f"{n}장 보완 필요", "body": "LLM 응답 누락", "visual_direction": "보완 필요", "image_prompt": "Clean editorial image, no random text."})
    plan["cards"] = cards
    for k in ["title", "content_genre", "strongest_message", "selected_angle", "target_customer", "core_problem", "main_message", "cta"]:
        plan[k] = clean(plan.get(k), "")
    if not plan["title"]:
        plan["title"] = clean(plan.get("strongest_message"), "LLM V2 카드뉴스")[:80]
    return plan


def slide(card):
    return f"{clean(card.get('headline'))}\n\n{clean(card.get('body'))}".strip()


def image(card):
    return f"장면 방향:\n{clean(card.get('visual_direction'))}\n\n이미지 생성 프롬프트:\n{clean(card.get('image_prompt'))}"


def save_plan(reference_id, plan):
    cards = plan["cards"]
    slides = [slide(c) for c in cards]
    images = [image(c) for c in cards]
    conn = connect_db()
    conn.execute("""
        INSERT INTO cardnews_plans
        (reference_id, title, target_customer, core_problem, main_message, cta, slide_1, slide_2, slide_3, slide_4, slide_5, slide_6, image_1, image_2, image_3, image_4, image_5, image_6, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (reference_id, plan["title"], plan.get("target_customer", ""), plan.get("core_problem", ""), plan.get("main_message", ""), plan.get("cta", ""), slides[0], slides[1], slides[2], slides[3], slides[4], slides[5], images[0], images[1], images[2], images[3], images[4], images[5], "LLM V2", datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()


def render_editor(plan):
    st.subheader("결과 편집")
    title = st.text_input("저장 제목", value=plan.get("title", ""))
    strongest = st.text_area("가장 강한 메시지", value=plan.get("strongest_message", ""), height=80)
    main = st.text_area("메인 메시지", value=plan.get("main_message", ""), height=80)
    cta = st.text_area("CTA/최종 판결", value=plan.get("cta", ""), height=80)
    edited_cards = []
    for i, c in enumerate(plan.get("cards", [])[:6]):
        with st.container(border=True):
            st.markdown(f"#### {i+1}장 · {clean(c.get('role'))}")
            h = st.text_area("헤드카피", value=clean(c.get("headline")), height=75, key=f"v2h{i}")
            b = st.text_area("바디카피", value=clean(c.get("body")), height=120, key=f"v2b{i}")
            vd = st.text_area("장면 방향", value=clean(c.get("visual_direction")), height=110, key=f"v2v{i}")
            ip = st.text_area("이미지 프롬프트", value=clean(c.get("image_prompt")), height=140, key=f"v2p{i}")
            edited_cards.append({"page": i+1, "role": clean(c.get("role")), "headline": h, "body": b, "visual_direction": vd, "image_prompt": ip})
    edited = dict(plan)
    edited.update({"title": title, "strongest_message": strongest, "main_message": main, "cta": cta, "cards": edited_cards})
    return edited


def main():
    st.set_page_config(page_title="LLM 카드뉴스 V2", page_icon="🔥", layout="wide")
    init_table()
    st.title("🔥 LLM 카드뉴스 V2")
    st.caption("4·5·6장이 약하면 자동 재작성하는 폭로형 카드뉴스 생성기")
    refs = load_references()
    mode = st.radio("입력 방식", ["저장된 원본 선택", "직접 붙여넣기"], horizontal=True)
    reference_id = 0
    source_text = ""
    if mode == "저장된 원본 선택" and not refs.empty:
        choices = {f"{get_value(r,'source_table')} · {r['id']} · {get_value(r,'main_topic_sentence') or get_value(r,'original_topic') or get_value(r,'title')}": r for _, r in refs.iterrows()}
        row = choices[st.selectbox("원본 선택", list(choices.keys()))]
        reference_id = int(row["id"])
        source_text = source_payload(row)
        with st.expander("전달 원문 보기"):
            st.text_area("source", value=source_text, height=300)
    else:
        source_text = st.text_area("원본 붙여넣기", height=360)

    st.markdown("---")
    c1,c2,c3 = st.columns(3)
    with c1:
        provider = st.selectbox("Provider", PROVIDERS)
        model = st.text_input("모델명", value=OPENAI_DEFAULT_MODEL if provider == "OpenAI" else ANTHROPIC_DEFAULT_MODEL)
    with c2:
        tone = st.selectbox("톤", TONE_OPTIONS)
        platform = st.selectbox("플랫폼", ["인스타 카드뉴스", "유튜브 커뮤니티", "쓰레드", "블로그", "범용"])
    with c3:
        image_ratio = st.selectbox("이미지 비율", IMAGE_RATIOS)
        image_style = st.selectbox("이미지 스타일", IMAGE_STYLES)
    target = st.text_input("타깃", value="한국 커뮤니티/투자 이슈에 반응하는 일반 독자")
    emphasis = st.text_input("강조 관점", value="개미 피해 구조, 오너 탈출, 숫자 붕괴, 상장폐지, 반복 공식")
    avoid = st.text_input("제외 관점", value="원문 밖 단정, 매수/매도 추천, 범죄 확정 표현")
    temperature = st.slider("창의성", 0.0, 1.0, 0.7, 0.05)
    max_tokens = st.slider("최대 토큰", 3000, 9000, 6500, 500)
    include_image_copy = st.checkbox("이미지에 헤드카피만 포함", value=True)
    opt = {"tone": tone, "platform": platform, "target": target, "image_ratio": image_ratio, "image_style": image_style, "include_image_copy": include_image_copy, "emphasis": emphasis, "avoid": avoid}

    if st.button("V2로 생성", type="primary"):
        if len(clean(source_text)) < 100:
            st.error("원본이 너무 짧습니다.")
        else:
            try:
                with st.spinner("1차 생성 중..."):
                    prompt = build_prompt(source_text, opt)
                    raw = call_openai(prompt, model, temperature, max_tokens) if provider == "OpenAI" else call_anthropic(prompt, model, temperature, max_tokens)
                    plan = normalize_plan(parse_json(raw))
                ok, notes = validate_late_pages(plan)
                if not ok:
                    with st.spinner("4·5·6장 약함 감지. 자동 재작성 중..."):
                        repair = "4·5·6장이 약하다. 아래 문제를 반드시 고쳐라: " + "; ".join(notes) + ". 4장은 숫자 붕괴, 5장은 피해/탈출/감금 구조, 6장은 반복 공식 또는 최종 판결로 재작성하라. 1~3장은 유지해도 된다."
                        prompt2 = build_prompt(source_text, opt, plan, repair)
                        raw2 = call_openai(prompt2, model, temperature, max_tokens) if provider == "OpenAI" else call_anthropic(prompt2, model, temperature, max_tokens)
                        plan = normalize_plan(parse_json(raw2))
                        ok, notes = validate_late_pages(plan)
                plan["quality_check"] = plan.get("quality_check", {})
                plan["quality_check"]["late_page_validation_passed"] = ok
                plan["quality_check"]["late_page_notes"] = notes
                st.session_state["v2_plan"] = plan
                st.session_state["v2_reference_id"] = reference_id
                st.success("생성 완료")
            except Exception as e:
                st.error(f"실패: {e}")

    if st.session_state.get("v2_plan"):
        st.markdown("---")
        edited = render_editor(st.session_state["v2_plan"])
        st.session_state["v2_plan"] = edited
        with st.expander("JSON 보기"):
            st.code(json.dumps(edited, ensure_ascii=False, indent=2))
        if st.button("V2 설계안 저장", type="primary"):
            save_plan(st.session_state.get("v2_reference_id", 0), edited)
            st.success("저장 완료")

if __name__ == "__main__":
    main()
