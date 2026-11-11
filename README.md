# TransM (AI 자동 자막 생성 & 문맥 교정 스튜디오)

TransM은 사용자가 업로드한 동영상(또는 로컬 디스크 미디어 폴더)에서 오디오를 분리하고, `faster-whisper`로 1차 음성 인식(STT)을 수행한 뒤, 로컬 AI 모델(Ollama `qwen2.5` 등)을 통해 문맥 교정 및 한국어 번역을 거쳐 최종 고품질 `.srt` 자막을 생성해 주는 올인원(All-in-One) 풀스택 웹 스튜디오입니다.

---

## ⚡ [비개발자 필독] 1초 초간편 자동 설치 및 실행 가이드

개발이나 코딩을 전혀 몰라도 상관없습니다! **`start.bat` 파일을 더블클릭**하면 모든 준비가 자동으로 진행됩니다.

```
📁 transM/
 └── 📄 start.bat  <--- 이 파일을 마우스로 '더블클릭' 하세요!
```

### 최초 실행 시 진행 흐름 (대화형 마법사 자동 안내)

1. **파이썬 가상환경 및 라이브러리 자동 구축**:
   - 실행에 필요한 가상환경(`backend/venv`)과 라이브러리를 컴퓨터가 스스로 설치합니다.
2. **하드웨어 자동 감지 & 사양별 원클릭 프리셋 선택 (`setup_wizard.py`)**:
   - 마법사가 실행되면 사용자의 **CPU, RAM 용량, NVIDIA GPU(VRAM) 유무를 자동으로 감지**하여 가장 적합한 사양 프리셋 번호를 추천합니다.
   - **원하는 사양 번호(또는 Enter를 눌러 추천 번호)만 선택하면 끝!**
     - **`[1] 🚀 권장 고사양 프리셋 (★ 현재 개발 PC 기준 최적 스펙)`**:
       - 권장: RTX 4070 Ti 이상(12GB VRAM), 32GB RAM
       - STT: `large-v3-turbo` (CUDA float16 초고속 가속)
       - LLM: `qwen2.5:14b` (한/영/중/일 구어체 번역 및 맞춤법 최고 품질)
       - DB: 파일 DB (SQLite - 설치 불필요)
     - **`[2] ⚖️ 표준 / 밸런스 프리셋`**:
       - 권장: RTX 3060 / 4060 등 6~8GB VRAM, 16GB RAM
       - STT: `large-v3-turbo` (CUDA float16)
       - LLM: `qwen2.5:7b` (빠른 처리 속도와 준수한 품질)
       - DB: 파일 DB (SQLite - 설치 불필요)
     - **`[3] 🍃 저사양 / 노트북 프리셋 (저사양 맞춤 선택지)`**:
       - 권장: 내장 그래픽, 4GB 이하 GPU, 8GB RAM, 일반 사무용 노트북
       - STT: `small` (CPU 또는 저사양 GPU int8 경량 모드)
       - LLM: `qwen2.5:3b` (초경량 고효율 로컬 AI 모델)
       - DB: 파일 DB (SQLite - 설치 불필요)
     - **`[4] ⚙️ 고급 사용자 맞춤 설정 (Custom)`**:
       - 외부 RDB(PostgreSQL) 연동 또는 개별 모델을 직접 지정하고 싶을 때 선택.
3. **선택한 AI 모델 자동 다운로드 및 설치**:
   - 선택한 프리셋의 LLM 모델(`qwen2.5:14b`, `qwen2.5:7b`, 또는 `qwen2.5:3b`)을 Ollama를 통해 실시간 진행률을 표시하며 즉시 다운로드합니다.
4. **웹 스튜디오 자동 실행**:
   - 설정이 완료되면 웹 브라우저(`http://localhost:8000` 또는 `http://localhost:5173`)가 자동으로 열립니다!
   - 브라우저 화면에서 동영상을 끌어다 놓기만 하면 즉시 자막이 생성됩니다.

> 💡 **설정을 다시 바꾸고 싶을 때는?**  
> 터미널이나 명령 프롬프트(CMD)에서 `python setup_wizard.py`를 실행하시면 언제든지 다시 설정할 수 있습니다.

---

## 💻 시스템 요구 사양 (System Requirements)

TransM은 로컬 AI 모델(Whisper 음성인식 및 Ollama LLM)을 사용자 PC에서 직접 구동하므로, 하드웨어 사양에 맞춰 최적의 모델을 선택하여 구동할 수 있습니다.

