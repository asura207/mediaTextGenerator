import React, { useState, useEffect } from 'react';
import { Save, Play, Check, Search, RotateCcw, Sparkles, Plus, Trash2, FileText, Clock } from 'lucide-react';
import { updateSubtitles } from '../api/client';

const formatTimestamp = (seconds) => {
  const totalMs = Math.round(Math.max(0, Number(seconds) || 0) * 1000);
  const hours = Math.floor(totalMs / 3600000);
  const mins = Math.floor((totalMs % 3600000) / 60000);
  const secs = Math.floor((totalMs % 60000) / 1000);
  const ms = totalMs % 1000;
  return `${String(hours).padStart(2, '0')}:${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
};

const parseTimestampToSeconds = (timeStr) => {
  if (!timeStr) return 0;
  const clean = timeStr.trim().replace('.', ',');
  const parts = clean.split(':');
  if (parts.length === 3) {
    const h = parseFloat(parts[0]) || 0;
    const m = parseFloat(parts[1]) || 0;
    const sParts = parts[2].split(',');
    const s = parseFloat(sParts[0]) || 0;
    const ms = parseFloat(sParts[1]) || 0;
    return h * 3600 + m * 60 + s + ms / 1000;
  } else if (parts.length === 2) {
    const m = parseFloat(parts[0]) || 0;
    const sParts = parts[1].split(',');
    const s = parseFloat(sParts[0]) || 0;
    const ms = parseFloat(sParts[1]) || 0;
    return m * 60 + s + ms / 1000;
  }
  return parseFloat(timeStr) || 0;
};

export default function SubtitleEditor({ taskId, initialSubtitles, onSeekVideo, onReset, onSubtitlesUpdated }) {
  const [subtitles, setSubtitles] = useState(initialSubtitles || []);
  const [searchQuery, setSearchQuery] = useState('');
  const [isSaving, setIsSaving] = useState(false);
  const [saveSuccess, setSaveSuccess] = useState(false);

  useEffect(() => {
    if (initialSubtitles) {
      setSubtitles(initialSubtitles);
    }
  }, [initialSubtitles]);

  const handleTextChange = (index, newText) => {
    setSubtitles((prev) =>
      prev.map((item) => (item.index === index ? { ...item, refined_text: newText, text: newText } : item))
    );
    setSaveSuccess(false);
  };

  const handleTimeChange = (index, field, value) => {
    setSubtitles((prev) =>
      prev.map((item) => {
        if (item.index !== index) return item;
        const updated = { ...item, [field]: value };
        if (field === 'start_time_str') {
          updated.start = parseTimestampToSeconds(value);
        } else if (field === 'end_time_str') {
          updated.end = parseTimestampToSeconds(value);
        }
        return updated;
      })
    );
    setSaveSuccess(false);
  };

  const handleAddSubtitle = () => {
    let nextStart = 0;
    if (subtitles.length > 0) {
      const last = subtitles[subtitles.length - 1];
      nextStart = Number(((last.end || 0) + 0.1).toFixed(3));
    }
    const nextEnd = Number((nextStart + 3.0).toFixed(3));
    const newIndex = subtitles.length > 0 ? Math.max(...subtitles.map((s) => Number(s.index) || 0)) + 1 : 1;

    const newSub = {
      index: newIndex,
      start: nextStart,
      end: nextEnd,
      start_time_str: formatTimestamp(nextStart),
      end_time_str: formatTimestamp(nextEnd),
      text: '',
      raw_text: '',
      refined_text: '',
    };
    setSubtitles((prev) => [...prev, newSub]);
    setSaveSuccess(false);
  };

  const handleDeleteSubtitle = (index) => {
    setSubtitles((prev) => prev.filter((item) => item.index !== index));
    setSaveSuccess(false);
  };

  const handleSaveChanges = async () => {
    setIsSaving(true);
    try {
      // Re-index remaining subtitles
      const reIndexed = subtitles.map((s, idx) => ({
        ...s,
        index: idx + 1,
        text: s.refined_text || s.text || s.raw_text || '',
        refined_text: s.refined_text || s.text || s.raw_text || '',
      }));

      const res = await updateSubtitles(taskId, reIndexed);
      setSubtitles(res.subtitles || reIndexed);
      setSaveSuccess(true);
      if (onSubtitlesUpdated) {
        onSubtitlesUpdated(res.subtitles || reIndexed);
      }
      setTimeout(() => setSaveSuccess(false), 2500);
    } catch (err) {
      console.error('Save subtitles error:', err);
      alert('자막 수정사항 저장 중 오류가 발생했습니다: ' + (err.response?.data?.detail || err.message));
    } finally {
      setIsSaving(false);
    }
  };

  const filteredSubtitles = subtitles.filter(
    (s) =>
      (s.refined_text || '').toLowerCase().includes(searchQuery.toLowerCase()) ||
      (s.raw_text || '').toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <div className="flex flex-col h-full bg-slate-900 border border-slate-800 rounded-2xl overflow-hidden shadow-2xl">
      {/* Top Toolbar */}
      <div className="p-4 bg-slate-800/80 border-b border-slate-700/80 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center space-x-2">
          <span className="text-sm font-semibold text-slate-200">
            총 {subtitles.length}개 세그먼트
          </span>
          <div className="relative">
            <Search className="w-3.5 h-3.5 absolute left-2.5 top-2.5 text-slate-400" />
            <input
              type="text"
              placeholder="자막 검색..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-8 pr-3 py-1 bg-slate-900/80 border border-slate-700 rounded-lg text-xs text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500 w-44"
            />
          </div>
        </div>

        <div className="flex items-center space-x-2">
          <button
            type="button"
            onClick={handleAddSubtitle}
            className="px-3 py-1.5 rounded-xl text-xs font-semibold bg-indigo-600/30 hover:bg-indigo-600 text-indigo-200 hover:text-white border border-indigo-500/40 transition flex items-center space-x-1.5 shadow-sm"
            title="새 자막 라인 추가"
          >
            <Plus className="w-3.5 h-3.5" />
            <span>자막 추가</span>
          </button>

          <button
            type="button"
            onClick={handleSaveChanges}
            disabled={isSaving}
            className={`px-3.5 py-1.5 rounded-xl text-xs font-semibold transition flex items-center space-x-1.5 shadow-md ${
              saveSuccess
                ? 'bg-emerald-600 text-white shadow-emerald-600/30'
                : 'bg-indigo-600 hover:bg-indigo-500 text-white shadow-indigo-600/25'
            }`}
          >
            {saveSuccess ? <Check className="w-3.5 h-3.5" /> : <Save className="w-3.5 h-3.5" />}
            <span>{saveSuccess ? '저장 완료!' : isSaving ? '저장 중...' : '수정사항 저장'}</span>
          </button>

          <button
            type="button"
            onClick={onReset}
            className="p-1.5 rounded-xl text-slate-400 hover:text-slate-200 hover:bg-slate-800 transition"
            title="목록으로 이동"
          >
            <RotateCcw className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Subtitles Scrollable List */}
      <div className="flex-1 overflow-y-auto p-4 space-y-3 max-h-[550px]">
        {filteredSubtitles.length === 0 ? (
          <div className="text-center py-12 px-4 space-y-4">
            <div className="w-12 h-12 mx-auto rounded-2xl bg-indigo-500/10 text-indigo-400 flex items-center justify-center border border-indigo-500/20">
              <FileText className="w-6 h-6" />
            </div>
            <div className="space-y-1">
              <p className="font-semibold text-slate-200 text-sm">
                등록된 자막 세그먼트가 없습니다
              </p>
              <p className="text-xs text-slate-400 max-w-sm mx-auto leading-relaxed">
                음성이 감지되지 않았거나 자막이 생성되지 않은 영상입니다.<br />
                직접 자막을 추가하고 저장하면 <strong>SRT 다운로드 버튼이 활성화</strong>됩니다.
              </p>
            </div>
            <button
              type="button"
              onClick={handleAddSubtitle}
              className="px-4 py-2 bg-indigo-600 hover:bg-indigo-500 text-white rounded-xl text-xs font-semibold transition shadow-md shadow-indigo-600/25 inline-flex items-center space-x-1.5"
            >
              <Plus className="w-4 h-4" />
              <span>첫 번째 자막 추가하기</span>
            </button>
          </div>
        ) : (
          filteredSubtitles.map((seg) => (
            <div
              key={seg.index}
              className="p-3.5 bg-slate-800/40 hover:bg-slate-800/80 border border-slate-800 hover:border-slate-700 rounded-xl transition space-y-2 group"
            >
              {/* Segment Header */}
              <div className="flex items-center justify-between text-xs flex-wrap gap-2">
                <div className="flex items-center space-x-2">
                  <span className="font-mono text-slate-400 font-semibold">#{seg.index}</span>
                  <button
                    type="button"
                    onClick={() => onSeekVideo && onSeekVideo(seg.start)}
                    className="font-mono px-2 py-0.5 rounded bg-slate-700/60 hover:bg-indigo-600 text-indigo-300 hover:text-white transition flex items-center space-x-1"
                    title="이 위치로 영상 이동"
                  >
                    <Play className="w-2.5 h-2.5 fill-current" />
                    <span>
                      {seg.start_time_str || formatTimestamp(seg.start)} → {seg.end_time_str || formatTimestamp(seg.end)}
                    </span>
                  </button>
                </div>

                <div className="flex items-center space-x-2">
                  {seg.raw_text && seg.raw_text !== seg.refined_text && (
                    <span className="text-[10px] text-purple-400/80 flex items-center space-x-1">
                      <Sparkles className="w-2.5 h-2.5" />
                      <span>AI 문맥 교정됨</span>
                    </span>
                  )}
                  <button
                    type="button"
                    onClick={() => handleDeleteSubtitle(seg.index)}
                    className="p-1 text-slate-500 hover:text-rose-400 hover:bg-rose-500/10 rounded-lg transition"
                    title="이 자막 라인 삭제"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>

              {/* Editable Refined Subtitle */}
              <textarea
                value={seg.refined_text || seg.text || ''}
                onChange={(e) => handleTextChange(seg.index, e.target.value)}
                rows={2}
                className="w-full bg-slate-900/90 border border-slate-700/80 focus:border-indigo-500 rounded-lg p-2.5 text-sm text-slate-100 placeholder-slate-500 focus:outline-none resize-none leading-relaxed transition"
                placeholder="자막 대사 입력..."
              />

              {/* Raw STT Comparison */}
              {seg.raw_text && seg.raw_text !== (seg.refined_text || seg.text) && (
                <div className="text-[11px] text-slate-500 bg-slate-900/50 p-1.5 rounded border border-slate-800/80">
                  <span className="text-slate-400 font-medium">Whisper 원본: </span>
                  <span className="line-through decoration-slate-600">{seg.raw_text}</span>
                </div>
              )}
            </div>
          ))
        )}
      </div>
    </div>
  );
}