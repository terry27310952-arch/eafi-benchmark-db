import json
import requests
import streamlit as st

st.set_page_config(page_title='LLM API 테스트', page_icon='🧠', layout='wide')
st.title('🧠 LLM API 테스트')
st.caption('Streamlit secrets에 저장한 외부 LLM 키가 정상 작동하는지 확인하는 페이지입니다.')

provider = st.selectbox('Provider', ['Gemini', 'Groq', 'OpenRouter'])
secret_map = {
    'Gemini': 'GEMINI_API_KEY',
    'Groq': 'GROQ_API_KEY',
    'OpenRouter': 'OPENROUTER_API_KEY',
}
model_map = {
    'Gemini': 'gemini-2.0-flash-lite',
    'Groq': 'llama-3.1-8b-instant',
    'OpenRouter': 'openrouter/auto',
}
secret_name = st.text_input('secrets key name', value=secret_map[provider])
model = st.text_input('model', value=model_map[provider])
prompt = st.text_area('테스트 프롬프트', value='한국어 카드뉴스 헤드카피 3개만 JSON 배열로 만들어줘.', height=120)


def get_secret(name):
    try:
        return st.secrets.get(name, '')
    except Exception:
        return ''


def call_gemini(key, model, prompt):
    url = f'https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={key}'
    payload = {
        'contents': [{'parts': [{'text': prompt}]}],
        'generationConfig': {'temperature': 0.5, 'responseMimeType': 'application/json'},
    }
    r = requests.post(url, json=payload, timeout=60)
    r.raise_for_status()
    data = r.json()
    return data['candidates'][0]['content']['parts'][0]['text']


def call_openai_style(url, key, model, prompt, extra_headers=None):
    headers = {'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'}
    if extra_headers:
        headers.update(extra_headers)
    payload = {
        'model': model,
        'messages': [
            {'role': 'system', 'content': 'Return valid JSON only.'},
            {'role': 'user', 'content': prompt},
        ],
        'temperature': 0.5,
    }
    r = requests.post(url, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()['choices'][0]['message']['content']


if st.button('호출 테스트', type='primary'):
    key = get_secret(secret_name)
    if not key:
        st.error(f'Streamlit secrets에 {secret_name} 값이 없습니다.')
    else:
        try:
            if provider == 'Gemini':
                out = call_gemini(key, model, prompt)
            elif provider == 'Groq':
                out = call_openai_style('https://api.groq.com/openai/v1/chat/completions', key, model, prompt)
            else:
                out = call_openai_style(
                    'https://openrouter.ai/api/v1/chat/completions',
                    key,
                    model,
                    prompt,
                    {'HTTP-Referer': 'https://eafi-benchmark-db.streamlit.app', 'X-Title': 'EAFI Cardnews Planner'},
                )
            st.success('호출 성공')
            st.code(out)
            try:
                st.json(json.loads(out))
            except Exception:
                pass
        except Exception as e:
            st.error(f'호출 실패: {e}')
