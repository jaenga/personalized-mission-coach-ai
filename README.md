# AI 생활습관 코치 MVP

React + FastAPI + Ollama 기반 어린이 생활습관 코치 프로토타입.

## 폴더 구조

```
capstone26/
├── backend/
│   ├── main.py           # FastAPI 라우터
│   ├── database.py       # SQLite CRUD
│   ├── ollama_client.py  # Ollama API 호출
│   ├── prompts.py        # ← 프롬프트 실험 파일
│   ├── .env              # 환경변수 (모델명, URL)
│   └── requirements.txt
└── frontend/
    ├── src/
    │   ├── App.jsx
    │   ├── api.js
    │   └── components/
    │       ├── MissionCard.jsx
    │       ├── FeedbackForm.jsx
    │       ├── CoachResponse.jsx
    │       └── HistoryList.jsx
    ├── index.html
    ├── package.json
    └── vite.config.js
```

## 실행 방법

### 1. Ollama 준비

```bash
# Ollama 설치 후 모델 다운로드
ollama pull gemma3:4b       # 기본 모델 (약 3.3GB)
# 또는
ollama pull llama3.2:3b
ollama pull qwen2.5:3b
```

### 2. 백엔드 실행

```bash
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn main:app --reload
# → http://localhost:8000
```

### 3. 프론트엔드 실행

```bash
cd frontend
npm install
npm run dev
# → http://localhost:5173
```

## 환경변수 (`backend/.env`)

| 변수              | 기본값                   | 설명            |
|------------------|--------------------------|----------------|
| OLLAMA_BASE_URL  | http://localhost:11434   | Ollama 주소     |
| OLLAMA_MODEL     | gemma3:4b                | 사용할 모델명    |

## API 엔드포인트

| Method | Path       | 설명          |
|--------|-----------|---------------|
| GET    | /mission  | 오늘의 미션    |
| POST   | /feedback | 결과 제출 → AI 응답 |
| GET    | /logs     | 기록 조회      |

### POST /feedback 요청 예시

```json
{
  "mission": "물 8잔 마시기",
  "result": "failure",
  "reason": "친구들이랑 놀다가 까먹었어요"
}
```

## 프롬프트 실험 방법

`backend/prompts.py`만 수정하면 됩니다:

```python
# 시스템 프롬프트 변경
SYSTEM_PROMPT = "..."

# 유저 프롬프트 구성 변경
def build_user_prompt(mission, result, reason): ...
```

모델 비교는 `.env`의 `OLLAMA_MODEL` 값만 바꾸면 됩니다:

```
OLLAMA_MODEL=llama3.2:3b
OLLAMA_MODEL=qwen2.5:3b
OLLAMA_MODEL=gemma3:4b
```

## 데이터 저장

`backend/coach.db` (SQLite) — 서버 최초 실행 시 자동 생성.

```sql
logs (id, mission, result, reason, ai_response, created_at)
```
