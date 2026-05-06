import ast
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

PRICE_RE = re.compile(r'\d+(?:[,.]\d+)?\s*(?:만원|천원|원|달러|조|억|%|배|명|개|건|년|개월|일)')
WORD_RE = re.compile(r'[가-힣A-Za-z0-9]{2,}')
OBJECT_LEAK_RE = re.compile(r"\[?\{\s*['\"](?:id|text|source|fact|event)['\"].*?\}\]?")
FORBIDDEN = [
    '현실 신호', '기대 신호', '결과 신호', '충돌 신호',
    'result_signal', 'reality_signal', 'expectation_signal', 'context_profile',
    'head_copy', 'body_copy', 'Copy intent', '헤드카피', '바디카피'
]
BAD_LABELS = ['핵심 단서', '판단 기준', '정리하면', '마지막 질문', '먼저 봐야 할 기준', '사람들이 놓치는 지점']
BAD_IMAGE_TOKENS = ['head_copy', 'body_copy', 'headline', 'body', '헤드카피', '바디카피', '카피:', 'caption:', 'title:', 'Copy intent']
STOPWORDS = set('만원에서 천원까지 결론 가격 주가 몰락 붕괴 폭락 하락 상승 급락 문제 결과 기준 영상 스크립트 원본 핵심 주제 이야기 카드뉴스 시장 투자자 미래 성장 기대 현실 숫자 검증 단서 배경 근거 간극 이번 오늘 사람들'.split())
TOK = {
    'market': ['주가', '가격', '만원', '천원', '시총', '고점', '저점', '폭락', '급락', '하락', '상승', '차트', '거래정지'],
    'expect': ['기대', '미래', '성장', '스토리', '전망', '호재', '테마', '사업', '개발', '투자', '가능성', '신사업', '진출', '2차전지'],
    'verify': ['실적', '매출', '영업', '손실', '적자', '숫자', '이익', '재무', '보고서', '증거', '전망치', '축소'],
    'finance': ['자금', '현금', '전환사채', 'CB', '유상증자', '부채', '차입', '상환', '조달', '유동성', '감사의견'],
    'execute': ['공시', '지연', '계약', '생산', '공장', '리튬', '배터리', '2차전지', '진행', '납품', '양산', '몽골', '광산'],
    'conflict': ['하지만', '그런데', '문제는', '반면', '그러나', '의심', '리스크', '위험', '논란', '갈등', '경고', '상장폐지', '의견거절'],
    'stakeholder': ['회사', '직원', '노조', '정부', '소비자', '시민', '주주', '투자자', '개미', '경영진', '소액주주'],
    'speaker': ['유튜버', '전문가', '인플루언서', '대표', '회장', '임원', '스피커', '아저씨', '애널리스트'],
    'howto': ['방법', '체크', '주의', '실수', '조건', '원리', '해야', '하지', '팁', '노하우'],
}
TEXT_KEYS = ['text', 'body', 'content', 'fact', 'event', 'answer', 'basis', 'source', 'quote', 'summary', 'claim']
SKIP_KEYS = {'id', 'role', 'card_no', 'step', 'type', 'label', 'score'}


def parse_possible_object(value):
    if isinstance(value, (dict, list, tuple)):
        return value
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if not ((text.startswith('{') and text.endswith('}')) or (text.startswith('[') and text.endswith(']'))):
        return None
    try:
        return json.loads(text)
    except Exception:
        try:
            return ast.literal_eval(text)
        except Exception:
            return None


def flatten_texts(value, depth=0):
    if depth > 6 or value is None:
        return []
    parsed = parse_possible_object(value)
    if parsed is not None and parsed is not value:
        return flatten_texts(parsed, depth + 1)
    if isinstance(value, dict):
        out = []
        for key in TEXT_KEYS:
            if key in value:
                out.extend(flatten_texts(value.get(key), depth + 1))
        if out:
            return out
        for key, item in value.items():
            if str(key) in SKIP_KEYS:
                continue
            out.extend(flatten_texts(item, depth + 1))
        return out
    if isinstance(value, (list, tuple, set)):
        out = []
        for item in value:
            out.extend(flatten_texts(item, depth + 1))
        return out
    text = str(value).strip()
    if not text or text.lower() in ['nan', 'none', 'null']:
        return []
    return [text]


def strip_object_leaks(text):
    text = str(text or '')
    parsed = parse_possible_object(text)
    if parsed is not None:
        parts = flatten_texts(parsed)
        return ' '.join(parts)
    # common single object/list leak embedded inside normal copy
    def repl(match):
        parts = flatten_texts(match.group(0))
        return ' '.join(parts) if parts else ''
    text = OBJECT_LEAK_RE.sub(repl, text)
    text = re.sub(r"\{\s*['\"]id['\"]\s*:\s*['\"][^'\"]+['\"]\s*,\s*['\"]text['\"]\s*:\s*['\"]", '', text)
    text = text.replace("'}]", '').replace('"}]', '').replace("'}", '').replace('"}', '')
    return text


