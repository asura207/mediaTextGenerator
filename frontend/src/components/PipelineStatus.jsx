import React, { useState, useEffect } from 'react';
import { Loader2, CheckCircle2, Music, Mic, Sparkles, FileText, AlertTriangle, Clock, Zap } from 'lucide-react';

const STAGES = [
  { id: 1, label: '오디오 추출', desc: 'moviepy/ffmpeg 오디오 분리', icon: Music, minProgress: 25, estTime: '약 30초~1분' },
  { id: 2, label: '음성 인식(STT)', desc: 'faster-whisper 정밀 타임스탬프 추출', icon: Mic, minProgress: 50, estTime: '약 2~4분 (CUDA 가속)' },
  { id: 3, label: 'LLM 문맥 교정 & 번역', desc: '로컬 Ollama 대화체 의역 & 문맥 정제', icon: Sparkles, minProgress: 75, estTime: '분량별 약 3~8분' },
  { id: 4, label: 'SRT 자막 생성', desc: '표준 pysrt 자막 파일 패키징', icon: FileText, minProgress: 100, estTime: '약 5초' },
];

export default function PipelineStatus({ task }) {
  if (!task) return null;

  const { status, stage, progress, error } = task;
  const isFailed = status === 'FAILED';
  const isCompleted = status === 'COMPLETED';

  // Elapsed timer
  const [elapsedSeconds, setElapsedSeconds] = useState(0);

  useEffect(() => {
    let interval = null;
    if (!isCompleted && !isFailed) {
      interval = setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [isCompleted, isFailed]);

  const formatElapsed = (sec) => {
    const mins = Math.floor(sec / 60);
    const secs = sec % 60;
    return `${mins > 0 ? mins + '분 ' : ''}${secs}초`;
  };

  const getEstimatedRemaining = () => {
    if (progress >= 95) return '마무리 중 (약 30초 이내)';
    if (progress >= 75) return '약 2~4분 남음 (자막 정리 중)';
    if (progress >= 50) return '약 3~6분 남음 (LLM 문맥 교정 & 번역 중)';
    if (progress >= 25) return '약 5~8분 남음 (CUDA 음성인식 중)';
    return '약 10~15분 예상';
  };

  return (
    <div className="w-full max-w-3xl mx-auto my-6 p-6 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="text-base font-semibold text-slate-100 flex items-center space-x-2">
            {!isCompleted && !isFailed && <Loader2 className="w-4 h-4 text-indigo-400 animate-spin" />}
            {isCompleted && <CheckCircle2 className="w-4 h-4 text-emerald-400" />}
            {isFailed && <AlertTriangle className="w-4 h-4 text-rose-400" />}
            <span>동영상 자막 파이프라인 진행 상태</span>
          </h3>
          <p className="text-xs text-slate-400 mt-0.5">{stage}</p>
        </div>
        <span className="text-xl font-extrabold text-indigo-400 font-mono">{progress}%</span>
      </div>

      {/* Main Progress Bar */}
      <div className="w-full bg-slate-800 rounded-full h-2.5 mb-5 overflow-hidden border border-slate-700/60 p-0.5">
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            isFailed ? 'bg-rose-500' : isCompleted ? 'bg-emerald-500' : 'bg-gradient-to-r from-indigo-500 via-purple-500 to-teal-400'
          }`}
          style={{ width: `${progress}%` }}
        />
      </div>

      {/* Real-time ETA Cards */}
      {!isCompleted && !isFailed && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2.5 mb-5">
          <div className="p-3 rounded-xl bg-slate-950/70 border border-amber-500/30 space-y-0.5">
            <span className="text-[11px] text-amber-400 font-medium flex items-center space-x-1">
              <Clock className="w-3.5 h-3.5 text-amber-400" />
              <span>예상 남은 시간</span>
            </span>
            <p className="text-xs font-bold text-amber-300">
              {getEstimatedRemaining()}
            </p>
          </div>

          <div className="p-3 rounded-xl bg-slate-950/70 border border-indigo-500/30 space-y-0.5">
            <span className="text-[11px] text-indigo-400 font-medium flex items-center space-x-1">
              <Clock className="w-3.5 h-3.5 text-indigo-400" />
              <span>진행 경과 시간</span>
            </span>
            <p className="text-xs font-bold text-slate-200 font-mono">
              {formatElapsed(elapsedSeconds)}
            </p>
          </div>

          <div className="col-span-2 sm:col-span-1 p-3 rounded-xl bg-slate-950/70 border border-teal-500/30 space-y-0.5">
            <span className="text-[11px] text-teal-400 font-medium flex items-center space-x-1">
              <Zap className="w-3.5 h-3.5 text-teal-400" />
              <span>가속 모드</span>
            </span>
            <p className="text-xs font-semibold text-teal-300 truncate">
              CUDA GPU (float16)
            </p>
          </div>
        </div>
      )}

      {/* Pipeline Steps Grid */}
      <div className="grid grid-cols-1 sm:grid-cols-4 gap-3">
        {STAGES.map((s) => {
          const Icon = s.icon;
          const isDone = progress >= s.minProgress;
          const isCurrent = !isDone && progress >= s.minProgress - 25;

          return (
            <div
              key={s.id}
              className={`p-3 rounded-xl border transition-all ${
                isDone
                  ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                  : isCurrent
                  ? 'bg-indigo-500/15 border-indigo-500/50 text-indigo-300 shadow-sm'
                  : 'bg-slate-950/40 border-slate-800 text-slate-500'
              }`}
            >
              <div className="flex items-center space-x-2 mb-1">
                <Icon className={`w-4 h-4 ${isDone ? 'text-emerald-400' : isCurrent ? 'text-indigo-400' : 'text-slate-500'}`} />
                <span className="text-xs font-semibold">{s.label}</span>
              </div>
              <p className="text-[10px] text-slate-400 line-clamp-1">{s.desc}</p>
              <span className="text-[9px] text-slate-500 mt-1 block font-mono">{s.estTime}</span>
            </div>
          );
        })}
      </div>

      {/* Error Message */}
      {isFailed && error && (
        <div className="mt-4 p-3 bg-rose-500/10 border border-rose-500/30 rounded-xl text-xs text-rose-400">
          <p className="font-semibold mb-1">오류 세부 내용:</p>
          <p className="font-mono">{error}</p>
        </div>
      )}
    </div>
  );
}

