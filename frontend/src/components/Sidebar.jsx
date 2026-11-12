import React, { useState, useEffect } from 'react';
import {
  Film,
  PlusCircle,
  Languages,
  FolderCheck,
  Cpu,
  Sparkles,
  Database,
  Activity,
  Layers,
  Bell,
  BellRing,
  BellOff,
  Settings,
  BookOpen
} from 'lucide-react';
import {
  getNotificationPermission,
  requestNotificationPermission,
  notifyTaskCompleted,
  isNotificationEnabled,
  setNotificationEnabled
} from '../utils/notification';

export default function Sidebar({
  activeTab,
  onTabChange,
  completedCount = 0,
  isTranslating = false,
  studioQueue = null,
  translatorQueue = null,
  systemSettings = null
}) {
  const isStudioBusy = studioQueue?.isBusy || false;
  const studioWaiting = studioQueue?.waitingCount || 0;

  const isTransBusy = translatorQueue?.isBusy || isTranslating || false;
  const transWaiting = translatorQueue?.waitingCount || 0;

  const totalActive = (isStudioBusy ? 1 : 0) + (isTransBusy ? 1 : 0);
  const totalWaiting = studioWaiting + transWaiting;

  const [notifPermission, setNotifPermission] = useState(getNotificationPermission());
  const [isPushActive, setIsPushActive] = useState(isNotificationEnabled());

  useEffect(() => {
    setNotifPermission(getNotificationPermission());
    setIsPushActive(isNotificationEnabled());

    const handleSettingChange = (e) => {
      if (e.detail && typeof e.detail.enabled === 'boolean') {
        setIsPushActive(e.detail.enabled);
      }
    };
    window.addEventListener('transm_push_setting_changed', handleSettingChange);
    return () => {
      window.removeEventListener('transm_push_setting_changed', handleSettingChange);
    };
  }, []);

  const handleNotificationClick = async () => {
    if (notifPermission === 'denied') {
      alert('브라우저 주소창 좌측의 설정/자물쇠 아이콘을 눌러 "알림" 권한을 "허용"으로 변경해 주세요.');
      return;
    }

    // Toggle: If currently ON -> Turn OFF!
    if (isPushActive && notifPermission === 'granted') {
      setNotificationEnabled(false);
      setIsPushActive(false);
      return;
    }

    // If currently OFF -> Request browser permission if needed, then Turn ON!
    let perm = notifPermission;
    if (perm !== 'granted') {
      perm = await requestNotificationPermission();
      setNotifPermission(perm);
    }

    if (perm === 'granted' || perm === 'default') {
      setNotificationEnabled(true);
      setIsPushActive(true);
      // Send test notification with popup so user can immediately verify!
      notifyTaskCompleted('테스트_영상.mp4');
    }
  };

  return (
    <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col h-screen sticky top-0 z-40 flex-shrink-0 select-none">
      {/* Top Brand Logo */}
      <div
        className="p-5 flex items-center space-x-3 cursor-pointer border-b border-slate-800/80 hover:bg-slate-850/40 transition-colors"
        onClick={() => onTabChange && onTabChange('studio')}
        title="자막 제작 스튜디오로 이동"
      >
        <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-indigo-600 via-indigo-500 to-teal-400 flex items-center justify-center shadow-lg shadow-indigo-500/25 flex-shrink-0">
          <Film className="w-5 h-5 text-white" />
        </div>
        <div className="min-w-0">
          <span className="text-base font-bold bg-gradient-to-r from-white via-slate-100 to-indigo-300 bg-clip-text text-transparent block truncate">
            TransM Studio
          </span>
          <span className="text-[11px] text-slate-400 block -mt-0.5 truncate">
            AI 비디오 자동 자막 & 번역
          </span>
        </div>
      </div>

      {/* Main Navigation (Vertical List) */}
      <nav className="flex-1 px-3 py-6 space-y-1.5 overflow-y-auto">
        <div className="px-3 pb-2 text-[10px] font-bold uppercase tracking-wider text-slate-400">
          메인 메뉴
        </div>

        {/* 1. Subtitle Creation Studio */}
        <button
          type="button"
          onClick={() => onTabChange && onTabChange('studio')}
          className={`w-full flex items-center justify-between px-3.5 py-3 rounded-xl text-xs font-semibold transition-all ${
            activeTab === 'studio'
              ? 'bg-gradient-to-r from-indigo-600 to-indigo-500 text-white shadow-lg shadow-indigo-600/30'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/70'
          }`}
        >
          <div className="flex items-center space-x-3 min-w-0">
            <PlusCircle
              className={`w-4 h-4 flex-shrink-0 ${
                isStudioBusy
                  ? 'text-indigo-300 animate-spin'
                  : activeTab === 'studio'
                  ? 'text-white'
                  : 'text-indigo-400'
              }`}
            />
            <span className="truncate">자막 제작 스튜디오</span>
          </div>

          <div className="flex items-center space-x-1 flex-shrink-0">
            {isStudioBusy && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-indigo-400/20 text-indigo-300 border border-indigo-400/40 animate-pulse">
                작업중
              </span>
            )}
            {studioWaiting > 0 && (
              <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-purple-500/25 text-purple-300 border border-purple-500/30">
                대기 {studioWaiting}
              </span>
            )}
          </div>
        </button>

        {/* 2. Subtitle Translator */}
        <button
          type="button"
          onClick={() => onTabChange && onTabChange('translate')}
          className={`w-full flex items-center justify-between px-3.5 py-3 rounded-xl text-xs font-semibold transition-all ${
            activeTab === 'translate'
              ? 'bg-gradient-to-r from-indigo-600 to-indigo-500 text-white shadow-lg shadow-indigo-600/30'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/70'
          }`}
        >
          <div className="flex items-center space-x-3 min-w-0">
            <Languages
              className={`w-4 h-4 flex-shrink-0 ${
                isTransBusy
                  ? 'text-teal-300 animate-spin'
                  : activeTab === 'translate'
                  ? 'text-white'
                  : 'text-indigo-400'
              }`}
            />
            <span className="truncate">자막 번역기</span>
          </div>

          <div className="flex items-center space-x-1 flex-shrink-0">
            {isTransBusy && (
              <span className="px-2 py-0.5 rounded-full text-[10px] font-bold bg-teal-400/20 text-teal-300 border border-teal-400/40 animate-pulse">
                번역중
              </span>
            )}
            {transWaiting > 0 && (
              <span className="px-1.5 py-0.5 rounded-full text-[10px] font-bold bg-sky-500/25 text-sky-300 border border-sky-500/30">
                대기 {transWaiting}
              </span>
            )}
          </div>
        </button>

        {/* 3. Completed Tasks Archive */}
        <button
          type="button"
          onClick={() => onTabChange && onTabChange('completed')}
          className={`w-full flex items-center justify-between px-3.5 py-3 rounded-xl text-xs font-semibold transition-all ${
            activeTab === 'completed'
              ? 'bg-gradient-to-r from-indigo-600 to-indigo-500 text-white shadow-lg shadow-indigo-600/30'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/70'
          }`}
        >
          <div className="flex items-center space-x-3">
            <FolderCheck
              className={`w-4 h-4 flex-shrink-0 ${
                activeTab === 'completed' ? 'text-white' : 'text-emerald-400'
              }`}
            />
            <span>작업 완료 보관함</span>
          </div>
          {completedCount > 0 && (
            <span
              className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
                activeTab === 'completed'
                  ? 'bg-white/20 text-white'
                  : 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/30'
              }`}
            >
              {completedCount}
            </span>
          )}
        </button>

        {/* 4. Proper Noun Dictionary (고유명사 사전) */}
        <button
          type="button"
          onClick={() => onTabChange && onTabChange('dictionary')}
          className={`w-full flex items-center justify-between px-3.5 py-3 rounded-xl text-xs font-semibold transition-all ${
            activeTab === 'dictionary'
              ? 'bg-gradient-to-r from-indigo-600 to-indigo-500 text-white shadow-lg shadow-indigo-600/30'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/70'
          }`}
        >
          <div className="flex items-center space-x-3">
            <BookOpen
              className={`w-4 h-4 flex-shrink-0 ${
                activeTab === 'dictionary' ? 'text-white' : 'text-amber-400'
              }`}
            />
            <span>고유명사 사전</span>
          </div>
          <span
            className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
              activeTab === 'dictionary'
                ? 'bg-white/20 text-white'
                : 'bg-amber-500/20 text-amber-300 border border-amber-500/30'
            }`}
          >
            사전
          </span>
        </button>

        {/* 5. Admin & Engine Settings */}
        <button
          type="button"
          onClick={() => onTabChange && onTabChange('settings')}
          className={`w-full flex items-center justify-between px-3.5 py-3 rounded-xl text-xs font-semibold transition-all ${
            activeTab === 'settings'
              ? 'bg-gradient-to-r from-indigo-600 to-indigo-500 text-white shadow-lg shadow-indigo-600/30'
              : 'text-slate-400 hover:text-white hover:bg-slate-800/70'
          }`}
        >
          <div className="flex items-center space-x-3">
            <Settings
              className={`w-4 h-4 flex-shrink-0 ${
                activeTab === 'settings' ? 'text-white' : 'text-amber-400'
              }`}
            />
            <span>환경 설정 (관리자)</span>
          </div>
          <span
            className={`px-2 py-0.5 rounded-full text-[10px] font-bold ${
              activeTab === 'settings'
                ? 'bg-white/20 text-white'
                : 'bg-amber-500/15 text-amber-300 border border-amber-500/30'
            }`}
          >
            모델설정
          </span>
        </button>

        {/* Real-time Global Queue Status Widget */}
        {(totalActive > 0 || totalWaiting > 0) && (
          <div className="mt-4 p-3 rounded-xl bg-slate-950/80 border border-indigo-500/30 space-y-2">
            <div className="flex items-center justify-between text-[11px] font-bold text-indigo-300">
              <span className="flex items-center space-x-1.5">
                <Activity className="w-3.5 h-3.5 text-indigo-400 animate-pulse" />
                <span>실시간 대기열 현황</span>
              </span>
              <span className="font-mono text-[10px] px-1.5 py-0.2 bg-indigo-500/20 rounded">
                총 {totalActive + totalWaiting}건
              </span>
            </div>
            <div className="space-y-1 text-[10px] text-slate-400">
              <div className="flex justify-between items-center">
                <span>동영상 제작:</span>
                <span className={isStudioBusy ? 'text-indigo-300 font-semibold' : 'text-slate-500'}>
                  {isStudioBusy ? '분석 진행 중' : '대기 없음'}
                  {studioWaiting > 0 && ` (+${studioWaiting} 대기)`}
                </span>
              </div>
              <div className="flex justify-between items-center">
                <span>자막 번역:</span>
                <span className={isTransBusy ? 'text-teal-300 font-semibold' : 'text-slate-500'}>
                  {isTransBusy ? '번역 진행 중' : '대기 없음'}
                  {transWaiting > 0 && ` (+${transWaiting} 대기)`}
                </span>
              </div>
            </div>
          </div>
        )}
      </nav>

      {/* Bottom AI Status Cards & Notification Toggle */}
      <div className="p-4 border-t border-slate-800/80 space-y-3">
        {/* Web Push Notification Toggle */}
        <button
          type="button"
          onClick={handleNotificationClick}
          className={`w-full p-2.5 rounded-xl border text-[11px] font-semibold flex items-center justify-between transition-all shadow-sm ${
            notifPermission === 'denied'
              ? 'bg-slate-900 border-slate-800 text-slate-500 cursor-not-allowed'
              : isPushActive && notifPermission === 'granted'
              ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300 hover:bg-emerald-500/20'
              : 'bg-slate-800/80 hover:bg-slate-800 border-slate-700 text-slate-400 hover:text-slate-200'
          }`}
          title={
            notifPermission === 'denied'
              ? '브라우저 주소창 설정에서 알림 권한이 차단되어 있습니다'
              : isPushActive && notifPermission === 'granted'
              ? '웹 푸시 알림이 켜져 있습니다 (클릭 시 알림 끄기)'
              : '웹 푸시 알림이 꺼져 있습니다 (클릭 시 알림 켜기)'
          }
        >
          <div className="flex items-center space-x-2 truncate">
            {notifPermission === 'denied' ? (
              <BellOff className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />
            ) : isPushActive && notifPermission === 'granted' ? (
              <BellRing className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0 animate-pulse" />
            ) : (
              <BellOff className="w-3.5 h-3.5 text-slate-400 flex-shrink-0" />
            )}
            <span className="truncate">
              {notifPermission === 'denied'
                ? '웹 푸시 알림 차단됨'
                : isPushActive && notifPermission === 'granted'
                ? '웹 푸시 알림 켜짐'
                : '웹 푸시 알림 꺼짐'}
            </span>
          </div>
          <span
            className={`text-[10px] font-mono px-1.5 py-0.5 rounded ${
              notifPermission === 'denied'
                ? 'bg-slate-800 text-slate-500'
                : isPushActive && notifPermission === 'granted'
                ? 'bg-emerald-500/20 text-emerald-300'
                : 'bg-slate-700 text-slate-300 font-bold'
            }`}
          >
            {notifPermission === 'denied'
              ? '차단'
              : isPushActive && notifPermission === 'granted'
              ? 'ON'
              : 'OFF'}
          </span>
        </button>

        <div
          onClick={() => onTabChange && onTabChange('settings')}
          className="p-3 bg-slate-950/70 hover:bg-slate-950 border border-slate-800 hover:border-indigo-500/40 rounded-xl space-y-2 text-xs cursor-pointer transition"
          title="클릭하여 AI 엔진 및 모델 설정 변경"
        >
          <div className="flex items-center justify-between text-slate-400 text-[11px]">
            <span className="flex items-center space-x-1.5">
              <Cpu className="w-3.5 h-3.5 text-emerald-400" />
              <span>Whisper STT</span>
            </span>
            <span className="font-mono text-slate-200 font-semibold truncate max-w-[110px]">
              {systemSettings?.whisper_model_size || 'large-v3-turbo'}
            </span>
          </div>
          <div className="flex items-center justify-between text-slate-400 text-[11px]">
            <span className="flex items-center space-x-1.5">
              <Sparkles className="w-3.5 h-3.5 text-purple-400" />
              <span>LLM 모델</span>
            </span>
            <span className="font-mono text-indigo-300 font-semibold truncate max-w-[110px]">
              {systemSettings?.ollama_model || 'qwen2.5:14b'}
            </span>
          </div>
          <div className="flex items-center justify-between text-slate-400 text-[11px]">
            <span className="flex items-center space-x-1.5">
              <Database className="w-3.5 h-3.5 text-teal-400" />
              <span>영구 저장소</span>
            </span>
            <span className="font-mono text-emerald-400 font-medium">PostgreSQL</span>
          </div>
        </div>

        <div className="flex items-center space-x-2 text-[11px] text-slate-400 px-1">
          <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
          <span>모든 AI 시스템 정상 가동</span>
        </div>
      </div>
    </aside>
  );
}
