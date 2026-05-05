import json, re, sqlite3
from datetime import datetime
from pathlib import Path
import pandas as pd
import streamlit as st

DB_PATH = Path('eafi_benchmark.db')
TOPIC_TYPES=['자동 감지','사건/논쟁','시장/투자','트렌드/이슈','브랜드/마케팅','라이프스타일','교육/노하우','기술/AI','직접 입력']
TONE=['담백','명확','강한 후킹','자극적']
RATIOS=['1:1','16:9','9:16','4:3']
IMG_STYLES=['깔끔한 인포그래픽','실사 시네마틱','3D 애니메이션','2D 일러스트','웹툰/만화형','미니멀 타이포그래피','뉴스 에디토리얼','데이터 대시보드','프리미엄 브랜드룩','AI 혼합 콜라주']
GOALS=['원본 내용 깊이 분석','카드뉴스 원천 데이터화','바이럴 후킹 추출','교육형 요약','이슈/트렌드 재가공']
PLAT=['인스타 카드뉴스','유튜브 커뮤니티','블로그','쓰레드','틱톡/숏폼','범용']
DEPTH=['핵심만','구조 분석','세부 근거까지','전환 관점','후킹/바이럴 관점']
TMPL=['자동 최적화','문제 제기형','체크리스트형','전후 비교형','교육형','트렌드 분석형']
TARGET={'일반 시청자':'해당 주제에 관심 있는 일반 시청자','브랜드/마케팅 담당자':'영상 제작을 검토 중인 브랜드/마케팅 담당자','콘텐츠 제작자':'유튜브와 숏폼을 꾸준히 운영해야 하는 콘텐츠 제작자','투자/시장 관심층':'시장 흐름과 이슈를 빠르게 파악하려는 사람','직접 입력':''}
ANGLE={'자동 생성':'__AUTO__','사건의 뒷면':'사건의 뒷면','문제폭로형':'문제폭로형','오해반박형':'오해반박형','체크리스트형':'체크리스트형','전후비교형':'전후비교형','바이럴 후킹형':'바이럴 후킹형','직접 입력':''}
PROB={'자동 추출':'__AUTO__','숨은 갈등':'겉으로 보이는 결과만 보고 그 뒤에 있는 갈등과 이해관계를 놓치는 상태','정보 과잉':'정보는 많지만 무엇을 기준으로 판단해야 하는지 흐려진 상태','직접 입력':''}
CTA={'자동 맥락형 엔딩':'__AUTO_CONTEXT__','댓글 유도':'여러분은 이 이야기를 어떻게 보시나요? 댓글로 남겨주세요','공유 유도':'이 이야기가 필요한 분에게 공유해보세요','팔로우 유도':'비슷한 분석을 계속 보고 싶다면 팔로우해두세요','DM 문의':'이런 카드뉴스 제작이 필요하다면 DM으로 문의해주세요','직접 입력':''}
STYLE={'깔끔한 인포그래픽':'clean editorial infographic, organized icons, clear hierarchy, generous whitespace','실사 시네마틱':'cinematic realistic photography, premium lighting, natural texture','3D 애니메이션':'stylized 3D animation, polished commercial render','2D 일러스트':'modern flat 2D illustration, clean shapes','웹툰/만화형':'Korean webtoon inspired illustration, dynamic panels','미니멀 타이포그래피':'minimal typography poster, bold graphic rhythm','뉴스 에디토리얼':'news editorial visual, data panels, reportage mood','데이터 대시보드':'data dashboard design, charts, UI cards','프리미엄 브랜드룩':'premium brand campaign visual, black and warm gray palette','AI 혼합 콜라주':'AI mixed media collage, realistic elements with graphic overlays'}
RATIO={'1:1':'square 1:1 composition','16:9':'wide 16:9 horizontal composition','9:16':'vertical 9:16 mobile story composition','4:3':'classic 4:3 editorial composition'}
PRICE=re.compile(r'\d+(?:[,.]\d+)?\s*(?:만원|천원|원|달러|조|억|%|배)')
NUM=re.compile(r'\d+(?:[,.]\d+)?\s*(?:만원|천원|원|조|억|%|배|달러|명|개|건)?')
WORD=re.compile(r'[가-힣A-Za-z0-9]{2,}')
TOK={'market':['주가','가격','만원','천원','시총','고점','저점','폭락','급락','하락','상승','급등','차트','거래량'],'expect':['기대','미래','성장','스토리','전망','호재','수혜','테마','비전','가능성','사업','개발','투자'],'verify':['실적','매출','영업','손실','적자','숫자','이익','재무','분기','보고서','성과','증거'],'finance':['자금','현금','전환사채','CB','유상증자','부채','차입','상환','조달','채권','유동성'],'execute':['공시','지연','계약','생산','공장','인허가','리튬','배터리','2차전지','진행','납품','양산'],'conflict':['하지만','그런데','문제는','반면','그러나','의심','리스크','위험','논란','갈등','반발','요구','경고'],'stake':['회사','직원','노조','정부','소비자','시민','주주','투자자','개미','경영진','기관','외국인'],'howto':['방법','체크','주의','실수','조건','원리','해야','하지','먼저','팁','노하우']}
STOP=set('만원에서 천원까지 결론 가격 주가 몰락 붕괴 폭락 하락 상승 급락 급등 문제 결과 기준 영상 스크립트 원본 핵심 주제 이야기 카드뉴스 시장 투자자 미래 성장 기대 현실 숫자 검증 단서 배경 근거 간극 이번 오늘 사람들'.split())
INTERNAL=['현실 신호','기대 신호','결과 신호','충돌 신호','context_profile','result_signal','expectation_signal','reality_signal','conflict_signal','verification_gap','market_repricing']
FIELD=['헤드카피','바디카피','카피','장면 방향','이미지 생성 프롬프트','Copy intent']
BAD_HEAD=['핵심 단서','사람들이 놓치는 지점','판단 기준','정리하면','마지막 질문','먼저 봐야 할 기준']

def db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; return c

