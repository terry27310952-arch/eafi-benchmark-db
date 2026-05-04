# EAFi Benchmark DB

EAFi 콘텐츠 리서치용 로컬 MVP입니다.

벤치마크 채널을 등록하고, 참고 콘텐츠를 저장한 뒤, 점수 기준으로 카드뉴스 후보를 추출하고, 카드뉴스 설계안, 이미지 프롬프트, 플랫폼별 콘텐츠까지 이어서 만드는 Streamlit 웹앱입니다.

## 현재 제작 흐름

```txt
벤치마크 채널 등록
↓
참고 콘텐츠 등록
↓
점수화
↓
카드뉴스 후보 추출
↓
카드뉴스 설계안 생성
↓
이미지 프롬프트 생성
↓
플랫폼별 콘텐츠 변환
```

## 빠른 실행

Python 3.10 이상 권장입니다.

### Windows

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

또는 아래 파일을 더블클릭합니다.

```txt
run_local.bat
```

### macOS / Linux

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

또는 아래 명령을 실행합니다.

```bash
chmod +x run_local.sh
./run_local.sh
```

## 실행 전 점검

```bash
python scripts/health_check.py
```

정상이라면 Python 버전, 필수 패키지, 주요 파일, SQLite 연결 상태를 확인해줍니다.

## 데모 데이터 넣기

처음 화면이 비어 있으면 아래 명령으로 예시 데이터를 넣을 수 있습니다.

```bash
python scripts/seed_demo_data.py
```

그 다음 다시 실행합니다.

```bash
streamlit run app.py
```

## 주요 기능

### 1. 메인 앱 `app.py`

- 벤치마크 채널 등록
- 참고 콘텐츠 등록
- 후킹 포인트, 전개 구조, 이미지 참고, EAFi 적용 아이디어 기록
- 리드 가능성, 이미지화 가능성, 후킹 강도, SEO 확장성, 전환 자연도 점수화
- 총점 20점 이상 카드뉴스 후보 자동 분류
- CSV 내보내기

### 2. 카드뉴스 설계안 생성

```txt
pages/1_카드뉴스_설계안_생성.py
```

참고 콘텐츠 후보를 6장 카드뉴스 원본 구조로 변환합니다.

- 핵심 주제
- 타깃 고객
- 핵심 문제
- 메인 메시지
- CTA
- 1장~6장 카피
- 1장~6장 이미지 방향

### 3. 이미지 프롬프트 생성

```txt
pages/2_이미지_프롬프트_생성.py
```

저장된 카드뉴스 설계안을 기반으로 장별 이미지 생성 프롬프트를 만듭니다.

- 스타일 프리셋
- 화면 비율
- 영문 프롬프트
- 네거티브 프롬프트
- CSV 내보내기

### 4. 플랫폼별 콘텐츠 변환

```txt
pages/3_플랫폼별_콘텐츠_변환.py
```

카드뉴스 설계안을 플랫폼별 콘텐츠로 변환합니다.

- Instagram Carousel
- Instagram Reels
- YouTube Shorts
- Naver Blog
- Threads
- TikTok

## 데이터 저장 방식

로컬 실행 시 아래 파일이 자동 생성됩니다.

```txt
eafi_benchmark.db
```

이 파일은 로컬 SQLite DB입니다. `.gitignore`에 포함되어 GitHub에는 올라가지 않습니다.

CSV 내보내기를 하면 아래 폴더가 자동 생성됩니다.

```txt
exports/
```

## 자주 막히는 부분

### `streamlit` 명령어를 찾을 수 없다고 나올 때

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

### 한글 파일명이 있는 페이지가 안 보일 때

Streamlit을 재시작하세요.

```bash
Ctrl + C
streamlit run app.py
```

### DB가 꼬인 것 같을 때

로컬 테스트 단계에서는 아래 파일을 삭제하고 다시 실행하면 새 DB가 생성됩니다.

```txt
eafi_benchmark.db
```

주의: 삭제하면 입력한 데이터도 사라집니다.

## 다음 개발 후보

- YouTube Data API 연동
- Naver Search API 연동
- Google Sheets 연동
- 카드뉴스 설계안 편집 기능
- 이미지 프롬프트 편집/상태 관리
- Streamlit Cloud 배포
