import json
import re
import sqlite3
from datetime import datetime
from pathlib import Path

import pandas as pd
import requests
import streamlit as st

DB_PATH = Path('eafi_benchmark.db')

PROVIDERS = ['규칙 기반만 사용', 'Gemini', 'Groq', 'OpenRouter']
DEFAULT_MODELS = {
    'Gemini': 'gemini-2.0-flash-lite',
    'Groq': 'llama-3.1-8b-instant',
    'OpenRouter': 'openrouter/auto',
}
SECRET_NAMES = {
    'Gemini': 'GEMINI_API_KEY',
    'Groq': 'GROQ_API_KEY',
    'OpenRouter': 'OPENROUTER_API_KEY',
}
IMAGE_RATIOS = ['1:1', '16:9', '9:16', '4:3']
IMAGE_STYLES = ['깔끔한 인포그래픽', '뉴스 에디토리얼', '실사 시네마틱', '3D 애니메이션', '미니멀 타이포그래피', '프리미엄 브랜드룩']
COPY_TONES = ['담백', '명확', '강한 후킹', '자극적']

PRICE_RE = re.compile(r'\d+(?:[,.]\d+)?\s*(?:만원|천원|원|달러|조|억|%|배)')
WORD_RE = re.compile(r'[가-힣A-Za-z0-9]{2,}')
FORBIDDEN = ['현실 신호', '기대 신호', '결과 신호', '충돌 신호', 'result_signal', 'reality_signal', 'expectation_signal', 'context_profile', '헤드카피', '바디카피', 'Copy intent']
BAD_HEADLINES = ['핵심 단서', '판단 기준', '정리하면', '마지막 질문', '먼저 봐야 할 기준', '사람들이 놓치는 지점']
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


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_table():
    conn = db()
    conn.execute('''
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
    ''')
    conn.commit()
    conn.close()


def clean(v, fallback=''):
    if v is None:
        return fallback
    text = str(v).strip()
    if text.lower() in ['nan', 'none', 'null']:
        return fallback
    return text or fallback


def scrub(text):
    text = clean(text)
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\[[sS]?\d+\]', '', text)
    text = re.sub(r'["“”\']', '', text)
    for word in FORBIDDEN:
        text = text.replace(word, '')
    fixes = {
        '왔습니다입니다': '왔습니다',
        '합니다입니다': '합니다',
        '됩니다입니다': '됩니다',
        '있습니다입니다': '있습니다',
        '입니다입니다': '입니다',
    }
    for a, b in fixes.items():
        text = text.replace(a, b)
    return re.sub(r'\s+', ' ', text).strip()


def shorten(text, limit=130):
    text = scrub(text)
    return text if len(text) <= limit else text[:limit - 1].rstrip() + '…'


def safe_json(v, fallback=None):
    if fallback is None:
        fallback = {}
    if isinstance(v, (dict, list)):
        return v
    try:
        return json.loads(clean(v)) if clean(v) else fallback
    except Exception:
        return fallback


def rv(row, key, fallback=''):
    try:
        return clean(row.get(key, fallback), fallback)
    except Exception:
        try:
            return clean(row[key], fallback)
        except Exception:
            return fallback


def has_any(text, tokens):
    return any(t in clean(text) for t in tokens)


def count_any(text, tokens):
    return sum(1 for t in tokens if t in clean(text))


def split_sentences(text):
    text = scrub(text)
    parts = re.split(r'(?<=[.!?。！？])\s+|(?<=다)\s+|(?<=요)\s+|(?<=죠)\s+|(?<=습니다)\s+', text)
    return [scrub(p) for p in parts if len(scrub(p)) > 12]


def load_references():
    conn = db()
    frames = []
    try:
        refs = pd.read_sql_query('''
            SELECT r.id, 'content_reference' AS source_table, c.platform, c.channel_name, c.category,
                   r.title, r.url, r.hook_point, r.structure_note, r.visual_note, r.eafi_application,
                   r.total_score, r.status, r.created_at
            FROM content_references r
            LEFT JOIN benchmark_channels c ON r.channel_id = c.id
            ORDER BY r.id DESC
        ''', conn)
        frames.append(refs)
    except Exception:
        pass
    try:
        yt = pd.read_sql_query('SELECT * FROM youtube_video_analyses ORDER BY id DESC', conn)
        if not yt.empty:
            yt['source_table'] = 'youtube_analysis'
            yt['platform'] = 'YouTube'
            yt['category'] = yt.get('source_kind', '영상 분석')
            yt['total_score'] = 20
            yt['status'] = '원본 해석'
            frames.append(yt)
    except Exception:
        pass
    conn.close()
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True, sort=False)
    for col in ['original_topic', 'main_topic_sentence', 'primary_claim', 'summary', 'transcript', 'keywords', 'event_type', 'source_kind', 'interpretation_slots', 'cardnews_seed', 'source_index', 'evidence_points', 'event_timeline', 'cause_effect_chain', 'audience_pain', 'contradiction_or_tension', 'hidden_assumption', 'viral_hook_logic']:
        if col not in df.columns:
            df[col] = ''
    return df.sort_values('created_at', ascending=False, na_position='last')