| 구분 | 권장 사양 (★ 현재 개발 PC 기준 최적 스펙) | 최소 사양 (저사양 PC / 노트북) |
| :--- | :--- | :--- |
| **운영체제 (OS)** | **Microsoft Windows 11 64-bit** (또는 Linux Ubuntu 22.04+) | Windows 10 64-bit / Linux / macOS |
| **CPU** | **AMD Ryzen 7 7800X3D** (8코어 16스레드) / Intel Core i7 13세대 이상 | 4코어 8스레드 이상 (Intel Core i5 8세대 / AMD Ryzen 5 2600 이상) |
| **RAM (메모리)** | **32 GB** 이상 | **8 GB** 이상 (16 GB 권장) |
| **GPU (그래픽카드)** | **NVIDIA GeForce RTX 4070 Ti (12GB VRAM)** 이상 | NVIDIA GTX 1660 / RTX 3050 (4~6GB VRAM) 또는 **내장 그래픽(CPU 연산)** |
| **권장 AI 조합** | • **STT**: `whisper large-v3-turbo` (CUDA `float16`)<br>• **LLM**: `qwen2.5:14b` (최고 품질 한/영/중/일 구어체 번역 및 맞춤법 교정) | • **STT**: `whisper small` 또는 `medium` (CPU/GPU `int8`)<br>• **LLM**: `qwen2.5:3b` (초경량) 또는 `qwen2.5:7b` |
| **저장공간** | NVMe SSD 여유 공간 **50 GB** 이상 (고속 미디어 입출력 및 AI 모델 캐시) | 여유 공간 **15 GB** 이상 (일반 SSD 권장) |

> 📌 **PC 사양별 최적 AI 모델 선택 팁**:
> * **현재 PC (RTX 4070 Ti 12GB + 32GB RAM)**:
>   - **`qwen2.5:14b`** + **`large-v3-turbo`** 조합을 사용하면 자막 번역 및 교정 퀄리티가 방송용 수준으로 극대화되며, GPU VRAM 12GB 내에서 100% 실시간 하드웨어 가속됩니다.
> * **보급형 외장 그래픽 (RTX 3060 / 4060 등 6~8GB VRAM + 16GB RAM)**:
>   - **`qwen2.5:7b`** + **`large-v3-turbo`** 조합을 추천합니다. 매우 빠른 처리 속도와 자연스러운 구어체 번역을 제공합니다.
> * **노트북 및 내장 그래픽 PC (GPU 없음 / 4GB 이하 VRAM + 8GB RAM)**:
>   - **`qwen2.5:3b`** + **`whisper small / base`** 모델을 선택하면 CPU만으로도 가볍고 원활하게 자막을 제작할 수 있습니다.

---

## 🛠 아키텍처 및 기술 스택

* **Backend**:
  * **Framework**: Python 3.10+, FastAPI, Uvicorn
  * **오디오 추출**: `moviepy` (FFmpeg 자동 폴백 지원, 인코딩 에러 방어)
  * **음성 인식 (STT)**: `faster-whisper` (NVIDIA CUDA GPU 가속 / RTX 최적화, CPU 폴백 지원)
  * **자막 문맥 교정 & 번역 (LLM)**: `ollama` Python SDK (선택 모델: `qwen2.5:14b` / `qwen2.5:7b` / `gemma4:12b` 등)
  * **데이터베이스**: **듀얼 DB 완벽 지원**
    * **SQLite**: 파일 기반 로컬 DB (설치 불필요, WAL 동시성 모드, 기본값)
    * **PostgreSQL**: 대규모 동시성 RDB (자동 데이터베이스 생성 지원)
  * **SRT 파일 생성 & 플레이어 호환성**: `pysrt`, 타임스탬프 갭(50ms)/중첩 100% 자동 보정, UTF-8 BOM 인코딩 (시리즈온, 팟플레이어 완벽 호환)
* **Frontend**:
  * **Framework**: React 18, Vite (단일 포트 8000 서빙 & 5173 개발 서버 모두 지원)
  * **UI/스타일**: Tailwind CSS, Lucide-react (모던 다크 테마)
  * **비디오 플레이어**: `react-player` (타임스탬프 클릭 싱크 연동 프리뷰)
  * **상태 관리 & 폴링**: `@tanstack/react-query`
  * **파일 다운로드**: `file-saver` (단일 SRT 및 일괄 ZIP 압축 다운로드)

---

## 🌟 주요 기능 명세

