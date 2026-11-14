import React, { forwardRef, useState, useEffect, useMemo } from 'react';
import ReactPlayer from 'react-player';
import { AlertTriangle } from 'lucide-react';

function formatVttTime(seconds) {
  const totalMs = Math.max(0, Math.round((Number(seconds) || 0) * 1000));
  const hrs = String(Math.floor(totalMs / 3600000)).padStart(2, '0');
  const mins = String(Math.floor((totalMs % 3600000) / 60000)).padStart(2, '0');
  const secs = String(Math.floor((totalMs % 60000) / 1000)).padStart(2, '0');
  const ms = String(totalMs % 1000).padStart(3, '0');
  return `${hrs}:${mins}:${secs}.${ms}`;
}

function parseTimeSec(val, strFallback) {
  if (typeof val === 'number' && !Number.isNaN(val)) return val;
  if (strFallback && typeof strFallback === 'string') {
    const m = strFallback.trim().match(/(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})/);
    if (m) {
      return (
        parseInt(m[1], 10) * 3600 +
        parseInt(m[2], 10) * 60 +
        parseInt(m[3], 10) +
        parseInt(m[4].padEnd(3, '0'), 10) / 1000
      );
    }
  }
  return 0;
}

const VideoPreview = forwardRef(({ videoUrl, subtitles = [], onProgress }, ref) => {
  const [currentTime, setCurrentTime] = useState(0);
  const [hasError, setHasError] = useState(false);
  const [vttBlobUrl, setVttBlobUrl] = useState(null);

  useEffect(() => {
    setHasError(false);
  }, [videoUrl]);

  const normalizedSubs = useMemo(() => {
    if (!Array.isArray(subtitles)) return [];
    return subtitles.map((s, idx) => {
      const st = parseTimeSec(s.start, s.start_str || s.start_time_str);
      const ed = Math.max(st + 0.15, parseTimeSec(s.end, s.end_str || s.end_time_str));
      const text = (s.refined_text || s.text || s.raw_text || '').trim();
      return { index: s.index || idx + 1, start: st, end: ed, text };
    });
  }, [subtitles]);

  // Convert .srt subtitle segments to WebVTT Blob URL and revoke previous Blob URL to prevent memory leaks
  useEffect(() => {
    if (!normalizedSubs.length) {
      setVttBlobUrl(null);
      return undefined;
    }
    const vttLines = ['WEBVTT\n'];
    normalizedSubs.forEach((s, idx) => {
      if (!s.text) return;
      vttLines.push(`${idx + 1}\n${formatVttTime(s.start)} --> ${formatVttTime(s.end)}\n${s.text}\n`);
    });
    const blob = new Blob([vttLines.join('\n')], { type: 'text/vtt;charset=utf-8' });
    const objectUrl = URL.createObjectURL(blob);
    setVttBlobUrl(objectUrl);

    return () => {
      URL.revokeObjectURL(objectUrl);
    };
  }, [normalizedSubs]);

  if (!videoUrl) return null;

  const handleProgress = (state) => {
    setCurrentTime(state.playedSeconds);
    if (onProgress) {
      onProgress(state);
    }
  };

  // Find currently active subtitle based on exact start and end times
  const activeSubtitle = normalizedSubs.find(
    (s) => currentTime >= s.start && currentTime <= s.end
  );

  const activeText = activeSubtitle?.text || '';

  return (
    <div className="rounded-2xl overflow-hidden bg-black border border-slate-800 shadow-2xl relative aspect-video flex items-center justify-center group">
      <ReactPlayer
        ref={ref}
        url={videoUrl}
        controls={!hasError}
        width="100%"
        height="100%"
        onProgress={handleProgress}
        progressInterval={100}
        onError={(err) => {
          console.warn("Video preview error:", err);
          setHasError(true);
        }}
        config={{
          file: {
            attributes: {
              controlsList: 'nodownload',
              crossOrigin: 'anonymous',
            },
            tracks: vttBlobUrl
              ? [
                  {
                    kind: 'subtitles',
                    src: vttBlobUrl,
                    srcLang: 'ko',
                    label: '한국어 (TransM)',
                    default: false,
                  },
                ]
              : [],
          },
        }}
      />

      {/* Fallback notice for formats (like raw WMV) that browser cannot decode directly */}
      {hasError && (
        <div className="absolute inset-0 bg-slate-900/90 backdrop-blur-sm flex flex-col items-center justify-center p-6 text-center z-20 space-y-3">
          <div className="w-12 h-12 rounded-2xl bg-amber-500/20 text-amber-400 flex items-center justify-center shadow-lg">
            <AlertTriangle className="w-6 h-6" />
          </div>
          <div className="space-y-1">
            <p className="font-semibold text-slate-200 text-sm">
              브라우저 내장 재생을 지원하지 않는 비디오 코덱입니다
            </p>
            <p className="text-xs text-slate-400 max-w-sm leading-relaxed">
              WMV 등 일부 마이크로소프트 전용 코덱은 웹 브라우저 자체 재생이 제한될 수 있습니다.
              자막 추출 및 문맥 교정, 타임스탬프 편집과 SRT 파일 다운로드는 모두 정상적으로 완료되었습니다.
            </p>
          </div>
        </div>
      )}

      {/* Subtitle Overlay: Appears when dialogue starts, supports 2-line speaker overlap, and disappears when dialogue ends */}
      {activeText && !hasError && (
        <div className="absolute bottom-12 left-4 right-4 pointer-events-none flex justify-center z-10 transition-opacity duration-150 animate-in fade-in">
          <div className="max-w-[90%] px-4 py-2 rounded-xl bg-black/85 backdrop-blur-md border border-white/10 text-white text-center font-bold text-sm sm:text-base md:text-lg shadow-2xl drop-shadow-[0_2px_4px_rgba(0,0,0,0.9)] leading-snug whitespace-pre-line">
            {activeText}
          </div>
        </div>
      )}
    </div>
  );
});

VideoPreview.displayName = 'VideoPreview';
export default VideoPreview;