def flatten_item(item):
    if isinstance(item, dict):
        return scrub(item.get('event') or item.get('source') or item.get('fact') or item.get('answer') or item.get('basis') or item.get('text') or '')
    return scrub(item)


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
            for sub_key in ['context_profile', 'fact_roles', 'fact_seeds', 'timeline_seeds', 'slide_seed']:
                item = obj.get(sub_key)
                if isinstance(item, dict):
                    pool.extend(item.values())
                elif isinstance(item, list):
                    pool.extend(item)
    pool.extend(split_sentences(rv(row, 'transcript'))[:120])
    out = []
    seen = set()
    for item in pool:
        text = flatten_item(item)
        key = re.sub(r'[^가-힣A-Za-z0-9]', '', text[:80])
        if text and key not in seen:
            seen.add(key)
            out.append(text)
        if len(out) >= 60:
            break
    return out


def infer_subject(topic, facts):
    text = PRICE_RE.sub(' ', f'{topic} {' '.join(facts[:8])}')
    candidates = []
    for word in WORD_RE.findall(text):
        word = re.sub(r'(의|은|는|이|가|을|를|에서|까지|으로|로|와|과)$', '', word)
        if not word or word in STOPWORDS or re.match(r'^\d', word):
            continue
        score = 5 if re.search(r'[가-힣]', word) else 1
        score += 3 if len(word) <= 5 else 0
        if word.endswith(('전자', '산업', '바이오', '에너지', '금양')):
            score += 4
        if word in ['가격', '주가', '시장', '투자', '결과', '문제', '배경']:
            score -= 5
        candidates.append((score, word))
    return sorted(candidates, reverse=True)[0][1] if candidates else '이 주제'


def find_fact(facts, tokens, fallback=''):
    ranked = []
    for index, fact in enumerate(facts):
        score = count_any(fact, tokens) * 3 + len(PRICE_RE.findall(fact))
        if score > 0:
            ranked.append((score, -index, fact))
    return sorted(ranked, reverse=True)[0][2] if ranked else fallback


def infer_mode(text, explicit=''):
    if explicit in ['market_or_company_shift', 'corporate_stock_collapse', 'market_analysis']:
        return 'market_or_company_shift'
    if explicit in ['stakeholder_conflict', 'samsung_labor', 'labor_conflict', 'legal_conflict']:
        return 'stakeholder_conflict'
    if explicit in ['howto_or_warning']:
        return 'howto_or_warning'
    scores = {
        'market_or_company_shift': count_any(text, TOK['market']) * 3 + count_any(text, TOK['verify']) * 2 + count_any(text, TOK['finance']) * 2 + len(PRICE_RE.findall(text)) * 3,
        'stakeholder_conflict': count_any(text, TOK['stakeholder']) * 2 + count_any(text, ['갈등', '반발', '요구', '파업', '소송', '법원', '노조', '직원']),
        'howto_or_warning': count_any(text, TOK['howto']) * 2,
        'issue_context': 1,
    }
    if len(PRICE_RE.findall(text)) >= 2 or (has_any(text, ['주가', '시총', '고점', '저점']) and has_any(text, ['폭락', '하락', '급락', '몰락', '붕괴'])):
        scores['market_or_company_shift'] += 12
    return max(scores.items(), key=lambda x: x[1])[0]


