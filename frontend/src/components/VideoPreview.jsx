import React, { forwardRef, useState, useEffect } from 'react';
import ReactPlayer from 'react-player';
import { AlertTriangle, PlayCircle } from 'lucide-react';

const VideoPreview = forwardRef(({ videoUrl, subtitles = [], onProgress }, ref) => {
  const [currentTime, setCurrentTime] = useState(0);
  const [hasError, setHasError] = useState(false);

  useEffect(() => {
    setHasError(false);
  }, [videoUrl]);

  if (!videoUrl) return null;

  const handleProgress = (state) => {
    setCurrentTime(state.playedSeconds);
    if (onProgress) {
      onProgress(state);
    }
  };

  // Find currently active subtitle based on exact start and end times
  const activeSubtitle = subtitles?.find(
    (s) => currentTime >= (s.start || 0) && currentTime <= (s.end || 0)
  );

  const activeText = activeSubtitle?.refined_text || activeSubtitle?.text || '';

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
            },
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

      {/* Subtitle Overlay: Appears when dialogue starts, and DISAPPEARS as soon as dialogue ends */}
      {activeText && !hasError && (
        <div className="absolute bottom-12 left-4 right-4 pointer-events-none flex justify-center z-10 transition-opacity duration-150 animate-in fade-in">
          <div className="max-w-[90%] px-4 py-2 rounded-xl bg-black/85 backdrop-blur-md border border-white/10 text-white text-center font-bold text-sm sm:text-base md:text-lg shadow-2xl drop-shadow-[0_2px_4px_rgba(0,0,0,0.9)] leading-snug">
            {activeText}
          </div>
        </div>
      )}
    </div>
  );
});

VideoPreview.displayName = 'VideoPreview';
export default VideoPreview;
