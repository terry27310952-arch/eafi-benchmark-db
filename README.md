# EAFi Benchmark DB

EAFi 콘텐츠 리서치용 MVP입니다.

벤치마크 채널을 등록하고, 참고 콘텐츠를 저장한 뒤, 점수 기준으로 카드뉴스 후보를 추출하는 Streamlit 웹앱입니다.

## 실행

```bash
pip install -r requirements.txt
streamlit run app.py
```

## 기능

- 벤치마크 채널 등록
- 참고 콘텐츠 등록
- 후킹 포인트, 전개 구조, 이미지 참고, EAFi 적용 아이디어 기록
- 리드 가능성, 이미지화 가능성, 후킹 강도, SEO 확장성, 전환 자연도 점수화
- 총점 20점 이상 카드뉴스 후보 자동 분류
- CSV 내보내기

## 다음 개발

- YouTube Data API 연동
- Naver Search API 연동
- 카드뉴스 6장 구조 자동 생성
- 이미지 프롬프트 자동 생성
