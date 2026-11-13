import React, { useState, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  Globe,
  Languages,
  UploadCloud,
  FileText,
  CheckCircle2,
  ArrowRight,
  Download,
  RefreshCw,
  Sparkles,
  AlertCircle,
  Film,
  Check,
  Eye,
  ChevronDown,
  Clock,
  Hourglass,
  Zap,
  Trash2,
  PlusCircle,
  Layers,
  ListOrdered
} from 'lucide-react';
import {
  detectLanguage,
  getCompletedTasks,
  downloadSrtFile
} from '../api/client';

const TARGET_LANGUAGES = [
  { code: 'ko', name: '한국어 (Korean)', flag: '🇰🇷' },
  { code: 'en', name: '영어 (English)', flag: '🇺🇸' },
  { code: 'ja', name: '일본어 (Japanese)', flag: '🇯🇵' },
  { code: 'zh', name: '중국어 (Chinese)', flag: '🇨🇳' },
  { code: 'es', name: '스페인어 (Spanish)', flag: '🇪🇸' },
  { code: 'fr', name: '프랑스어 (French)', flag: '🇫🇷' },
  { code: 'de', name: '독일어 (German)', flag: '🇩🇪' },
  { code: 'it', name: '이탈리아어 (Italian)', flag: '🇮🇹' },
  { code: 'pt', name: '포르투갈어 (Portuguese)', flag: '🇵🇹' },
  { code: 'ru', name: '러시아어 (Russian)', flag: '🇷🇺' },
  { code: 'vi', name: '베트남어 (Vietnamese)', flag: '🇻🇳' },
  { code: 'th', name: '태국어 (Thai)', flag: '🇹🇭' },
  { code: 'id', name: '인도네시아어 (Indonesian)', flag: '🇮🇩' },
  { code: 'ar', name: '아랍어 (Arabic)', flag: '🇸🇦' },
  { code: 'hi', name: '힌디어 (Hindi)', flag: '🇮🇳' },
  { code: 'tr', name: '튀르키예어 (Turkish)', flag: '🇹🇷' },
  { code: 'nl', name: '네덜란드어 (Dutch)', flag: '🇳🇱' },
  { code: 'pl', name: '폴란드어 (Polish)', flag: '🇵🇱' },
  { code: 'uk', name: '우크라이나어 (Ukrainian)', flag: '🇺🇦' },
  { code: 'el', name: '그리스어 (Greek)', flag: '🇬🇷' },
];