def init_table():
    c=db(); c.execute("""CREATE TABLE IF NOT EXISTS cardnews_plans (id INTEGER PRIMARY KEY AUTOINCREMENT, reference_id INTEGER, title TEXT NOT NULL, target_customer TEXT, core_problem TEXT, main_message TEXT, cta TEXT, slide_1 TEXT, slide_2 TEXT, slide_3 TEXT, slide_4 TEXT, slide_5 TEXT, slide_6 TEXT, image_1 TEXT, image_2 TEXT, image_3 TEXT, image_4 TEXT, image_5 TEXT, image_6 TEXT, status TEXT DEFAULT '초안', created_at TEXT NOT NULL)"""); c.commit(); c.close()

def clean(v,d=''):
    if v is None: return d
    s=str(v).strip()
    return d if s.lower() in ['nan','none','null'] else (s or d)

def js(v,d=None):
    d={} if d is None else d
    if isinstance(v,(dict,list)): return v
    try: return json.loads(clean(v)) if clean(v) else d
    except Exception: return d

def gv(row,k,d=''):
    try: return clean(row.get(k,d),d)
    except Exception:
        try: return clean(row[k],d)
        except Exception: return d

def strip_text(t):
    t=clean(t); t=re.sub(r'https?://\S+','',t); t=re.sub(r'\[[sS]?\d+\]','',t); t=re.sub(r'[\"“”\']','',t)
    for f in FIELD: t=re.sub(rf'(?im)^\s*{re.escape(f)}\s*[:：]?\s*','',t)
    return re.sub(r'\s+',' ',t).strip()

def norm(t):
    t=strip_text(t)
    for a,b in {'현실 신호':'검증할 숫자','기대 신호':'처음의 기대','결과 신호':'드러난 결과','충돌 신호':'엇갈린 지점','기대가 숫자로 검증되는 순간이 왔습니다':'기대가 숫자로 검증되는 순간','그 기대를 다시 확인하게 만든':'그 기대를 흔든','왔습니다입니다':'왔습니다','합니다입니다':'합니다','됩니다입니다':'됩니다','있습니다입니다':'있습니다','입니다입니다':'입니다'}.items(): t=t.replace(a,b)
    for x in INTERNAL: t=t.replace(x,'')
    return re.sub(r'\s+',' ',t).strip()

def short(t,n=130):
    t=norm(t); return t if len(t)<=n else t[:n-1].rstrip()+'…'

def polish(t,tone='명확'):
    t='\n'.join(x.strip() for x in clean(norm(t)).splitlines() if x.strip())
    for a,b in {'왔습니다입니다':'왔습니다','합니다입니다':'합니다','됩니다입니다':'됩니다','있습니다입니다':'있습니다','때문입니다입니다':'때문입니다','입니다입니다':'입니다','..':'.'}.items(): t=t.replace(a,b)
    return t.strip()

def trim(t):
    return re.sub(r'(입니다|합니다|였습니다|했습니다|왔습니다|됩니다|있습니다|없습니다|됐습니다|니다|다|요)[.!?！。]*$','',norm(t)).strip()

def has(t,arr): return any(x in clean(t) for x in arr)
def cnt(t,arr): return sum(1 for x in arr if x in clean(t))
def split_sents(t): return [norm(x) for x in re.split(r'(?<=[.!?。！？])\s+|(?<=다)\s+|(?<=요)\s+|(?<=죠)\s+|(?<=습니다)\s+',strip_text(t)) if len(norm(x))>10]
def first(*vals,fb=''):
    for v in vals:
        if isinstance(v,str) and norm(v): return norm(v)
        if v: return v
    return fb

def load_refs():
    c=db(); dfs=[]
    try: dfs.append(pd.read_sql_query("""SELECT r.id,'content_reference' AS source_table,c.platform,c.channel_name,c.category,r.title,r.url,r.hook_point,r.structure_note,r.visual_note,r.eafi_application,r.total_score,r.status,r.created_at FROM content_references r LEFT JOIN benchmark_channels c ON r.channel_id=c.id ORDER BY r.id DESC""",c))
    except Exception: pass
    try:
        yt=pd.read_sql_query('SELECT * FROM youtube_video_analyses ORDER BY id DESC',c)
        if not yt.empty:
            yt['source_table']='youtube_analysis'; yt['platform']='YouTube'; yt['category']=yt.get('source_kind','영상 분석'); yt['total_score']=20; yt['status']='원본 해석'; dfs.append(yt)
    except Exception: pass
    c.close()
    if not dfs: return pd.DataFrame()
    df=pd.concat(dfs,ignore_index=True,sort=False)
    for col in ['source_kind','event_type','original_topic','main_topic_sentence','primary_claim','actor_map','event_timeline','cardnews_seed','interpretation_slots','source_index','contradiction_or_tension','hidden_assumption','emotional_trigger','viral_hook_logic','reusable_structure','source_grounded_qa','evidence_points','cause_effect_chain','audience_pain','keywords','summary','transcript','interpretation_report']:
        if col not in df.columns: df[col]=''
    return df.sort_values('created_at',ascending=False,na_position='last')

def load_plans():
    c=db(); df=pd.read_sql_query('SELECT * FROM cardnews_plans ORDER BY id DESC LIMIT 50',c); c.close(); return df

def flatten(x):
    if isinstance(x,dict): return norm(x.get('event') or x.get('source') or x.get('fact') or x.get('answer') or x.get('basis') or x.get('text') or '')
    return norm(x)

def collect_facts(row):
    pool=[gv(row,k) for k in ['primary_claim','original_topic','main_topic_sentence','audience_pain','contradiction_or_tension','hidden_assumption']]
    for k in ['evidence_points','event_timeline','cause_effect_chain','source_grounded_qa']:
        v=js(gv(row,k),[]); pool += v if isinstance(v,list) else []
    for k in ['interpretation_slots','cardnews_seed','source_index','interpretation_report']:
        o=js(gv(row,k),{})
        if isinstance(o,dict):
            for sub in ['fact_roles','context_profile','fact_seeds','timeline_seeds']:
                it=o.get(sub)
                if isinstance(it,dict): pool+=list(it.values())
                elif isinstance(it,list): pool+=it
            if isinstance(o.get('slide_seed'),dict): pool+=list(o['slide_seed'].values())
            if isinstance(o.get('source_index'),dict): pool+=list(o['source_index'].values())
            if isinstance(o.get('interpretation_slots'),dict): pool+=list(o['interpretation_slots'].values())
    pool += split_sents(gv(row,'summary'))[:30]+split_sents(gv(row,'transcript'))[:120]
    out=[]; seen=set()
    for it in pool:
        v=flatten(it); key=re.sub(r'[^가-힣A-Za-z0-9]','',v[:80])
        if v and key not in seen:
            seen.add(key); out.append(v)
        if len(out)>=80: break
    return out