def clean(value, fallback=''):
    if value is None:
        return fallback
    parts = flatten_texts(value)
    text = ' '.join(parts) if len(parts) > 1 or isinstance(value, (dict, list, tuple)) else str(value).strip()
    text = strip_object_leaks(text).strip()
    if text.lower() in ['nan', 'none', 'null']:
        return fallback
    text = re.sub(r'https?://\S+', '', text)
    text = re.sub(r'\[[sS]?\d+\]', '', text)
    for word in FORBIDDEN:
        text = text.replace(word, '')
    fixes = {
        '왔습니다입니다': '왔습니다', '합니다입니다': '합니다', '됩니다입니다': '됩니다',
        '있습니다입니다': '있습니다', '입니다입니다': '입니다', '때문입니다입니다': '때문입니다',
        '니다입니다': '니다', '요입니다': '요'
    }
    for old, new in fixes.items():
        text = text.replace(old, new)
    text = re.sub(r"[\[\]{}]+", ' ', text)
    text = re.sub(r"['\"](?:id|text|source|fact|event)['\"]\s*:\s*", ' ', text)
    return re.sub(r'\s+', ' ', text).strip(' ,:;') or fallback


def safe_json(value, fallback=None):
    if fallback is None:
        fallback = {}
    parsed = parse_possible_object(value)
    return parsed if parsed is not None else fallback


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
    parts = re.split(r'(?<=[.!?。！？])\s+|(?<=다)\s+|(?<=요)\s+|(?<=죠)\s+|(?<=습니다)\s+|\n+', text)
    return [clean(p) for p in parts if len(clean(p)) > 12]


def compact_source_excerpt(text, head=8500, tail=2200):
    text = clean(text)
    if len(text) <= head + tail + 500:
        return text
    return text[:head].rstrip() + '\n\n...[중간 생략: 핵심 문장은 evidence_bank에 보존됨]...\n\n' + text[-tail:].lstrip()


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
    for col in ['original_topic', 'main_topic_sentence', 'primary_claim', 'summary', 'transcript', 'keywords', 'event_type', 'interpretation_slots', 'cardnews_seed', 'source_index', 'evidence_points', 'event_timeline', 'audience_pain', 'contradiction_or_tension', 'hidden_assumption', 'source_grounded_qa', 'cause_effect_chain', 'interpretation_report']:
        if col not in df.columns:
            df[col] = ''
    return df


def full_source_text(row):
    pieces = [rv(row, 'original_topic'), rv(row, 'main_topic_sentence'), rv(row, 'primary_claim'), rv(row, 'summary'), rv(row, 'transcript'), rv(row, 'hook_point'), rv(row, 'structure_note'), rv(row, 'visual_note'), rv(row, 'eafi_application')]
    return '\n'.join([p for p in pieces if p])


def collect_facts(row):
    pool = []
    for key in ['primary_claim', 'original_topic', 'main_topic_sentence', 'audience_pain', 'contradiction_or_tension', 'hidden_assumption', 'summary']:
        pool.extend(flatten_texts(rv(row, key)))
    for key in ['evidence_points', 'event_timeline', 'cause_effect_chain', 'source_grounded_qa', 'interpretation_slots', 'cardnews_seed', 'source_index', 'interpretation_report']:
        raw = row.get(key, '') if hasattr(row, 'get') else ''
        parsed = parse_possible_object(raw)
        pool.extend(flatten_texts(parsed if parsed is not None else raw))
    pool.extend(split_sentences(rv(row, 'transcript'))[:180])
    out, seen = [], set()
    for item in pool:
        text = clean(item)
        if len(text) < 10:
            continue
        if any(leak in text for leak in ["'id':", '"id":', "'text':", '"text":']):
            text = clean(strip_object_leaks(text))
        key = re.sub(r'[^가-힣A-Za-z0-9]', '', text[:90])
        if key and key not in seen:
            seen.add(key)
            out.append(text)
        if len(out) >= 90:
            break
    return out


def count_any(text, tokens):
    text = clean(text)
    return sum(1 for t in tokens if t in text)


def keyword_hits(text, tokens):
    text = clean(text)
    return [t for t in tokens if t in text]


def extract_numbers(text):
    nums = PRICE_RE.findall(clean(text))
    seen = []
    for n in nums:
        n = n.strip()
        if n and n not in seen:
            seen.append(n)
    return seen[:20]


def infer_subject(topic, facts):
    context = topic + ' ' + ' '.join(facts[:10])
    text = PRICE_RE.sub(' ', context)
    candidates = []
    for word in WORD_RE.findall(text):
        word = re.sub(r'(의|은|는|이|가|을|를|에서|까지|으로|로|와|과)$', '', word)
        if not word or word in STOPWORDS or re.match(r'^\d', word):
            continue
        score = 5 if re.search(r'[가-힣]', word) else 1
        score += 3 if len(word) <= 5 else 0
        if word.endswith(('전자', '산업', '바이오', '에너지', '금양', '그룹', '홀딩스')):
            score += 4
        if word in ['가격', '주가', '시장', '투자', '결과', '문제', '배경']:
            score -= 5
        candidates.append((score, word))
    return sorted(candidates, reverse=True)[0][1] if candidates else '이 주제'


def find_fact(facts, tokens, fallback):
    ranked = []
    for idx, fact in enumerate(facts):
        fact = clean(fact)
        score = count_any(fact, tokens) * 3 + len(extract_numbers(fact))
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
        'market_or_company_shift': count_any(text, TOK['market']) * 3 + count_any(text, TOK['verify']) * 2 + count_any(text, TOK['finance']) * 2 + len(extract_numbers(text)) * 3,
        'stakeholder_conflict': count_any(text, TOK['stakeholder']) * 2 + count_any(text, ['갈등', '반발', '요구', '파업', '소송', '법원', '노조', '직원']),
        'howto_or_warning': count_any(text, TOK['howto']) * 2,
        'issue_context': 1,
    }
    if len(extract_numbers(text)) >= 2 and count_any(text, TOK['market']) >= 1:
        scores['market_or_company_shift'] += 12
    return max(scores.items(), key=lambda x: x[1])[0]