def analyze_reference(row):
    facts = collect_facts(row)
    topic = rv(row, 'original_topic') or rv(row, 'main_topic_sentence') or rv(row, 'title') or '원본 주제'
    joined = ' '.join([topic, rv(row, 'keywords'), rv(row, 'event_type')] + facts[:40])
    mode = infer_mode(joined, rv(row, 'event_type'))
    subject = infer_subject(topic, facts)
    return {
        'mode': mode,
        'topic': scrub(topic),
        'subject': subject,
        'result': scrub(rv(row, 'primary_claim') or find_fact(facts, TOK['market'] + ['논란', '몰락', '붕괴', '문제'], topic)),
        'metric': scrub(find_fact(facts, TOK['market'], rv(row, 'primary_claim') or topic)),
        'expectation': scrub(find_fact(facts, TOK['expect'], '사람들이 먼저 믿었던 성장 기대와 미래 서사')),
        'verification': scrub(find_fact(facts, TOK['verify'], '그 기대가 실제 숫자로 증명되는지 확인해야 하는 구간')),
        'finance': scrub(find_fact(facts, TOK['finance'], '자금 조달과 현금 흐름도 다시 봐야 할 변수')),
        'execution': scrub(find_fact(facts, TOK['execute'], '사업 진행 속도와 공시된 리스크')),
        'conflict': scrub(rv(row, 'contradiction_or_tension') or find_fact(facts, TOK['conflict'], '겉으로 보이는 결과와 실제 판단 기준이 엇갈린 지점')),
        'audience_problem': scrub(rv(row, 'audience_pain') or '독자는 결과에 먼저 반응하지만, 그 결과를 만든 배경과 조건은 놓치기 쉽습니다.'),
        'facts': facts[:18],
    }


def default_cards(a):
    s = a['subject']
    if a['mode'] == 'market_or_company_shift':
        nums = PRICE_RE.findall(a['metric'])
        headline1 = f'{nums[0]}에서 {nums[1]}까지\n무너진 건 가격만이 아닙니다' if len(nums) >= 2 else f'{s}\n무너진 건 차트만이 아닙니다'
        return [
            {'headline': headline1, 'body': '이 이야기는 단순한 급락이 아닙니다. 먼저 봐야 할 건, 이 가격을 밀어올렸던 믿음이 무엇이었는지입니다.', 'scene': '어두운 금융 뉴스룸 배경, 수직으로 떨어지는 차트, 금이 간 상징 오브젝트', 'image_prompt': 'sharp falling financial chart, cracked symbolic object, dark editorial newsroom'},
            {'headline': '처음엔 믿을 이유가 있었습니다', 'body': f'시장은 늘 미래를 먼저 가격에 반영합니다. 이때 사람들을 움직인 건 {shorten(a['expectation'], 90)}였습니다.', 'scene': '빛나는 성장 그래프와 미래 사업을 상징하는 오브젝트', 'image_prompt': 'glowing growth chart, future business object, optimistic data panels'},
            {'headline': '문제는 숫자가 따라오지 못했다는 겁니다', 'body': f'기대가 커질수록 시장은 더 구체적인 증거를 요구합니다. 여기서 봐야 할 건 {shorten(a['verification'], 95)}입니다.', 'scene': '회계 보고서, 빨간 경고등, 꺾이는 그래프', 'image_prompt': 'accounting report, red warning light, broken downward graph'},
            {'headline': '시장은 더 이상 스토리만 보지 않았습니다', 'body': f'한 번 의심이 시작되면 기준은 바뀝니다. 미래 가능성보다 {shorten(a['finance'], 65)}와 {shorten(a['conflict'], 65)}가 먼저 보입니다.', 'scene': '계산기, 투자자 모니터, 재평가되는 차트', 'image_prompt': 'calculator, investor monitor, repriced chart, red and gray data cards'},
            {'headline': '핵심은 하락률이 아닙니다', 'body': f'중요한 건 이 하락이 과한 공포인지, 뒤늦은 재평가인지입니다. 가격보다 먼저 봐야 할 건 {shorten(a['execution'], 90)}입니다.', 'scene': '저울, 두 갈래 길, 미래 기대 그래프와 리스크 문서', 'image_prompt': 'scale, forked road, future growth chart versus risk document'},
            {'headline': '이건 기회일까요, 경고일까요?', 'body': '다시 보려면 차트보다 먼저 확인해야 합니다. 이 기대가 아직 숫자로 증명되고 있는지, 아니면 시장이 이미 답을 바꾼 건지 말입니다.', 'scene': '갈림길 앞 투자자 실루엣, 반등 차트와 경고 표지판', 'image_prompt': 'investor silhouette at crossroads, rebound chart, warning sign'},
        ]
    return [
        {'headline': f'{s}\n결론만 보면 놓치는 게 있습니다', 'body': '사람들이 먼저 본 건 결과입니다. 하지만 이 이야기는 그 장면 하나로 설명되지 않습니다.', 'scene': '강한 뉴스 헤드라인과 흐릿한 배경 자료', 'image_prompt': 'strong news headline, blurred documents, editorial layout'},
        {'headline': '먼저 배경을 봐야 합니다', 'body': f'이 이야기가 커진 이유는 {shorten(a['expectation'], 95)} 때문입니다. 결론 전에 쌓인 맥락이 있습니다.', 'scene': '오래된 자료 사진과 연결선', 'image_prompt': 'archival photo, connection lines, context board'},
        {'headline': '문제는 여기서 시작됩니다', 'body': f'분위기가 바뀐 지점은 {shorten(a['conflict'], 95)}입니다. 여기서 단순한 이야기가 의문으로 바뀝니다.', 'scene': '갈라지는 선과 충돌하는 정보 카드', 'image_prompt': 'split line, conflicting info cards'},
        {'headline': '근거를 다시 봐야 합니다', 'body': f'원문에서 다시 확인해야 할 건 {shorten(a['verification'], 95)}입니다. 결론보다 근거가 판단을 바꿉니다.', 'scene': '돋보기와 체크된 사실 카드', 'image_prompt': 'magnifying glass, checked fact card'},
        {'headline': '핵심은 이 간극입니다', 'body': f'중요한 건 누가 더 자극적으로 말했느냐가 아니라, {shorten(a['conflict'], 95)}입니다.', 'scene': '저울과 양쪽에 놓인 결과와 맥락', 'image_prompt': 'scale, result versus context'},
        {'headline': '이제 다르게 보이시나요?', 'body': '이 이야기를 다시 본다면, 결론보다 먼저 그 결론을 만든 배경부터 확인해야 합니다.', 'scene': '큰 질문과 희미한 자료들이 남는 마무리 카드', 'image_prompt': 'large question, faded evidence, quiet ending card'},
    ]


