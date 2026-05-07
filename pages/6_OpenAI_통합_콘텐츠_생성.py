import ast
import hashlib
import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

DB_PATH = Path("eafi_benchmark.db")
OUTPUT_TYPES = ["카드뉴스 6장", "1분 쇼츠 대본", "5분 미드폼 유튜브 대본"]
PROVIDERS = ["규칙 기반만 사용", "OpenAI", "Gemini", "Groq", "OpenRouter"]
DEFAULT_MODELS = {
    "OpenAI": "gpt-5-mini",
    "Gemini": "gemini-2.0-flash-lite",
    "Groq": "llama-3.1-8b-instant",
    "OpenRouter": "openrouter/auto",
}
SECRET_NAMES = {
    "OpenAI": "OPENAI_API_KEY",
    "Gemini": "GEMINI_API_KEY",
    "Groq": "GROQ_API_KEY",
    "OpenRouter": "OPENROUTER_API_KEY",
}
IMAGE_RATIOS = ["1:1", "16:9", "9:16", "4:3"]
IMAGE_STYLES = ["깔끔한 인포그래픽", "뉴스 에디토리얼", "실사 시네마틱", "3D 애니메이션", "미니멀 타이포그래피", "프리미엄 브랜드룩"]
TONES = ["담백", "명확", "강한 후킹", "자극적"]

TEXT_KEYS = ["text", "body", "content", "fact", "event", "answer", "basis", "source", "quote", "summary", "claim", "script"]
SKIP_KEYS = {"id", "role", "card_no", "step", "type", "label", "score"}
NUMBER_RE = re.compile(r"\d+(?:[,.]\d+)?\s*(?:만원|천원|원|달러|조|억|%|배|명|개|건|년|개월|일)")
BAD_COPY = ["현실 신호", "핵심 포인트", "핵심 단서", "판단 기준", "정리하면", "마지막 질문", "head_copy", "body_copy", "Copy intent"]
BAD_IMAGE = ["head_copy", "body_copy", "headline", "body", "헤드카피", "바디카피", "Copy intent", "caption:", "title:"]
DRIFT_TERMS = ["테마주", "급등주", "상장폐지", "거래정지", "리튬", "배터리", "광산", "가전라인", "성과급", "노조", "주가", "차트", "소액주주", "시총"]
SIGNALS = ["하지만", "그런데", "반면", "문제는", "결국", "이유", "때문", "요구", "주장", "충돌", "갈등", "비용", "손해", "이익", "위험", "리스크", "선택", "폐쇄", "통제", "검증", "확인"]


def parse_obj(value):
    if isinstance(value, (dict, list, tuple)):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not ((text.startswith("{") and text.endswith("}")) or (text.startswith("[") and text.endswith("]"))):
        return None
    try:
        return json.loads(text)
    except Exception:
        try:
            return ast.literal_eval(text)
        except Exception:
            return None


def flatten(value, depth=0):
    if depth > 7 or value is None:
        return []
    parsed = parse_obj(value)
    if parsed is not None and parsed is not value:
        return flatten(parsed, depth + 1)
    if isinstance(value, dict):
        out = []
        for key in TEXT_KEYS:
            if key in value:
                out.extend(flatten(value.get(key), depth + 1))
        if out:
            return out
        for key, item in value.items():
            if str(key) not in SKIP_KEYS:
                out.extend(flatten(item, depth + 1))
        return out
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            out.extend(flatten(item, depth + 1))
        return out
    text = str(value).strip()
    if not text or text.lower() in ["nan", "none", "null"]:
        return []
    return [text]


def clean(value, fallback=""):
    if value is None:
        return fallback
    text = " ".join(flatten(value)) if isinstance(value, (dict, list, tuple)) else str(value).strip()
    parsed = parse_obj(text)
    if parsed is not None:
        text = " ".join(flatten(parsed))
    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\[[sS]?\d+\]", "", text)
    text = re.sub(r"['\"](?:id|text|source|fact|event|role)['\"]\s*:\s*", " ", text)
    text = re.sub(r"[\[\]{}]+", " ", text)
    for bad in BAD_COPY:
        text = text.replace(bad, "")
    fixes = {"왔습니다입니다": "왔습니다", "합니다입니다": "합니다", "됩니다입니다": "됩니다", "있습니다입니다": "있습니다", "입니다입니다": "입니다", "니다입니다": "니다", "요입니다": "요"}
    for old, new in fixes.items():
        text = text.replace(old, new)
    return re.sub(r"\s+", " ", text).strip(" ,:;") or fallback


def shorten(text, limit=150):
    text = clean(text)
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def split_sentences(text):
    text = clean(text)
    parts = re.split(r"(?<=[.!?。！？])\s+|(?<=다)\s+|(?<=요)\s+|(?<=죠)\s+|(?<=습니다)\s+|\n+", text)
    return [clean(p) for p in parts if len(clean(p)) > 12]


