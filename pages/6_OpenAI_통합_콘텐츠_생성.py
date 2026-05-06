import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

DB_PATH = Path('eafi_benchmark.db')

OUTPUT_TYPES = ['카드뉴스 6장', '1분 쇼츠 대본', '5분 미드폼 유튜브 대본']
PROVIDERS = ['규칙 기반만 사용', 'OpenAI', 'Gemini', 'Groq', 'OpenRouter']
DEFAULT_MODELS = {
    'OpenAI': 'gpt-5-mini',
    'Gemini': 'gemini-2.0-flash-lite',
    'Groq': 'llama-3.1-8b-instant',
    'OpenRouter': 'openrouter/auto',
}
SECRET_NAMES = {
    'OpenAI': 'OPENAI_API_KEY',
    'Gemini': 'GEMINI_API_KEY',
    'Groq': 'GROQ_API_KEY',
    'OpenRouter': 'OPENROUTER_API_KEY',
}
TONES = ['담백', '명확', '강한 후킹', '자극적']
IMAGE_RATIOS = ['1:1', '16:9', '9:16', '4:3']
IMAGE_STYLES = ['깔끔한 인포그래픽', '뉴스 에디토리얼', '실사 시네마틱', '3D 애니메이션', '미니멀 타이포그래피', '프리미엄 브랜드룩']

PRICE_RE = re.compile(r'\d+(?:[,.]\d+)?\s*(?:만원|천원|원|달러|조|억|%|배)')
WORD_RE = re.compile(r'[가-힣A-Za-z0-9]{2,}')
FORBIDDEN = ['현실 신호', '기대 신호', '결과 신호', '충돌 신호', 'result_signal', 'reality_signal', 'expectation_signal', 'context_profile', '헤드카피', '바디카피', 'Copy intent']
BAD_LABELS = ['핵심 단서', '판단 기준', '정리하면', '마지막 질문', '먼저 봐야 할 기준', '사람들이 놓치는 지점']
STOPWORDS = set('만원에서 천원까지 결론 가격 주가 몰락 붕괴 폭락 하락 상승 급락 문제 결과 기준 영상 스크립트 원본 핵심 주제 이야기 카드뉴스 시장 투자자 미래 성장 기대 현실 숫자 검증 단서 배경 근거 간극 이번 오늘 사람들'.split())
TOK = {
    'market': ['주가', '가격', '만원', '천원', '시총', '고점', '저점', '폭락', '급락', '하락', '상승', '차트'],
    'expect': ['기대', '미래', '성장', '스토리', '전망', '호재', '테마', '사업', '개발', '투자', '가능성'],
    'verify': ['실적', '매출', '영업', '손실', '적자', '숫자', '이익', '재무', '보고서', '증거'],
    'finance': ['자금', '현금', '전환사채', 'CB', '유상증자', '부채', '차입', '상환', '조달', '유동성'],
    'execute': ['공시', '지연', '계약', '생산', '공장', '리튬', '배터리', '2차전지', '진행', '납품', '양산'],
    'conflict': ['하지만', '그런데', '문제는', '반면', '그러나', '의심', '리스크', '위험', '논란', '갈등', '경고'],
    'stakeholder': ['회사', '직원', '노조', '정부', '소비자', '시민', '주주', '투자자', '개미', '경영진'],
    'howto': ['방법', '체크', '주의', '실수', '조건', '원리', '해야', '하지', '팁', '노하우'],
}


def clean(value, fallback=''):
    if value is None:
        return fallback
    text = str(value).strip()
    if text.lower() in ['nan', 'none', 'null']:
        return fallback
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\[[sS]?\d+\]', '', text)
    for word in FORBIDDEN:
        text = text.replace(word, '')
    fixes = {
        '왔습니다입니다': '왔습니다',
        '합니다입니다': '합니다',
        '됩니다입니다': '됩니다',
        '있습니다입니다': '있습니다',
        '입니다입니다': '입니다',
    }
    for old, new in fixes.items():
        text = text.replace(old, new)
    return re.sub(r'\s+', ' ', text).strip() or fallback