def build_llm_prompt(analysis, default_plan, tone, ratio, style, include_copy):
    return f'''
너는 한국 커뮤니티와 인스타 카드뉴스 문법을 잘 아는 콘텐츠 에디터다.
아래 원본 분석과 초안을 기반으로 6장 카드뉴스를 다시 작성하라.

절대 규칙:
- 반드시 JSON만 출력한다. 설명 문장, 마크다운 금지.
- cards는 정확히 6개.
- 각 card는 headline, body, scene, image_prompt 필드를 가진다.
- headline은 1~2줄, 짧고 사람이 쓴 말처럼 쓴다.
- body는 1~2문장, 원문 팩트를 기반으로 설명한다.
- 2장과 3장은 반드시 배경/근거 설명을 충분히 넣는다.
- 현실 신호, 기대 신호, 결과 신호, 충돌 신호, 핵심 단서, 판단 기준, 정리하면, 마지막 질문 같은 라벨형 표현 금지.
- 원문에 없는 구체 사실을 지어내지 않는다.
- 투자/주식 내용이면 매수/매도 추천처럼 쓰지 않는다.
- image_prompt에는 headline만 렌더링하라고 지시한다. body는 이미지에 넣지 않는다.
- 이미지 비율: {ratio}, 이미지 스타일: {style}, 이미지 내 카피 포함: {include_copy}
- 어조: {tone}

원본 분석:
{json.dumps(analysis, ensure_ascii=False, indent=2)}

규칙 기반 초안:
{json.dumps(default_plan, ensure_ascii=False, indent=2)}

출력 형식:
{{
  "title": "카드뉴스 제목",
  "core_problem": "독자가 놓치기 쉬운 핵심 문제",
  "main_message": "전체 메시지",
  "cta": "맥락에 맞는 마지막 질문 또는 행동 유도",
  "cards": [
    {{"headline":"", "body":"", "scene":"", "image_prompt":""}}
  ]
}}
'''


def get_secret(name):
    try:
        return st.secrets.get(name, '')
    except Exception:
        return ''


def call_gemini(key, model, prompt, temperature):
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}'
    payload = {'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': {'temperature': temperature, 'responseMimeType': 'application/json'}}
    res = requests.post(url, json=payload, timeout=60)
    res.raise_for_status()
    return res.json()['candidates'][0]['content']['parts'][0]['text']


def call_chat(url, key, model, prompt, temperature, headers_extra=None):
    headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
    if headers_extra:
        headers.update(headers_extra)
    payload = {'model': model, 'messages': [{'role': 'system', 'content': 'Return valid JSON only.'}, {'role': 'user', 'content': prompt}], 'temperature': temperature}
    res = requests.post(url, json=payload, headers=headers, timeout=60)
    res.raise_for_status()
    return res.json()['choices'][0]['message']['content']