def get_secret(name):
    try:
        return st.secrets.get(name, "")
    except Exception:
        return ""


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_tables():
    conn = db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS generated_content_outputs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            reference_id INTEGER,
            output_type TEXT,
            provider TEXT,
            model TEXT,
            title TEXT,
            body_text TEXT,
            body_json TEXT,
            created_at TEXT NOT NULL
        )
    """)
    conn.commit()
    conn.close()


def rv(row, key, fallback=""):
    try:
        return clean(row.get(key, fallback), fallback)
    except Exception:
        try:
            return clean(row[key], fallback)
        except Exception:
            return fallback


def load_refs():
    conn = db()
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
            SELECT r.id, 'content_reference' AS source_table, c.channel_name, r.title, r.hook_point,
                   r.structure_note, r.visual_note, r.eafi_application, r.created_at
            FROM content_references r
            LEFT JOIN benchmark_channels c ON r.channel_id = c.id
            ORDER BY r.id DESC
        """, conn)
        if not refs.empty:
            frames.append(refs)
    except Exception:
        pass
    conn.close()
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True, sort=False)
    for col in ["original_topic", "main_topic_sentence", "primary_claim", "summary", "transcript", "keywords", "event_type", "interpretation_slots", "cardnews_seed", "source_index", "evidence_points", "event_timeline", "audience_pain", "contradiction_or_tension", "hidden_assumption", "source_grounded_qa", "cause_effect_chain", "interpretation_report", "hook_point", "structure_note", "visual_note", "eafi_application"]:
        if col not in df.columns:
            df[col] = ""
    return df


def full_source_text(row):
    keys = ["original_topic", "main_topic_sentence", "primary_claim", "summary", "transcript", "hook_point", "structure_note", "visual_note", "eafi_application"]
    pieces = [rv(row, k) for k in keys]
    for key in ["evidence_points", "event_timeline", "source_grounded_qa", "cause_effect_chain", "interpretation_slots", "cardnews_seed", "source_index", "interpretation_report"]:
        raw = row.get(key, "") if hasattr(row, "get") else ""
        pieces.extend(flatten(parse_obj(raw) or raw))
    return "\n".join([clean(p) for p in pieces if clean(p)])


def numbers(text):
    out = []
    for n in NUMBER_RE.findall(clean(text)):
        if n not in out:
            out.append(n)
    return out[:20]


def evidence_role(sent):
    s = clean(sent)
    if any(x in s for x in ["하지만", "그런데", "반면", "문제는", "충돌", "갈등"]):
        return "tension"
    if any(x in s for x in ["요구", "주장", "말했", "제안", "선언"]):
        return "claim_or_demand"
    if any(x in s for x in ["때문", "이유", "원인", "배경"]):
        return "background"
    if any(x in s for x in ["결국", "결과", "현재", "지금"]):
        return "result"
    if numbers(s):
        return "number_or_evidence"
    return "context"


def collect_evidence(source_text):
    seen, scored = set(), []
    for sent in split_sentences(source_text):
        if len(sent) < 16:
            continue
        score = 1 + min(5, len(numbers(sent)) * 2) + sum(1 for sig in SIGNALS if sig in sent)
        if 35 <= len(sent) <= 230:
            score += 2
        if len(sent) > 360:
            score -= 2
        key = re.sub(r"[^가-힣A-Za-z0-9]", "", sent[:90])
        if key and key not in seen:
            seen.add(key)
            scored.append((score, sent))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [{"id": f"E{i+1}", "fact": shorten(sent, 230), "role": evidence_role(sent), "why_it_matters": ""} for i, (_, sent) in enumerate(scored[:24])]


def compact_source(text, limit=14000):
    text = clean(text)
    if len(text) <= limit:
        return text
    head = int(limit * 0.72)
    return text[:head].rstrip() + "\n\n...[중간 생략: 후보 근거는 evidence_bank에 보존됨]...\n\n" + text[-(limit-head):].lstrip()


