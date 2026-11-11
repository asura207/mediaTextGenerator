# TransM 프로젝트 통합 명세 및 구현 가이드 (prompt.md)

본 문서는 **TransM (AI 자동 자막 생성 & 문맥 교정 스튜디오)** 프로젝트의 전체 요구사항, 시스템 아키텍처, 구현된 모든 기능, API 명세, 데이터베이스 스키마, 환경 설정 및 보안 가이드를 총망라한 마스터 명세서입니다.

---

## 1. 프로젝트 개요

* **프로젝트명**: TransM (Transcription & Translation Studio)
* **목적**: 동영상 파일(또는 로컬 디스크 미디어 폴더)로부터 음성을 고품질로 인식하여 타임스탬프 자막을 자동 생성하고, 최신 로컬 LLM을 결합하여 방송/영화/유튜브 수준의 자연스러운 일상 구어체 한국어 자막(`.srt`)으로 문맥 교정 및 번역을 제공하는 원스톱 스튜디오 플랫폼.
* **주요 특징**:
  * 완전 로컬/프라이빗 구동 지원 (NVIDIA CUDA GPU 가속 faster-whisper + 로컬 Ollama LLM).
  * 대용량 다중 영상 순차 파이프라인 처리 (대기열 시스템).
  * 하위 폴더 깊이 무제한 자동 재귀 검색 및 대형 시즌 영상 일괄 큐잉 (최대 5,000건).
  * 대용량 완료 보관함 100건 단위 페이징 및 신규 미다운로드 자막 일괄 압축 다운로드.
  * 오류 발생 시 자동 건너뛰기 및 상세 오류 원클릭 복사.
  * 실시간 브라우저 웹 푸시 알림 및 인터랙티브 자막 편집기.
  * 민감 접속 정보의 프로퍼티(`.env`) 완전 분리 및 git commit 예외 처리 (`.env.example` 제공).

---

## 2. 시스템 아키텍처 및 기술 스택

### 2.1 Backend 기술 스택
* **언어 및 런타임**: Python 3.10+
* **웹 프레임워크**: FastAPI 0.110+, Uvicorn 0.28+ (ASGI)
* **음성 추출 (Audio Extraction)**: `moviepy` (16kHz 모노 WAV 추출, 시스템 `ffmpeg` 서브프로세스 자동 폴백)
* **음성 인식 (STT)**: `faster-whisper` (NVIDIA CUDA GPU 가속, float16 연산, RTX 4070 Ti 최적화, CPU 폴백)
* **문맥 교정 & 번역 (LLM)**: `ollama` Python SDK (로컬 Ollama 서비스 연동, 기본 모델: `qwen2.5:14b`, `gemma4:12b` 등 지원)
* **자막 처리**: `pysrt` (표준 SubRip `.srt` 파싱/생성, 타임스탬프 갭/중첩 자동 최적화)
* **데이터베이스**: PostgreSQL (`sqlalchemy` 엔진, `psycopg2-binary`, 커넥션 풀링 및 자동 재연결)
* **환경 변수 관리**: `python-dotenv` (`.env` 자동 로드)
* **비동기 처리**: `aiofiles` (대용량 비디오 청크 스트리밍), FastAPI `BackgroundTasks`

### 2.2 Frontend 기술 스택
* **프레임워크**: React 18, Vite 5
* **스타일링**: Tailwind CSS, Lucide-react (아이콘)
* **상태 관리 & 데이터 페칭**: `@tanstack/react-query` (서버 상태 실시간 폴링 및 캐싱)
* **미디어 재생**: `react-player` (동영상-자막 타임스탬프 실시간 동기화 및 탐색)
* **네트워크 통신**: `axios` (대용량 업로드 진행률 `onUploadProgress` 실시간 프로그레스 바)
* **파일 저장**: `file-saver` (SRT 및 ZIP 일괄 다운로드)

---

## 3. 핵심 기능별 상세 구현 명세

### 3.1 동영상 작업 대기열 (Studio Queue)
* **대용량 파일 업로드 & 순차 실행**:
  * 사용자가 여러 개의 영상을 드래그 앤 드롭하거나 파일/폴더 선택 시 `studio_queue_items`에 대기 상태(`WAITING`)로 등록.
  * 현재 실행 중인 영상이 완료되거나 오류 발생 시 다음 대기 항목을 자동으로 감지하여 순차 실행.