def saved_profile(row):
    cand=[]
    for k in ['interpretation_slots','cardnews_seed','source_index','interpretation_report']:
        o=js(gv(row,k),{})
        if isinstance(o,dict):
            cand.append(o.get('context_profile',{}))
            if isinstance(o.get('fact_roles'),dict): cand.append(o['fact_roles'].get('context_profile',{}))
            if isinstance(o.get('source_index'),dict): cand.append(o['source_index'].get('context_profile',{}))
            if isinstance(o.get('interpretation_slots'),dict): cand.append(o['interpretation_slots'].get('context_profile',{}))
    for c in cand:
        if isinstance(c,dict) and c: return {k:norm(v) if isinstance(v,str) else v for k,v in c.items()}
    return {}

def subject_score(tok,text):
    tok=re.sub(r'(의|은|는|이|가|을|를|에서|까지|으로|로|와|과)$','',tok.strip())
    if not tok or tok in STOP or PRICE.search(tok) or re.match(r'^\d',tok): return -999
    sc=(4 if re.search('[가-힣]',tok) else 0)+(2 if len(tok)<=5 else 0)+(1 if tok in text else 0)
    if tok.endswith(('전자','산업','바이오','에너지','금양')): sc+=3
    if has(tok,['가격','주가','시장','투자','결과','문제','배경']): sc-=5
    return sc

def infer_subject(topic,fs,prof):
    ps=norm(prof.get('subject','') if isinstance(prof,dict) else ''); text=norm(topic+' '+' '.join(fs[:8]))
    if ps and subject_score(ps,text)>0: return re.sub(r'(의|은|는|이|가|을|를)$','',ps)
    cand=[]
    for t in WORD.findall(PRICE.sub(' ',text)):
        b=re.sub(r'(의|은|는|이|가|을|를|에서|까지|으로|로|와|과)$','',t); sc=subject_score(b,text)
        if sc>-100: cand.append((sc,b))
    return sorted(cand,reverse=True)[0][1] if cand else '이 주제'

def find_fact(fs,tokens,fb=''):
    ranked=[]
    for i,f in enumerate(fs):
        sc=cnt(f,tokens)*3+len(NUM.findall(f))
        if sc>0: ranked.append((sc,-i,f))
    return norm(sorted(ranked,reverse=True)[0][2]) if ranked else norm(fb)

def mode_score(text,explicit=''):
    if explicit in ['market_or_company_shift','corporate_stock_collapse','market_analysis','시장/기업 분석형','문맥형 시장/기업 분석']: return 'market_or_company_shift',{'forced':explicit}
    if explicit in ['stakeholder_conflict','samsung_labor','labor_conflict','legal_conflict','문맥형 이해관계 갈등','사건형']: return 'stakeholder_conflict',{'forced':explicit}
    if explicit in ['howto_or_warning','문맥형 노하우/경고','튜토리얼/노하우형']: return 'howto_or_warning',{'forced':explicit}
    scores={'market_or_company_shift':cnt(text,TOK['market'])*3+cnt(text,TOK['verify'])*2+cnt(text,TOK['finance'])*2+len(PRICE.findall(text))*3,'stakeholder_conflict':cnt(text,TOK['stake'])*2+cnt(text,['갈등','반발','요구','파업','소송','법원','노조','직원']),'howto_or_warning':cnt(text,TOK['howto'])*2,'issue_context':1}
    if len(PRICE.findall(text))>=2 or (has(text,['주가','시총','고점','저점']) and has(text,['폭락','하락','급락','몰락','붕괴'])): scores['market_or_company_shift']+=12
    return max(scores.items(),key=lambda x:x[1])[0],scores

def build_signals(row,prof,fs,topic):
    joined=' '.join([topic]+fs[:40]+[gv(row,'keywords')]); m,scores=mode_score(joined,prof.get('mode') or gv(row,'event_type')); subj=infer_subject(topic,fs,prof)
    result=first(prof.get('result_signal',''),gv(row,'primary_claim'),find_fact(fs,TOK['market']+['논란','몰락','붕괴','문제'],topic),fb=topic)
    metric=first(prof.get('metric_signal',''),find_fact(fs,TOK['market'],result),fb=result)
    exp=first(prof.get('expectation_signal',''),find_fact(fs,TOK['expect'],'미래 가능성에 대한 기대가 먼저 쌓였습니다'),fb='미래 가능성에 대한 기대가 먼저 쌓였습니다')
    ver=find_fact(fs,TOK['verify'],'실적과 숫자가 그 기대를 따라오는지 확인해야 했습니다')
    fin=find_fact(fs,TOK['finance'],'자금 조달과 현금 흐름도 다시 봐야 할 변수였습니다')
    exe=find_fact(fs,TOK['execute'],'사업 진행 속도와 공시된 리스크도 판단에 영향을 줍니다')
    rep=find_fact(fs,TOK['conflict']+TOK['market'],'시장은 미래 이야기보다 증명된 숫자를 보기 시작했습니다')
    conf=first(prof.get('conflict_signal',''),gv(row,'contradiction_or_tension'),rep,fb='겉으로 보이는 결과와 실제 판단 기준이 엇갈린 지점')
    return {'mode':m,'mode_scores':scores,'subject':subj,'result':norm(result),'metric':norm(metric),'expectation':norm(exp),'verification_gap':norm(ver),'financial_pressure':norm(fin),'execution_risk':norm(exe),'market_repricing':norm(rep),'conflict':norm(conf),'data_quality':{'facts_count':len(fs),'has_price':bool(PRICE.search(joined)),'has_verification':has(joined,TOK['verify']),'has_finance':has(joined,TOK['finance']),'has_execution':has(joined,TOK['execute'])}}