def safe_json(value, fallback=None):
    if fallback is None:
        fallback = {}
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(clean(value)) if clean(value) else fallback
    except Exception:
        return fallback


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_tables():
    conn = db()
    conn.execute('''
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
    ''')
    conn.commit()
    conn.close()


def rv(row, key, fallback=''):
    try:
        return clean(row.get(key, fallback), fallback)
    except Exception:
        try:
            return clean(row[key], fallback)
        except Exception:
            return fallback


def shorten(text, limit=130):
    text = clean(text)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def split_sentences(text):
    text = clean(text)
    parts = re.split(r'(?<=[.!?。！？])\s+|(?<=다)\s+|(?<=요)\s+|(?<=죠)\s+|(?<=습니다)\s+', text)
    return [clean(p) for p in parts if len(clean(p)) > 12]


def load_refs():
    conn = db()
    frames = []
    try:
        yt = pd.read_sql_query('SELECT * FROM youtube_video_analyses ORDER BY id DESC', conn)
        if not yt.empty:
            yt['source_table'] = 'youtube_analysis'
            frames.append(yt)
    except Exception:
        pass
    try:
        refs = pd.read_sql_query('''
            SELECT r.id, 'content_reference' AS source_table, c.channel_name, r.title, r.hook_point,
                   r.structure_note, r.visual_note, r.eafi_application, r.created_at
            FROM content_references r
            LEFT JOIN benchmark_channels c ON r.channel_id = c.id
            ORDER BY r.id DESC
        ''', conn)
        frames.append(refs)
    except Exception:
        pass
    conn.close()
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True, sort=False)
    for col in ['original_topic', 'main_topic_sentence', 'primary_claim', 'summary', 'transcript', 'keywords', 'event_type', 'interpretation_slots', 'cardnews_seed', 'source_index', 'evidence_points', 'event_timeline', 'audience_pain', 'contradiction_or_tension', 'hidden_assumption']:
        if col not in df.columns:
            df[col] = ''
    return df


def flatten(item):
    if isinstance(item, dict):
        return clean(item.get('event') or item.get('source') or item.get('fact') or item.get('answer') or item.get('basis') or item.get('text') or '')
    return clean(item)


def collect_facts(row):
    pool = []
    for key in ['primary_claim', 'original_topic', 'main_topic_sentence', 'audience_pain', 'contradiction_or_tension', 'hidden_assumption', 'summary']:
        pool.append(rv(row, key))
    for key in ['evidence_points', 'event_timeline', 'cause_effect_chain', 'source_grounded_qa']:
        val = safe_json(rv(row, key), [])
        if isinstance(val, list):
            pool.extend(val)
    for key in ['interpretation_slots', 'cardnews_seed', 'source_index', 'interpretation_report']:
        obj = safe_json(rv(row, key), {})
        if isinstance(obj, dict):
            for sub in ['context_profile', 'fact_roles', 'fact_seeds', 'timeline_seeds', 'slide_seed']:
                item = obj.get(sub)
                if isinstance(item, dict):
                    pool.extend(item.values())
                elif isinstance(item, list):
                    pool.extend(item)
    pool.extend(split_sentences(rv(row, 'transcript'))[:120])
    out, seen = [], set()
    for item in pool:
        text = flatten(item)
        key = re.sub(r'[^가-힣A-Za-z0-9]', '', text[:80])
        if text and key not in seen:
            seen.add(key)
            out.append(text)
        if len(out) >= 55:
            break
    return out


def count_any(text, tokens):
    return sum(1 for t in tokens if t in clean(text))