* **폴더 하위 무제한 재귀 검색**:
  * **브라우저 File System Access API**: `window.showDirectoryPicker()`를 지원하여 사용자가 선택한 상위 폴더 내의 모든 하위 폴더(시즌 1, 시즌 2, OVA, 특전 등)를 깊이 제한 없이 끝까지 탐색.
  * **크로미움 100건 제한 우회**: 드래그 앤 드롭 시 `DirectoryReader.readEntries()`가 한 번에 100개 파일만 반환하는 브라우저 제한을 `while` 루프로 끝까지 읽어와 누락 방지.
  * **미디어 확장자 선필터링**: 이미지(`Scans/`), 텍스트 등 비동영상 파일을 선별 제외하여 브라우저의 대량 파일 업로드 경고 팝업 차단.
  * **최대 5,000건 일괄 큐잉**: 기존 100건 제한을 5,000건으로 확대.
* **로컬 디스크 폴더 탐색기 (Server Folder Browser)**:
  * 웹 업로드 대기 없이 서버 로컬 디스크의 미디어 경로를 직접 탐색하고 `os.walk`로 재귀 스캔하여 즉시 작업큐에 등록하는 모달 제공.
  * 환경 변수(`MEDIA_SCAN_DIRS`)에 설정된 경로들을 빠른 바로가기(`quick_roots`)로 제공.
* **하위 폴더 상대 경로 보존 및 자연 정렬**:
  * 서로 다른 하위 폴더에 같은 이름(`01.mkv`, `02.mkv`)이 있어도 상대 경로(`시즌1/01.mkv`, `시즌2/01.mkv`)를 식별자로 유지하여 충돌 및 중복 완료 판정 방지.
  * 숫자 인식 자연 정렬(`_natural_sort_key`)로 1화, 2화, ..., 10화 순서대로 정렬.
* **지연 업로드 (Deferred Upload)**:
  * 브라우저에서 선택한 파일은 메모리에 모두 올리지 않고, 작업 순서가 되어 파이프라인이 시작되는 시점에 스트리밍 업로드하여 네트워크/브라우저 메모리 부하 방지.
* **오류 자동 넘김 (Auto-Advance on Error) & 오류 복사**:
  * 특정 영상에 오디오 스트림이 없거나 처리 중 예외 발생 시 파이프라인이 중단되지 않고 즉시 다음 대기 작업으로 자동 전환.
  * 오류 발생 항목에 **[오류 복사]** 및 **[전체 오류 복사]** 버튼을 제공하여 디버깅 문의 시 간편하게 복사 가능.
* **완료 항목 자동 제거**:
  * 자막 생성이 완료된 항목은 대기열 목록에서 즉시 사라지고 [작업 완료 보관함]으로 자동 이동.
* **서버 재시작 자동 복구**:
  * FastAPI `lifespan` 시작 시 데이터베이스를 검사하여 중단된 작업이 있을 경우 원본 미디어와 체크포인트를 감지하여 자동 재개.

---

### 3.2 음성 인식 & LLM 문맥 교정 파이프라인
* **1단계: 오디오 추출**:
  * 원본 영상에서 16kHz 모노 WAV 오디오를 추출 (moviepy 및 direct ffmpeg 프로세스 자동 폴백).
* **2단계: faster-whisper 정밀 음성인식**:
  * NVIDIA CUDA GPU 가속(`large-v3-turbo`, `float16`)을 활용하여 타임스탬프와 세그먼트 고속 추출.
  * Voice Activity Detection (VAD) 필터로 묵음 구간 정밀 제거.
* **3단계: Ollama LLM 문맥 교정 및 한국어 구어체 의역**:
  * 로컬 Ollama 모델(`qwen2.5:14b` 등)을 사용하여 사전식 직역투나 딱딱한 문어체를 배제하고, 자연스러운 일상 대화체로 윤문.
  * 타임라인 인덱스(1:1 ID)를 엄격히 보존.
  * **배치 단위 데이터베이스 체크포인트**: 10개 단위 세그먼트 교정 완료 시마다 PostgreSQL에 실시간 저장하여 중단 시 처음부터 다시 하지 않고 즉시 이어하기 지원.
* **4단계: CJK 전각 기호 및 AI 메타 응답 원천 차단 필터링**:
  * `qwen2.5` 등 모델에서 간혹 발생하는 중국어 설명(`翻译成...`, `。，：“”`, `""`) 및 AI 거절 문구(`"아 알겠습니다. 내용이 너무 짧아서..."`)를 방지하기 위해:
    * 단일 세그먼트 폴백 시 JSON 포맷(`format="json"`) 강제.
    * 1~3글자 초단문/추임새(`好`, `嗯`, `ねえ`, `ちょっと`, `もしもし`, 단일 가나 등)는 사전 매핑(`fast_translate_short`)으로 즉시 변환.
    * `sanitize_subtitle_text` 및 `is_ai_meta_response` 필터로 전각 특수기호 제거 및 첫 번째 유효 한국어 대사만 정제 추출.