def seed_source_map(row):
    source_text = full_source_text(row)
    title = rv(row, "original_topic") or rv(row, "main_topic_sentence") or rv(row, "title") or "원본 주제"
    evidence = collect_evidence(source_text)
    surface = evidence[0]["fact"] if evidence else clean(title)
    return {
        "source_title": clean(title),
        "source_hash": hashlib.md5(clean(source_text).encode("utf-8")).hexdigest()[:10],
        "source_length": len(source_text),
        "source_excerpt": compact_source(source_text),
        "numbers": numbers(source_text)[:12],
        "one_sentence_summary": clean(title),
        "surface_story": surface,
        "real_story": "표면적인 결론보다 그 결론을 만든 조건, 이해관계, 근거를 따라가야 하는 이야기입니다.",
        "central_tension": rv(row, "contradiction_or_tension") or "겉으로 보이는 주장과 실제 판단 기준이 충돌하는 지점입니다.",
        "audience_blind_spot": rv(row, "audience_pain") or "독자는 결과에 먼저 반응하지만, 그 결과를 만든 맥락은 놓치기 쉽습니다.",
        "hidden_assumption": rv(row, "hidden_assumption") or "당연하다고 받아들이는 전제가 실제로는 검증되어야 한다는 점입니다.",
        "stakes": "이 선택이나 사건이 누구에게 어떤 비용과 영향을 남기는지 확인해야 합니다.",
        "key_actors": [],
        "evidence_bank": evidence,
        "causal_chain": [{"step": i + 1, "event": e["fact"], "why_it_matters": e["role"]} for i, e in enumerate(evidence[:6])],
        "editorial_angles": [{"angle": "결과가 아니라 결과를 만든 구조를 추적하는 관점", "rationale": "독자가 놓치는 건 대개 결론 이전의 조건과 이해관계입니다.", "risk": "너무 추상적으로 쓰면 원본 고유성이 사라집니다."}],
        "chosen_angle": "결과가 아니라 결과를 만든 구조를 추적하는 관점",
        "card_plan": [
            {"card_no": 1, "role": "hook", "question": "가장 먼저 독자를 멈춰 세울 표면 결과는 무엇인가?", "evidence_ids": ["E1"], "must_explain": "결과 뒤에 더 큰 맥락이 있음을 암시한다."},
            {"card_no": 2, "role": "background", "question": "이 일이 왜 시작됐고 왜 사람들이 반응했나?", "evidence_ids": ["E2"], "must_explain": "원본의 배경을 구체적으로 설명한다."},
            {"card_no": 3, "role": "actor_logic", "question": "등장 주체들은 각각 무엇을 원하고 무엇을 감수하나?", "evidence_ids": ["E3"], "must_explain": "주체별 이해관계를 보여준다."},
            {"card_no": 4, "role": "tension", "question": "어디서 논리와 이해관계가 충돌하나?", "evidence_ids": ["E4"], "must_explain": "핵심 대립을 원본 근거로 설명한다."},
            {"card_no": 5, "role": "stakes", "question": "이 선택이 현실화되면 누가 어떤 비용을 치르나?", "evidence_ids": ["E5"], "must_explain": "피해, 비용, 리스크, 후폭풍을 설명한다."},
            {"card_no": 6, "role": "lesson", "question": "이 원본이 남기는 판단 기준은 무엇인가?", "evidence_ids": ["E6"], "must_explain": "원본에 맞는 질문이나 체크 기준으로 닫는다."},
        ],
        "avoid_angles": ["원본에 없는 도메인 템플릿 끼워넣기", "키워드 하나로 주제 유형을 고정하기", "비슷한 문장 반복하기"],
    }


def interpretation_prompt(seed):
    return f"""
너는 원본을 먼저 읽고 편집 가능한 Source Map으로 바꾸는 콘텐츠 해석기다.
분기 로직, 고정 도메인 템플릿, 키워드 매칭식 판단을 쓰지 마라.
원본 자체에서 표면 이야기, 진짜 이야기, 등장 주체, 이해관계, 원인과 결과, 독자가 놓치는 지점을 추론하라.
원본에 없는 도메인 단어를 넣지 마라.
반드시 JSON만 출력한다.

seed_source_map:
{json.dumps(seed, ensure_ascii=False, indent=2)}

출력 형식:
{{"source_title":"", "one_sentence_summary":"", "surface_story":"", "real_story":"", "central_tension":"", "audience_blind_spot":"", "hidden_assumption":"", "stakes":"", "key_actors":[{{"name":"", "position":"", "wants":"", "risk_or_cost":""}}], "evidence_bank":[{{"id":"E1", "fact":"", "role":"", "why_it_matters":""}}], "causal_chain":[{{"step":1, "event":"", "why_it_matters":""}}], "editorial_angles":[{{"angle":"", "rationale":"", "risk":""}}], "chosen_angle":"", "card_plan":[{{"card_no":1, "role":"", "question":"", "evidence_ids":["E1"], "must_explain":""}}], "avoid_angles":[]}}

조건:
- card_plan은 정확히 6개.
- evidence_bank는 원본에 있는 내용만 사용.
- 각 카드의 질문은 원본에 맞게 달라져야 한다.
"""


def normalize_source_map(obj, seed):
    if not isinstance(obj, dict):
        return seed
    out = seed.copy()
    for key in ["source_title", "one_sentence_summary", "surface_story", "real_story", "central_tension", "audience_blind_spot", "hidden_assumption", "stakes", "chosen_angle"]:
        out[key] = clean(obj.get(key), out.get(key, ""))
    for key in ["key_actors", "evidence_bank", "causal_chain", "editorial_angles", "card_plan", "avoid_angles"]:
        if isinstance(obj.get(key), list) and obj.get(key):
            out[key] = obj[key]
    if len(out.get("card_plan", [])) != 6:
        out["card_plan"] = seed["card_plan"]
    out["evidence_bank"] = normalize_evidence(out.get("evidence_bank", []), seed.get("evidence_bank", []))
    return out