1. **동영상 작업 대기열 (Studio Queue)**
   - 대용량 동영상 일괄 업로드 및 순차적 자동 백그라운드 파이프라인 가동.
   - **폴더 하위 무제한 재귀 검색**: 로컬 디스크 탐색기를 통해 하위 폴더 내의 모든 영상 파일을 한 번에 최대 5,000건까지 큐에 일괄 등록.
   - **오류 발생 시 자동 넘김 및 오류 복사**: 특정 영상 처리 실패 시 멈추지 않고 다음 대기 영상으로 자동 전환되며, 상세 오류를 클릭 한 번으로 복사 가능.
   - **완료 항목 자동 보관함 이동**: 자막 생성이 완료된 항목은 대기열에서 자동으로 정리되어 [작업 완료 보관함]으로 이동.

2. **작업 완료 보관함 (Completed Archive)**
   - 완료 자막 영구 보관 (SQLite / PostgreSQL).
   - **100건 단위 페이징**: 대용량 작업(수백~수천 건)도 페이지당 100건씩 쾌적하게 조회 및 관리.
   - **일괄 다운로드**: 신규 미다운로드 자막만 선별하여 ZIP 다운로드 또는 전체 자막 일괄 압축 다운로드 지원.
   - **인라인 자막 편집기**: 영상 프리뷰와 자막 타임라인이 연동되어 실시간 수정 및 저장 가능.

3. **SRT 자막 번역기 (Subtitle Translator)**
   - 기존 완료된 자막 또는 신규 `.srt` 파일을 업로드하여 다국어(한국어, 영어, 일본어, 중국어 등)로 자동 번역.
   - 언어 자동 감지 및 로컬 LLM을 통한 자연스러운 대화체 의역.

4. **관리자 시스템 설정 (Admin Engine Settings)**
   - 화면에서 로컬 LLM 모델 및 Whisper 모델, 배치 크기 실시간 변경 및 즉시 적용.
   - 미설치된 Ollama 모델 원클릭 다운로드 기능 탑재.
   - 현재 구동 중인 DB 엔진(SQLite vs PostgreSQL) 상태 실시간 모니터링.

---

## 📁 디렉터리 구조

```text
transM/
├── setup_wizard.py           # 대화형 간편 설치 & 환경설정 마법사
├── start.bat                 # 비개발자 원클릭 전체 실행 런처
├── stop.bat                  # 서비스 일괄 종료 스크립트
├── start_background.vbs      # 백그라운드 무창 실행 스크립트
├── .env.example              # 환경 변수 설정 템플릿
├── .gitignore                # 보안 및 런타임 파일 git 제외
├── prompt.md                 # 프로젝트 전체 구현 상세 및 시스템 설계 명세
├── README.md                 # 프로젝트 안내 및 설치/실행 가이드
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
│   │   │   └── srt_generator.py      # SRT 생성, 50ms 갭 최적화, UTF-8-SIG 인코딩
│   │   ├── config.py         # 환경 변수 로드 및 런타임 설정 (SQLite/Postgres 지원)
│   │   ├── database.py       # SQLite / PostgreSQL 듀얼 DB 추상화 엔진
│   │   ├── models.py         # Pydantic 데이터 모델
│   │   └── main.py           # FastAPI 앱 초기화 및 SPA 통합 정적 서빙
│   ├── data/                 # 런타임 데이터 (SQLite transm.db, 업로드/처리 결과물)
│   ├── requirements.txt      # 백엔드 Python 패키지 의존성
│   └── run.py                # 백엔드 Uvicorn 구동 스크립트
└── frontend/
    ├── src/
    │   ├── api/              # API 통신 클라이언트
    │   ├── components/       # UI 컴포넌트 (Queue, Archive, Editor, Admin 등)
    │   └── App.jsx           # 메인 레이아웃 및 탭 네비게이션
    ├── dist/                 # Vite 사전 빌드된 프론트엔드 (백엔드 포트 8000 단독 구동 가능)
    ├── package.json
    └── vite.config.js        # Vite 개발 서버 설정
```

---

## 💻 개발자용 수동 설정 및 구동 가이드

### 1. 가상환경 및 의존성 설치
```bash
cd backend
python -m venv venv
# Windows:
venv\Scripts\activate
# Linux/macOS:
source venv/bin/activate

pip install -r requirements.txt
```

### 2. 환경 변수 설정
```bash
# 마법사를 통해 생성하거나 .env.example 복사
python setup_wizard.py
# 또는 수동 설정:
cp .env.example .env
```

### 3. 서버 구동
* **백엔드 (API & 웹 통합)**:
  ```bash
  cd backend
  python run.py
  ```
  - 브라우저 접속: `http://localhost:8000` (Swagger API 문서: `http://localhost:8000/docs`)
* **프론트엔드 개발 서버 (Vite HMR)**:
  ```bash
  cd frontend
  npm install
  npm run dev
  ```
  - 브라우저 접속: `http://localhost:5173`