def infer_subject(topic, facts):
    context = topic + ' ' + ' '.join(facts[:8])
    text = PRICE_RE.sub(' ', context)
    candidates = []
    for word in WORD_RE.findall(text):
        word = re.sub(r'(의|은|는|이|가|을|를|에서|까지|으로|로|와|과)$', '', word)
        if not word or word in STOPWORDS or re.match(r'^\d', word):
            continue
        score = 5 if re.search(r'[가-힣]', word) else 1
        score += 3 if len(word) <= 5 else 0
        if word.endswith(('전자', '산업', '바이오', '에너지', '금양')):
            score += 4
        candidates.append((score, word))
    return sorted(candidates, reverse=True)[0][1] if candidates else '이 주제'


def find_fact(facts, tokens, fallback):
    ranked = []
    for idx, fact in enumerate(facts):
        score = count_any(fact, tokens) * 3 + len(PRICE_RE.findall(fact))
        if score > 0:
            ranked.append((score, -idx, fact))
    return sorted(ranked, reverse=True)[0][2] if ranked else fallback


def infer_mode(text, explicit=''):
    if explicit in ['market_or_company_shift', 'corporate_stock_collapse', 'market_analysis']:
        return 'market_or_company_shift'
    if explicit in ['stakeholder_conflict', 'samsung_labor', 'labor_conflict', 'legal_conflict']:
        return 'stakeholder_conflict'
    if explicit == 'howto_or_warning':
        return 'howto_or_warning'
    scores = {
        'market_or_company_shift': count_any(text, TOK['market']) * 3 + count_any(text, TOK['verify']) * 2 + count_any(text, TOK['finance']) * 2 + len(PRICE_RE.findall(text)) * 3,
        'stakeholder_conflict': count_any(text, TOK['stakeholder']) * 2 + count_any(text, ['갈등', '반발', '요구', '파업', '소송', '법원', '노조', '직원']),
        'howto_or_warning': count_any(text, TOK['howto']) * 2,
        'issue_context': 1,
    }
    if len(PRICE_RE.findall(text)) >= 2:
        scores['market_or_company_shift'] += 12
    return max(scores.items(), key=lambda x: x[1])[0]


def build_context_pack(row):
    facts = collect_facts(row)
    topic = rv(row, 'original_topic') or rv(row, 'main_topic_sentence') or rv(row, 'title') or '원본 주제'
    joined = ' '.join([topic, rv(row, 'keywords'), rv(row, 'event_type')] + facts[:40])
    mode = infer_mode(joined, rv(row, 'event_type'))
    subject = infer_subject(topic, facts)
    pack = {
        'source_title': clean(topic),
        'subject': subject,
        'content_mode': mode,
        'visible_result': rv(row, 'primary_claim') or find_fact(facts, TOK['market'] + ['논란', '몰락', '붕괴', '문제'], topic),
        'key_metric': find_fact(facts, TOK['market'], topic),
        'old_belief': find_fact(facts, TOK['expect'], '사람들이 먼저 믿었던 기대와 미래 서사'),
        'verification': find_fact(facts, TOK['verify'], '그 기대가 실제 숫자로 증명되는지 확인해야 하는 구간'),
        'finance': find_fact(facts, TOK['finance'], '자금 조달과 현금 흐름도 다시 봐야 할 변수'),
        'execution': find_fact(facts, TOK['execute'], '사업 진행 속도와 공시된 리스크'),
        'tension': rv(row, 'contradiction_or_tension') or find_fact(facts, TOK['conflict'], '겉으로 보이는 결과와 실제 판단 기준이 엇갈린 지점'),
        'audience_problem': rv(row, 'audience_pain') or '독자는 결과에 먼저 반응하지만, 그 결과를 만든 배경과 조건은 놓치기 쉽습니다.',
        'tone_profile': '초반은 강한 숫자/결과로 멈춰 세우고, 중반은 배경과 근거를 설명하며, 후반은 판단 기준과 질문으로 닫는다.',
        'must_use_facts': facts[:16],
    }
    return {k: clean(v) if isinstance(v, str) else v for k, v in pack.items()}