def analyze(row,topic_sel,context):
    fs=collect_facts(row); prof=saved_profile(row); slots=js(gv(row,'interpretation_slots'),{})
    topic=first(slots.get('original_topic','') if isinstance(slots,dict) else '',gv(row,'original_topic'),gv(row,'main_topic_sentence'),gv(row,'title'),fb='원본에 담긴 핵심 변화')
    sig=build_signals(row,prof,fs,topic); prof={**prof,**sig}; m=sig['mode']
    tt={'market_or_company_shift':'시장/투자','stakeholder_conflict':'사건/논쟁','howto_or_warning':'교육/노하우','issue_context':'트렌드/이슈'}.get(m,'트렌드/이슈') if topic_sel=='자동 감지' else topic_sel
    return {'source_table':gv(row,'source_table'),'event_type':m,'topic_type':tt,'topic':norm(topic),'primary_claim':first(gv(row,'primary_claim'),sig['result'],fb=topic),'audience_problem':first(gv(row,'audience_pain'),'독자는 결과에 먼저 반응하지만, 그 결과를 만든 배경과 조건은 놓치기 쉽습니다'),'conflict':first(gv(row,'contradiction_or_tension'),sig['conflict'],fb='결과와 배경 사이의 간극'),'hidden_assumption':first(gv(row,'hidden_assumption'),'겉으로 보이는 결과가 곧 전체 이유라는 착각'),'emotional_trigger':first(gv(row,'emotional_trigger'),'강한 결과와 뒤늦게 드러난 맥락이 만드는 재판단 욕구'),'viral_hook_logic':first(gv(row,'viral_hook_logic'),'강한 결과를 먼저 보여주고, 그 뒤의 기대와 검증 과정을 순서대로 공개하는 구조'),'narrative_structure':first(gv(row,'narrative_structure'),'결과 제시 → 기대 공개 → 숫자 검증 → 재평가 → 판단 기준 → 질문'),'reusable_structure':first(gv(row,'reusable_structure'),'결과로 멈춰 세우고, 기대와 검증의 간극을 분해한 뒤 질문으로 닫는 구조'),'facts':fs,'profile':prof}

def card(role,h,b,v): return {'role':role,'headline':polish(h),'body':polish(b),'visual_spec':v}
def comb(c): return c.get('headline','')+('\n\n'+c.get('body','') if c.get('body') else '')
def gen_cta(cta): return not clean(cta) or '__AUTO_CONTEXT__' in clean(cta) or '저장해두고' in clean(cta)
def vhead(metric,s):
    nums=[x.strip() for x in PRICE.findall(norm(metric)) if x.strip()]
    if len(nums)>=2: return f'{nums[0]}에서 {nums[1]}까지\n무너진 건 가격만이 아닙니다'
    if len(nums)==1: return f'{nums[0]}이라는 숫자\n그 자체가 경고였습니다'
    if has(metric,['폭락','급락','하락','무너','몰락','붕괴']): return f'{s}\n무너진 건 차트만이 아닙니다'
    return f'{s}\n결과만 보면 놓치는 게 있습니다'

def ending(a,cta):
    if clean(cta) and not gen_cta(cta): return norm(cta)
    return {'market_or_company_shift':'다시 보려면 차트보다 먼저 확인해야 합니다. 이 기대가 아직 숫자로 증명되고 있는지, 아니면 시장이 이미 답을 바꾼 건지 말입니다.','stakeholder_conflict':'이 갈등을 다시 본다면, 누가 더 크게 말했는지가 아니라 누가 어떤 비용을 감수하는지부터 봐야 합니다.','howto_or_warning':'다음에 같은 상황을 만나면, 결론보다 조건을 먼저 확인해보세요. 적용 기준이 달라지면 결과도 달라집니다.'}.get(a.get('event_type'),'이 이야기를 다시 본다면, 결론보다 먼저 그 결론을 만든 배경부터 확인해야 합니다.')
def vis(s,r,obj,scene,cont,cam='정면에 가까운 카드뉴스형 구도',text='상단 25%에 헤드라인용 넓은 여백',tone='eaf 브랜드 톤의 레드, 블랙, 웜 그레이 기반'):
    return {'visual_subject':s,'role':r,'main_object':obj,'scene':scene,'contrast':cont,'camera':cam,'text_area':text,'brand_tone':tone}

def market_cards(a,cta):
    p=a['profile']; s=p['subject']; exp=trim(p['expectation']); ver=trim(p['verification_gap']); fin=trim(p['financial_pressure']); exe=trim(p['execution_risk']); rep=trim(p['market_repricing']); conf=trim(p['conflict'])
    return [card('shock',vhead(p['metric'],s),'그런데 이 이야기는 단순한 급락이 아닙니다. 먼저 봐야 할 건, 이 가격을 밀어올렸던 믿음이 무엇이었는지입니다.',vis(s,'shock','수직으로 떨어지는 주가 차트, 금이 간 상징 오브젝트, 흩어진 투자자 영수증','어두운 금융 뉴스룸 배경','과거 기대감과 현재 급락을 강하게 대비','살짝 내려다보는 정면 3D 인포그래픽 구도')),card('belief','처음엔 믿을 이유가 있었습니다',f'시장은 늘 미래를 먼저 가격에 반영합니다. 이때 사람들을 움직인 건 {short(exp,95)}였습니다.',vis(s,'belief','빛나는 성장 그래프, 미래 사업을 상징하는 오브젝트, 기대감이 모이는 데이터 패널','밝은 데이터룸 또는 미래형 산업 배경','상승 기대와 아직 검증되지 않은 숫자를 대비')),card('verify','문제는 숫자가 따라오지 못했다는 겁니다',f'기대가 커질수록 시장은 더 구체적인 증거를 요구합니다. 여기서 투자자가 봐야 할 건 {short(ver,100)}입니다.',vis(s,'verify','회계 보고서, 빨간 경고등, 꺾이는 그래프, 체크 표시가 들어간 리스크 문서','차가운 회계 자료와 모니터가 놓인 분석 데스크','성장 서사와 숫자 검증의 충돌을 대비')),card('repricing','시장은 더 이상 스토리만 보지 않았습니다',f'한 번 의심이 시작되면 기준은 바뀝니다. 미래 가능성보다 {short(fin,62)}, 그리고 {short(rep,62)}가 먼저 보이기 시작합니다.',vis(s,'repricing','계산기, 투자자 모니터, 재평가되는 차트, 빨간색과 회색 데이터 카드','증권사 리서치룸 같은 차가운 공간','기대에서 검증으로 바뀌는 시선을 표현')),card('standard','핵심은 하락률이 아닙니다',f'중요한 건 이 하락이 과한 공포인지, 뒤늦은 재평가인지입니다. 가격보다 먼저 봐야 할 건 {short(exe,75)}와 {short(conf,75)}입니다.',vis(s,'standard','저울, 두 갈래 길, 한쪽엔 미래 기대 그래프, 다른 쪽엔 차가운 실적표와 리스크 문서','절제된 금융 인포그래픽 배경','기회와 리스크가 동시에 놓인 판단 장면')),card('final','이건 기회일까요, 경고일까요?',ending(a,cta),vis(s,'final','갈림길 앞 투자자 실루엣, 한쪽은 반등 차트, 다른 쪽은 경고등이 켜진 리스크 표지판','어두운 배경에 선택지가 선명하게 보이는 마무리 장면','희망과 경고가 동시에 보이도록 대비'))]

