import React, { useState, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import Sidebar from './components/Sidebar';
import VideoUploader from './components/VideoUploader';
import CompletedList from './components/CompletedList';
import SubtitleTranslator from './components/SubtitleTranslator';
import AdminSettings from './components/AdminSettings';
import ProperNounDictionary from './components/ProperNounDictionary';
import { getCompletedTasks, getSystemSettings } from './api/client';
import { useStudioQueue } from './hooks/useStudioQueue';
import { useTranslatorQueue } from './hooks/useTranslatorQueue';
import { notifyTaskCompleted } from './utils/notification';
import { CheckCircle2, BellRing, X, ExternalLink } from 'lucide-react';

export default function App() {
  const [activeTab, setActiveTab] = useState('studio'); // 'studio' | 'translate' | 'completed' | 'settings'
  const [translateTargetTaskId, setTranslateTargetTaskId] = useState(null);
  const [recentlyCompletedNotice, setRecentlyCompletedNotice] = useState(null);
  const [toastNotice, setToastNotice] = useState(null);
  const [systemSettings, setSystemSettings] = useState({
    ollama_model: 'qwen2.5:14b',
    whisper_model_size: 'large-v3-turbo',
    whisper_device: 'cuda',
    whisper_compute_type: 'float16',
    llm_batch_size: 10
  });

  useEffect(() => {
    getSystemSettings()
      .then((res) => {
        if (res?.current) {
          setSystemSettings(res.current);
        }
      })
      .catch(() => {});
  }, []);

  // Listen to global transm_task_completed events for instant floating toast popups
  useEffect(() => {
    let timer = null;
    const handleTaskCompleted = (e) => {
      if (e.detail) {
        setToastNotice(e.detail);
        if (timer) clearTimeout(timer);
        timer = setTimeout(() => {
          setToastNotice(null);
        }, 8000); // Auto-dismiss after 8 seconds
      }
    };
    window.addEventListener('transm_task_completed', handleTaskCompleted);
    return () => {
      window.removeEventListener('transm_task_completed', handleTaskCompleted);
      if (timer) clearTimeout(timer);
    };
  }, []);

  // Query completed tasks count for sidebar badge and table view
  const { data: completedTasks, refetch: refetchCompleted } = useQuery({
    queryKey: ['completed-tasks'],
    queryFn: getCompletedTasks,
    refetchInterval: 5000,
  });

  // Studio Multi-file sequential queue with deferred video upload
  const studioQueue = useStudioQueue({
    onTaskCompleted: (statusData) => {
      refetchCompleted();
      const fn = statusData.filename || '동영상';
      setRecentlyCompletedNotice({
        taskId: statusData.task_id,
        filename: fn,
        subtitleCount: statusData.subtitles?.length || 0,
      });
      // Web Push notification: [동영상 제목] + " 자막이 생성되었습니다"
      notifyTaskCompleted(fn, () => {
        setActiveTab('completed');
      });
    }
  });

  // Translator Multi-file sequential queue
  const translatorQueue = useTranslatorQueue({
    onTaskCompleted: (statusData) => {
      refetchCompleted();
      const fn = statusData?.filename || '자막 번역';
      notifyTaskCompleted(fn, () => {
        setActiveTab('completed');
      });
    }
  });

  return (
    <div className="min-h-screen flex bg-slate-950 text-slate-100 font-sans relative">
      {/* 0. Floating Real-Time Web Push Toast Notification */}
      {toastNotice && (
        <div className="fixed top-6 right-6 z-50 max-w-sm w-full bg-slate-900/95 backdrop-blur-md border border-emerald-500/40 text-slate-100 rounded-2xl p-4 shadow-2xl shadow-emerald-950/40 animate-in slide-in-from-top-4 fade-in duration-300">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-start space-x-3">
              <div className="w-9 h-9 rounded-xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0 mt-0.5 border border-emerald-500/30">
                <BellRing className="w-5 h-5 animate-pulse" />
              </div>
              <div className="space-y-1">
                <div className="flex items-center space-x-1.5">
                  <span className="text-[11px] font-bold uppercase tracking-wider text-emerald-400">
                    작업 완료 알림
                  </span>
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-ping" />
                </div>
                <h4 className="font-bold text-sm text-white line-clamp-1">
                  {toastNotice.filename || toastNotice.title}
                </h4>
                <p className="text-xs text-slate-300 font-medium">
                  {toastNotice.message || `${toastNotice.filename} 자막이 생성되었습니다`}
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setToastNotice(null)}
              className="text-slate-400 hover:text-white p-1 rounded-lg hover:bg-slate-800 transition"
              title="닫기"
            >
              <X className="w-4 h-4" />
            </button>
          </div>
          <div className="mt-3 pt-2.5 border-t border-slate-800/80 flex justify-end space-x-2">
            <button
              type="button"
              onClick={() => {
                if (typeof toastNotice.onClick === 'function') {
                  toastNotice.onClick();
                } else {
                  setActiveTab('completed');
                }
                setToastNotice(null);
              }}
              className="px-3 py-1.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-xs font-semibold flex items-center space-x-1.5 transition shadow-sm"
            >
              <span>작업 완료 보관함 보기</span>
              <ExternalLink className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* 1. Left Vertical Sidebar Navigation */}
      <Sidebar
        activeTab={activeTab}
        onTabChange={(tab) => {
          setActiveTab(tab);
        }}
        completedCount={completedTasks?.length || 0}
        studioQueue={studioQueue}
        translatorQueue={translatorQueue}
        systemSettings={systemSettings}
      />

      {/* 2. Main Content Viewport */}
      <div className="flex-1 flex flex-col min-w-0 min-h-screen overflow-x-hidden">
        <main className="flex-1 max-w-6xl w-full mx-auto px-4 sm:px-8 py-8">
          {/* TAB 1: Completed Tasks Archive (List & Interactive Detail View) */}
          {activeTab === 'completed' && (
            <CompletedList
              onNewTask={() => setActiveTab('studio')}
              onTranslateTask={(tid) => {
                setTranslateTargetTaskId(tid);
                const chosen = completedTasks?.find((t) => t.task_id === tid);
                translatorQueue.addExistingTask(tid, chosen?.filename, 'ko');
                setActiveTab('translate');
              }}
            />
          )}

          {/* TAB 2: Subtitle Translator (Language Auto-detection & Ollama Translation) */}
          {activeTab === 'translate' && (
            <SubtitleTranslator
              initialTaskId={translateTargetTaskId}
              translatorQueue={translatorQueue}
              onOpenInStudio={() => {
                setActiveTab('completed');
              }}
            />
          )}

          {/* TAB 4: Admin & System Engine Settings */}
          {activeTab === 'settings' && (
            <AdminSettings
              onSettingsUpdated={(newSettings) => {
                setSystemSettings(newSettings);
              }}
            />
          )}

          {/* TAB 5: Proper Noun Dictionary (고유명사 사전) */}
          {activeTab === 'dictionary' && (
            <ProperNounDictionary />
          )}

          {/* TAB 3: Subtitle Creation Studio (Queue Dashboard & Deferred Upload) */}
          {activeTab === 'studio' && (
            <div className="space-y-6">
              {/* Recently completed friendly notification banner */}
              {recentlyCompletedNotice && !studioQueue.isBusy && (
                <div className="p-4 rounded-2xl bg-emerald-950/40 border border-emerald-500/30 flex items-center justify-between gap-3 text-xs shadow-lg backdrop-blur animate-in fade-in">
                  <div className="flex items-center space-x-3">
                    <div className="w-8 h-8 rounded-xl bg-emerald-500/20 text-emerald-400 flex items-center justify-center flex-shrink-0">
                      <CheckCircle2 className="w-4 h-4" />
                    </div>
                    <span className="text-slate-200">
                      <strong>{recentlyCompletedNotice.filename}</strong> ({recentlyCompletedNotice.subtitleCount}개 자막) 자막 생성이 완료되어 <strong>[작업 완료 보관함]</strong>에 안전하게 저장되었습니다.
                    </span>
                  </div>
                  <div className="flex items-center space-x-2 flex-shrink-0">
                    <button
                      type="button"
                      onClick={() => setActiveTab('completed')}
                      className="px-3.5 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-semibold transition-all shadow-md"
                    >
                      보관함에서 확인하기
                    </button>
                    <button
                      type="button"
                      onClick={() => setRecentlyCompletedNotice(null)}
                      className="px-2.5 py-1 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition"
                      title="닫기"
                    >
                      ✕
                    </button>
                  </div>
                </div>
              )}

              <div className="py-6">
                <div className="text-center max-w-2xl mx-auto mb-8 space-y-3">
                  <h1 className="text-3xl sm:text-4xl font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-100 to-indigo-300 bg-clip-text text-transparent">
                    동영상 음성을 감지하여 고품질 SRT 자막으로 변환
                  </h1>
                  <p className="text-slate-400 text-sm leading-relaxed">
                    faster-whisper ({systemSettings?.whisper_model_size || 'large-v3-turbo'})의 정밀 타임스탬프 추출과 로컬 Ollama ({systemSettings?.ollama_model || 'qwen2.5:14b'})의 지능형 구어체 교정을 결합하여
                    자연스러운 자막을 생성합니다.
                  </p>
                </div>
                <VideoUploader
                  queue={studioQueue.queue}
                  activeItem={studioQueue.activeItem}
                  waitingCount={studioQueue.waitingCount}
                  isBusy={studioQueue.isBusy}
                  isLoadingQueue={studioQueue.isLoadingQueue}
                  onAddVideos={studioQueue.addVideos}
                  onAddServerFolder={studioQueue.addServerFolder}
                  onRemoveItem={studioQueue.removeQueueItem}
                  onClearCompleted={studioQueue.clearCompleted}
                  onViewCompleted={() => setActiveTab('completed')}
                />
              </div>
            </div>
          )}
        </main>

        {/* Footer */}
        <footer className="border-t border-slate-900 py-6 text-center text-xs text-slate-500">
          TransM Studio • Powered by faster-whisper ({systemSettings?.whisper_model_size || 'large-v3-turbo'}), moviepy, pysrt & Ollama ({systemSettings?.ollama_model || 'qwen2.5:14b'})
        </footer>
      </div>
    </div>
  );
}