def normalize_evidence(items, fallback):
    result = []
    for i, item in enumerate(items[:24]):
        fact = clean(item.get("fact") or item.get("text") or item.get("event") if isinstance(item, dict) else item)
        if fact:
            result.append({"id": f"E{i+1}", "fact": fact, "role": evidence_role(fact), "why_it_matters": clean(item.get("why_it_matters"), "") if isinstance(item, dict) else ""})
    return result or fallback


def extract_response_text(data):
    if isinstance(data, dict) and data.get("output_text"):
        return data["output_text"]
    chunks = []
    for item in data.get("output", []) if isinstance(data, dict) else []:
        for content in item.get("content", []):
            if content.get("type") in ["output_text", "text"] and content.get("text"):
                chunks.append(content["text"])
    return "\n".join(chunks)


def explain_http_error(provider, err):
    status = getattr(err.response, "status_code", None) if getattr(err, "response", None) is not None else None
    if status == 400:
        return f"{provider} 요청 형식 또는 모델명이 맞지 않습니다. 모델명과 JSON 출력 옵션을 확인하세요."
    if status == 401:
        return f"{provider} API Key 인증에 실패했습니다. secrets key 또는 직접 입력한 키를 확인하세요."
    if status == 403:
        return f"{provider} API 권한이 막혀 있습니다. 해당 모델 접근 권한이나 결제/프로젝트 권한을 확인하세요."
    if status == 429:
        return f"{provider} 호출 제한에 걸렸습니다. 잠시 후 다시 시도하거나 다른 Provider를 선택하세요."
    if status and status >= 500:
        return f"{provider} 서버 쪽 오류입니다. 잠시 후 재시도하거나 다른 Provider를 쓰세요."
    return f"{provider} 호출 중 HTTP 오류가 발생했습니다. 상태코드: {status or 'unknown'}"


def call_llm(provider, key, model, prompt, temperature):
    if provider == "OpenAI":
        payload = {"model": model, "input": prompt, "temperature": temperature, "text": {"format": {"type": "json_object"}}}
        res = requests.post("https://api.openai.com/v1/responses", json=payload, headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"}, timeout=150)
        res.raise_for_status()
        return extract_response_text(res.json())
    if provider == "Gemini":
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}"
        payload = {"contents": [{"parts": [{"text": prompt}]}], "generationConfig": {"temperature": temperature, "responseMimeType": "application/json"}}
        res = requests.post(url, json=payload, timeout=120)
        res.raise_for_status()
        return res.json()["candidates"][0]["content"]["parts"][0]["text"]
    url = "https://api.groq.com/openai/v1/chat/completions" if provider == "Groq" else "https://openrouter.ai/api/v1/chat/completions"
    headers = {"Authorization": f"Bearer {key}", "Content-Type": "application/json"}
    if provider == "OpenRouter":
        headers.update({"HTTP-Referer": "https://eafi-benchmark-db.streamlit.app", "X-Title": "EAFI Content Generator"})
    payload = {"model": model, "messages": [{"role": "system", "content": "Return valid JSON only."}, {"role": "user", "content": prompt}], "temperature": temperature}
    res = requests.post(url, json=payload, headers=headers, timeout=120)
    res.raise_for_status()
    return res.json()["choices"][0]["message"]["content"]


def safe_call_llm(provider, key, model, prompt, temperature):
    if provider == "규칙 기반만 사용" or not key or not model:
        return None, "", "LLM 미사용 또는 API Key/Model 누락"
    try:
        return call_llm(provider, key, model, prompt, temperature), "", ""
    except requests.HTTPError as err:
        return None, "", explain_http_error(provider, err)
    except requests.Timeout:
        return None, "", f"{provider} 호출 시간이 초과됐습니다. 원본이 길면 모델을 바꾸거나 다시 시도하세요."
    except requests.RequestException as err:
        return None, "", f"{provider} 네트워크 호출 오류: {type(err).__name__}"
    except Exception as err:
        return None, "", f"{provider} 처리 오류: {type(err).__name__}"


def parse_json(text):
    text = clean(text)
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    try:
        return json.loads(text)
    except Exception:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def safe_parse_json(text):
    try:
        return parse_json(text), ""
    except Exception as err:
        return {}, f"JSON 파싱 실패: {type(err).__name__}"


