from typing import List, Optional, Any
from pydantic import BaseModel, Field, model_validator
from app.services.srt_generator import format_timestamp

class SubtitleSegment(BaseModel):
    index: int = 0
    start: float = Field(0.0, description="Start time in seconds")
    end: float = Field(0.0, description="End time in seconds")
    start_time_str: str = Field("", description="Formatted start time HH:MM:SS,mmm")
    end_time_str: str = Field("", description="Formatted end time HH:MM:SS,mmm")
    raw_text: str = Field("", description="Original text extracted by Whisper")
    refined_text: str = Field("", description="Context-corrected text refined by Ollama LLM")

    @model_validator(mode="before")
    @classmethod
    def normalize_fields(cls, data: Any):
        if isinstance(data, dict):
            st = float(data.get("start") or 0.0)
            et = float(data.get("end") or 0.0)
            
            st_str = data.get("start_time_str") or data.get("start_str")
            if not st_str:
                st_str = format_timestamp(st)
            else:
                st_str = str(st_str).replace(".", ",")
            
            et_str = data.get("end_time_str") or data.get("end_str")
            if not et_str:
                et_str = format_timestamp(et)
            else:
                et_str = str(et_str).replace(".", ",")
                
            raw = data.get("raw_text") or data.get("original_text") or data.get("text") or ""
            refined = data.get("refined_text") or data.get("text") or raw

            return {
                "index": int(data.get("index") or data.get("id") or 0),
                "start": st,
                "end": et,
                "start_time_str": st_str,
                "end_time_str": et_str,
                "raw_text": raw,
                "refined_text": refined
            }
        return data

class TaskStatus(BaseModel):
    task_id: str
    status: str = Field(..., description="PENDING | PROCESSING | COMPLETED | FAILED")
    stage: str = Field(..., description="Human-readable stage description")
    progress: int = Field(0, description="Progress percentage 0-100")
    filename: str = ""
    error: Optional[str] = None
    subtitles: List[SubtitleSegment] = []
    srt_download_url: Optional[str] = None
    video_url: Optional[str] = None
    eta_str: Optional[str] = None
    eta_seconds: Optional[int] = None

class UpdateSubtitlesRequest(BaseModel):
    subtitles: List[SubtitleSegment]

class DictionaryEntryCreate(BaseModel):
    source_word: str
    target_word: str
    notes: Optional[str] = None

class DictionaryEntryUpdate(BaseModel):
    source_word: str
    target_word: str
    notes: Optional[str] = None

class DictionaryBatchDelete(BaseModel):
    ids: List[int]

class CloudLLMTestRequest(BaseModel):
    provider: str
    api_key: Optional[str] = None
    model: Optional[str] = None