def conflict_cards(a,cta):
    p=a['profile']; s=p['subject']; exp=trim(p['expectation']); ver=trim(p['verification_gap']); conf=trim(p['conflict'])
    return [card('hook',f'{s}\n겉으로 보이는 싸움이 전부는 아닙니다','처음 눈에 들어오는 건 강한 충돌 장면입니다. 하지만 갈등은 그 장면 하나로 끝나지 않습니다.',vis(s,'hook','서로 마주 선 두 집단, 가운데 갈라진 선, 뉴스 헤드라인 패널','긴장감 있는 뉴스룸 배경','양쪽 입장이 동시에 보이는 대립 구도')),card('demand','먼저 요구 조건을 봐야 합니다',f'갈등은 보통 요구에서 시작됩니다. 이 원문에서 먼저 확인할 것은 {short(exp,95)}입니다.',vis(s,'demand','요구서, 숫자가 표시된 문서, 한쪽 이해관계자들의 손짓','회의실 또는 협상 테이블','요구의 명분과 비용을 대비')),card('response','상대의 계산은 달랐습니다',f'반대편은 같은 장면을 다르게 봅니다. 여기서 부딪힌 현실적 조건은 {short(ver,95)}입니다.',vis(s,'response','차가운 계산서, 비용 그래프, 닫힌 회의실 문','건조한 기업 회의실 배경','감정적 요구와 냉정한 계산의 대비')),card('collision','갈등은 여기서 커졌습니다',f'핵심은 누가 더 목소리가 큰지가 아닙니다. 진짜 충돌 지점은 {short(conf,95)}입니다.',vis(s,'collision','충돌하는 화살표, 양쪽 주장 카드, 가운데 깨지는 선','다층 인포그래픽 배경','두 논리가 정면으로 부딪히는 장면')),card('cost','결국 누군가는 비용을 냅니다','이런 갈등은 승패보다 비용을 봐야 합니다. 누가 얻고, 누가 감수하는지가 판단의 핵심입니다.',vis(s,'cost','비용 계산표, 손익 저울, 서로 다른 이해관계자 아이콘','차분한 분석 보드','이득과 손실을 한 화면에서 대비')),card('final','당신은 어느 쪽이 더 설득력 있나요?',ending(a,cta),vis(s,'final','두 갈래 선택지와 중앙의 물음표, 양쪽 입장이 정리된 카드','여백이 넓은 마무리 카드','독자가 판단하게 만드는 균형 구도'))]

def howto_cards(a,cta):
    p=a['profile']; s=p['subject']; exp=trim(p['expectation']); ver=trim(p['verification_gap']); exe=trim(p['execution_risk'])
    return [card('hook',f'{s}\n그냥 따라 하면 놓치는 게 있습니다','겉으로는 쉬워 보여도 결과가 갈리는 지점은 따로 있습니다.',vis(s,'hook','잘못된 선택지와 올바른 선택지가 갈라진 체크리스트','깔끔한 생활형 인포그래픽 배경','흔한 실수와 올바른 기준을 대비')),card('why','먼저 이유를 알아야 합니다',f'사람들이 흔히 믿는 건 {short(exp,90)}입니다. 하지만 이유를 모르면 적용이 흔들립니다.',vis(s,'why','돋보기, 원리 도식, 핵심 이유가 연결된 화살표','밝은 교육형 카드 배경','결론보다 원리를 먼저 보여주는 구성')),card('condition','중요한 건 조건입니다',f'실제로 달라지는 지점은 {short(ver,95)}입니다. 조건을 놓치면 같은 방법도 다르게 작동합니다.',vis(s,'condition','조건표, 온오프 스위치, 체크된 기준 카드','정리된 체크리스트 보드','성공 조건과 실패 조건을 대비')),card('risk','여기서 실수가 갈립니다',f'주의해야 할 건 {short(exe,95)}입니다. 팁보다 중요한 건 언제, 누구에게, 어떻게 적용되는지입니다.',vis(s,'risk','경고 아이콘, 틀린 선택을 가리키는 빨간 표시, 올바른 경로','미니멀한 경고 카드 배경','안전한 선택과 위험한 선택을 대비')),card('check','정리하면 조건부터 봐야 합니다','무작정 따라 하기보다, 내 상황에서 이 조건이 맞는지 먼저 확인해야 합니다.',vis(s,'check','세 가지 체크포인트가 적힌 카드, 손가락으로 첫 번째 항목을 가리키는 장면','깔끔한 노하우 카드뉴스 배경','저장하고 다시 보는 체크리스트 느낌')),card('final','다음엔 이것부터 확인하세요',ending(a,cta),vis(s,'final','저장 버튼, 체크리스트, 작은 메모 카드','밝고 정돈된 마무리 카드','실행과 저장을 유도하는 구성'))]