def interpret_source(provider, key, model, seed, temperature):
    prompt = interpretation_prompt(seed)
    raw, _, error = safe_call_llm(provider, key, model, prompt, temperature)
    if error or not raw:
        return seed, raw or "", len(prompt), error
    parsed, parse_error = safe_parse_json(raw)
    if parse_error:
        return seed, raw, len(prompt), parse_error
    return normalize_source_map(parsed, seed), raw, len(prompt), ""


def card_scene(head, body):
    return f"원본의 핵심 긴장과 이해관계를 시각화한 카드뉴스 장면. 중심 오브젝트는 '{shorten(head, 28)}'의 의미를 상징하고, 배경에는 서로 다른 선택지와 근거 자료가 대비되는 구성"


def rule_output(output_type, source_map):
    if output_type == "카드뉴스 6장":
        ev = source_map.get("evidence_bank", [])
        cards = []
        for i, plan in enumerate(source_map.get("card_plan", [])[:6]):
            fact = ev[i]["fact"] if i < len(ev) else source_map.get("surface_story", "")
            q = clean(plan.get("question"), f"{i+1}장 핵심 질문")
            must = clean(plan.get("must_explain"), "")
            if i == 0:
                head = shorten(source_map.get("surface_story"), 42)
                body = f"이 이야기는 한 문장의 결론으로 끝나지 않습니다. 핵심은 {shorten(source_map.get('real_story'), 110)}"
            elif i == 5:
                head = shorten(source_map.get("chosen_angle") or "이 이야기가 남기는 질문", 42)
                body = f"다시 볼 때는 이 질문이 필요합니다. {q} {shorten(source_map.get('stakes'), 90)}"
            else:
                head = shorten(q, 42)
                body = f"{must} 원본에서 봐야 할 근거는 {shorten(fact, 135)}입니다."
            cards.append({"headline": head, "body": body, "scene": card_scene(head, body)})
        return {"title": source_map.get("source_title", "카드뉴스"), "core_problem": source_map.get("audience_blind_spot", ""), "main_message": source_map.get("chosen_angle", ""), "cta": "이 이야기를 다시 본다면 무엇부터 확인해야 할까요?", "cards": cards}
    if output_type == "1분 쇼츠 대본":
        script = f"0초\n{source_map.get('surface_story','')}\n이 결론만 보면 놓치는 게 있습니다.\n\n10초\n{source_map.get('real_story','')}\n\n25초\n핵심 긴장은 여기서 생깁니다.\n{source_map.get('central_tension','')}\n\n45초\n왜 중요하냐면, {source_map.get('stakes','')}\n\n60초\n이 이야기를 다시 본다면 무엇부터 확인해야 할까요?"
        return {"title": source_map.get("source_title", "1분 쇼츠"), "hook": source_map.get("surface_story", ""), "script": clean(script), "shot_plan": [], "cta": "댓글로 여러분의 판단을 남겨주세요."}
    script = f"오프닝\n{source_map.get('surface_story','')}\n\n표면 이야기\n{source_map.get('one_sentence_summary','')}\n\n진짜 이야기\n{source_map.get('real_story','')}\n\n핵심 긴장\n{source_map.get('central_tension','')}\n\n근거\n{' '.join([e.get('fact','') for e in source_map.get('evidence_bank', [])[:4]])}\n\n마무리\n{source_map.get('stakes','')} 여러분은 이 흐름을 어떻게 보시나요?"
    return {"title": source_map.get("source_title", "5분 미드폼"), "hook": source_map.get("surface_story", ""), "script": clean(script), "chapter_plan": [], "cta": "여러분은 이 흐름을 어떻게 보시나요?"}


def content_prompt(output_type, source_map, tone, ratio, style, include_copy, issues=None, previous=""):
    base = f"""
너는 Source Map을 콘텐츠로 바꾸는 편집자다.
분기형 템플릿을 쓰지 말고 source_map에 있는 원본 맥락만 사용하라.
원본에 없는 도메인 단어와 프레임을 끼워넣지 마라.
반드시 JSON만 출력한다.
어조: {tone}

source_map:
{json.dumps(source_map, ensure_ascii=False, indent=2)}
"""
    if issues:
        base += f"\n이전 결과 문제점:\n{chr(10).join('- ' + x for x in issues)}\n기존 출력:\n{previous}\n"
    if output_type == "카드뉴스 6장":
        return base + f"""
출력 형식: {{"title":"", "core_problem":"", "main_message":"", "cta":"", "cards":[{{"headline":"", "body":"", "scene":""}}]}}
규칙:
- cards는 정확히 6개.
- card_plan 1~6의 질문과 역할을 따라가되 문장은 자연스럽게 새로 쓴다.
- 각 장은 evidence_bank의 구체 근거를 최소 하나 반영한다.
- 2장과 3장은 배경과 이해관계를 충분히 설명한다.
- 내부 필드명, id, text, evidence_id를 출력하지 마라.
- scene에는 시각 장면만 쓴다.
- 이미지 비율 {ratio}, 이미지 스타일 {style}, 헤드라인 렌더링 {include_copy}
"""
    if output_type == "1분 쇼츠 대본":
        return base + "출력 형식: {\"title\":\"\", \"hook\":\"\", \"script\":\"\", \"shot_plan\":[{\"time\":\"\", \"visual\":\"\"}], \"cta\":\"\"}\n55~70초 분량, surface_story → real_story → central_tension → stakes 순서로 구어체 작성."
    return base + "출력 형식: {\"title\":\"\", \"hook\":\"\", \"script\":\"\", \"chapter_plan\":[{\"section\":\"\", \"purpose\":\"\"}], \"cta\":\"\"}\n약 5분 분량, 표면 이야기 → 진짜 이야기 → 등장 주체 → 핵심 긴장 → 근거 → 판단 기준 → 마무리."