* **5단계: SRT 생성 및 타임스탬프 최적화**:
  * `pysrt` 기반 표준 UTF-8 `.srt` 파일 생성.
  * 자막 간 겹침 방지 및 최소/최대 노출 시간 최적화.

---

### 3.3 작업 완료 보관함 (Completed Tasks Archive)
* **PostgreSQL 영구 보관**:
  * `completed_tasks` 테이블에 완료 일시, 파일명, 자막 개수, 다운로드 횟수, 최종 다운로드 일시 저장.
* **100건 단위 페이징 (Pagination)**:
  * 완료 건수가 수백~수천 건으로 늘어나도 한 페이지에 100건씩 분할 표시.
  * 상/하단 페이징 네비게이션 바 (`«`, `이전`, `1`, `2`, `...`, `다음`, `»`, 현재 표시 구간 표시).
  * **현재 페이지 전체 선택 (100건)** 및 **모든 페이지 전체 선택** 지원.
* **카테고리 탭 분리**:
  * [전체 완료건], [자막제작 스튜디오 완료건], [자막번역기 작업완료건]으로 분리 조회.
* **일괄 다운로드 & 추적**:
  * **[미다운로드건 일괄 다운로드]**: 아직 다운로드하지 않은 신규 자막만 선별하여 ZIP 압축 다운로드. 다운로드 완료 시 즉시 다운로드 횟수 1 증가 및 파란색 배지로 상태 전환.
  * **[전체 일괄 다운로드]**: 현재 탭의 모든 자막을 ZIP으로 압축 다운로드.
* **인라인 자막 편집기 & 동영상 싱크 프리뷰**:
  * 완료된 영상을 클릭하면 상세 뷰어로 진입하여 `react-player`로 영상 재생.
  * 자막 타임스탬프 클릭 시 영상 해당 위치로 즉시 이동.
  * 자막 텍스트 인라인 수정 후 [수정사항 저장] 클릭 시 PostgreSQL 및 디스크 `.srt` 파일 즉시 재생성.
* **완료 배너 반응형 최적화**:
  * 상단 완료 알림 배너 내에 [SRT 다운로드], [자막 번역하기], [완료 목록], [새 작업] 버튼이 화면 크기에 상관없이 박스 내에 안정적으로 정렬.

---

### 3.4 SRT 자막 번역기 (Subtitle Translator)
* **다국어 번역 지원**:
  * 한국어(ko), 영어(en), 일본어(ja), 중국어(zh), 스페인어(es), 프랑스어(fr), 독일어(de) 지원.
* **기존 작업 연동 & 파일 직접 업로드**:
  * 완료 보관함의 자막을 원클릭으로 번역기로 불러오거나, 외부 `.srt` 파일 드래그 앤 드롭 지원.
* **원문 언어 자동 감지**:
  * 자막 텍스트의 유니코드 및 어휘 분석을 통한 원문 언어 자동 판별.
* **번역 큐 및 체크포인트**:
  * 번역 파이프라인도 배치 단위 체크포인트를 저장하여 안정적으로 백그라운드 처리.

---

### 3.5 관리자 엔진 설정 (Admin Settings)
* **LLM 모델 설정**:
  * 로컬 Ollama 서버에 설치된 모델 자동 탐색 및 드롭다운 선택.
  * 추천 모델(`qwen2.5:14b`, `qwen2.5:7b`, `gemma4:12b` 등) 및 신규 모델 웹 UI 다운로드/풀(Pull) 기능.
* **Whisper STT 모델 설정**:
  * 모델 크기(`large-v3-turbo`, `large-v3`, `medium`, `small`, `base`).
  * 연산 디바이스(`cuda`, `cpu`) 및 연산 정밀도(`float16`, `int8_float16`, `int8`).
* **설정 즉시 반영 및 완료건 재추출**:
  * 관리자 설정 변경 시 즉시 런타임 적용.
  * 옵션 활성화 시 기존 완료된 작업을 변경된 모델 기준으로 작업 대기열에 다시 등록하여 전체 재추출 실행.

---

### 3.6 알림 및 사용자 경험 (UX)
* **실시간 브라우저 웹 푸시 알림**:
  * 작업 완료 시 브라우저 Notification API를 통해 백그라운드 상태에서도 "[영상 제목] 자막이 생성되었습니다" 알림 발송 및 클릭 시 완료 보관함 바로 이동.
