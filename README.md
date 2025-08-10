## 작업 환경 준비

- python 가상환경 venv 만들고 활성화

```scss
python -m venv .venv
.\.venv\Scripts\activate
```

- 크롤링 관련 라이브러리 설치

```scss
pip install requests beautifulsoup4 playwright
playwright install
```

- 시간대 처리를 위한 라이브러리

```scss
pip install tzdata
```

## 사용 방법

- velog 크롤링

```scss
python crawl_velog.py --handle 벨로그아이디
```

실행 하면 out.json 파일 생성

out.json 파일에는 크롤링 결과가 기록됩니다

- 데이터 분석

```scss
python analyze.py
```

out.json 파일을 읽어서 분석 결과 출력

summary.json에 기록됩니다

## 수집한 데이터

- **`author.handle`**
    
    분석 대상의 Velog 닉네임
    
- **`active_start` / `active_end`**
    
    분석된 글 중에서 가장 오래된 글의 작성일과 가장 최근 글의 작성일
    
- **`active_days`**
    
    글을 실제로 작성한 날짜의 개수
    
- **`total_posts`**
    
    전체 작성 글 개수
    
- **`total_study_posts`**
    
    전체 글 중 학습/기술 관련 글의 개수
    
    현재는 모든 글을 학습 관련으로 분류 → 개선 필요
    
- **`posts_per_month`**
    
    월별 작성 글 수
    
- **`longest_streak_days`**
    
    연속해서 글을 작성한 최대 일수
    
- **`max_gap_days`**
    
    글 작성 사이에 가장 길게 비어있었던 기간
    
- **`interval_cv`**
    
    글 작성 간격의 변동성
    
    값이 0에 가까우면 일정하게 작성했다는 뜻
    
- **`last_90d_posts`**
    
    최근 90일 동안 작성한 글의 개수
    
- **`last_90d_weeks_active`**
    
    최근 90일 동안 글을 작성한 주(week)의 개수입니다.
    
    예를 들어 12주 중 5주에서 글을 작성했다면 5가 됨
    
- **`cadence_score`**
    
    글 작성 빈도와 규칙성을 종합적으로 평가한 점수
    
    값이 높을수록 자주, 규칙적으로 글을 작성했다는 뜻
    
- **`top_topics`**
    
    글 내용을 분석해 주제별로 분류한 결과