def normalize_output(output_type, obj, fallback):
    if not isinstance(obj, dict):
        return fallback
    if output_type == "카드뉴스 6장":
        raw_cards = obj.get("cards") if isinstance(obj.get("cards"), list) else []
        cards = []
        for i in range(6):
            base = fallback.get("cards", [{}] * 6)[i]
            src = raw_cards[i] if i < len(raw_cards) and isinstance(raw_cards[i], dict) else {}
            cards.append({"headline": clean(src.get("headline") or src.get("head_copy"), base.get("headline", "")), "body": clean(src.get("body") or src.get("body_copy"), base.get("body", "")), "scene": sanitize_scene(src.get("scene") or src.get("image_description") or base.get("scene", ""))})
        return {"title": clean(obj.get("title"), fallback.get("title", "")), "core_problem": clean(obj.get("core_problem"), fallback.get("core_problem", "")), "main_message": clean(obj.get("main_message"), fallback.get("main_message", "")), "cta": clean(obj.get("cta"), fallback.get("cta", "")), "cards": cards}
    if output_type == "1분 쇼츠 대본":
        return {"title": clean(obj.get("title"), fallback.get("title", "")), "hook": clean(obj.get("hook"), fallback.get("hook", "")), "script": clean(obj.get("script"), fallback.get("script", "")), "shot_plan": obj.get("shot_plan") if isinstance(obj.get("shot_plan"), list) else [], "cta": clean(obj.get("cta"), fallback.get("cta", ""))}
    return {"title": clean(obj.get("title"), fallback.get("title", "")), "hook": clean(obj.get("hook"), fallback.get("hook", "")), "script": clean(obj.get("script"), fallback.get("script", "")), "chapter_plan": obj.get("chapter_plan") if isinstance(obj.get("chapter_plan"), list) else [], "cta": clean(obj.get("cta"), fallback.get("cta", ""))}


def validate_cardnews(cards, source_map, source_text):
    issues = []
    if len(cards) != 6:
        issues.append("카드 수가 정확히 6장이 아님")
    joined = " ".join([clean(c.get("headline", "")) + " " + clean(c.get("body", "")) for c in cards])
    for bad in BAD_COPY:
        if bad in joined:
            issues.append(f"금지 표현 포함: {bad}")
    if any(x in joined for x in ["'id':", '"id":', "'text':", '"text":']):
        issues.append("내부 객체 필드명이 카피에 섞임")
    source_blob = clean(source_text + " " + json.dumps(source_map, ensure_ascii=False))
    for term in DRIFT_TERMS:
        if term in joined and term not in source_blob:
            issues.append(f"원본에 없는 도메인 단어 사용: {term}")
    for idx, c in enumerate(cards, 1):
        if idx in [2, 3] and len(clean(c.get("body"))) < 65:
            issues.append(f"{idx}장 배경 설명이 부족함")
    return {"passed": not issues, "issues": issues}


def generate_content(output_type, provider, key, model, source_map, tone, ratio, style, include_copy, temperature, source_text):
    fallback = rule_output(output_type, source_map)
    if provider == "규칙 기반만 사용" or not key or not model:
        quality = validate_cardnews(fallback.get("cards", []), source_map, source_text) if output_type == "카드뉴스 6장" else {"passed": True, "issues": []}
        return fallback, "", "", 0, quality, "LLM 미사용 또는 API Key/Model 누락"
    prompt = content_prompt(output_type, source_map, tone, ratio, style, include_copy)
    raw, _, error = safe_call_llm(provider, key, model, prompt, temperature)
    if error or not raw:
        quality = validate_cardnews(fallback.get("cards", []), source_map, source_text) if output_type == "카드뉴스 6장" else {"passed": True, "issues": []}
        return fallback, raw or "", "", len(prompt), quality, error
    parsed, parse_error = safe_parse_json(raw)
    if parse_error:
        quality = validate_cardnews(fallback.get("cards", []), source_map, source_text) if output_type == "카드뉴스 6장" else {"passed": True, "issues": []}
        return fallback, raw, "", len(prompt), quality, parse_error
    result = normalize_output(output_type, parsed, fallback)
    quality = validate_cardnews(result.get("cards", []), source_map, source_text) if output_type == "카드뉴스 6장" else {"passed": True, "issues": []}
    repair_raw = ""
    if output_type == "카드뉴스 6장" and not quality["passed"]:
        repair_prompt = content_prompt(output_type, source_map, tone, ratio, style, include_copy, quality["issues"], raw)
        repair_raw, _, repair_error = safe_call_llm(provider, key, model, repair_prompt, temperature)
        if repair_raw and not repair_error:
            repaired_obj, repaired_parse_error = safe_parse_json(repair_raw)
            if not repaired_parse_error:
                repaired = normalize_output(output_type, repaired_obj, fallback)
                repaired_quality = validate_cardnews(repaired.get("cards", []), source_map, source_text)
                if repaired_quality["passed"] or len(repaired.get("cards", [])) == 6:
                    result, quality = repaired, repaired_quality
    return result, raw, repair_raw, len(prompt), quality, ""