def default_cardnews(pack):
    nums = PRICE_RE.findall(pack['key_metric'])
    h1 = f"{nums[0]}에서 {nums[1]}까지\n무너진 건 가격만이 아닙니다" if len(nums) >= 2 else f"{pack['subject']}\n결과만 보면 놓치는 게 있습니다"
    return {
        'title': f"{pack['subject']} 카드뉴스",
        'core_problem': pack['audience_problem'],
        'main_message': pack['tension'],
        'cta': '이건 기회일까요, 경고일까요?',
        'cards': [
            {'headline': h1, 'body': '이 이야기는 단순한 급락이 아닙니다. 먼저 봐야 할 건, 이 결과를 밀어올렸던 믿음이 무엇이었는지입니다.', 'scene': '어두운 뉴스룸 배경, 급락 차트, 금이 간 상징 오브젝트'},
            {'headline': '처음엔 믿을 이유가 있었습니다', 'body': f"시장은 미래를 먼저 반영합니다. 이때 사람들을 움직인 건 {shorten(pack['old_belief'], 90)}였습니다.", 'scene': '빛나는 성장 그래프와 기대감을 상징하는 데이터 패널'},
            {'headline': '문제는 숫자가 따라오지 못했다는 겁니다', 'body': f"기대가 커질수록 시장은 더 구체적인 증거를 요구합니다. 여기서 봐야 할 건 {shorten(pack['verification'], 95)}입니다.", 'scene': '회계 보고서, 빨간 경고등, 꺾이는 그래프'},
            {'headline': '기준은 여기서 바뀌었습니다', 'body': f"한 번 의심이 시작되면 시장은 스토리보다 {shorten(pack['finance'], 65)}와 {shorten(pack['tension'], 65)}를 먼저 봅니다.", 'scene': '계산기, 투자자 모니터, 재평가되는 차트'},
            {'headline': '핵심은 하락률이 아닙니다', 'body': f"중요한 건 과한 공포인지, 뒤늦은 재평가인지입니다. 가격보다 먼저 봐야 할 건 {shorten(pack['execution'], 90)}입니다.", 'scene': '저울, 두 갈래 길, 미래 기대 그래프와 리스크 문서'},
            {'headline': '이건 기회일까요, 경고일까요?', 'body': '다시 보려면 차트보다 먼저 확인해야 합니다. 기대가 아직 숫자로 증명되고 있는지, 시장이 이미 답을 바꾼 건지 말입니다.', 'scene': '갈림길 앞 투자자 실루엣, 반등 차트와 경고 표지판'},
        ]
    }


def default_shorts(pack):
    return {
        'title': f"{pack['subject']} 1분 쇼츠",
        'hook': f"{pack['key_metric']} 이 숫자만 보면 놓치는 게 있습니다.",
        'script': f"""0초
{pack['key_metric']}
그런데 이건 단순한 결과가 아닙니다.

5초
사람들이 먼저 본 건 가격과 반응이었지만,
진짜 봐야 할 건 그 결과를 만든 기대였습니다.

15초
처음엔 믿을 이유가 있었습니다.
{shorten(pack['old_belief'], 90)}

28초
문제는 그 기대가 숫자로 증명되느냐였습니다.
{shorten(pack['verification'], 95)}

42초
한 번 의심이 시작되면 시장은 스토리보다 근거를 먼저 봅니다.
{shorten(pack['tension'], 95)}

55초
이건 기회일까요, 경고일까요?
댓글로 여러분의 판단을 남겨주세요.""",
        'shot_plan': [],
        'cta': '댓글로 여러분의 판단을 남겨주세요.',
    }