def call_llm(provider, key, model, prompt, temperature):
    if provider == 'Gemini':
        return call_gemini(key, model, prompt, temperature)
    if provider == 'Groq':
        return call_chat('https://api.groq.com/openai/v1/chat/completions', key, model, prompt, temperature)
    if provider == 'OpenRouter':
        return call_chat('https://openrouter.ai/api/v1/chat/completions', key, model, prompt, temperature, {'HTTP-Referer': 'https://eafi-benchmark-db.streamlit.app', 'X-Title': 'EAFI Cardnews Planner'})
    raise ValueError('provider 없음')


def parse_json(text):
    text = clean(text).strip()
    text = re.sub(r'^```(?:json)?', '', text)
    text = re.sub(r'```$', '', text)
    try:
        return json.loads(text)
    except Exception:
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            return json.loads(text[start:end + 1])
        raise


def validate_plan(plan, analysis, defaults):
    cards = plan.get('cards') if isinstance(plan, dict) else None
    if not isinstance(cards, list):
        cards = defaults
    fixed = []
    for i in range(6):
        src = cards[i] if i < len(cards) and isinstance(cards[i], dict) else defaults[i]
        default = defaults[i]
        headline = scrub(src.get('headline') or default['headline'])
        body = scrub(src.get('body') or default['body'])
        scene = scrub(src.get('scene') or default['scene'])
        image_prompt = scrub(src.get('image_prompt') or default['image_prompt'])
        if any(bad in headline for bad in BAD_HEADLINES):
            headline = default['headline']
        if len(body) < 25:
            body = default['body']
        fixed.append({'headline': headline, 'body': body, 'scene': scene, 'image_prompt': image_prompt})
    return {
        'title': scrub(plan.get('title') if isinstance(plan, dict) else '') or f"{analysis['subject']} 카드뉴스",
        'core_problem': scrub(plan.get('core_problem') if isinstance(plan, dict) else '') or analysis['audience_problem'],
        'main_message': scrub(plan.get('main_message') if isinstance(plan, dict) else '') or analysis['conflict'],
        'cta': scrub(plan.get('cta') if isinstance(plan, dict) else '') or fixed[-1]['body'],
        'cards': fixed,
    }


def image_prompt(card, ratio, style, include_copy):
    copy_rule = f"Render only this Korean headline text if text is needed: '{card['headline']}'. Do not render body copy, labels, captions, random letters, watermark, or UI field names." if include_copy else 'clean image only, no text, no captions, no typography, no letters, no watermark, no logo.'
    return f"{ratio} composition, {style}. {card['scene']}. {card['image_prompt']}. Body context for composition only: {shorten(card['body'], 120)}. {copy_rule}"