def issue_cards(a,cta):
    p=a['profile']; s=p['subject']; res=trim(p['result']); exp=trim(p['expectation']); ver=trim(p['verification_gap']); conf=trim(p['conflict'])
    return [card('hook',f'{s}\n결론만 보면 놓치는 게 있습니다',f'사람들이 먼저 본 건 {short(res,90)}입니다. 하지만 이 이야기는 그 장면 하나로 설명되지 않습니다.',vis(s,'hook','강한 뉴스 헤드라인, 흐릿한 배경 자료, 중앙의 핵심 오브젝트','뉴스 에디토리얼 배경','결과와 숨은 배경을 대비')),card('background','먼저 배경을 봐야 합니다',f'이 이야기가 커진 이유는 {short(exp,95)} 때문입니다. 겉으로 보이는 결론 전에 쌓인 맥락이 있습니다.',vis(s,'background','오래된 자료 사진, 지도 또는 데이터 패널, 배경을 연결하는 선','차분한 다큐멘터리형 카드 배경','현재 결과와 과거 배경을 연결')),card('turn','문제는 여기서 시작됩니다',f'분위기가 바뀐 지점은 {short(conf,95)}입니다. 여기서 단순한 이야기가 의문으로 바뀝니다.',vis(s,'turn','갈라지는 선, 충돌하는 두 정보 카드, 중앙의 경고 표시','긴장감 있는 인포그래픽 배경','평온한 배경과 충돌 지점을 대비')),card('verify','근거를 다시 봐야 합니다',f'원문에서 다시 확인해야 할 건 {short(ver,95)}입니다. 결론보다 이 근거가 판단을 바꿉니다.',vis(s,'verify','돋보기, 원문 자료, 체크된 사실 카드','분석 데스크 배경','표면적 반응과 실제 근거를 대비')),card('standard','핵심은 이 간극입니다',f'중요한 건 누가 더 자극적으로 말했느냐가 아니라, {short(conf,95)}입니다.',vis(s,'standard','저울, 양쪽에 놓인 결과와 맥락, 가운데 벌어진 간극','미니멀한 판단 기준 카드','감정과 기준의 대비')),card('final','이제 다르게 보이시나요?',ending(a,cta),vis(s,'final','빈 여백 위의 큰 질문, 뒤쪽에 희미한 자료와 주체들','여백 중심 마무리 카드','독자가 다시 생각하게 만드는 조용한 엔딩'))]

def build_brief(a,cta):
    m=a.get('event_type','issue_context')
    if m=='market_or_company_shift': return {'card_arc':'market_result_belief_numbers_repricing_standard','cards':market_cards(a,cta)}
    if m=='stakeholder_conflict': return {'card_arc':'conflict_demand_response_cost','cards':conflict_cards(a,cta)}
    if m=='howto_or_warning': return {'card_arc':'howto_mistake_reason_condition_risk','cards':howto_cards(a,cta)}
    return {'card_arc':'issue_result_context_gap','cards':issue_cards(a,cta)}

def fallback_head(i,a):
    p=a.get('profile',{}); s=p.get('subject','이 주제'); m=a.get('event_type','issue_context')
    table={'market_or_company_shift':[vhead(p.get('metric',''),s),'처음엔 믿을 이유가 있었습니다','문제는 숫자가 따라오지 못했다는 겁니다','시장은 더 이상 스토리만 보지 않았습니다','핵심은 하락률이 아닙니다','이건 기회일까요, 경고일까요?'],'stakeholder_conflict':[f'{s}\n겉으로 보이는 싸움이 전부는 아닙니다','먼저 요구 조건을 봐야 합니다','상대의 계산은 달랐습니다','갈등은 여기서 커졌습니다','결국 누군가는 비용을 냅니다','당신은 어느 쪽이 더 설득력 있나요?'],'howto_or_warning':[f'{s}\n그냥 따라 하면 놓치는 게 있습니다','먼저 이유를 알아야 합니다','중요한 건 조건입니다','여기서 실수가 갈립니다','정리하면 조건부터 봐야 합니다','다음엔 이것부터 확인하세요'],'issue_context':[f'{s}\n결론만 보면 놓치는 게 있습니다','먼저 배경을 봐야 합니다','문제는 여기서 시작됩니다','근거를 다시 봐야 합니다','핵심은 이 간극입니다','이제 다르게 보이시나요?']}
    return table.get(m,table['issue_context'])[min(i,5)]

def quality_guard(cards,a,cta):
    out=[]; seen=set()
    for i,c in enumerate(cards[:6]):
        c=dict(c); c['headline']=polish(c.get('headline','')); c['body']=polish(c.get('body',''))
        if any(b==c['headline'].strip() or b in c['headline'] for b in BAD_HEAD) or c['headline'] in seen: c['headline']=fallback_head(i,a)
        seen.add(c['headline'])
        if len(strip_text(c['body']))<35:
            p=a.get('profile',{}); c['body']=f"이 장에서는 원문에서 확인된 구체 조건을 봐야 합니다. 핵심 단서는 {short(p.get('verification_gap') or p.get('conflict') or a.get('primary_claim'),90)}입니다."
        if i==5 and gen_cta(c['body']): c['body']=ending(a,cta)
        c['headline']=polish(c['headline']); c['body']=polish(c['body']); out.append(c)
    return out

def direction(spec):
    if not isinstance(spec,dict): return clean(spec,'구체적인 오브젝트와 배경, 대비, 카메라 구도를 포함한 카드뉴스 장면')
    return f"{spec.get('scene','')}. 중앙 오브젝트: {spec.get('main_object','')}. 대비: {spec.get('contrast','')}. 카메라/구도: {spec.get('camera','')}. 텍스트 영역: {spec.get('text_area','')}. 브랜드 톤: {spec.get('brand_tone','')}.".strip()

def img_copy(c):
    h=strip_text(c.get('headline','')).replace('\n',' '); b=strip_text(c.get('body','')).replace('\n',' ')
    for x in FIELD: h=h.replace(x,''); b=b.replace(x,'')
    return short(h,50),short(b,120)