def evidence_role(sentence):
    s = clean(sentence)
    if count_any(s, ['주가', '급락', '폭락', '고점', '저점', '거래정지']):
        return 'shock'
    if count_any(s, ['소액주주', '시총', '규모', '명', '조원', '억원']):
        return 'scale'
    if count_any(s, TOK['expect']):
        return 'hype'
    if count_any(s, TOK['speaker']):
        return 'speaker'
    if count_any(s, ['적자', '의견거절', '상장폐지', '상폐', '관리종목', '축소', '손실']):
        return 'collapse'
    if count_any(s, TOK['finance']):
        return 'finance'
    if count_any(s, TOK['execute']):
        return 'execution'
    if count_any(s, ['교훈', '확인', '체크', '기준', '질문']):
        return 'lesson'
    return 'general'


def build_editorial_angle_candidates(source_text, mode):
    text = clean(source_text)
    if mode == 'market_or_company_shift':
        angles = []
        if count_any(text, TOK['expect']) and count_any(text, TOK['conflict'] + TOK['verify']):
            angles.append('테마와 기대가 어떻게 거품이 되고 무너졌는지 보여주는 구조')
        if count_any(text, TOK['speaker']):
            angles.append('스피커와 시장 기대가 어떻게 집단 믿음을 키웠는지 추적하는 구조')
        if count_any(text, ['거래정지', '상장폐지', '의견거절', '소액주주']):
            angles.append('주가 하락보다 무서운 투자자 고립과 비상구 폐쇄 구조')
        angles += ['한 종목 사례를 통해 다음 테마주를 볼 때 확인할 기준을 정리하는 구조', '화려한 미래 서사와 차가운 숫자가 충돌하는 순간을 보여주는 구조']
        return list(dict.fromkeys(angles))[:5]
    if mode == 'stakeholder_conflict':
        return ['겉으로 보이는 갈등보다 각 이해관계자가 감수하는 비용을 보여주는 구조', '요구와 책임이 충돌하는 지점을 순서대로 추적하는 구조', '감정적 반응을 판단 기준으로 재배열하는 구조']
    if mode == 'howto_or_warning':
        return ['사람들이 따라 하기 전에 놓치는 조건을 보여주는 구조', '결론보다 원리와 적용 기준을 먼저 설명하는 구조', '흔한 실수를 체크리스트로 바꾸는 구조']
    return ['표면적인 결과보다 그 결과를 만든 구조를 설명하는 관점', '사람들이 왜 이 메시지에 반응하는지 심리와 맥락을 풀어내는 관점', '사례 하나를 일반화 가능한 기준으로 바꾸는 관점']


def build_narrative_arc(mode):
    if mode == 'market_or_company_shift':
        return ['충격적인 결과 제시', '사람들이 왜 믿었는지 배경 설명', '기대가 증폭된 방식', '숫자와 사실이 흔들린 순간', '리스크 현실화와 피해 규모', '다음에 같은 실수를 피하는 기준']
    if mode == 'stakeholder_conflict':
        return ['갈등 장면 제시', '요구 조건 설명', '상대 계산 설명', '충돌 지점', '비용과 피해', '판단 질문']
    if mode == 'howto_or_warning':
        return ['흔한 실수', '이유 설명', '조건 설명', '위험 지점', '체크리스트', '실행 질문']
    return ['문제 제시', '배경 설명', '핵심 갈등', '근거 제시', '전환점', '교훈']


def build_card_questions(mode):
    if mode == 'market_or_company_shift':
        return ['가장 충격적인 결과는 무엇인가?', '사람들은 왜 이 회사를 믿게 되었나?', '그 믿음은 어떤 서사와 스피커를 통해 커졌나?', '어떤 숫자와 사실이 그 믿음을 흔들었나?', '왜 투자자들은 빠르게 빠져나오기 어려웠나?', '다음 유사 사례에서 무엇을 먼저 확인해야 하나?']
    if mode == 'stakeholder_conflict':
        return ['겉으로 보이는 갈등은 무엇인가?', '한쪽은 무엇을 요구하고 있나?', '상대는 무엇을 계산하고 있나?', '양쪽 논리가 충돌하는 지점은 어디인가?', '누가 어떤 비용을 감수하게 되나?', '독자는 무엇을 기준으로 판단해야 하나?']
    if mode == 'howto_or_warning':
        return ['사람들이 흔히 하는 실수는 무엇인가?', '왜 그 방법이 작동하거나 실패하는가?', '적용 조건은 무엇인가?', '주의해야 할 위험은 무엇인가?', '독자가 바로 확인할 체크포인트는 무엇인가?', '마지막으로 어떤 행동을 유도할 것인가?']
    return ['가장 먼저 보여줄 문제는 무엇인가?', '독자가 이 문제를 믿게 되는 배경은 무엇인가?', '긴장과 대립은 어디서 생기나?', '무엇이 핵심 전환점인가?', '독자가 얻을 기준은 무엇인가?', '마지막에 어떤 질문이나 행동을 남길 것인가?']


