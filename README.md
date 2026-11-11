# TransM (AI 자동 자막 생성 & 문맥 교정 스튜디오)

TransM은 사용자가 업로드한 동영상(또는 로컬 디스크 미디어 폴더)에서 오디오를 추출하고, `faster-whisper`로 1차 타임스탬프 자막을 생성한 뒤, 로컬 Ollama 모델(`qwen2.5:14b` 등)을 통해 문맥 교정 및 한국어 번역을 거쳐 최종 고품질 `.srt` 자막을 생성해 주는 풀스택 웹 애플리케이션입니다.

---

## 🛠 아키텍처 및 기술 스택

* **Backend**:
  * **Framework**: Python 3.10+, FastAPI, Uvicorn
  * **오디오 추출**: `moviepy` (FFmpeg 서브프로세스 자동 폴백)
  * **음성 인식 (STT)**: `faster-whisper` (NVIDIA CUDA GPU 가속 / RTX 4070 Ti 최적화, CPU 폴백 지원)
  * **자막 문맥 교정 & 번역 (LLM)**: `ollama` Python SDK (로컬 Ollama 연동, 모델: `qwen2.5:14b` / `gemma4:12b` 등)
  * **데이터베이스**: PostgreSQL (작업 상태, 세그먼트 체크포인트, 완료 자막 보관소 영구 저장)
  * **SRT 파일 생성 & 최적화**: `pysrt`, 타임스탬프 갭/중첩 자동 보정
  * **환경설정 관리**: `python-dotenv` 기반 환경 변수 분리 (`.env`)
* **Frontend**:
  * **Framework**: React 18, Vite
  * **UI/스타일**: Tailwind CSS, Lucide-react
  * **비디오 플레이어**: `react-player` (타임스탬프 클릭 연동 프리뷰)
  * **상태 관리 & 폴링**: `@tanstack/react-query`
  * **파일 다운로드**: `file-saver` (단일 SRT 및 다중 ZIP 일괄 다운로드)
  * **HTTP 클라이언트**: `axios` (대용량 업로드 프로그레스 바 연동)

---

## 🌟 주요 기능

1. **동영상 작업 대기열 (Studio Queue)**
   - 대용량 동영상 일괄 업로드 및 순차적 자동 백그라운드 파이프라인 가동.
   - **폴더 하위 무제한 재귀 검색**: 파일 시스템 접근 API 및 로컬 디스크 탐색기를 통해 하위 폴더 내의 모든 영상 파일을 한 번에 최대 5,000건까지 큐에 일괄 등록.
   - **오류 발생 시 자동 넘김 및 오류 복사**: 특정 영상 처리 실패 시 멈추지 않고 다음 대기 영상으로 자동 전환되며, 상세 오류를 클릭 한 번으로 복사 가능.
   - **완료 항목 자동 보관함 이동**: 자막 생성이 완료된 항목은 대기열에서 자동으로 정리되어 [작업 완료 보관함]으로 이동.

2. **작업 완료 보관함 (Completed Archive)**
   - PostgreSQL 기반 완료 자막 영구 보관.
   - **100건 단위 페이징**: 대용량 작업(수백~수천 건)도 페이지당 100건씩 쾌적하게 조회 및 관리.
   - **일괄 다운로드**: 신규 미다운로드 자막만 선별하여 ZIP 다운로드 또는 전체 자막 일괄 압축 다운로드 지원.
   - **인라인 자막 편집기**: 영상 프리뷰와 자막 타임라인이 연동되어 실시간 수정 및 저장 가능.

3. **SRT 자막 번역기 (Subtitle Translator)**
   - 기존 완료된 자막 또는 신규 `.srt` 파일을 업로드하여 다국어(한국어, 영어, 일본어, 중국어 등)로 자동 번역.
   - 언어 자동 감지 및 로컬 LLM을 통한 자연스러운 대화체 의역.

4. **관리자 시스템 설정 (Admin Engine Settings)**
   - Ollama LLM 모델(`qwen2.5:14b`, `qwen2.5:7b`, `gemma4:12b` 등) 및 Whisper 모델(`large-v3-turbo`, `large-v3` 등)을 화면에서 선택 및 즉시 적용.
   - 새 모델 적용 시 기존 완료된 자막을 일괄 재추출 큐로 등록하는 기능 제공.

---

## 📁 디렉터리 구조