def make_prompts(ctx,cards):
    base=RATIO[ctx['image_ratio']]+', '+STYLE[ctx['image_style']]; dirs=[]; prs=[]; used=set()
    for i,c in enumerate(cards):
        spec=dict(c.get('visual_spec',{})) if isinstance(c.get('visual_spec',{}),dict) else {}; key=spec.get('main_object','')[:35]
        if key in used: spec['main_object']=f'{i+1}장 역할에 맞는 별도 상징 오브젝트, 이전 장과 겹치지 않는 구성'
        used.add(spec.get('main_object','')[:35]); d=direction(spec); h,b=img_copy(c)
        rule=f"Render only this Korean headline text if text is needed: '{h}'. Do not render body copy. Do not render labels, UI field names, captions, watermark, random letters, or extra text. Use the body copy only as conceptual context for the visual composition." if ctx['include_image_copy'] else 'clean image only, no text, no captions, no typography, no letters, no watermark, no logo'
        dirs.append(d); prs.append(f'{base}. {d} Body context for composition only: {b}. {rule}')
    return dirs,prs

def finalize(ctx,title,msg,cards):
    cards=quality_guard(cards,ctx['analysis'],ctx['cta']); cards=[{**c,'headline':polish(c.get('headline',''),ctx['tone']),'body':polish(c.get('body',''),ctx['tone'])} for c in cards]
    dirs,prs=make_prompts(ctx,cards); slides=[comb(c) for c in cards]
    return {'title':polish(title,ctx['tone']),'target_customer':ctx['topic_type'],'core_problem':polish(ctx.get('problem') or msg,ctx['tone']),'main_message':polish(msg,ctx['tone']),'cta':ending(ctx['analysis'],ctx['cta']),'common_style':ctx['common_style'],'cards':cards,'slides':slides,'directions':dirs,'prompts':prs,'images':[f'장면 방향:\n{dirs[i]}\n\n이미지 생성 프롬프트:\n{prs[i]}' for i in range(6)],'brief_debug':ctx.get('brief_debug',{})}

def build_plan(ctx):
    brief=build_brief(ctx['analysis'],ctx['cta']); ctx['brief_debug']={'card_arc':brief.get('card_arc'),'mode':ctx['analysis'].get('event_type'),'profile':ctx['analysis'].get('profile',{})}
    return finalize(ctx,f"[{ctx['analysis'].get('event_type','context')}] {short(ctx['analysis'].get('topic','원본 주제'),44)}",ctx['analysis'].get('audience_problem',''),brief['cards'])

def auto_angle(v,a):
    if v and v!='__AUTO__' and v not in ['사건의 뒷면','문제폭로형','오해반박형','체크리스트형','전후비교형','바이럴 후킹형']: return v
    return {'market_or_company_shift':'가격보다 먼저 봐야 할 기대와 숫자의 간극','stakeholder_conflict':'요구와 책임이 충돌한 지점','howto_or_warning':'사람들이 놓치는 적용 조건'}.get(a.get('event_type'),'결론 뒤에 숨은 맥락')

def auto_prob(v,a): return v if v and v!='__AUTO__' and '카드뉴스' not in v else a.get('audience_problem','독자는 결과를 먼저 보지만, 그 결과를 만든 배경과 조건은 놓치기 쉽습니다')
def selector(label,opts,key,default=None,height=80):
    labs=list(opts.keys()); sel=st.selectbox(label,labs,index=labs.index(default) if default in labs else 0,key=f'{key}_select')
    return (st.text_area(f'{label} 직접 입력',height=height,key=f'{key}_custom'),sel) if sel=='직접 입력' else (opts[sel],sel)