def build_structural_insight_pack(mode):
    if mode == 'market_or_company_shift':
        return {
            'reader_problem': '사람들은 이 사례를 단순 주가 하락으로 보지만, 실제로는 기대가 만들어지고 숫자로 무너지는 구조를 놓치기 쉽다.',
            'hidden_premise': '시장은 화려한 서사만으로 오래 유지되지 않고 결국 실적, 현금흐름, 공시, 실행력을 확인한다.',
            'tension_structure': '미래 기대와 현재 숫자의 대립',
            'emotion_trigger': '놓친 기회에 대한 탐욕보다 빠져나오지 못할 수 있다는 공포가 더 크게 작동한다.',
            'viral_hook_logic': '극단적 가격 낙차 → 믿게 된 이유 → 붕괴 근거 → 투자자 고립 → 다음에도 반복될 수 있다는 경고',
            'reusable_structure': '충격 숫자 → 믿음의 배경 → 기대 증폭 → 숫자 붕괴 → 피해 현실화 → 체크 질문',
        }
    return {
        'reader_problem': '독자는 결과는 보지만 그 결과를 만든 구조를 잘 보지 못한다.',
        'hidden_premise': '좋은 콘텐츠는 정보 나열보다 관점의 재배열에서 나온다.',
        'tension_structure': '겉으로 보이는 결과와 실제 원인의 대립',
        'emotion_trigger': '내가 놓친 맥락을 알게 되는 순간 생기는 재판단 욕구',
        'viral_hook_logic': '익숙한 사례 제시 → 숨은 맥락 공개 → 오해 교정 → 재사용 가능한 기준 제공',
        'reusable_structure': '문제 제시 → 배경 설명 → 숨은 전제 → 전환점 → 핵심 기준 → 행동 유도',
    }


def build_rich_context_pack(row):
    facts = collect_facts(row)
    source_text = full_source_text(row)
    topic = rv(row, 'original_topic') or rv(row, 'main_topic_sentence') or rv(row, 'title') or '원본 주제'
    joined = ' '.join([topic, rv(row, 'keywords'), rv(row, 'event_type'), source_text] + facts[:50])
    mode = infer_mode(joined, rv(row, 'event_type'))
    subject = infer_subject(topic, facts)
    sentences = split_sentences(source_text)
    evidence_bank, seen = [], set()
    for s in facts + sentences:
        s = clean(s)
        if len(s) < 18:
            continue
        key = re.sub(r'[^가-힣A-Za-z0-9]', '', s[:90])
        if key in seen:
            continue
        seen.add(key)
        evidence_bank.append({'role': evidence_role(s), 'fact': shorten(s, 230)})
        if len(evidence_bank) >= 34:
            break
    angles = build_editorial_angle_candidates(source_text, mode)
    rich = {
        'source_title': clean(topic),
        'source_length': len(source_text),
        'source_excerpt': compact_source_excerpt(source_text),
        'subject': subject,
        'content_mode': mode,
        'numbers': extract_numbers(source_text)[:14],
        'keywords': {
            'market': keyword_hits(source_text, TOK['market']),
            'hype': keyword_hits(source_text, TOK['expect']),
            'risk': keyword_hits(source_text, TOK['conflict'] + TOK['verify']),
            'speaker': keyword_hits(source_text, TOK['speaker']),
        },
        'visible_result': rv(row, 'primary_claim') or find_fact(facts, TOK['market'] + ['논란', '몰락', '붕괴', '문제'], topic),
        'key_metric': find_fact(facts, TOK['market'], topic),
        'old_belief': find_fact(facts, TOK['expect'], '사람들이 먼저 믿었던 기대와 미래 서사'),
        'verification': find_fact(facts, TOK['verify'], '그 기대가 실제 숫자로 증명되는지 확인해야 하는 구간'),
        'finance': find_fact(facts, TOK['finance'], '자금 조달과 현금 흐름도 다시 봐야 할 변수'),
        'execution': find_fact(facts, TOK['execute'], '사업 진행 속도와 공시된 리스크'),
        'tension': rv(row, 'contradiction_or_tension') or find_fact(facts, TOK['conflict'], '겉으로 보이는 결과와 실제 판단 기준이 엇갈린 지점'),
        'audience_problem': rv(row, 'audience_pain') or '독자는 결과에 먼저 반응하지만, 그 결과를 만든 배경과 조건은 놓치기 쉽습니다.',
        'editorial_angle_candidates': angles,
        'chosen_angle': angles[0] if angles else '핵심 사건의 구조와 교훈',
        'narrative_arc': build_narrative_arc(mode),
        'card_role_questions': build_card_questions(mode),
        'evidence_bank': evidence_bank,
        'structural_insight_pack': build_structural_insight_pack(mode),
        'tone_dna': {
            'style': '강한 오프닝, 맥락 설명, 숫자/사실 근거, 마지막 교훈',
            'emotion_curve': '충격 → 이해 → 의심 → 붕괴 → 교훈',
            'avoid': ['과도하게 추상적인 문장', '같은 표현 반복', '내부 라벨형 카피', '증권 추천처럼 보이는 문장'],
        },
    }
    return rich


def build_context_pack(row):
    return build_rich_context_pack(row)


