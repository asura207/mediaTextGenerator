import React, { useState } from 'react';
import { CheckCircle2, Download, RotateCcw, ListFilter, Languages, CheckCheck, Sparkles, AlertCircle } from 'lucide-react';
import { downloadSrtFile } from '../api/client';

export default function CompletedBanner({ task, onReset, onGoToList, onTranslate, onDownloaded }) {
  const [isDownloading, setIsDownloading] = useState(false);

  const isDownloaded = (task?.download_count || 0) > 0 || task?.downloaded;
  const downloadCount = task?.download_count || 0;
  const subtitleCount = task?.subtitles?.length ?? task?.subtitle_count ?? 0;
  const hasSubtitles = subtitleCount > 0;

  const handleDownload = async () => {
    if (!task?.task_id || !hasSubtitles) return;
    setIsDownloading(true);
    try {
      let baseName = task.filename 
        ? task.filename.replace(/\.[^/.]+$/, "") 
        : `subtitles_${task.task_id.slice(0, 8)}`;
      for (const lang of ['_ko', '_en', '_ja', '_zh', '_es']) {
        if (baseName.endsWith(lang)) {
          baseName = baseName.slice(0, -lang.length);
          break;
        }
      }
      const filename = `${baseName}.srt`;
      await downloadSrtFile(task.task_id, filename);
      if (onDownloaded) onDownloaded();
    } catch (err) {
      alert('SRT 파일 다운로드 중 오류가 발생했습니다: ' + (err.response?.data?.detail || err.message));
    } finally {
      setIsDownloading(false);
    }
  };

  return (
    <div
      className={`w-full my-4 p-5 rounded-2xl shadow-2xl backdrop-blur flex flex-col lg:flex-row lg:items-center justify-between gap-4 border transition-all overflow-hidden ${
        !hasSubtitles
          ? 'bg-gradient-to-r from-amber-950/20 via-slate-900/90 to-slate-900/90 border-amber-500/30'
          : isDownloaded
          ? 'bg-gradient-to-r from-blue-950/30 via-slate-900/90 to-indigo-950/30 border-blue-500/30'
          : 'bg-gradient-to-r from-emerald-950/40 via-slate-900/90 to-indigo-950/40 border-emerald-500/35'
      }`}
    >
      {/* Left: Completion Badge & Info */}
      <div className="flex items-center space-x-3.5 min-w-0 flex-1">
        <div
          className={`w-11 h-11 rounded-2xl flex items-center justify-center shadow-lg flex-shrink-0 border ${
            !hasSubtitles
              ? 'bg-amber-500/15 border-amber-500/30 text-amber-400 shadow-amber-500/10'
              : isDownloaded
              ? 'bg-blue-500/15 border-blue-500/30 text-blue-400 shadow-blue-500/10'
              : 'bg-emerald-500/15 border-emerald-500/30 text-emerald-400 shadow-emerald-500/10'
          }`}
        >
          {!hasSubtitles ? (
            <AlertCircle className="w-6 h-6" />
          ) : isDownloaded ? (
            <CheckCheck className="w-6 h-6" />
          ) : (
            <CheckCircle2 className="w-6 h-6" />
          )}
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2 flex-wrap">
            <h3 className="text-base font-bold text-white whitespace-nowrap">
              {!hasSubtitles ? '음성이 감지되지 않아 자막이 0건입니다' : '자막 생성이 성공적으로 완료되었습니다!'}
            </h3>
            <span
              className={`px-2.5 py-0.5 text-xs font-semibold rounded-full border whitespace-nowrap ${
                !hasSubtitles
                  ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
                  : isDownloaded
                  ? 'bg-blue-500/15 text-blue-300 border-blue-500/30'
                  : 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
              }`}
            >
              {!hasSubtitles ? '자막 없음 (0건)' : `${subtitleCount.toLocaleString()}개 자막`}
            </span>
            {hasSubtitles && (
              isDownloaded ? (
                <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 text-xs font-semibold bg-blue-500/20 text-blue-300 rounded-full border border-blue-500/40 whitespace-nowrap">
                  <CheckCheck className="w-3 h-3 text-blue-400 flex-shrink-0" />
                  <span>다운로드 완료 ({downloadCount}회)</span>
                </span>
              ) : (
                <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 text-xs font-bold bg-emerald-500/20 text-emerald-300 rounded-full border border-emerald-500/40 animate-pulse whitespace-nowrap">
                  <Sparkles className="w-3 h-3 text-emerald-400 flex-shrink-0" />
                  <span>신규 완료 (미다운로드)</span>
                </span>
              )
            )}
          </div>
          <p className="text-xs text-slate-400 mt-1 truncate" title={task?.filename || '영상'}>
            {task?.filename || '영상'} • {!hasSubtitles ? '아래 자막 편집기에서 자막을 직접 추가하고 저장할 수 있습니다' : 'PostgreSQL에 영구 보관 완료'}
          </p>
        </div>
      </div>

      {/* Right: Focused Action Buttons (Highlighted SRT Download & Translate) */}
      <div className="flex items-center gap-2 flex-shrink-0 flex-wrap">
        <button
          type="button"
          onClick={handleDownload}
          disabled={!hasSubtitles || isDownloading}
          className={`flex items-center space-x-2 px-4 py-2.5 text-xs sm:text-sm font-bold rounded-xl transition-all shadow-lg whitespace-nowrap ${
            !hasSubtitles
              ? 'opacity-50 cursor-not-allowed bg-slate-800 text-slate-500 border border-slate-700/60 shadow-none'
              : isDownloaded
              ? 'bg-slate-800 hover:bg-slate-700 text-slate-200 hover:text-white border border-slate-700 shadow-slate-900/50 hover:scale-[1.02] active:scale-[0.98]'
              : 'text-white bg-gradient-to-r from-emerald-600 via-teal-600 to-indigo-600 hover:from-emerald-500 hover:to-indigo-500 shadow-emerald-600/25 hover:scale-[1.02] active:scale-[0.98]'
          }`}
          title={
            !hasSubtitles
              ? '생성된 자막이 없어 다운로드할 수 없습니다. 아래 자막 편집기에서 자막을 추가하고 저장해 주세요.'
              : isDownloaded
              ? `이미 ${downloadCount}회 다운로드된 자막입니다`
              : 'SRT 자막 다운로드'
          }
        >
          {!hasSubtitles ? (
            <>
              <Download className="w-4 h-4 text-slate-500 flex-shrink-0" />
              <span>자막 없음</span>
            </>
          ) : isDownloaded ? (
            <>
              <CheckCheck className="w-4 h-4 text-blue-400 flex-shrink-0" />
              <span>{isDownloading ? '다운로드 중...' : `SRT 재다운로드 (${downloadCount}회)`}</span>
            </>
          ) : (
            <>
              <Download className="w-4 h-4 flex-shrink-0" />
              <span>{isDownloading ? '다운로드 중...' : 'SRT 다운로드'}</span>
            </>
          )}
        </button>

        {onTranslate && hasSubtitles && (
          <button
            type="button"
            onClick={onTranslate}
            className="flex items-center space-x-1.5 px-3.5 py-2.5 text-xs font-semibold text-indigo-300 hover:text-white bg-indigo-600/20 hover:bg-indigo-600/35 border border-indigo-500/40 rounded-xl transition-all shadow-sm whitespace-nowrap"
            title="이 자막을 원하는 언어로 번역합니다"
          >
            <Languages className="w-3.5 h-3.5 flex-shrink-0" />
            <span>자막 번역하기</span>
          </button>
        )}

        {onGoToList && (
          <button
            type="button"
            onClick={onGoToList}
            className="flex items-center space-x-1.5 px-3 py-2.5 text-xs font-medium text-slate-300 hover:text-white bg-slate-800/80 hover:bg-slate-700 border border-slate-700 rounded-xl transition-all whitespace-nowrap"
            title="완료된 작업 목록 보기"
          >
            <ListFilter className="w-3.5 h-3.5 flex-shrink-0" />
            <span>완료 목록</span>
          </button>
        )}

        <button
          type="button"
          onClick={onReset}
          className="flex items-center space-x-1.5 px-3 py-2.5 text-xs font-medium text-slate-400 hover:text-rose-400 bg-slate-900/60 hover:bg-slate-800 border border-slate-800 rounded-xl transition-all whitespace-nowrap"
          title="새 작업을 등록합니다"
        >
          <RotateCcw className="w-3.5 h-3.5 flex-shrink-0" />
          <span>새 작업</span>
        </button>
      </div>
    </div>
  );
}