* **앱 내 실시간 토스트 팝업**:
  * 화면 우측 상단 플로팅 배너로 작업 완료 즉시 시각화.

---

## 4. 환경 변수 및 설정 프로퍼티 명세 (비식별화)

모든 민감 접속 정보(IP, 포트, DB 계정, 비밀번호 등)는 코드베이스에서 완전히 분리되어 `.env` 파일로부터 로드됩니다.  
저장소에는 템플릿 파일인 `.env.example`만 업로드되며, 실제 `.env` 파일은 `.gitignore`에 등록되어 커밋에서 제외됩니다.

### 4.1 프로퍼티 목록 (`.env.example`)
```env
# ==============================================================================
# TransM Environment Configuration Template (.env.example)
# Copy this file to '.env' and fill in your actual environment properties.
# ==============================================================================

# 1. Server Configuration
SERVER_HOST=0.0.0.0
SERVER_PORT=8000

# 2. PostgreSQL Database Connection
POSTGRES_HOST=your-db-host
POSTGRES_PORT=5432
POSTGRES_DB=your_database_name
POSTGRES_USER=your_db_user
POSTGRES_PASSWORD=your_db_password

# 3. Ollama LLM Service Configuration
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=qwen2.5:14b
LLM_BATCH_SIZE=10

# 4. Whisper STT Configuration
# Models: large-v3-turbo, large-v3, medium, small, base
# Device: cuda (GPU acceleration), cpu
# Compute Type: float16, int8_float16, int8
WHISPER_MODEL_SIZE=large-v3-turbo
WHISPER_DEVICE=cuda
WHISPER_COMPUTE_TYPE=float16

# 5. Local Media Search Directories (Comma or semicolon separated paths)
# Example: D:\Media\Videos,D:\Movies,E:\Anime
MEDIA_SCAN_DIRS=
```

---

## 5. 데이터베이스 스키마 명세 (PostgreSQL)

### 5.1 `transm_tasks` (작업 상세 및 세그먼트 체크포인트)
| 컬럼명 | 데이터 타입 | 설명 |
| :--- | :--- | :--- |
| `task_id` | `VARCHAR(64)` (PK) | 고유 작업 UUID |
| `filename` | `VARCHAR(512)` | 영상 또는 자막 원본 파일명 (상대 경로 포함) |
| `status` | `VARCHAR(32)` | `WAITING`, `PROCESSING`, `COMPLETED`, `FAILED` |
| `stage` | `VARCHAR(256)` | 현재 세부 처리 단계 메시지 |
| `progress` | `INTEGER` | 전체 진행률 (0 ~ 100) |
| `video_path` | `VARCHAR(1024)` | 서버 측 비디오 파일 절대 경로 |
| `audio_path` | `VARCHAR(1024)` | 추출된 WAV 오디오 파일 경로 |
| `srt_path` | `VARCHAR(1024)` | 생성된 `.srt` 자막 파일 경로 |
| `srt_download_url` | `VARCHAR(256)` | 다운로드 엔드포인트 URL |
| `error` | `TEXT` | 실패 시 상세 오류 메시지 |
| `raw_segments` | `JSONB` | Whisper STT 1차 원문 세그먼트 목록 |
| `checkpoint_segments` | `JSONB` | LLM 문맥 교정 완료된 세그먼트 맵 (`{id: text}`) |
| `subtitles` | `JSONB` | 최종 자막 세그먼트 배열 |
| `created_at` | `TIMESTAMP` | 작업 생성 일시 |
| `updated_at` | `TIMESTAMP` | 최종 업데이트 일시 |

### 5.2 `completed_tasks` (완료 작업 보관소)
| 컬럼명 | 데이터 타입 | 설명 |
| :--- | :--- | :--- |
| `task_id` | `VARCHAR(64)` (PK) | 고유 작업 UUID |
| `filename` | `VARCHAR(512)` | 완성된 영상/자막 파일명 |
| `subtitle_count` | `INTEGER` | 생성된 총 자막 라인 수 |
| `srt_path` | `VARCHAR(1024)` | `.srt` 파일 저장 경로 |
| `srt_download_url` | `VARCHAR(256)` | 다운로드 URL |
| `task_type` | `VARCHAR(32)` | `studio` (스튜디오 추출) / `translator` (다국어 번역) |
| `download_count` | `INTEGER` | 다운로드 횟수 (기본 0) |
| `last_downloaded_at` | `TIMESTAMP` | 최근 다운로드 일시 |
| `completed_at` | `TIMESTAMP` | 작업 완료 일시 |