def default_cardnews(pack):
    nums = pack.get('numbers') or extract_numbers(pack.get('key_metric', ''))
    h1 = f"{nums[0]}에서 {nums[1]}까지\n무너진 건 가격만이 아닙니다" if len(nums) >= 2 else f"{pack['subject']}\n결과만 보면 놓치는 게 있습니다"
    return {
        'title': f"{pack['subject']} 카드뉴스",
        'core_problem': pack['audience_problem'],
        'main_message': pack['chosen_angle'],
        'cta': '다음 유사 사례를 볼 때, 무엇을 먼저 확인해야 할까요?',
        'cards': [
            {'headline': h1, 'body': '이 이야기는 단순한 급락이 아닙니다. 먼저 봐야 할 건 이 결과를 밀어올렸던 믿음이 무엇이었는지입니다.', 'scene': '어두운 뉴스룸 배경, 급락 차트, 금이 간 상징 오브젝트'},
            {'headline': '처음엔 믿을 이유가 있었습니다', 'body': f"시장은 미래를 먼저 반영합니다. 이때 사람들을 움직인 건 {shorten(pack['old_belief'], 110)}였습니다.", 'scene': '과거 기업 정체성과 미래 산업 이미지가 겹쳐지는 장면'},
            {'headline': '믿음은 혼자 커지지 않습니다', 'body': f"테마, 스피커, 장밋빛 전망이 맞물리면 기대는 숫자보다 빠르게 움직입니다. 핵심 재료는 {shorten(pack['chosen_angle'], 100)}입니다.", 'scene': '작은 불씨가 거대한 테마의 불길로 번지는 인포그래픽'},
            {'headline': '시장은 결국 숫자로 돌아옵니다', 'body': f"기대가 커질수록 시장은 더 구체적인 증거를 요구합니다. 여기서 봐야 할 건 {shorten(pack['verification'], 110)}입니다.", 'scene': '화려한 홍보 이미지 뒤로 재무제표와 빨간 경고등이 드러나는 장면'},
            {'headline': '진짜 공포는 빠져나갈 문입니다', 'body': f"하락률보다 무서운 건 리스크가 현실화될 때입니다. {shorten(pack['finance'], 80)}와 {shorten(pack['execution'], 80)}가 함께 보입니다.", 'scene': '닫힌 비상구, 멈춘 차트, 어두운 극장 같은 투자자 고립 장면'},
            {'headline': '다음 테마주도 같은 질문을 남깁니다', 'body': '화려한 서사가 아니라 실적, 현금흐름, 공시, 이해관계를 먼저 확인해야 합니다. 이 회사는 정말 숫자로 증명하고 있나요?', 'scene': '화려한 포장지 안의 빈 상자와 실적, 현금흐름, 이해관계 체크리스트'},
        ]
    }


def default_shorts(pack):
    nums = ', '.join(pack.get('numbers', [])[:3]) or pack.get('key_metric', '')
    return {
        'title': f"{pack['subject']} 1분 쇼츠",
        'hook': f"{nums} 이 숫자만 보면 놓치는 게 있습니다.",
        'script': f"""0초
{nums}
이건 단순한 결과가 아닙니다.

5초
사람들이 먼저 본 건 가격이었지만,
진짜 봐야 할 건 그 가격을 만든 믿음입니다.

15초
처음엔 믿을 이유가 있었습니다.
{shorten(pack['old_belief'], 95)}

28초
그 믿음은 테마와 전망을 만나 더 커졌습니다.
하지만 기대가 커질수록 시장은 숫자를 요구합니다.

42초
여기서 흔들린 건 {shorten(pack['verification'], 95)}입니다.
한 번 의심이 시작되면 시장은 스토리보다 근거를 먼저 봅니다.

55초
이건 기회일까요, 경고일까요?
댓글로 여러분의 판단을 남겨주세요.""",
        'shot_plan': [],
        'cta': '댓글로 여러분의 판단을 남겨주세요.'
    }


def default_midform(pack):
    nums = ', '.join(pack.get('numbers', [])[:4]) or pack.get('key_metric', '')
    return {
        'title': f"{pack['subject']} 5분 미드폼 대본",
        'hook': f"{nums} 이 숫자의 의미를 다시 봐야 합니다.",
        'script': f"""오프닝
{nums}
이 숫자만 보면 단순한 하락처럼 보입니다. 그런데 오늘 봐야 할 건 가격 그 자체가 아니라 그 가격을 만들었던 기대와 그 기대가 흔들린 이유입니다.

문제 제기
많은 사람들은 결과를 먼저 봅니다. 올랐는지, 떨어졌는지, 끝났는지부터 판단합니다. 하지만 시장에서 더 중요한 건 결과가 아니라 결과를 만든 구조입니다.

배경
처음엔 믿을 이유가 있었습니다. {shorten(pack['old_belief'], 220)} 시장은 현재 숫자보다 미래 가능성을 먼저 반영합니다. 문제는 그 가능성이 실제 숫자로 증명되는 순간입니다.

기대가 커진 방식
이 원본의 핵심 각도는 {pack['chosen_angle']}입니다. 기대는 혼자 커지지 않습니다. 테마, 스피커, 전망, 공시가 한 방향을 가리킬 때 사람들은 현재보다 미래를 먼저 사기 시작합니다.

근거
여기서 봐야 할 첫 번째 근거는 {shorten(pack['verification'], 220)}입니다. 기대가 커질수록 시장은 더 구체적인 증거를 요구합니다.

리스크
두 번째는 자금과 실행 리스크입니다. {shorten(pack['finance'], 180)} 그리고 {shorten(pack['execution'], 180)} 이런 요소들이 겹치면 시장은 더 이상 같은 기준으로 보지 않습니다.

핵심 판단
결국 핵심은 이겁니다. {shorten(pack['tension'], 220)} 가격보다 먼저 기대가 아직 숫자로 증명되고 있는지 확인해야 합니다.

마무리
그래서 이건 단순히 떨어졌냐, 싸졌냐의 문제가 아닙니다. 다시 볼 기회인지, 아직 남은 경고인지 판단하려면 차트보다 먼저 근거를 봐야 합니다. 여러분은 이 흐름을 어떻게 보시나요?""",
        'chapter_plan': [],
        'cta': '여러분은 이 흐름을 어떻게 보시나요?'
    }