export default function SubtitleTranslator({ initialTaskId, onOpenInStudio, translatorQueue }) {
  const [sourceMode, setSourceMode] = useState('upload'); // 'upload' | 'existing'
  const [selectedTaskId, setSelectedTaskId] = useState(initialTaskId || '');
  const [selectedFiles, setSelectedFiles] = useState([]);
  const [isDragging, setIsDragging] = useState(false);
  const fileInputRef = useRef(null);
  const appendInputRef = useRef(null);

  // Target language state (Default: Korean)
  const [targetLang, setTargetLang] = useState('ko');

  // Detection state
  const [detecting, setDetecting] = useState(false);
  const [detectionResult, setDetectionResult] = useState(null);
  const [detectError, setDetectError] = useState(null);

  // Fetch completed tasks from PostgreSQL
  const { data: completedTasks, isLoading: loadingTasks } = useQuery({
    queryKey: ['completed-tasks'],
    queryFn: getCompletedTasks,
  });

  // Automatically select initialTaskId or latest completed task
  useEffect(() => {
    if (initialTaskId) {
      setSelectedTaskId(initialTaskId);
      setSourceMode('existing');
    } else if (completedTasks && completedTasks.length > 0 && !selectedTaskId && selectedFiles.length === 0) {
      setSelectedTaskId(completedTasks[0].task_id);
    }
  }, [initialTaskId, completedTasks]);

  // Run language detection for the first selected file or existing task
  useEffect(() => {
    let active = true;

    async function runDetection() {
      const fileToDetect = selectedFiles.length > 0 ? selectedFiles[0] : null;
      if (sourceMode === 'existing' && !selectedTaskId) {
        setDetectionResult(null);
        return;
      }
      if (sourceMode === 'upload' && !fileToDetect) {
        setDetectionResult(null);
        return;
      }

      setDetecting(true);
      setDetectError(null);

      try {
        const res = await detectLanguage({
          file: sourceMode === 'upload' ? fileToDetect : null,
          taskId: sourceMode === 'existing' ? selectedTaskId : null,
        });
        if (active) {
          setDetectionResult(res);
        }
      } catch (err) {
        if (active) {
          const msg = err.response?.data?.detail || err.message || '언어 감지 실패';
          setDetectError(msg);
          setDetectionResult(null);
        }
      } finally {
        if (active) setDetecting(false);
      }
    }

    runDetection();
    return () => {
      active = false;
    };
  }, [sourceMode, selectedTaskId, selectedFiles]);

  // File selection handling (Max 10 files)
  const handleFiles = (fileList) => {
    const rawFiles = Array.from(fileList || []);
    if (rawFiles.length === 0) return;

    let srtFiles = rawFiles.filter((f) => f.name.toLowerCase().endsWith('.srt'));
    if (srtFiles.length === 0) {
      alert('.srt 자막 파일만 선택할 수 있습니다.');
      return;
    }

    if (srtFiles.length > 10) {
      alert(`한 번에 최대 10개 파일까지 선택할 수 있습니다. 상위 10개 파일이 등록됩니다.`);
      srtFiles = srtFiles.slice(0, 10);
    }

    setSelectedFiles(srtFiles);
    setSourceMode('upload');
  };

  const handleDragOver = (e) => {
    e.preventDefault();
    setIsDragging(true);
  };
  const handleDragLeave = () => setIsDragging(false);
  const handleDrop = (e) => {
    e.preventDefault();
    setIsDragging(false);
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleFiles(e.dataTransfer.files);
    }
  };

  const handleFileChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleFiles(e.target.files);
    }
  };

  // Add files to translatorQueue
  const handleEnqueue = () => {
    if (!translatorQueue) return;

    if (sourceMode === 'upload') {
      if (selectedFiles.length === 0) {
        alert('번역할 SRT 자막 파일을 1개 이상 선택해주세요 (최대 10개).');
        return;
      }
      const res = translatorQueue.addSrtFiles(selectedFiles, targetLang);
      if (res.warning) {
        alert(res.warning);
      }
      setSelectedFiles([]);
      setDetectionResult(null);
    } else {
      if (!selectedTaskId) {
        alert('번역할 완료 작업을 선택해주세요.');
        return;
      }
      const chosen = completedTasks?.find((t) => t.task_id === selectedTaskId);
      const name = chosen?.filename || '영상 자막';
      translatorQueue.addExistingTask(selectedTaskId, name, targetLang);
      setDetectionResult(null);
    }
  };

  // Dynamic append files to existing queue
  const handleAppendFiles = (e) => {
    if (!translatorQueue) return;
    if (e.target.files && e.target.files.length > 0) {
      const res = translatorQueue.addSrtFiles(e.target.files, targetLang);
      if (res.warning) {
        alert(res.warning);
      }
    }
  };

  const activeItem = translatorQueue?.activeItem;
  const waitingItems = translatorQueue?.waitingItems || [];
  const completedItems = translatorQueue?.completedItems || [];
  const hasQueue = (translatorQueue?.queue?.length || 0) > 0;

  // Active item progress & ETA calculation
  const taskData = activeItem?.taskData;
  const stage = taskData?.stage || (activeItem?.status === 'STARTING' ? '번역 파이프라인 초기화 중...' : '번역 준비 중...');
  const progress = taskData?.progress || (activeItem?.status === 'STARTING' ? 5 : 10);

  const batchMatch = stage.match(/(\d+)\s*\/\s*(\d+)/);
  const currentBatch = batchMatch ? parseInt(batchMatch[1], 10) : null;
  const totalBatches = batchMatch ? parseInt(batchMatch[2], 10) : null;

  const calculateEta = () => {
    if (!currentBatch || !totalBatches || currentBatch <= 0) {
      return '계산 중...';
    }
    const remainingBatches = Math.max(0, totalBatches - currentBatch);
    if (remainingBatches === 0) return '마무리 중...';
    const estSec = remainingBatches * 22;
    const mins = Math.floor(estSec / 60);
    const secs = estSec % 60;
    if (mins > 0) return `약 ${mins}분 ${secs > 0 ? secs + '초' : ''} 남음`;
    return `약 ${secs}초 남음`;
  };

  const handleDownload = async (taskId, filename) => {
    try {
      await downloadSrtFile(taskId, filename || 'subtitles_ko.srt');
    } catch (err) {
      alert('SRT 파일 다운로드 중 오류가 발생했습니다.');
    }
  };

  return (
    <div className="max-w-5xl mx-auto py-6 space-y-8">
      {/* Header Banner */}
      <div className="text-center max-w-2xl mx-auto space-y-3">
        <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full bg-indigo-500/10 border border-indigo-500/20 text-indigo-400 text-xs font-semibold">
          <Languages className="w-3.5 h-3.5" />
          <span>다국어 AI 자막 일괄 번역기</span>
        </div>
        <h1 className="text-3xl font-extrabold tracking-tight bg-gradient-to-r from-white via-slate-100 to-indigo-300 bg-clip-text text-transparent">
          SRT 언어 자동 감지 및 스마트 번역
        </h1>
        <p className="text-slate-400 text-sm leading-relaxed">
          한 번에 최대 <strong className="text-indigo-300 font-semibold">10개</strong>의 SRT 자막 파일을 등록하여 순차적으로 자동 번역할 수 있습니다.
          작업이 진행 중인 동안에도 추가 파일을 언제든지 대기열에 등록할 수 있습니다.
        </p>
      </div>

      {/* Active & Waiting Queue Dashboard (If Queue Has Items) */}
      {hasQueue && (
        <div className="space-y-6">
          {/* Active Translating Task Card */}
          {activeItem && (
            <div className="p-6 rounded-2xl bg-slate-900 border border-indigo-500/40 shadow-2xl backdrop-blur space-y-5 animate-in fade-in">
              <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
                <div className="flex items-center space-x-3.5">
                  <div className="w-11 h-11 rounded-2xl bg-indigo-600/20 border border-indigo-500/30 flex items-center justify-center text-indigo-400 flex-shrink-0">
                    <RefreshCw className="w-5 h-5 animate-spin text-indigo-400" />
                  </div>
                  <div>
                    <div className="flex items-center space-x-2 flex-wrap">
                      <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 animate-pulse">
                        현재 번역 중
                      </span>
                      <h3 className="text-base font-bold text-white truncate max-w-md">
                        {activeItem.filename}
                      </h3>
                    </div>
                    <p className="text-xs text-slate-400 mt-0.5">
                      목표 언어: <strong className="text-indigo-300">{TARGET_LANGUAGES.find((l) => l.code === activeItem.targetLang)?.name || activeItem.targetLang}</strong> • {stage}
                    </p>
                  </div>
                </div>

                <div className="flex items-center space-x-2 self-end sm:self-center">
                  <input
                    ref={appendInputRef}
                    type="file"
                    accept=".srt"
                    multiple
                    onChange={handleAppendFiles}
                    className="hidden"
                  />
                  <button
                    type="button"
                    onClick={() => appendInputRef.current?.click()}
                    className="flex items-center space-x-1.5 px-3 py-1.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition-all shadow-sm"
                  >
                    <PlusCircle className="w-3.5 h-3.5 text-indigo-400" />
                    <span>추가 자막 등록 (최대 10개)</span>
                  </button>
                </div>
              </div>

              {/* Progress Bar */}
              <div className="space-y-1.5">
                <div className="flex justify-between text-xs font-semibold">
                  <span className="text-indigo-300">{stage}</span>
                  <span className="text-white font-mono">{progress}%</span>
                </div>
                <div className="w-full h-2.5 bg-slate-800 rounded-full overflow-hidden p-0.5 border border-slate-700">
                  <div
                    className="h-full bg-gradient-to-r from-indigo-500 via-purple-500 to-emerald-400 rounded-full transition-all duration-300"
                    style={{ width: `${Math.max(progress, 5)}%` }}
                  />
                </div>
              </div>

              {/* Status & ETA Cards */}
              <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
                <div className="p-3 rounded-xl bg-slate-950/80 border border-amber-500/30 space-y-0.5">
                  <span className="text-[11px] text-amber-400 font-medium flex items-center space-x-1">
                    <Clock className="w-3 h-3 text-amber-400" />
                    <span>예상 남은 시간</span>
                  </span>
                  <p className="text-sm font-bold text-amber-300">
                    {calculateEta()}
                  </p>
                </div>

                <div className="p-3 rounded-xl bg-slate-950/80 border border-indigo-500/30 space-y-0.5">
                  <span className="text-[11px] text-indigo-400 font-medium flex items-center space-x-1">
                    <Hourglass className="w-3 h-3 text-indigo-400" />
                    <span>번역 진행 배치</span>
                  </span>
                  <p className="text-sm font-bold text-slate-100">
                    {currentBatch && totalBatches ? `${currentBatch} / ${totalBatches} 배치` : '배치 준비 중'}
                  </p>
                </div>

                <div className="col-span-2 sm:col-span-1 p-3 rounded-xl bg-slate-950/80 border border-teal-500/30 space-y-0.5">
                  <span className="text-[11px] text-teal-400 font-medium flex items-center space-x-1">
                    <Zap className="w-3 h-3 text-teal-400" />
                    <span>대기 중인 자막</span>
                  </span>
                  <p className="text-sm font-bold text-teal-300">
                    {waitingItems.length}건 대기 중
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Waiting Queue List */}
          {waitingItems.length > 0 && (
            <div className="p-5 rounded-2xl bg-slate-900 border border-slate-800 space-y-3 shadow-xl">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2">
                  <ListOrdered className="w-4 h-4 text-indigo-400" />
                  <h4 className="text-sm font-bold text-slate-200">
                    번역 대기열 ({waitingItems.length}건)
                  </h4>
                </div>
                <span className="text-[11px] text-slate-400">
                  현재 번역이 완료되면 자동으로 다음 자막 번역을 시작합니다.
                </span>
              </div>

              <div className="space-y-2">
                {waitingItems.map((item, idx) => (
                  <div
                    key={item.id}
                    className="flex items-center justify-between p-3 rounded-xl bg-slate-950/60 border border-slate-800/80 hover:border-slate-700 transition-all text-xs"
                  >
                    <div className="flex items-center space-x-3 min-w-0">
                      <span className="w-6 h-6 rounded-lg bg-slate-800 text-slate-300 font-mono font-bold flex items-center justify-center text-xs flex-shrink-0">
                        #{idx + 1}
                      </span>
                      <FileText className="w-4 h-4 text-slate-400 flex-shrink-0" />
                      <div className="truncate">
                        <p className="font-semibold text-slate-200 truncate">{item.filename}</p>
                        <p className="text-[11px] text-slate-500">
                          목표 언어: {TARGET_LANGUAGES.find((l) => l.code === item.targetLang)?.name || item.targetLang}
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center space-x-2 flex-shrink-0">
                      <span className="px-2 py-0.5 rounded-full bg-amber-500/10 text-amber-300 border border-amber-500/20 text-[10px] font-semibold">
                        대기 중
                      </span>
                      <button
                        type="button"
                        onClick={() => translatorQueue.removeQueueItem(item.id)}
                        className="p-1 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition"
                        title="대기열에서 제거"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Completed Items in Current Session */}
          {completedItems.length > 0 && (
            <div className="p-5 rounded-2xl bg-emerald-950/20 border border-emerald-500/30 space-y-3 shadow-xl">
              <div className="flex items-center justify-between">
                <div className="flex items-center space-x-2 text-emerald-400">
                  <CheckCircle2 className="w-4 h-4" />
                  <h4 className="text-sm font-bold text-emerald-300">
                    번역 완료된 자막 ({completedItems.length}건)
                  </h4>
                </div>
                <button
                  type="button"
                  onClick={() => translatorQueue.clearCompleted()}
                  className="text-[11px] text-slate-400 hover:text-white transition"
                >
                  완료 항목 비우기
                </button>
              </div>

              <div className="space-y-2">
                {completedItems.map((item) => (
                  <div
                    key={item.id}
                    className="flex items-center justify-between p-3 rounded-xl bg-slate-900/80 border border-emerald-500/30 text-xs"
                  >
                    <div className="flex items-center space-x-3 min-w-0">
                      <Check className="w-4 h-4 text-emerald-400 flex-shrink-0" />
                      <div className="truncate">
                        <p className="font-semibold text-slate-200 truncate">{item.filename}</p>
                        <p className="text-[11px] text-emerald-400/80">
                          번역 완료 • PostgreSQL 보관 완료
                        </p>
                      </div>
                    </div>

                    <div className="flex items-center space-x-2 flex-shrink-0">
                      {item.taskId && (
                        <button
                          type="button"
                          onClick={() => handleDownload(item.taskId, item.taskData?.filename || item.filename)}
                          className="flex items-center space-x-1 px-3 py-1.5 rounded-xl bg-emerald-600 hover:bg-emerald-500 text-white font-semibold text-xs transition shadow-sm"
                        >
                          <Download className="w-3.5 h-3.5" />
                          <span>SRT 다운로드</span>
                        </button>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Main Translation Registration Card */}
      <div className="bg-slate-900/80 border border-slate-800 rounded-2xl shadow-xl backdrop-blur overflow-hidden divide-y divide-slate-800">
        {/* Step 1: Source Selection Mode */}
        <div className="p-6 space-y-4">
          <div className="flex items-center justify-between">
            <span className="text-xs font-bold tracking-wider text-indigo-400 uppercase flex items-center space-x-2">
              <span className="w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-300 flex items-center justify-center text-[11px] font-bold">1</span>
              <span>번역할 자막 파일 등록 (최대 10개)</span>
            </span>

            {/* Mode Toggle Buttons */}
            <div className="flex items-center space-x-1 p-1 bg-slate-950/60 border border-slate-800 rounded-xl text-xs">
              <button
                type="button"
                onClick={() => setSourceMode('upload')}
                className={`px-3 py-1.5 rounded-lg transition-all ${
                  sourceMode === 'upload'
                    ? 'bg-indigo-600 text-white font-semibold shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                PC에서 SRT 파일 업로드 (다중 선택)
              </button>
              <button
                type="button"
                onClick={() => setSourceMode('existing')}
                className={`px-3 py-1.5 rounded-lg transition-all ${
                  sourceMode === 'existing'
                    ? 'bg-indigo-600 text-white font-semibold shadow-sm'
                    : 'text-slate-400 hover:text-white'
                }`}
              >
                기존 완료 작업에서 선택
              </button>
            </div>
          </div>

          {/* Mode 1: Multi-file Drag and Drop SRT Upload */}
          {sourceMode === 'upload' && (
            <div
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
              className={`p-8 border-2 border-dashed rounded-2xl text-center cursor-pointer transition-all ${
                isDragging
                  ? 'border-indigo-500 bg-indigo-500/10'
                  : selectedFiles.length > 0
                  ? 'border-emerald-500/40 bg-emerald-500/5'
                  : 'border-slate-800 hover:border-slate-700 bg-slate-950/40'
              }`}
            >
              <input
                ref={fileInputRef}
                type="file"
                accept=".srt"
                multiple
                onChange={handleFileChange}
                className="hidden"
              />
              <div className="flex flex-col items-center justify-center space-y-2">
                <div className={`w-12 h-12 rounded-xl flex items-center justify-center ${
                  selectedFiles.length > 0
                    ? 'bg-emerald-500/15 text-emerald-400 border border-emerald-500/30'
                    : 'bg-indigo-500/10 text-indigo-400 border border-indigo-500/20'
                }`}>
                  {selectedFiles.length > 0 ? <FileText className="w-6 h-6" /> : <UploadCloud className="w-6 h-6" />}
                </div>
                <div className="space-y-0.5">
                  <p className="text-sm font-semibold text-slate-200">
                    {selectedFiles.length > 0
                      ? `총 ${selectedFiles.length}개 SRT 파일이 선택되었습니다`
                      : 'SRT 자막 파일을 이곳에 드래그하거나 클릭하여 선택 (최대 10개)'}
                  </p>
                  <p className="text-xs text-slate-500">
                    {selectedFiles.length > 0
                      ? selectedFiles.map((f) => f.name).join(', ')
                      : '한 번에 최대 10개의 .srt 자막 파일을 등록할 수 있습니다.'}
                  </p>
                </div>
              </div>
            </div>
          )}

          {/* Mode 2: Select from Completed Tasks */}
          {sourceMode === 'existing' && (
            <div className="space-y-3">
              {loadingTasks ? (
                <div className="h-12 bg-slate-800/50 rounded-xl animate-pulse" />
              ) : completedTasks && completedTasks.length > 0 ? (
                <div className="relative">
                  <select
                    value={selectedTaskId}
                    onChange={(e) => setSelectedTaskId(e.target.value)}
                    className="w-full bg-slate-950/70 border border-slate-700/80 rounded-xl px-4 py-3 text-sm text-slate-100 font-medium focus:outline-none focus:border-indigo-500 transition-colors appearance-none pr-10"
                  >
                    {completedTasks.map((t) => (
                      <option key={t.task_id} value={t.task_id}>
                        {t.filename} ({t.subtitle_count?.toLocaleString() || 0}개 자막) - ID: {t.task_id.slice(0, 8)}
                      </option>
                    ))}
                  </select>
                  <ChevronDown className="w-4 h-4 text-slate-400 absolute right-4 top-1/2 -translate-y-1/2 pointer-events-none" />
                </div>
              ) : (
                <div className="p-4 rounded-xl bg-slate-950/40 border border-dashed border-slate-800 text-center text-xs text-slate-400">
                  완료된 자막 작업이 없습니다. [PC에서 SRT 파일 업로드] 탭을 이용해주세요.
                </div>
              )}
            </div>
          )}

          {/* Auto Detection Status Box */}
          {detecting && (
            <div className="flex items-center space-x-2 text-xs text-indigo-400 animate-pulse p-3 bg-indigo-950/30 border border-indigo-900/40 rounded-xl">
              <RefreshCw className="w-3.5 h-3.5 animate-spin" />
              <span>자막 원문 텍스트의 언어를 분석하고 있습니다...</span>
            </div>
          )}

          {detectError && (
            <div className="flex items-center space-x-2 text-xs text-rose-400 p-3 bg-rose-950/30 border border-rose-900/40 rounded-xl">
              <AlertCircle className="w-4 h-4 flex-shrink-0" />
              <span>{detectError}</span>
            </div>
          )}

          {detectionResult && !detecting && (
            <div className="p-4 rounded-xl bg-slate-950/80 border border-indigo-500/30 space-y-3">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center space-x-2.5">
                  <span className="text-xs text-slate-400">자동 감지된 원문 언어:</span>
                  <span className="inline-flex items-center space-x-1.5 px-3 py-1 rounded-full text-xs font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 shadow-sm">
                    <Globe className="w-3.5 h-3.5" />
                    <span>{detectionResult.source_lang_name}</span>
                  </span>
                  <span className="text-[11px] text-slate-500">
                    (신뢰도 {(detectionResult.confidence * 100).toFixed(0)}%)
                  </span>
                </div>

                <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
                  총 {detectionResult.total_segments?.toLocaleString()}개 자막 항목
                </span>
              </div>
            </div>
          )}
        </div>

        {/* Step 2: Target Language Selection */}
        <div className="p-6 space-y-4">
          <span className="text-xs font-bold tracking-wider text-indigo-400 uppercase flex items-center space-x-2">
            <span className="w-5 h-5 rounded-full bg-indigo-500/20 text-indigo-300 flex items-center justify-center text-[11px] font-bold">2</span>
            <span>번역할 목표 언어 선택</span>
          </span>

          <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
            {TARGET_LANGUAGES.map((lang) => {
              const isSelected = targetLang === lang.code;
              return (
                <button
                  key={lang.code}
                  type="button"
                  onClick={() => setTargetLang(lang.code)}
                  className={`p-3 rounded-xl border text-left transition-all flex items-center justify-between ${
                    isSelected
                      ? 'bg-indigo-600/15 border-indigo-500 shadow-md shadow-indigo-500/10 text-white'
                      : 'bg-slate-950/40 border-slate-800 hover:border-slate-700 text-slate-300'
                  }`}
                >
                  <div className="flex items-center space-x-2">
                    <span className="text-lg">{lang.flag}</span>
                    <span className="text-xs font-semibold">{lang.name}</span>
                  </div>
                  {isSelected && <Check className="w-4 h-4 text-indigo-400" />}
                </button>
              );
            })}
          </div>
        </div>

        {/* Step 3: Action Button */}
        <div className="p-6 bg-slate-950/40 flex flex-col sm:flex-row items-center justify-between gap-4">
          <div className="text-xs text-slate-400">
            💡 로컬 Ollama gemma4:12b 모델을 사용하여 고품질 문맥 번역을 순차적으로 진행합니다.
          </div>

          <button
            type="button"
            onClick={handleEnqueue}
            disabled={(sourceMode === 'upload' && selectedFiles.length === 0) || (sourceMode === 'existing' && !selectedTaskId)}
            className="w-full sm:w-auto flex items-center justify-center space-x-2 px-6 py-3 text-sm font-bold text-white bg-gradient-to-r from-indigo-600 via-indigo-500 to-teal-500 hover:from-indigo-500 hover:to-teal-400 rounded-xl transition-all shadow-lg shadow-indigo-600/30 hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50 disabled:pointer-events-none"
          >
            <Sparkles className="w-4 h-4" />
            <span>
              {sourceMode === 'upload' && selectedFiles.length > 1
                ? `${selectedFiles.length}건 번역 대기열 등록 및 시작`
                : '선택한 자막 번역 시작'}
            </span>
            <ArrowRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