def default_midform(pack):
    return {
        'title': f"{pack['subject']} 5분 미드폼 대본",
        'hook': f"{pack['key_metric']} 이 숫자의 의미를 다시 봐야 합니다.",
        'script': f"""오프닝
{pack['key_metric']}
이 숫자만 보면 단순한 하락처럼 보입니다. 그런데 오늘 봐야 할 건 가격 그 자체가 아니라, 그 가격을 만들었던 기대와 그 기대가 흔들린 이유입니다.

문제 제기
많은 사람들은 결과를 먼저 봅니다. 올랐는지, 떨어졌는지, 끝났는지, 다시 갈 수 있는지부터 판단합니다. 하지만 시장에서 더 중요한 건 결과가 아니라 결과를 만든 구조입니다.

배경
처음엔 믿을 이유가 있었습니다. {shorten(pack['old_belief'], 180)} 시장은 언제나 현재 숫자보다 미래 가능성을 먼저 반영합니다. 문제는 그 가능성이 실제 숫자로 증명되는 순간입니다.

근거
여기서 봐야 할 첫 번째 근거는 {shorten(pack['verification'], 180)}입니다. 기대가 커질수록 시장은 더 구체적인 증거를 요구합니다. 말보다 숫자, 분위기보다 실적, 스토리보다 진행 상황을 보게 됩니다.

리스크
두 번째는 자금과 실행 리스크입니다. {shorten(pack['finance'], 160)} 그리고 {shorten(pack['execution'], 160)} 이런 요소들이 겹치면 시장은 더 이상 같은 기준으로 보지 않습니다.

핵심 판단
결국 핵심은 이겁니다. {shorten(pack['tension'], 180)} 이 하락이 과한 공포인지, 아니면 뒤늦은 재평가인지 보려면 가격보다 먼저 기대가 아직 숫자로 증명되고 있는지 확인해야 합니다.

마무리
그래서 이건 단순히 떨어졌냐, 싸졌냐의 문제가 아닙니다. 다시 볼 기회인지, 아직 남은 경고인지 판단하려면 차트보다 먼저 근거를 봐야 합니다. 여러분은 이 흐름을 어떻게 보시나요?""",
        'chapter_plan': [],
        'cta': '여러분은 이 흐름을 어떻게 보시나요?',
    }


def build_default(output_type, pack):
    if output_type == '카드뉴스 6장':
        return default_cardnews(pack)
    if output_type == '1분 쇼츠 대본':
        return default_shorts(pack)
    return default_midform(pack)


def build_prompt(output_type, pack, default_output, tone, ratio, style, include_copy):
    common = f"""
너는 한국 커뮤니티와 유튜브 문법을 잘 아는 콘텐츠 에디터다.
아래 source_context_pack은 긴 원본 대본을 의미 단위로 압축한 것이다.
원문 전체를 보지 못하더라도 맥락, 감정선, 논리 전개를 유지해서 재작성하라.
반드시 JSON만 출력한다. 마크다운 금지.
금지 표현: {', '.join(FORBIDDEN + BAD_LABELS)}
원문에 없는 구체 사실을 지어내지 말고, 투자/주식 내용은 매수/매도 추천처럼 쓰지 마라.
어조: {tone}

source_context_pack:
{json.dumps(pack, ensure_ascii=False, indent=2)}

규칙 기반 초안:
{json.dumps(default_output, ensure_ascii=False, indent=2)}
"""
    if output_type == '카드뉴스 6장':
        return common + f"""
출력 형식:
{{"title":"", "core_problem":"", "main_message":"", "cta":"", "cards":[{{"headline":"", "body":"", "scene":""}}]}}
규칙:
- cards는 정확히 6개.
- headline은 1~2줄, body는 1~2문장.
- 2장과 3장은 배경/근거 설명을 충분히 넣는다.
- scene은 이미지 생성용 장면 설명이다.
- 이미지 비율: {ratio}, 이미지 스타일: {style}, 이미지 내 헤드라인 포함: {include_copy}
"""
    if output_type == '1분 쇼츠 대본':
        return common + """
출력 형식:
{"title":"", "hook":"", "script":"", "shot_plan":[{"time":"", "visual":""}], "cta":""}
규칙:
- 전체 길이는 약 55~70초 분량.
- 첫 3초에 강한 숫자/결과/반전으로 멈춰 세운다.
- 문장은 짧고 구어체로 쓴다.
- 타임코드를 포함한다.
- 마지막은 댓글 유도형 질문으로 닫는다.
"""
    return common + """
출력 형식:
{"title":"", "hook":"", "script":"", "chapter_plan":[{"section":"", "purpose":""}], "cta":""}
규칙:
- 전체 길이는 약 5분 분량.
- 오프닝, 문제 제기, 배경, 근거 1, 근거 2, 리스크/반론, 판단 기준, 마무리 구조로 쓴다.
- 단순 요약이 아니라 시청자가 이해할 수 있게 설명을 충분히 넣는다.
- 구어체 존댓말로 쓴다.
- 투자/주식 내용이면 단정 추천이 아니라 판단 기준 중심으로 쓴다.
"""