def sanitize_scene(text):
    text = clean(text)
    for token in BAD_IMAGE:
        text = text.replace(token, "")
    return text.replace("문구", "장면").replace("카피", "시각 요소").strip()


def image_prompt(card, ratio, style, include_copy):
    head = clean(card.get("headline"))
    body = clean(card.get("body"))
    scene = sanitize_scene(card.get("scene"))
    if include_copy:
        copy_rule = f"Render only this Korean headline text if text is needed: '{head}'. Do not render body copy, labels, captions, random letters, watermark, or UI field names."
    else:
        copy_rule = "clean image only, no text, no captions, no typography, no letters, no watermark, no logo."
    return f"{ratio} composition, {style}. {scene}. Visual context only: {shorten(body, 120)}. {copy_rule}"


def body_text(output_type, result):
    if output_type == "카드뉴스 6장":
        return "\n\n".join([f"{i+1}장\n{c['headline']}\n{c['body']}" for i, c in enumerate(result.get("cards", []))])
    return result.get("script", "")


def save_output(reference_id, output_type, provider, model, result):
    conn = db()
    conn.execute("""
        INSERT INTO generated_content_outputs
        (reference_id, output_type, provider, model, title, body_text, body_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (reference_id, output_type, provider, model, result.get("title", ""), body_text(output_type, result), json.dumps(result, ensure_ascii=False), datetime.now().isoformat(timespec="seconds")))
    conn.commit()
    conn.close()


def main():
    st.set_page_config(page_title="LLM API 콘텐츠 생성", page_icon="🧠", layout="wide")
    init_tables()
    st.title("🧠 LLM API 콘텐츠 생성")
    st.caption("Source Map 우선 구조. LLM 호출 실패 시 앱을 터뜨리지 않고 규칙 기반 결과로 대체합니다.")

    refs = load_refs()
    if refs.empty:
        st.warning("먼저 YouTube 영상 내용 분석에서 원본 해석 결과를 저장하세요.")
        return

    with st.sidebar:
        output_type = st.selectbox("출력 유형", OUTPUT_TYPES)
        provider = st.selectbox("Provider", PROVIDERS, index=1)
        model = st.text_input("Model", value=DEFAULT_MODELS.get(provider, ""))
        secret_name = st.text_input("Streamlit secrets key", value=SECRET_NAMES.get(provider, ""))
        key_manual = st.text_input("API Key 직접 입력", type="password")
        use_secret = st.checkbox("secrets에서 API Key 읽기", value=True)
        api_key = get_secret(secret_name) if use_secret and secret_name else key_manual
        temperature = st.slider("temperature", 0.1, 1.0, 0.45, 0.05)
        tone = st.selectbox("어조", TONES, index=2)
        ratio = st.selectbox("이미지 비율", IMAGE_RATIOS)
        style = st.selectbox("이미지 스타일", IMAGE_STYLES)
        include_copy = st.checkbox("카드뉴스 이미지에 헤드라인만 넣기", value=True)

    options = {f"{rv(row, 'source_table')} · {row['id']} · {rv(row, 'main_topic_sentence') or rv(row, 'original_topic') or rv(row, 'title')}": row for _, row in refs.iterrows()}
    selected = st.selectbox("원본 콘텐츠 선택", list(options.keys()))
    row = options[selected]
    source_text = full_source_text(row)
    seed = seed_source_map(row)

    source_key = f"source_map_{int(row['id'])}_{seed['source_hash']}_{provider}_{model}"
    if source_key not in st.session_state:
        st.session_state[source_key] = seed
        st.session_state[source_key + "_raw"] = ""
        st.session_state[source_key + "_prompt_len"] = 0
        st.session_state[source_key + "_error"] = ""

    col_a, col_b = st.columns(2)
    interpret_btn = col_a.button("원본 해석 다시 생성")
    run_btn = col_b.button("콘텐츠 생성", type="primary")

    if interpret_btn:
        smap, raw_map, prompt_len, error = interpret_source(provider, api_key, model, seed, temperature)
        st.session_state[source_key] = smap
        st.session_state[source_key + "_raw"] = raw_map
        st.session_state[source_key + "_prompt_len"] = prompt_len
        st.session_state[source_key + "_error"] = error
        if error:
            st.warning(f"Source Map 해석은 규칙 기반으로 대체됐습니다. 원인: {error}")
        else:
            st.success("Source Map 해석 완료")

    source_map = st.session_state[source_key]

    with st.expander("Source Map / 원본 해석 결과", expanded=True):
        st.json({k: v for k, v in source_map.items() if k != "source_excerpt"})
    with st.expander("원본 발췌 / LLM 전달용"):
        st.text_area("source_excerpt", value=source_map.get("source_excerpt", ""), height=260)
    with st.expander("Source Map LLM 원문"):
        st.write(f"prompt 문자 수: {st.session_state.get(source_key + '_prompt_len', 0):,}")
        if st.session_state.get(source_key + "_error"):
            st.warning(st.session_state.get(source_key + "_error"))
        st.code(st.session_state.get(source_key + "_raw", ""))

    output_key = f"semantic_output_{output_type}_{int(row['id'])}_{seed['source_hash']}_{provider}_{model}"
    if run_btn or output_key not in st.session_state:
        result, raw, repair_raw, prompt_len, quality, error = generate_content(output_type, provider, api_key, model, source_map, tone, ratio, style, include_copy, temperature, source_text)
        result["quality"] = quality
        result["error"] = error
        st.session_state[output_key] = result
        st.session_state[output_key + "_raw"] = raw
        st.session_state[output_key + "_repair_raw"] = repair_raw
        st.session_state[output_key + "_prompt_len"] = prompt_len
        st.session_state[output_key + "_error"] = error

    result = st.session_state[output_key]
    st.markdown("---")

    if result.get("error"):
        st.warning(f"LLM 생성 실패로 규칙 기반 초안을 표시합니다. 원인: {result.get('error')}")

    if output_type == "카드뉴스 6장":
        st.markdown("### 카드뉴스 구성 직접 수정")
        quality = result.get("quality", {"passed": True, "issues": []})
        if quality.get("passed"):
            st.success("품질 검사 통과")
        else:
            st.warning("품질 검사 이슈: " + " / ".join(quality.get("issues", [])))
        edited = []
        for i, card in enumerate(result.get("cards", []), 1):
            with st.container(border=True):
                st.markdown(f"#### {i}장")
                head = st.text_area("헤드카피", value=clean(card.get("headline")), height=80, key=f"{output_key}_h_{i}")
                body = st.text_area("바디카피", value=clean(card.get("body")), height=125, key=f"{output_key}_b_{i}")
                scene = st.text_area("장면 방향", value=sanitize_scene(card.get("scene")), height=95, key=f"{output_key}_s_{i}")
                st.text_area("이미지 생성 프롬프트", value=image_prompt({"headline": head, "body": body, "scene": scene}, ratio, style, include_copy), height=135, key=f"{output_key}_p_{i}")
                edited.append({"headline": head, "body": body, "scene": scene})
        result["cards"] = edited
    else:
        label = "1분 쇼츠 대본" if output_type == "1분 쇼츠 대본" else "5분 미드폼 유튜브 대본"
        st.markdown(f"### {label} 직접 수정")
        result["title"] = st.text_input("제목", value=result.get("title", ""), key=f"{output_key}_title")
        result["hook"] = st.text_area("후킹 문장", value=result.get("hook", ""), height=80, key=f"{output_key}_hook")
        result["script"] = st.text_area("대본", value=result.get("script", ""), height=540, key=f"{output_key}_script")
        with st.expander("구성표"):
            st.json(result.get("shot_plan") or result.get("chapter_plan") or [])

    result["title"] = st.text_input("저장 제목", value=result.get("title", source_map.get("source_title", "")), key=f"{output_key}_save_title")
    with st.expander("콘텐츠 LLM 원문 출력"):
        st.write(f"prompt 문자 수: {st.session_state.get(output_key + '_prompt_len', 0):,}")
        if st.session_state.get(output_key + "_error"):
            st.warning(st.session_state.get(output_key + "_error"))
        st.code(st.session_state.get(output_key + "_raw", ""))
    with st.expander("콘텐츠 repair 출력"):
        st.code(st.session_state.get(output_key + "_repair_raw", ""))

    if st.button("이 결과 저장", type="primary"):
        save_output(int(row["id"]), output_type, provider, model, result)
        st.success("콘텐츠 생성 결과를 저장했습니다.")


if __name__ == "__main__":
    main()
