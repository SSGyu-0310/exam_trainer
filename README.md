# 맞춤형 모의고사 웹 애플리케이션 (MVP 스타터)

이 저장소는 **Flask + SQLite** 기반의 최소 기능(MVP) 구현 예제입니다.  
초보자도 그대로 실행해서 동작을 확인하고, 점진적으로 확장할 수 있도록 구성했습니다.

## 빠른 실행 방법

1) (선택) 가상환경 생성
```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate
```

2) 필요한 패키지 설치
```bash
pip install -r requirements.txt
```

3) 데이터베이스 초기화 (샘플 데이터 포함)
```bash
python scripts/init_db.py
```

4) 서버 실행
```bash
python app.py
```
브라우저에서 http://127.0.0.1:5000 접속

## 폴더 구조

```
mock-exam-starter/
├─ app.py                  # Flask 서버 (라우팅/로직)
├─ data/
│  └─ questions.db         # SQLite DB (init_db.py 실행 시 생성)
├─ scripts/
│  ├─ init_db.py           # DB 생성/시드 스크립트
│  └─ schema.sql           # DB 스키마
├─ static/
│  ├─ main.css             # 기본 스타일
│  ├─ main.js              # 간단한 프론트 스크립트
│  └─ pdfs/                # 원본 문제 PDF를 둘 위치
├─ templates/
│  ├─ base.html
│  ├─ index.html           # 필터/시험지 생성
│  ├─ exam.html            # 문제 풀이 화면
│  └─ results.html         # 채점 결과
└─ requirements.txt
```

## 확장 아이디어
- 오답노트(틀린 문제 북마크, 재시험)
- 학습 통계(과목/주제별 정확도, 소요시간)
- 사용자 계정/세션(진행중 시험 저장, 시도 이력)
- PDF 페이지 뷰어/하이라이트(원본 확인 UX)
- 문제 난이도/출처/연도 태깅 및 필터