def extract_response_text(data):
    if data.get('output_text'):
        return data['output_text']
    chunks = []
    for item in data.get('output', []):
        for content in item.get('content', []):
            if content.get('type') in ['output_text', 'text'] and content.get('text'):
                chunks.append(content['text'])
    return '\n'.join(chunks)


def call_llm(provider, key, model, prompt, temperature):
    if provider == 'OpenAI':
        url = 'https://api.openai.com/v1/responses'
        headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
        payload = {
            'model': model,
            'input': prompt,
            'temperature': temperature,
            'text': {'format': {'type': 'json_object'}},
        }
        res = requests.post(url, json=payload, headers=headers, timeout=90)
        res.raise_for_status()
        return extract_response_text(res.json())
    if provider == 'Gemini':
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}'
        payload = {'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': {'temperature': temperature, 'responseMimeType': 'application/json'}}
        res = requests.post(url, json=payload, timeout=60)
        res.raise_for_status()
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
    url = 'https://api.groq.com/openai/v1/chat/completions' if provider == 'Groq' else 'https://openrouter.ai/api/v1/chat/completions'
    if provider == 'OpenRouter':
        headers.update({'HTTP-Referer': 'https://eafi-benchmark-db.streamlit.app', 'X-Title': 'EAFI Content Generator'})
    payload = {'model': model, 'messages': [{'role': 'system', 'content': 'Return valid JSON only.'}, {'role': 'user', 'content': prompt}], 'temperature': temperature}
    res = requests.post(url, json=payload, headers=headers, timeout=60)
    res.raise_for_status()
    return res.json()['choices'][0]['message']['content']


def parse_json(text):
    text = clean(text).strip()
    text = re.sub(r'^```(?:json)?', '', text)
    text = re.sub(r'```$', '', text)
    try:
        return json.loads(text)
    except Exception:
        start, end = text.find('{'), text.rfind('}')
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def validate_result(output_type, obj, default_output):
    if not isinstance(obj, dict):
        return default_output
    if output_type == '카드뉴스 6장':
        cards = obj.get('cards') if isinstance(obj.get('cards'), list) else default_output['cards']
        fixed = []
        for i in range(6):
            src = cards[i] if i < len(cards) and isinstance(cards[i], dict) else default_output['cards'][i]
            base = default_output['cards'][i]
            fixed.append({'headline': clean(src.get('headline') or base['headline']), 'body': clean(src.get('body') or base['body']), 'scene': clean(src.get('scene') or base['scene'])})
        return {'title': clean(obj.get('title'), default_output['title']), 'core_problem': clean(obj.get('core_problem'), default_output['core_problem']), 'main_message': clean(obj.get('main_message'), default_output['main_message']), 'cta': clean(obj.get('cta'), default_output['cta']), 'cards': fixed}
    if output_type == '1분 쇼츠 대본':
        return {'title': clean(obj.get('title'), default_output['title']), 'hook': clean(obj.get('hook'), default_output.get('hook', '')), 'script': clean(obj.get('script'), default_output['script']), 'shot_plan': obj.get('shot_plan') if isinstance(obj.get('shot_plan'), list) else [], 'cta': clean(obj.get('cta'), default_output.get('cta', ''))}
    return {'title': clean(obj.get('title'), default_output['title']), 'hook': clean(obj.get('hook'), default_output.get('hook', '')), 'script': clean(obj.get('script'), default_output['script']), 'chapter_plan': obj.get('chapter_plan') if isinstance(obj.get('chapter_plan'), list) else [], 'cta': clean(obj.get('cta'), default_output.get('cta', ''))}