def save_plan(ref,plan):
    c=db(); c.execute("""INSERT INTO cardnews_plans (reference_id,title,target_customer,core_problem,main_message,cta,slide_1,slide_2,slide_3,slide_4,slide_5,slide_6,image_1,image_2,image_3,image_4,image_5,image_6,status,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",(ref,plan['title'],plan['target_customer'],plan['core_problem'],plan['main_message'],plan['cta'],*plan['slides'],*plan['images'],'원본 주제',datetime.now().isoformat(timespec='seconds'))); c.commit(); c.close()

def set_state(plan,sig,force=False):
    if force or st.session_state.get('original_topic_signature')!=sig or 'original_topic_plan' not in st.session_state:
        st.session_state['original_topic_signature']=sig; st.session_state['original_topic_plan']=plan; st.session_state['original_topic_version']=st.session_state.get('original_topic_version',0)+1

def ensure_cards(plan):
    if plan.get('cards'): return plan['cards']
    out=[]
    for slide in plan.get('slides',['','','','','','']):
        parts=[p.strip() for p in clean(slide).split('\n\n')]; out.append(card('manual',parts[0] if parts else '','\n\n'.join(parts[1:]) if len(parts)>1 else '',{}))
    return out[:6]

def render_edit(plan,version):
    suf=f'v{version}'; st.markdown('### 공통 이미지 스타일'); common=st.text_area('공통 스타일',value=plan['common_style'],height=90,key=f'ot_common_{suf}')
    st.markdown('### 핵심 설계'); title=st.text_input('저장할 주제명',value=plan['title'],key=f'ot_title_{suf}'); prob=st.text_area('핵심 문제',value=plan['core_problem'],height=80,key=f'ot_problem_{suf}'); msg=st.text_area('메인 메시지',value=plan['main_message'],height=90,key=f'ot_message_{suf}'); cta=st.text_input('맥락형 엔딩/CTA',value=plan['cta'],key=f'ot_cta_{suf}')
    st.markdown('### 6장 카드뉴스 구성 직접 수정'); cards=ensure_cards(plan); edits=[]; dirs=[]; prs=[]
    for i in range(6):
        c=cards[i] if i<len(cards) else card('manual','','',{})
        with st.container(border=True):
            st.markdown(f'#### {i+1}장'); h=st.text_area('헤드카피',value=c.get('headline',''),height=80,key=f'ot_headline_{i}_{suf}'); b=st.text_area('바디카피',value=c.get('body',''),height=115,key=f'ot_body_{i}_{suf}'); d=st.text_area('장면 방향',value=plan['directions'][i],height=105,key=f'ot_direction_{i}_{suf}'); p=st.text_area('이미지 생성 프롬프트',value=plan['prompts'][i],height=150,key=f'ot_prompt_{i}_{suf}'); edits.append({**c,'headline':h,'body':b}); dirs.append(d); prs.append(p)
    slides=[comb(c) for c in edits]; e=dict(plan); e.update({'common_style':common,'title':title,'core_problem':prob,'main_message':msg,'cta':cta,'cards':edits,'slides':slides,'directions':dirs,'prompts':prs,'images':[f'장면 방향:\n{dirs[i]}\n\n이미지 생성 프롬프트:\n{prs[i]}' for i in range(6)]}); return e

def main():
    st.set_page_config(page_title='원본 주제 카드뉴스',page_icon='📰',layout='wide'); init_table(); st.title('📰 원본 주제 카드뉴스'); st.caption('방어형 분석 엔진: 주체 추출, 분기 판정, 문장 종결, 반복어 검수를 한 번에 처리합니다.')
    refs=load_refs()
    if refs.empty: st.warning('먼저 YouTube 영상 내용 분석에서 원본 해석 결과를 저장하세요.'); return
    opts={f"{gv(row,'source_table')} · {row['id']} · {gv(row,'main_topic_sentence') or gv(row,'original_topic') or gv(row,'title')}":row for _,row in refs.iterrows()}; row=opts[st.selectbox('원본 콘텐츠 선택',list(opts.keys()))]
    st.markdown('---'); st.markdown('### 콘텐츠 분석 조건'); c1,c2,c3=st.columns(3)
    with c1: topic_sel=st.selectbox('주제 유형',TOPIC_TYPES,index=0); goal=st.selectbox('콘텐츠 목적',GOALS,index=1)
    with c2: tmpl=st.selectbox('콘텐츠 구조',TMPL,index=0); platform=st.selectbox('플랫폼/사용처',PLAT,index=0)
    with c3: tone=st.selectbox('후킹 강도',TONE,index=2); depth=st.selectbox('분석 깊이',DEPTH,index=1)
    c4,c5=st.columns(2)
    with c4: target,_=selector('타깃 독자',TARGET,'ot_target','일반 시청자'); angle_v,_=selector('카드뉴스 핵심 각도',ANGLE,'ot_angle','자동 생성'); prob_v,_=selector('핵심 문제',PROB,'ot_problem_preset','자동 추출')
    with c5: emphasis=st.text_input('강조할 관점',placeholder='예: 가격 변화, 기대감, 실적, 자금 부담, 사업 진행 리스크'); avoid=st.text_input('제외할 관점',placeholder='예: 원문 밖 단정, 매수/매도 추천'); cta,_=selector('엔딩/CTA',CTA,'ot_cta_preset','자동 맥락형 엔딩')
    st.markdown('### 이미지 생성 조건'); i1,i2,i3=st.columns(3)
    with i1: img_ratio=st.selectbox('이미지 비율',RATIOS,index=0)
    with i2: img_style=st.selectbox('이미지 스타일',IMG_STYLES,index=0)
    with i3: include=st.checkbox('이미지 안에 헤드카피만 넣기',value=True); st.caption('바디카피와 라벨은 렌더링 대상에서 제외됩니다.')
    analysis=analyze(row,topic_sel,{'content_goal':goal,'platform_focus':platform,'analysis_depth':depth,'target_audience':target,'emphasis':emphasis,'avoid':avoid})
    if topic_sel=='직접 입력': analysis['topic_type']=st.text_input('주제 유형 직접 입력',value='사용자 정의')
    angle=auto_angle(angle_v,analysis); problem=auto_prob(prob_v,analysis); common=f'비율: {img_ratio} / 스타일: {img_style} / 사용처: {platform}.'+(' 이미지 안에는 짧은 헤드카피만 포함. 바디카피는 디자인 참고용.' if include else ' 텍스트 없는 클린 이미지. no text, no captions, no typography, no letters, no watermark, no logo.')
    with st.expander('원본 분석 결과 / 품질 진단',expanded=True):
        st.write(f"**감지된 주제 유형:** {analysis['topic_type']}"); st.write(f"**문맥 모드:** {analysis['event_type']}"); st.write(f"**원본 주제:** {analysis['topic']}"); st.write(f"**핵심 주장:** {analysis['primary_claim']}"); st.write(f"**독자 문제:** {analysis['audience_problem']}"); st.write(f"**갈등/긴장 구조:** {analysis['conflict']}"); st.markdown('##### signal_pack'); st.json(analysis.get('profile',{})); st.markdown('##### 사용 가능한 핵심 팩트'); [st.write(f'- {f}') for f in analysis.get('facts',[])[:12]]
    ctx={'analysis':analysis,'template':'문제 제기형' if tmpl=='자동 최적화' else tmpl,'tone':tone,'topic_type':analysis['topic_type'],'angle':angle,'problem':problem,'cta':cta,'common_style':common,'image_ratio':img_ratio,'image_style':img_style,'include_image_copy':include}
    plan=build_plan(ctx); sig='|'.join([str(int(row['id'])),gv(row,'source_table'),analysis['topic'],analysis['event_type'],ctx['template'],tone,img_ratio,img_style,str(include),angle,problem,cta,emphasis,avoid,json.dumps(analysis.get('profile',{}),ensure_ascii=False)]); set_state(plan,sig)
    rcol,icol=st.columns([1,3])
    with rcol:
        if st.button('현재 선택값으로 초안 다시 생성'): set_state(plan,sig,force=True); st.rerun()
    with icol: st.info('주체 추출/시장형 분기/문장 종결/반복어 검수를 방어형으로 처리합니다. 결과가 이상하면 위 signal_pack의 subject와 mode부터 확인하세요.')
    st.markdown('---'); edited=render_edit(st.session_state.get('original_topic_plan',plan),st.session_state.get('original_topic_version',0))
    with st.expander('CardBrief 디버그'): st.json(edited.get('brief_debug',{}))
    if st.button('이 설계안 저장',type='primary'): save_plan(int(row['id']),edited); st.success('원본 주제 카드뉴스 설계안을 저장했습니다.')
    st.markdown('---'); st.markdown('### 최근 저장된 카드뉴스'); plans=load_plans(); st.info('아직 저장된 카드뉴스가 없습니다.') if plans.empty else st.dataframe(plans,use_container_width=True,hide_index=True)
if __name__=='__main__': main()