```text
transM/
├── .env.example              # 환경 변수 설정 템플릿 (비식별화된 샘플)
├── .gitignore                # 환경 변수(.env) 및 런타임 데이터 git 제외
├── prompt.md                 # 프로젝트 전체 구현 상세 및 시스템 설계 명세
├── README.md                 # 프로젝트 안내 및 설치/실행 가이드
├── start.bat                 # 백엔드 & 프론트엔드 동시 실행 런처
├── stop.bat                  # 서비스 일괄 종료 스크립트
├── start_background.vbs      # 백그라운드 백그라운드 실행 스크립트
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   └── routes.py     # REST API 엔드포인트
│   │   ├── services/
│   │   │   ├── audio_extractor.py     # 오디오 분리 및 추출 (16kHz mono WAV)
│   │   │   ├── whisper_stt.py        # faster-whisper 음성인식
│   │   │   ├── llm_refiner.py        # LLM 구어체 문맥 교정 및 전각 기호 필터링
│   │   │   ├── subtitle_translator.py# 자막 다국어 번역 서비스
│   │   │   ├── language_detector.py  # 자막 언어 자동 감지
│   │   │   └── srt_generator.py      # SRT 생성 및 타임스탬프 최적화
│   │   ├── config.py         # 환경 변수 로드 및 런타임 설정
│   │   ├── database.py       # PostgreSQL 연동 및 체크포인트 영구 저장
│   │   ├── models.py         # Pydantic 데이터 모델
│   │   └── main.py           # FastAPI 앱 초기화 및 생명주기 관리
│   ├── data/                 # 런타임 데이터 (업로드/처리 결과물)
│   ├── requirements.txt      # 백엔드 Python 패키지 의존성
│   └── run.py                # 백엔드 Uvicorn 구동 스크립트
└── frontend/
    ├── src/
    │   ├── api/              # API 통신 클라이언트
    │   ├── components/       # UI 컴포넌트 (Uploader, Queue, Editor, Banner 등)
    │   ├── hooks/            # Studio 및 Translator 큐 상태 관리 훅
    │   └── App.jsx           # 메인 레이아웃 및 탭 네비게이션
    ├── package.json
    └── vite.config.js        # Vite 개발 서버 및 백엔드 프록시 설정
```

---

## 🚀 설치 및 환경 설정 가이드

### 1. 환경 변수 파일(`.env`) 생성
프로젝트 루트 디렉토리의 `.env.example` 파일을 복사하여 `.env` 파일을 생성하고 접속 정보를 설정합니다.

```bash
cp .env.example .env
```

`.env` 설정 항목 예시:
```env
# 서버 설정
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# PostgreSQL 데이터베이스 설정
POSTGRES_HOST=your-db-host
POSTGRES_PORT=5432
POSTGRES_DB=your_database_name
POSTGRES_USER=your_db_user
POSTGRES_PASSWORD=your_db_password

# Ollama LLM 서비스 설정
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:14b
LLM_BATCH_SIZE=10

# Whisper STT 설정
WHISPER_MODEL_SIZE=large-v3-turbo
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16

# 로컬 미디어 탐색 폴더 (쉼표 구분)
MEDIA_SCAN_DIRS=D:\Media,D:\Videos
```

---

### 2. 백엔드 (Backend) 설정 및 실행

```bash
cd backend

# 1) 가상환경 생성 및 활성화
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

# 2) 필수 패키지 설치
pip install -r requirements.txt

# 3) 백엔드 서버 구동
python run.py
```
* API 문서(Swagger UI): `http://localhost:8000/docs`
* 상태 확인: `http://localhost:8000/healthz`

---

### 3. 프론트엔드 (Frontend) 설정 및 실행

새 터미널 창을 엽니다.

```bash
cd frontend

# 1) npm 패키지 설치
npm install

# 2) 프론트엔드 개발 서버 실행
npm run dev
```
* 웹 브라우저에서 `http://localhost:5173` 접속.

---

### 4. 원클릭 실행 (Windows)
* 루트 디렉토리의 `start.bat`을 실행하면 백엔드와 프론트엔드가 각각 별도의 콘솔 창에서 동시에 시작되며 브라우저가 자동 실행됩니다.
* 백그라운드 무창 실행을 원할 경우 `start_background.vbs`를 실행할 수 있습니다.
* 서비스 종료는 `stop.bat`을 실행합니다.