def build_image_prompt(card, ratio, style, include_copy):
    copy_rule = f"Render only this Korean headline text if text is needed: '{card['headline']}'. Do not render body copy, labels, captions, random letters, watermark, or UI field names." if include_copy else 'clean image only, no text, no captions, no typography, no letters, no watermark, no logo.'
    return f"{ratio} composition, {style}. {card['scene']}. Body context for composition only: {shorten(card['body'], 120)}. {copy_rule}"


def body_text(output_type, result):
    if output_type == '카드뉴스 6장':
        return '\n\n'.join([f"{i+1}장\n{c['headline']}\n{c['body']}" for i, c in enumerate(result['cards'])])
    return result.get('script', '')


def save_output(reference_id, output_type, provider, model, result):
    conn = db()
    conn.execute('''
        INSERT INTO generated_content_outputs
        (reference_id, output_type, provider, model, title, body_text, body_json, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    ''', (reference_id, output_type, provider, model, result.get('title', ''), body_text(output_type, result), json.dumps(result, ensure_ascii=False), datetime.now().isoformat(timespec='seconds')))
    conn.commit()
    conn.close()


def get_secret(name):
    try:
        return st.secrets.get(name, '')
    except Exception:
        return ''


def main():
    st.set_page_config(page_title='OpenAI 통합 콘텐츠 생성', page_icon='🧠', layout='wide')
    init_tables()
    st.title('🧠 OpenAI 통합 콘텐츠 생성')
    st.caption('OpenAI Responses API까지 포함한 통합 생성기입니다. 카드뉴스, 쇼츠, 미드폼을 선택 생성합니다.')

    refs = load_refs()
    if refs.empty:
        st.warning('먼저 YouTube 영상 내용 분석에서 원본 해석 결과를 저장하세요.')
        return

    with st.sidebar:
        st.markdown('### 출력 유형')
        output_type = st.selectbox('무엇을 만들까요?', OUTPUT_TYPES)
        st.markdown('### LLM API')
        provider = st.selectbox('Provider', PROVIDERS, index=1)
        model = st.text_input('Model', value=DEFAULT_MODELS.get(provider, ''))
        secret_name = st.text_input('Streamlit secrets key', value=SECRET_NAMES.get(provider, ''))
        key_manual = st.text_input('API Key 직접 입력', type='password')
        use_secret = st.checkbox('secrets에서 API Key 읽기', value=True)
        api_key = get_secret(secret_name) if use_secret and secret_name else key_manual
        temperature = st.slider('temperature', 0.1, 1.0, 0.55, 0.05)
        st.markdown('### 스타일')
        tone = st.selectbox('어조', TONES, index=2)
        ratio = st.selectbox('이미지 비율', IMAGE_RATIOS)
        style = st.selectbox('이미지 스타일', IMAGE_STYLES)
        include_copy = st.checkbox('카드뉴스 이미지에 헤드라인만 넣기', value=True)

    options = {f"{rv(row, 'source_table')} · {row['id']} · {rv(row, 'main_topic_sentence') or rv(row, 'original_topic') or rv(row, 'title')}": row for _, row in refs.iterrows()}
    selected = st.selectbox('원본 콘텐츠 선택', list(options.keys()))
    row = options[selected]
    pack = build_context_pack(row)
    default_output = build_default(output_type, pack)

    with st.expander('source_context_pack / 압축 맥락 패키지', expanded=True):
        st.json(pack)

    col1, col2 = st.columns(2)
    run_rule = col1.button('규칙 기반 초안 생성')
    run_llm = col2.button('LLM으로 재작성', type='primary')

    state_key = f"openai_multi_{output_type}_{int(row['id'])}"
    if run_rule or run_llm or state_key not in st.session_state:
        result = default_output
        raw = ''
        if run_llm and provider != '규칙 기반만 사용' and api_key and model:
            prompt = build_prompt(output_type, pack, default_output, tone, ratio, style, include_copy)
            with st.expander('LLM prompt 길이 진단'):
                st.write(f'문자 수: {len(prompt):,}')
            try:
                raw = call_llm(provider, api_key, model, prompt, temperature)
                result = validate_result(output_type, parse_json(raw), default_output)
                st.success(f'{provider} 호출 완료')
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else 'unknown'
                if status == 429:
                    st.error('LLM 호출 제한에 걸렸습니다. 잠시 후 다시 시도하거나 다른 Provider로 바꿔보세요. API 키는 화면에 표시하지 않습니다.')
                else:
                    st.error(f'LLM 호출 실패: HTTP {status}. 규칙 기반 초안으로 대체합니다.')
            except Exception as e:
                st.error(f'LLM 처리 실패. 규칙 기반 초안으로 대체합니다: {type(e).__name__}')
        st.session_state[state_key] = result
        st.session_state[state_key + '_raw'] = raw

    result = st.session_state[state_key]
    st.markdown('---')

    if output_type == '카드뉴스 6장':
        st.markdown('### 카드뉴스 구성 직접 수정')
        edited_cards = []
        for i, card in enumerate(result['cards'], 1):
            with st.container(border=True):
                st.markdown(f'#### {i}장')
                headline = st.text_area('헤드카피', value=card['headline'], height=80, key=f'{state_key}_h_{i}')
                body = st.text_area('바디카피', value=card['body'], height=110, key=f'{state_key}_b_{i}')
                scene = st.text_area('장면 방향', value=card['scene'], height=90, key=f'{state_key}_s_{i}')
                prompt = build_image_prompt({'headline': headline, 'body': body, 'scene': scene}, ratio, style, include_copy)
                st.text_area('이미지 생성 프롬프트', value=prompt, height=130, key=f'{state_key}_p_{i}')
                edited_cards.append({'headline': headline, 'body': body, 'scene': scene})
        result['cards'] = edited_cards
    else:
        label = '1분 쇼츠 대본' if output_type == '1분 쇼츠 대본' else '5분 미드폼 유튜브 대본'
        st.markdown(f'### {label} 직접 수정')
        result['title'] = st.text_input('제목', value=result.get('title', ''), key=f'{state_key}_title')
        result['hook'] = st.text_area('후킹 문장', value=result.get('hook', ''), height=80, key=f'{state_key}_hook')
        result['script'] = st.text_area('대본', value=result.get('script', ''), height=520, key=f'{state_key}_script')
        with st.expander('구성표'):
            plan_key = 'shot_plan' if output_type == '1분 쇼츠 대본' else 'chapter_plan'
            st.json(result.get(plan_key, []))

    result['title'] = st.text_input('저장 제목', value=result.get('title', ''), key=f'{state_key}_save_title')
    with st.expander('LLM 원문 출력'):
        st.code(st.session_state.get(state_key + '_raw', ''))

    if st.button('이 결과 저장', type='primary'):
        save_output(int(row['id']), output_type, provider, model, result)
        st.success('콘텐츠 생성 결과를 저장했습니다.')


if __name__ == '__main__':
    main()