def build_default(output_type, pack):
    if output_type == '카드뉴스 6장':
        return default_cardnews(pack)
    if output_type == '1분 쇼츠 대본':
        return default_shorts(pack)
    return default_midform(pack)


def build_quality_rubric(pack):
    return {
        'min_numeric_mentions': 2 if pack.get('content_mode') == 'market_or_company_shift' else 1,
        'min_cards': 6,
        'min_body_length_card2_3': 70,
        'forbidden_phrases': ['현실 신호', '핵심 포인트', '확인해보세요', '기준은 저장해두고 다시 확인해보세요', "'id':", '"id":', "'text':", '"text":'] + BAD_LABELS
    }


def validate_cardnews_quality(cards, pack):
    rubric = build_quality_rubric(pack)
    issues = []
    if not isinstance(cards, list) or len(cards) < 6:
        return {'passed': False, 'issues': ['카드 수가 6장 미만']}
    numeric_count, heads = 0, []
    for idx, card in enumerate(cards[:6], start=1):
        head = clean(card.get('headline') or card.get('head_copy') or '')
        body = clean(card.get('body') or card.get('body_copy') or '')
        heads.append(head)
        if not head:
            issues.append(f'{idx}장 헤드카피 누락')
        if not body:
            issues.append(f'{idx}장 바디카피 누락')
        if idx in [2, 3] and len(body) < rubric['min_body_length_card2_3']:
            issues.append(f'{idx}장 설명 밀도 부족')
        numeric_count += len(extract_numbers(head + ' ' + body))
        for bad in rubric['forbidden_phrases']:
            if bad and (bad in head or bad in body):
                issues.append(f'{idx}장 금지 표현 포함: {bad}')
    if len(set(heads)) < max(4, len(heads) - 1):
        issues.append('헤드카피 중복률이 높음')
    if numeric_count < rubric['min_numeric_mentions']:
        issues.append('구체 숫자 반영 부족')
    last = clean(cards[5].get('body') or cards[5].get('body_copy') or '') + ' ' + clean(cards[5].get('headline') or cards[5].get('head_copy') or '')
    if not any(k in last for k in ['질문', '확인', '기준', '체크', '교훈', '다음', '숫자']):
        issues.append('마지막 장에 교훈/체크 질문 부족')
    return {'passed': len(issues) == 0, 'issues': issues}


def sanitize_image_description(text):
    text = clean(text)
    for token in BAD_IMAGE_TOKENS:
        text = text.replace(token, '')
    return text.replace('문구', '장면').replace('카피', '시각 요소').strip()