### 5.3 `studio_queue_items` (스튜디오 순차 대기열)
| 컬럼명 | 데이터 타입 | 설명 |
| :--- | :--- | :--- |
| `id` | `VARCHAR(64)` (PK) | 대기열 아이템 UUID |
| `filename` | `VARCHAR(512)` | 영상 파일명 (하위 폴더 상대 경로 포함) |
| `size` | `BIGINT` | 파일 크기 (바이트) |
| `status` | `VARCHAR(32)` | `WAITING`, `UPLOADING`, `PROCESSING`, `COMPLETED`, `FAILED` |
| `upload_progress` | `INTEGER` | 스트리밍 업로드 진행률 (0 ~ 100) |
| `task_id` | `VARCHAR(64)` | 생성된 파이프라인 태스크 ID |
| `error` | `TEXT` | 에러 메시지 |
| `client_id` | `VARCHAR(64)` | 클라이언트 식별자 |
| `sort_order` | `INTEGER` | 큐 순서 인덱스 |
| `created_at` | `TIMESTAMP` | 등록 일시 |

---

## 6. 주요 REST API 명세 요약

| Method | Endpoint | 설명 |
| :--- | :--- | :--- |
| `POST` | `/api/upload` | 동영상 파일 업로드 및 백그라운드 파이프라인 즉시 시작 |
| `GET` | `/api/tasks/{task_id}` | 특정 작업의 상태, 진행률, 인라인 자막 세그먼트 조회 |
| `PUT` | `/api/tasks/{task_id}/subtitles` | 인라인 수정된 자막 세그먼트 저장 및 `.srt` 파일 재생성 |
| `GET` | `/api/download/{task_id}` | 원본 영상명 매칭 `.srt` 자막 단일 다운로드 |
| `GET` | `/api/video/{task_id}` | react-player 비디오 스트리밍 프리뷰 (웹 호환 자동 트랜스코딩) |
| `GET` | `/api/completed-tasks` | 완료 보관함 목록 조회 (`task_type`, `page`, `page_size`, `limit`, `offset` 지원) |
| `POST` | `/api/download/batch-undownloaded`| 미다운로드 자막만 선별하여 ZIP 압축 다운로드 |
| `POST` | `/api/download/batch-all` | 선택/전체 자막 ZIP 압축 일괄 다운로드 |
| `POST` | `/api/tasks/batch-delete` | 선택한 작업 및 관련 파일 일괄 영구 삭제 |
| `DELETE`| `/api/tasks/all` | 보관함 전체 작업 및 파일 일괄 영구 삭제 |
| `GET` | `/api/studio-queue` | 스튜디오 작업 대기열 목록 조회 |
| `POST` | `/api/studio-queue/sync` | 클라이언트 대기열 상태 동기화 |
| `POST` | `/api/studio-queue/add-folder` | 서버 로컬 디스크 폴더 재귀 스캔 및 대기열 일괄 등록 |
| `GET` | `/api/studio-queue/browse-folders`| 서버 로컬 디스크 디렉토리 목록 브라우징 |
| `POST` | `/api/studio-queue/clear-completed`| 대기열 내 완료/오류 항목 정리 |
| `POST` | `/api/translate/detect` | 자막 원문 언어 자동 감지 |
| `POST` | `/api/translate/start` | 다국어 자막 번역 파이프라인 비동기 실행 |
| `GET` | `/api/settings` | 현재 LLM 및 Whisper 런타임 설정 및 선택지 조회 |
| `POST` | `/api/settings` | 관리자 엔진 설정 변경 (완료건 재추출 옵션 지원) |
| `POST` | `/api/settings/pull-model` | 로컬 Ollama 모델 다운로드/설치 |

---

## 7. 로컬 실행 및 서비스 제어 가이드

1. **사전 준비**:
   * 로컬 PostgreSQL 서버 실행 및 데이터베이스 생성.
   * 로컬 Ollama 서비스 구동 및 권장 모델 풀 (`ollama run qwen2.5:14b`).
   * FFmpeg 시스템 PATH 등록 확인.
2. **설정 적용**:
   * `.env.example`을 복사하여 `.env`를 생성하고 실제 접속 정보 기입.
3. **원클릭 실행**:
   * `start.bat`: 백엔드(`:8000`)와 프론트엔드(`:5173`)를 동시 실행하고 브라우저를 자동 오픈.
   * `start_background.vbs`: 콘솔 창 없이 백그라운드 무창 모드로 실행.
   * `stop.bat`: 8000, 5173 포트를 점유하는 TransM 프로세스 일괄 종료.