def save_result(reference_id, result, images):
    slides = [f"{c['headline']}\n\n{c['body']}" for c in result['cards']]
    conn = db()
    conn.execute('''
        INSERT INTO cardnews_plans
        (reference_id, title, target_customer, core_problem, main_message, cta,
         slide_1, slide_2, slide_3, slide_4, slide_5, slide_6,
         image_1, image_2, image_3, image_4, image_5, image_6, status, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (reference_id, result['title'], 'LLM API 카드뉴스', result['core_problem'], result['main_message'], result['cta'], *slides, *images, 'LLM API 초안', datetime.now().isoformat(timespec='seconds')))
    conn.commit()
    conn.close()


def main():
    st.set_page_config(page_title='LLM API 카드뉴스', page_icon='🧠', layout='wide')
    init_table()
    st.title('🧠 LLM API 카드뉴스')
    st.caption('규칙 엔진으로 팩트를 추출하고, Gemini/Groq/OpenRouter로 카피를 재작성한 뒤 다시 검수합니다.')

    refs = load_references()
    if refs.empty:
        st.warning('먼저 YouTube 영상 내용 분석에서 원본 해석 결과를 저장하세요.')
        return

    with st.sidebar:
        st.markdown('### LLM API 설정')
        provider = st.selectbox('Provider', PROVIDERS, index=0)
        secret_name = st.text_input('Streamlit secrets key', value=SECRET_NAMES.get(provider, ''))
        model = st.text_input('Model', value=DEFAULT_MODELS.get(provider, ''))
        temperature = st.slider('temperature', 0.1, 1.0, 0.55, 0.05)
        st.markdown('### 이미지/카피')
        ratio = st.selectbox('이미지 비율', IMAGE_RATIOS, index=0)
        style = st.selectbox('이미지 스타일', IMAGE_STYLES, index=0)
        tone = st.selectbox('어조', COPY_TONES, index=2)
        include_copy = st.checkbox('이미지에 헤드라인만 넣기', value=True)

    options = {f"{rv(row, 'source_table')} · {row['id']} · {rv(row, 'main_topic_sentence') or rv(row, 'original_topic') or rv(row, 'title')}": row for _, row in refs.iterrows()}
    selected = st.selectbox('원본 콘텐츠 선택', list(options.keys()))
    row = options[selected]
    analysis = analyze_reference(row)
    defaults = default_cards(analysis)

    with st.expander('팩트 추출/분기 진단', expanded=True):
        st.json(analysis)

    run_llm = st.button('LLM으로 카드뉴스 생성', type='primary')
    run_rule = st.button('규칙 기반 초안 생성')

    if run_llm or run_rule or 'llm_cardnews_result' not in st.session_state:
        raw = ''
        if run_llm and provider != '규칙 기반만 사용':
            key = get_secret(secret_name)
            if not key:
                st.error(f'Streamlit secrets에 {secret_name} 값이 없습니다. 규칙 기반 초안으로 대체합니다.')
                result = validate_plan({'cards': defaults}, analysis, defaults)
            else:
                try:
                    prompt = build_llm_prompt(analysis, defaults, tone, ratio, style, include_copy)
                    raw = call_llm(provider, key, model, prompt, temperature)
                    result = validate_plan(parse_json(raw), analysis, defaults)
                    st.success(f'{provider} 호출 완료')
                except Exception as e:
                    st.error(f'LLM 호출 실패. 규칙 기반 초안으로 대체합니다: {e}')
                    result = validate_plan({'cards': defaults}, analysis, defaults)
        else:
            result = validate_plan({'title': f"{analysis['subject']} 카드뉴스", 'core_problem': analysis['audience_problem'], 'main_message': analysis['conflict'], 'cta': defaults[-1]['body'], 'cards': defaults}, analysis, defaults)
        st.session_state['llm_cardnews_result'] = result
        st.session_state['llm_raw_output'] = raw

    result = st.session_state['llm_cardnews_result']
    style_text = {
        '깔끔한 인포그래픽': 'clean editorial infographic, organized icons, generous whitespace',
        '뉴스 에디토리얼': 'news editorial visual, data panels, reportage mood',
        '실사 시네마틱': 'cinematic realistic photography, premium lighting',
        '3D 애니메이션': 'stylized 3D animation, polished commercial render',
        '미니멀 타이포그래피': 'minimal typography poster, bold graphic rhythm',
        '프리미엄 브랜드룩': 'premium brand campaign visual, black, red, warm gray palette',
    }.get(style, style)
    images = [image_prompt(card, ratio, style_text, include_copy) for card in result['cards']]

    st.markdown('---')
    st.markdown('### 6장 카드뉴스 구성 직접 수정')
    edited_cards = []
    edited_images = []
    for i, card in enumerate(result['cards'], start=1):
        with st.container(border=True):
            st.markdown(f'#### {i}장')
            headline = st.text_area('헤드카피', value=card['headline'], height=80, key=f'llm_h_{i}')
            body = st.text_area('바디카피', value=card['body'], height=110, key=f'llm_b_{i}')
            scene = st.text_area('장면 방향', value=card['scene'], height=95, key=f'llm_s_{i}')
            prompt = st.text_area('이미지 생성 프롬프트', value=images[i - 1], height=145, key=f'llm_p_{i}')
            edited_cards.append({'headline': headline, 'body': body, 'scene': scene, 'image_prompt': card.get('image_prompt', '')})
            edited_images.append(prompt)

    final = {**result, 'cards': edited_cards}
    final['title'] = st.text_input('저장 제목', value=result['title'])
    final['core_problem'] = st.text_area('핵심 문제', value=result['core_problem'], height=80)
    final['main_message'] = st.text_area('메인 메시지', value=result['main_message'], height=80)
    final['cta'] = st.text_input('CTA/마지막 질문', value=result['cta'])

    with st.expander('LLM 원문 출력'):
        st.code(st.session_state.get('llm_raw_output', ''))

    if st.button('이 설계안 저장', type='primary'):
        save_result(int(row['id']), final, edited_images)
        st.success('LLM API 기반 카드뉴스 설계안을 저장했습니다.')


if __name__ == '__main__':
    main()