def build_prompt(output_type, pack, default_output, tone, ratio, style, include_copy, repair_issues=None, previous_raw=''):
    common = f"""
너는 한국 커뮤니티와 유튜브 문법을 잘 아는 콘텐츠 편집자다.
너의 임무는 원본을 요약하는 것이 아니라, 가장 강한 서사 축을 찾아 콘텐츠 형식에 맞게 재편집하는 것이다.
반드시 JSON만 출력한다. 마크다운 금지.
금지 표현: {', '.join(FORBIDDEN + BAD_LABELS)}
내부 데이터 객체, id, text, source 같은 필드명은 절대 출력하지 마라.
원문에 없는 구체 사실을 지어내지 말고, 투자/주식 내용은 매수/매도 추천처럼 쓰지 마라.
어조: {tone}

rich_context_pack:
{json.dumps(pack, ensure_ascii=False, indent=2)}

규칙 기반 초안:
{json.dumps(default_output, ensure_ascii=False, indent=2)}
"""
    if repair_issues:
        common += f"""

이전 결과는 품질 기준을 통과하지 못했다.
문제점:
{chr(10).join('- ' + issue for issue in repair_issues)}

기존 출력:
{previous_raw}

반드시 위 문제를 고쳐서 다시 작성하라.
"""
    if output_type == '카드뉴스 6장':
        return common + f"""
출력 형식:
{{"title":"", "core_problem":"", "main_message":"", "cta":"", "cards":[{{"headline":"", "body":"", "scene":""}}]}}
카드뉴스 규칙:
- cards는 정확히 6개.
- 1장은 충격 결과로 멈춰 세운다.
- 2장은 왜 믿었는지 배경을 충분히 설명한다.
- 3장은 믿음이 어떻게 증폭됐는지 설명한다.
- 4장은 어떤 숫자/사실이 그 믿음을 흔들었는지 설명한다.
- 5장은 피해, 고립, 리스크 현실화를 보여준다.
- 6장은 다음 유사 사례에 적용할 질문/기준으로 닫는다.
- 각 장은 이전 장과 다른 정보를 전진시켜라.
- 각 장마다 evidence_bank의 구체 근거를 최소 하나 반영하되 객체 구조는 출력하지 마라.
- scene은 이미지 생성용 장면 설명이다. 이미지 안에 넣을 글자를 설명하지 말고 시각 장면만 설명하라.
- 이미지 비율: {ratio}, 이미지 스타일: {style}, 이미지 내 헤드라인 포함: {include_copy}
"""
    if output_type == '1분 쇼츠 대본':
        return common + """
출력 형식:
{"title":"", "hook":"", "script":"", "shot_plan":[{"time":"", "visual":""}], "cta":""}
쇼츠 규칙:
- 전체 길이는 약 55~70초 분량.
- 첫 3초에 강한 숫자/결과/반전으로 멈춰 세운다.
- 원본의 감정선: 충격 → 이유 → 반전 → 판단 질문.
- 문장은 짧고 구어체로 쓴다.
- 타임코드를 포함한다.
- 마지막은 댓글 유도형 질문으로 닫는다.
"""
    return common + """
출력 형식:
{"title":"", "hook":"", "script":"", "chapter_plan":[{"section":"", "purpose":""}], "cta":""}
미드폼 규칙:
- 전체 길이는 약 5분 분량.
- 오프닝, 문제 제기, 배경, 믿음이 커진 방식, 근거 1, 리스크/반론, 판단 기준, 마무리 구조로 쓴다.
- 단순 요약이 아니라 시청자가 이해할 수 있게 설명을 충분히 넣는다.
- 원본의 말맛과 감정선을 유지한다.
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
        payload = {'model': model, 'input': prompt, 'temperature': temperature, 'text': {'format': {'type': 'json_object'}}}
        res = requests.post(url, json=payload, headers=headers, timeout=120)
        res.raise_for_status()
        return extract_response_text(res.json())
    if provider == 'Gemini':
        url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}'
        payload = {'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': {'temperature': temperature, 'responseMimeType': 'application/json'}}
        res = requests.post(url, json=payload, timeout=90)
        res.raise_for_status()
        return res.json()['candidates'][0]['content']['parts'][0]['text']
    headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
    url = 'https://api.groq.com/openai/v1/chat/completions' if provider == 'Groq' else 'https://openrouter.ai/api/v1/chat/completions'
    if provider == 'OpenRouter':
        headers.update({'HTTP-Referer': 'https://eafi-benchmark-db.streamlit.app', 'X-Title': 'EAFI Content Generator'})
    payload = {'model': model, 'messages': [{'role': 'system', 'content': 'Return valid JSON only.'}, {'role': 'user', 'content': prompt}], 'temperature': temperature}
    res = requests.post(url, json=payload, headers=headers, timeout=90)
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


def normalize_card(src, base):
    return {
        'headline': clean(src.get('headline') or src.get('head_copy') or base.get('headline') or base.get('head_copy') or ''),
        'body': clean(src.get('body') or src.get('body_copy') or base.get('body') or base.get('body_copy') or ''),
        'scene': sanitize_image_description(src.get('scene') or src.get('image_description') or base.get('scene') or base.get('image_description') or '')
    }


def validate_result(output_type, obj, default_output, pack=None):
    if not isinstance(obj, dict):
        obj = {}
    if output_type == '카드뉴스 6장':
        cards = obj.get('cards') if isinstance(obj.get('cards'), list) else default_output['cards']
        fixed = []
        for i in range(6):
            src = cards[i] if i < len(cards) and isinstance(cards[i], dict) else default_output['cards'][i]
            fixed.append(normalize_card(src, default_output['cards'][i]))
        result = {
            'title': clean(obj.get('title'), default_output['title']),
            'core_problem': clean(obj.get('core_problem'), default_output['core_problem']),
            'main_message': clean(obj.get('main_message'), default_output['main_message']),
            'cta': clean(obj.get('cta'), default_output['cta']),
            'cards': fixed
        }
        if pack:
            result['quality'] = validate_cardnews_quality(fixed, pack)
        return result
    if output_type == '1분 쇼츠 대본':
        return {
            'title': clean(obj.get('title'), default_output['title']),
            'hook': clean(obj.get('hook'), default_output.get('hook', '')),
            'script': clean(obj.get('script'), default_output['script']),
            'shot_plan': obj.get('shot_plan') if isinstance(obj.get('shot_plan'), list) else [],
            'cta': clean(obj.get('cta'), default_output.get('cta', '')),
        }
    return {
        'title': clean(obj.get('title'), default_output['title']),
        'hook': clean(obj.get('hook'), default_output.get('hook', '')),
        'script': clean(obj.get('script'), default_output['script']),
        'chapter_plan': obj.get('chapter_plan') if isinstance(obj.get('chapter_plan'), list) else [],
        'cta': clean(obj.get('cta'), default_output.get('cta', '')),
    }


def generate_with_repair(output_type, provider, api_key, model, pack, default_output, tone, ratio, style, include_copy, temperature):
    prompt = build_prompt(output_type, pack, default_output, tone, ratio, style, include_copy)
    raw = call_llm(provider, api_key, model, prompt, temperature)
    result = validate_result(output_type, parse_json(raw), default_output, pack)
    repair_raw = ''
    if output_type == '카드뉴스 6장':
        quality = result.get('quality', {'passed': True, 'issues': []})
        if not quality.get('passed'):
            repair_prompt = build_prompt(output_type, pack, default_output, tone, ratio, style, include_copy, quality.get('issues', []), raw)
            repair_raw = call_llm(provider, api_key, model, repair_prompt, temperature)
            repaired = validate_result(output_type, parse_json(repair_raw), default_output, pack)
            if repaired.get('quality', {}).get('passed') or len(repaired.get('cards', [])) == 6:
                result = repaired
    return result, raw, repair_raw, len(prompt)


def build_image_prompt(card, ratio, style, include_copy):
    scene = sanitize_image_description(card.get('scene', ''))
    copy_rule = f"Render only this Korean headline text if text is needed: '{card['headline']}'. Do not render body copy, labels, captions, random letters, watermark, or UI field names." if include_copy else 'clean image only, no text, no captions, no typography, no letters, no watermark, no logo.'
    return f"{ratio} composition, {style}. {scene}. Body context for composition only: {shorten(card['body'], 120)}. {copy_rule}"


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
    st.set_page_config(page_title='LLM API 콘텐츠 생성', page_icon='🧠', layout='wide')
    init_tables()
    st.title('🧠 LLM API 콘텐츠 생성')
    st.caption('객체 누출 방지 + rich_context_pack 기반으로 카드뉴스, 1분 쇼츠, 5분 미드폼을 선택 생성합니다.')

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
    pack = build_rich_context_pack(row)
    default_output = build_default(output_type, pack)

    with st.expander('rich_context_pack / 편집 맥락 패키지', expanded=True):
        st.json({k: v for k, v in pack.items() if k != 'source_excerpt'})
    with st.expander('원본 발췌 / LLM 전달용'):
        st.text_area('source_excerpt', value=pack.get('source_excerpt', ''), height=260)
    with st.expander('구조 인사이트'):
        st.json(pack.get('structural_insight_pack', {}))

    col1, col2 = st.columns(2)
    run_rule = col1.button('규칙 기반 초안 생성')
    run_llm = col2.button('LLM으로 재작성', type='primary')

    state_key = f"safe_rich_multi_{output_type}_{int(row['id'])}_{provider}_{model}"
    if run_rule or run_llm or state_key not in st.session_state:
        result, raw, repair_raw, prompt_len = default_output, '', '', 0
        if run_llm and provider != '규칙 기반만 사용' and api_key and model:
            try:
                result, raw, repair_raw, prompt_len = generate_with_repair(output_type, provider, api_key, model, pack, default_output, tone, ratio, style, include_copy, temperature)
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
        st.session_state[state_key + '_repair_raw'] = repair_raw
        st.session_state[state_key + '_prompt_len'] = prompt_len

    result = st.session_state[state_key]
    st.markdown('---')

    if output_type == '카드뉴스 6장':
        st.markdown('### 카드뉴스 구성 직접 수정')
        quality = result.get('quality') or validate_cardnews_quality(result.get('cards', []), pack)
        if quality.get('passed'):
            st.success('품질 검사 통과')
        else:
            st.warning('품질 검사 이슈: ' + ' / '.join(quality.get('issues', [])))
        edited_cards = []
        for i, card in enumerate(result['cards'], 1):
            with st.container(border=True):
                st.markdown(f'#### {i}장')
                headline = st.text_area('헤드카피', value=clean(card['headline']), height=80, key=f'{state_key}_h_{i}')
                body = st.text_area('바디카피', value=clean(card['body']), height=120, key=f'{state_key}_b_{i}')
                scene = st.text_area('장면 방향', value=sanitize_image_description(card['scene']), height=95, key=f'{state_key}_s_{i}')
                prompt = build_image_prompt({'headline': headline, 'body': body, 'scene': scene}, ratio, style, include_copy)
                st.text_area('이미지 생성 프롬프트', value=prompt, height=135, key=f'{state_key}_p_{i}')
                edited_cards.append({'headline': headline, 'body': body, 'scene': scene})
        result['cards'] = edited_cards
    else:
        label = '1분 쇼츠 대본' if output_type == '1분 쇼츠 대본' else '5분 미드폼 유튜브 대본'
        st.markdown(f'### {label} 직접 수정')
        result['title'] = st.text_input('제목', value=result.get('title', ''), key=f'{state_key}_title')
        result['hook'] = st.text_area('후킹 문장', value=result.get('hook', ''), height=80, key=f'{state_key}_hook')
        result['script'] = st.text_area('대본', value=result.get('script', ''), height=540, key=f'{state_key}_script')
        with st.expander('구성표'):
            plan_key = 'shot_plan' if output_type == '1분 쇼츠 대본' else 'chapter_plan'
            st.json(result.get(plan_key, []))

    result['title'] = st.text_input('저장 제목', value=result.get('title', ''), key=f'{state_key}_save_title')
    with st.expander('LLM 원문 출력'):
        st.write(f"prompt 문자 수: {st.session_state.get(state_key + '_prompt_len', 0):,}")
        st.code(st.session_state.get(state_key + '_raw', ''))
    with st.expander('LLM repair 출력'):
        st.code(st.session_state.get(state_key + '_repair_raw', ''))

    if st.button('이 결과 저장', type='primary'):
        save_output(int(row['id']), output_type, provider, model, result)
        st.success('콘텐츠 생성 결과를 저장했습니다.')


if __name__ == '__main__':
    main()
