import React, { useState, useRef, useEffect } from 'react';
import {
  UploadCloud,
  FileVideo,
  AlertCircle,
  CheckCircle2,
  Clock,
  Trash2,
  Play,
  RotateCcw,
  Sparkles,
  Layers,
  Check,
  Plus,
  FolderUp,
  FolderPlus,
  Loader2,
  Music,
  Mic,
  FileText,
  Zap,
  Activity,
  Copy,
  FolderSearch,
  HardDrive,
  ChevronRight,
  CornerLeftUp,
  X
} from 'lucide-react';
import { browseLocalFolders } from '../api/client';
import { VALID_EXTENSIONS } from '../hooks/useStudioQueue';

const PIPELINE_STAGES = [
  { id: 1, name: '1. 오디오 추출', desc: '음원 분리 및 정규화', icon: Music, minPct: 25 },
  { id: 2, name: '2. 음성 인식(STT)', desc: 'faster-whisper CUDA', icon: Mic, minPct: 50 },
  { id: 3, name: '3. AI 자막 교정', desc: 'Ollama Qwen 2.5', icon: Sparkles, minPct: 89 },
  { id: 4, name: '4. SRT 패키징', desc: '자막 완성 및 DB 저장', icon: FileText, minPct: 100 },
];

export default function VideoUploader({
  queue = [],
  activeItem = null,
  waitingCount = 0,
  isBusy = false,
  isLoadingQueue = false,
  onAddVideos,
  onAddServerFolder,
  onRemoveItem,
  onClearCompleted,
  onViewCompleted
}) {
  const [dragActive, setDragActive] = useState(false);
  const [warningMsg, setWarningMsg] = useState('');
  const [infoMsg, setInfoMsg] = useState('');
  const [copiedErrorId, setCopiedErrorId] = useState(null);
  const [isScanningFolder, setIsScanningFolder] = useState(false);
  const [scanStatusMsg, setScanStatusMsg] = useState('');

  // Server/Local Folder Browser Modal State
  const [showFolderModal, setShowFolderModal] = useState(false);
  const [folderBrowsePath, setFolderBrowsePath] = useState('');
  const [folderParentPath, setFolderParentPath] = useState('');
  const [folderQuickRoots, setFolderQuickRoots] = useState([]);
  const [folderSubdirs, setFolderSubdirs] = useState([]);
  const [directVideoCount, setDirectVideoCount] = useState(0);
  const [isLoadingFolders, setIsLoadingFolders] = useState(false);
  const [folderModalError, setFolderModalError] = useState('');

  const fileInputRef = useRef(null);
  const folderInputRef = useRef(null);
  const appendFileInputRef = useRef(null);
  const appendFolderInputRef = useRef(null);

  const visibleQueue = queue.filter((it) => it.status !== 'COMPLETED');
  const failedItems = visibleQueue.filter((it) => it.status === 'FAILED');

  const copyTextToClipboard = async (text) => {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (_) {
      try {
        const ta = document.createElement('textarea');
        ta.value = text;
        ta.style.position = 'fixed';
        ta.style.opacity = '0';
        document.body.appendChild(ta);
        ta.focus();
        ta.select();
        document.execCommand('copy');
        document.body.removeChild(ta);
        return true;
      } catch (e) {
        return false;
      }
    }
  };

  const handleCopyError = async (item) => {
    const errText = item.error || item.taskData?.error || '알 수 없는 오류가 발생했습니다.';
    const errStage = item.taskData?.stage || '동영상 파이프라인 처리 중';
    const payload = [
      `[동영상 자막 생성 오류 문의]`,
      `• 파일명: ${item.filename}`,
      item.taskId ? `• 작업 ID: ${item.taskId}` : null,
      `• 발생 단계: ${errStage}`,
      `• 오류 내용: ${errText}`
    ]
      .filter(Boolean)
      .join('\n');

    const ok = await copyTextToClipboard(payload);
    if (ok) {
      setCopiedErrorId(item.id);
      setInfoMsg(`'${item.filename}' 오류 내용이 복사되었습니다. 채팅창에 붙여넣기(Ctrl+V)하여 질문해 주세요!`);
      setTimeout(() => {
        setCopiedErrorId((prev) => (prev === item.id ? null : prev));
      }, 2500);
    }
  };

  const handleCopyAllErrors = async () => {
    if (failedItems.length === 0) return;
    const blocks = failedItems.map((item, i) => {
      const errText = item.error || item.taskData?.error || '알 수 없는 오류';
      const errStage = item.taskData?.stage || '동영상 파이프라인 처리 중';
      return `${i + 1}. 파일명: ${item.filename}\n   - 단계: ${errStage}\n   - 오류: ${errText}`;
    });
    const payload = `[동영상 자막 생성 오류 일괄 문의 (${failedItems.length}건)]\n\n${blocks.join('\n\n')}`;
    const ok = await copyTextToClipboard(payload);
    if (ok) {
      setCopiedErrorId('ALL_ERRORS');
      setInfoMsg(`오류 ${failedItems.length}건의 상세 내용이 클립보드에 복사되었습니다. 채팅창에 붙여넣기(Ctrl+V)하여 질문해 주세요!`);
      setTimeout(() => {
        setCopiedErrorId((prev) => (prev === 'ALL_ERRORS' ? null : prev));
      }, 2500);
    }
  };

  // Live elapsed timer for active processing task
  const [elapsedSeconds, setElapsedSeconds] = useState(0);
  const activeTaskId = activeItem?.taskId;

  useEffect(() => {
    setElapsedSeconds(0);
  }, [activeTaskId]);

  useEffect(() => {
    let interval = null;
    if (activeItem && (activeItem.status === 'PROCESSING' || activeItem.status === 'UPLOADING')) {
      interval = setInterval(() => {
        setElapsedSeconds((prev) => prev + 1);
      }, 1000);
    }
    return () => clearInterval(interval);
  }, [activeItem?.status, activeTaskId]);

  const formatElapsed = (sec) => {
    const mins = Math.floor(sec / 60);
    const secs = sec % 60;
    return `${mins > 0 ? `${mins}분 ` : ''}${secs < 10 ? '0' : ''}${secs}초`;
  };

  const handleDrag = (e) => {
    e.preventDefault();
    e.stopPropagation();
    if (e.type === 'dragenter' || e.type === 'dragover') {
      setDragActive(true);
    } else if (e.type === 'dragleave') {
      setDragActive(false);
    }
  };

  const extractFilesFromDataTransfer = async (dataTransfer) => {
    const items = dataTransfer.items;
    if (items && items.length > 0 && typeof items[0].webkitGetAsEntry === 'function') {
      const files = [];

      const readAllDirectoryEntries = async (reader) => {
        const allEntries = [];
        while (true) {
          const batch = await new Promise((resolve) => {
            reader.readEntries(
              (entries) => resolve(entries || []),
              () => resolve([])
            );
          });
          if (!batch || batch.length === 0) break;
          allEntries.push(...batch);
        }
        return allEntries;
      };

      const traverse = async (entry, parentPath = '') => {
        if (!entry) return;
        const currentRelPath = parentPath ? `${parentPath}/${entry.name}` : entry.name;
        if (entry.isFile) {
          const ext = entry.name.split('.').pop().toLowerCase();
          if (!VALID_EXTENSIONS.includes(ext)) return;
          return new Promise((resolve) => {
            entry.file(
              (f) => {
                if (f) {
                  try {
                    Object.defineProperty(f, 'relativePath', {
                      value: (entry.fullPath || currentRelPath).replace(/^\/+/, ''),
                      configurable: true
                    });
                  } catch (_) {}
                  files.push(f);
                }
                resolve();
              },
              () => resolve()
            );
          });
        } else if (entry.isDirectory) {
          const reader = entry.createReader();
          const children = await readAllDirectoryEntries(reader);
          for (const child of children) {
            await traverse(child, currentRelPath);
          }
        }
      };

      // Capture all entries synchronously first before any await
      const rootEntries = [];
      for (let i = 0; i < items.length; i++) {
        const item = items[i];
        if (item.kind === 'file') {
          const entry = item.webkitGetAsEntry();
          if (entry) {
            rootEntries.push(entry);
          }
        }
      }

      setIsScanningFolder(true);
      setScanStatusMsg('드롭한 폴더 및 하위 폴더의 모든 영상을 검색하고 있습니다...');
      try {
        for (const entry of rootEntries) {
          await traverse(entry, '');
        }
      } finally {
        setIsScanningFolder(false);
        setScanStatusMsg('');
      }

      if (files.length > 0) {
        return files;
      }
    }
    return Array.from(dataTransfer.files || []);
  };

  // Recursive folder picker using File System Access API (walks all subfolders without browser file-count limits)
  const handleSelectFolderRecursive = async (fallbackInputRef) => {
    setWarningMsg('');
    setInfoMsg('');
    if (typeof window.showDirectoryPicker === 'function') {
      try {
        const dirHandle = await window.showDirectoryPicker({ mode: 'read' });
        setIsScanningFolder(true);
        setScanStatusMsg(`'${dirHandle.name}' 및 모든 하위 폴더에서 동영상을 검색 중...`);

        const discoveredFiles = [];
        const walkDirectoryHandle = async (handle, currentPath) => {
          for await (const entry of handle.values()) {
            if (entry.kind === 'directory') {
              setScanStatusMsg(`하위 폴더 검색 중: ${currentPath}/${entry.name} (${discoveredFiles.length}개 발견)`);
              await walkDirectoryHandle(entry, `${currentPath}/${entry.name}`);
            } else if (entry.kind === 'file') {
              const ext = entry.name.split('.').pop().toLowerCase();
              if (VALID_EXTENSIONS.includes(ext)) {
                try {
                  const file = await entry.getFile();
                  Object.defineProperty(file, 'relativePath', {
                    value: `${currentPath}/${entry.name}`,
                    configurable: true
                  });
                  discoveredFiles.push(file);
                } catch (_) {}
              }
            }
          }
        };

        await walkDirectoryHandle(dirHandle, dirHandle.name);
        setIsScanningFolder(false);
        setScanStatusMsg('');

        if (discoveredFiles.length === 0) {
          setWarningMsg(`선택한 폴더('${dirHandle.name}') 및 하위 폴더에 지원되는 동영상 파일이 없습니다.`);
          return;
        }
        processSelectedFiles(discoveredFiles);
        return;
      } catch (err) {
        setIsScanningFolder(false);
        setScanStatusMsg('');
        if (err && err.name === 'AbortError') {
          return; // User cancelled dialog
        }
        // Fallback to input[webkitdirectory] if showDirectoryPicker fails
      }
    }
    fallbackInputRef?.current?.click();
  };

  const openServerFolderBrowser = async (initialPath = '') => {
    setShowFolderModal(true);
    setFolderModalError('');
    await loadServerFolderPath(initialPath);
  };

  const loadServerFolderPath = async (targetPath = '') => {
    setIsLoadingFolders(true);
    setFolderModalError('');
    try {
      const res = await browseLocalFolders(targetPath);
      setFolderBrowsePath(res.current_path || '');
      setFolderParentPath(res.parent_path || '');
      setFolderQuickRoots(res.quick_roots || []);
      setFolderSubdirs(res.folders || []);
      setDirectVideoCount(res.direct_video_count || 0);
    } catch (err) {
      setFolderModalError(err.response?.data?.detail || err.message || '폴더 목록을 불러오지 못했습니다.');
    } finally {
      setIsLoadingFolders(false);
    }
  };

  const handleConfirmServerFolder = async (pathToScan) => {
    const target = (pathToScan ?? folderBrowsePath).trim();
    if (!target) {
      setFolderModalError('검색할 폴더를 선택하거나 경로를 입력해 주세요.');
      return;
    }
    setIsScanningFolder(true);
    setFolderModalError('');
    setWarningMsg('');
    setInfoMsg('');
    try {
      const res = await onAddServerFolder(target);
      setShowFolderModal(false);
      const subText = res.subfolder_count > 0 ? ` (하위 폴더 ${res.subfolder_count}곳 포함)` : '';
      setInfoMsg(
        `'${res.folder_name}'${subText}에서 동영상 총 ${res.total_found}개를 검색하여 ${res.added_count}개를 작업 대기열에 등록했습니다.`
      );
    } catch (err) {
      setFolderModalError(err.response?.data?.detail || err.message || '하위 폴더 영상 검색에 실패했습니다.');
    } finally {
      setIsScanningFolder(false);
    }
  };

  const renderServerFolderModal = () => {
    if (!showFolderModal) return null;
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 backdrop-blur-sm p-4 animate-in fade-in duration-200">
        <div className="w-full max-w-2xl bg-slate-900 border border-slate-700 rounded-2xl shadow-2xl overflow-hidden flex flex-col max-h-[85vh]">
          <div className="p-4 bg-slate-950/80 border-b border-slate-800 flex items-center justify-between">
            <div className="flex items-center space-x-2.5">
              <div className="p-2 rounded-xl bg-purple-500/20 text-purple-400 border border-purple-500/30">
                <FolderSearch className="w-5 h-5" />
              </div>
              <div>
                <h3 className="text-sm font-bold text-white">폴더 지정 (하위 폴더 전체 동영상 자동 검색)</h3>
                <p className="text-[11px] text-slate-400">
                  지정한 폴더와 그 안의 모든 하위 폴더를 끝까지 검색하여 동영상을 한 번에 작업큐에 담습니다.
                </p>
              </div>
            </div>
            <button
              type="button"
              onClick={() => setShowFolderModal(false)}
              className="p-1.5 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition"
            >
              <X className="w-4 h-4" />
            </button>
          </div>

          <div className="p-4 space-y-3 flex-1 overflow-y-auto">
            {/* Quick Roots */}
            {folderQuickRoots.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {folderQuickRoots.map((qr) => (
                  <button
                    key={qr.path}
                    type="button"
                    onClick={() => loadServerFolderPath(qr.path)}
                    className={`px-2.5 py-1 rounded-lg text-xs font-medium border transition flex items-center space-x-1.5 ${
                      folderBrowsePath === qr.path
                        ? 'bg-purple-600 text-white border-purple-500'
                        : 'bg-slate-800/80 text-slate-300 border-slate-700 hover:bg-slate-800'
                    }`}
                  >
                    <HardDrive className="w-3 h-3 text-purple-400" />
                    <span>{qr.label}</span>
                  </button>
                ))}
              </div>
            )}

            {/* Direct Path Input & Up Button */}
            <div className="flex items-center gap-2">
              {folderBrowsePath && (
                <button
                  type="button"
                  onClick={() => loadServerFolderPath(folderParentPath)}
                  className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold flex items-center space-x-1 border border-slate-700 flex-shrink-0"
                  title="상위 폴더로 이동"
                >
                  <CornerLeftUp className="w-3.5 h-3.5" />
                  <span>상위 폴더</span>
                </button>
              )}
              <input
                type="text"
                value={folderBrowsePath}
                onChange={(e) => setFolderBrowsePath(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' && folderBrowsePath.trim()) {
                    loadServerFolderPath(folderBrowsePath.trim());
                  }
                }}
                placeholder="예: D:\Videos 또는 D:\Media (경로 입력 후 Enter로 이동)"
                className="flex-1 px-3.5 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white font-mono focus:outline-none focus:border-purple-500"
              />
              <button
                type="button"
                onClick={() => loadServerFolderPath(folderBrowsePath)}
                className="px-3 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 flex-shrink-0"
              >
                이동
              </button>
            </div>

            {folderModalError && (
              <div className="p-3 rounded-xl bg-rose-950/60 border border-rose-500/40 text-rose-200 text-xs flex items-center space-x-2">
                <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
                <span>{folderModalError}</span>
              </div>
            )}

            {/* Subdirectory List */}
            <div className="border border-slate-800 rounded-xl bg-slate-950/60 divide-y divide-slate-800/80 max-h-72 overflow-y-auto">
              {isLoadingFolders ? (
                <div className="p-8 text-center text-xs text-slate-400 flex items-center justify-center space-x-2">
                  <Loader2 className="w-4 h-4 animate-spin text-purple-400" />
                  <span>폴더 목록을 불러오는 중...</span>
                </div>
              ) : folderSubdirs.length === 0 ? (
                <div className="p-6 text-center text-xs text-slate-400">
                  하위 폴더가 없습니다. {directVideoCount > 0 ? `(현재 폴더 내 동영상 ${directVideoCount}개)` : ''}
                </div>
              ) : (
                folderSubdirs.map((dir) => (
                  <div
                    key={dir.path}
                    className="p-2.5 px-3.5 hover:bg-slate-900/90 flex items-center justify-between gap-2 transition group"
                  >
                    <button
                      type="button"
                      onClick={() => loadServerFolderPath(dir.path)}
                      className="flex items-center space-x-2.5 text-left min-w-0 flex-1"
                    >
                      <FolderUp className="w-4 h-4 text-purple-400 flex-shrink-0" />
                      <span className="text-xs font-medium text-slate-200 group-hover:text-white truncate">
                        {dir.name}
                      </span>
                      <ChevronRight className="w-3.5 h-3.5 text-slate-600 group-hover:text-slate-400 flex-shrink-0" />
                    </button>
                    <button
                      type="button"
                      onClick={() => handleConfirmServerFolder(dir.path)}
                      disabled={isScanningFolder}
                      className="px-2.5 py-1 rounded-lg bg-purple-600/20 hover:bg-purple-600 text-purple-300 hover:text-white border border-purple-500/30 text-[11px] font-semibold transition flex-shrink-0"
                    >
                      이 폴더(하위 포함) 큐에 담기
                    </button>
                  </div>
                ))
              )}
            </div>
          </div>

          <div className="p-4 bg-slate-950/80 border-t border-slate-800 flex items-center justify-between gap-3">
            <span className="text-xs text-slate-400 truncate font-mono">
              {folderBrowsePath ? `선택 경로: ${folderBrowsePath}` : '상단 디스크 또는 폴더를 선택해 주세요'}
            </span>
            <div className="flex items-center space-x-2 flex-shrink-0">
              <button
                type="button"
                onClick={() => setShowFolderModal(false)}
                className="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-medium"
              >
                취소
              </button>
              <button
                type="button"
                disabled={!folderBrowsePath || isScanningFolder}
                onClick={() => handleConfirmServerFolder(folderBrowsePath)}
                className="px-4 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 disabled:opacity-40 text-white text-xs font-bold flex items-center space-x-1.5 shadow-lg shadow-purple-600/30 transition"
              >
                {isScanningFolder ? (
                  <>
                    <Loader2 className="w-3.5 h-3.5 animate-spin" />
                    <span>하위 폴더 검색 중...</span>
                  </>
                ) : (
                  <>
                    <FolderPlus className="w-3.5 h-3.5" />
                    <span>현재 폴더 + 모든 하위 폴더 영상 큐에 담기</span>
                  </>
                )}
              </button>
            </div>
          </div>
        </div>
      </div>
    );
  };

  const handleDrop = async (e) => {
    e.preventDefault();
    e.stopPropagation();
    setDragActive(false);
    if (e.dataTransfer) {
      const files = await extractFilesFromDataTransfer(e.dataTransfer);
      if (files && files.length > 0) {
        processSelectedFiles(files);
      }
    }
  };

  const handleChange = (e) => {
    if (e.target.files && e.target.files.length > 0) {
      processSelectedFiles(e.target.files);
      e.target.value = ''; // Reset so same file/folder can be selected again
    }
  };

  const processSelectedFiles = (files) => {
    setWarningMsg('');
    setInfoMsg('');
    if (!onAddVideos) return;
    const res = onAddVideos(files);
    if (res?.warning) {
      setWarningMsg(res.warning);
    }
    if (res?.info && !res?.warning) {
      setInfoMsg(res.info);
    }
  };

  const formatSize = (bytes) => {
    if (!bytes) return '0 B';
    const mb = bytes / (1024 * 1024);
    if (mb >= 1000) {
      return `${(mb / 1024).toFixed(2)} GB`;
    }
    return `${mb.toFixed(1)} MB`;
  };

  // 0. Initial Loading State: Synchronizing queue with server on fresh mount
  if (isLoadingQueue && visibleQueue.length === 0) {
    return (
      <div className="w-full max-w-3xl mx-auto my-12 p-10 bg-slate-900/70 border border-slate-800 rounded-3xl flex flex-col items-center justify-center space-y-4 shadow-xl backdrop-blur animate-in fade-in duration-300">
        <div className="w-12 h-12 rounded-2xl bg-indigo-500/20 text-indigo-400 border border-indigo-500/30 flex items-center justify-center">
          <Layers className="w-6 h-6 animate-pulse text-indigo-400" />
        </div>
        <div className="text-center space-y-1.5">
          <h3 className="text-base font-bold text-slate-200">
            서버 작업 대기열 및 진행 상황 동기화 중...
          </h3>
          <p className="text-xs text-slate-400">
            다른 브라우저 또는 백엔드에서 처리 중인 작업을 실시간으로 확인하고 있습니다.
          </p>
        </div>
      </div>
    );
  }

  // 1. Initial State: Queue is completely empty
  if (visibleQueue.length === 0 && !activeItem) {
    return (
      <div className="w-full max-w-3xl mx-auto my-6 space-y-4">
        <div
          className={`relative border-2 border-dashed rounded-3xl p-10 text-center transition-all ${
            dragActive
              ? 'border-indigo-500 bg-indigo-500/10 scale-[1.01]'
              : 'border-slate-700 bg-slate-900/60 hover:border-slate-600'
          }`}
          onDragEnter={handleDrag}
          onDragLeave={handleDrag}
          onDragOver={handleDrag}
          onDrop={handleDrop}
        >
          {/* File input (individual video files) */}
          <input
            ref={fileInputRef}
            type="file"
            accept="video/*,.mp4,.mkv,.mov,.webm,.avi,.wmv,.asf,.flv,.ts,.m4v"
            multiple
            className="hidden"
            onChange={handleChange}
          />
          {/* Folder input (entire directory of video files) */}
          <input
            ref={folderInputRef}
            type="file"
            webkitdirectory=""
            directory=""
            multiple
            className="hidden"
            onChange={handleChange}
          />

          <div className="flex flex-col items-center justify-center space-y-4 py-4">
            <div className="flex items-center space-x-3">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-indigo-600 to-indigo-500 border border-indigo-400/30 flex items-center justify-center text-white shadow-xl shadow-indigo-600/25">
                <UploadCloud className="w-7 h-7" />
              </div>
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-tr from-purple-600 to-indigo-600 border border-purple-400/30 flex items-center justify-center text-white shadow-xl shadow-purple-600/25">
                <FolderUp className="w-7 h-7" />
              </div>
            </div>

            <div className="space-y-1.5 max-w-xl">
              <p className="text-xl font-bold text-slate-100">
                자막을 생성할 동영상 파일이나 폴더를 드래그하여 놓으세요
              </p>
              <p className="text-xs text-slate-400 leading-relaxed">
                개별 동영상 다중 선택뿐만 아니라, <strong className="text-purple-300 font-semibold">폴더를 통째로 선택</strong>하여 폴더 내 모든 영상을 한 번에 작업 대기열에 등록할 수 있습니다.
              </p>
              <p className="text-[11px] text-slate-500">
                지원 포맷: MP4, MKV, MOV, WebM, AVI, WMV, ASF, FLV, TS, M4V
              </p>
            </div>

            <div className="pt-2 flex flex-wrap items-center justify-center gap-3">
              <button
                type="button"
                onClick={() => fileInputRef.current?.click()}
                className="px-5 py-3 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs transition shadow-lg shadow-indigo-600/30 flex items-center space-x-2"
              >
                <FileVideo className="w-4 h-4" />
                <span>동영상 파일 찾아보기</span>
              </button>
              <button
                type="button"
                onClick={() => handleSelectFolderRecursive(folderInputRef)}
                className="px-5 py-3 rounded-xl bg-purple-600 hover:bg-purple-500 text-white font-semibold text-xs transition shadow-lg shadow-purple-600/30 flex items-center space-x-2"
              >
                <FolderUp className="w-4 h-4" />
                <span>폴더 선택 (하위 폴더 포함 일괄 등록)</span>
              </button>
              <button
                type="button"
                onClick={() => openServerFolderBrowser('')}
                className="px-5 py-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-purple-300 border border-purple-500/40 font-semibold text-xs transition shadow-lg flex items-center space-x-2"
              >
                <FolderSearch className="w-4 h-4 text-purple-400" />
                <span>로컬 디스크 폴더 탐색기</span>
              </button>
            </div>

            {isScanningFolder && scanStatusMsg && (
              <div className="pt-2 flex items-center justify-center space-x-2 text-xs text-purple-300 font-semibold animate-pulse">
                <Loader2 className="w-4 h-4 animate-spin text-purple-400" />
                <span>{scanStatusMsg}</span>
              </div>
            )}

            <div className="pt-3 flex flex-wrap items-center justify-center gap-x-4 gap-y-1 text-[11px] text-slate-500">
              <span className="flex items-center space-x-1">
                <Sparkles className="w-3.5 h-3.5 text-indigo-400" />
                <span>순차 대기열 자동 처리</span>
              </span>
              <span>•</span>
              <span className="flex items-center space-x-1">
                <FolderPlus className="w-3.5 h-3.5 text-purple-400" />
                <span>폴더 내 영상 자동 감지</span>
              </span>
              <span>•</span>
              <span className="flex items-center space-x-1">
                <Clock className="w-3.5 h-3.5 text-teal-400" />
                <span>분석 시작 시점 지연 업로드</span>
              </span>
            </div>
          </div>
        </div>

        {infoMsg && (
          <div className="p-3.5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex items-center space-x-2.5 text-emerald-300 text-xs animate-in fade-in">
            <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
            <span>{infoMsg}</span>
          </div>
        )}

        {warningMsg && (
          <div className="p-3.5 bg-amber-500/10 border border-amber-500/30 rounded-xl flex items-center space-x-2.5 text-amber-300 text-xs">
            <AlertCircle className="w-4 h-4 flex-shrink-0" />
            <span className="whitespace-pre-line">{warningMsg}</span>
          </div>
        )}
        {renderServerFolderModal()}
      </div>
    );
  }

  // 2. Active Queue State: Shows active task + waiting list + append dropzone
  return (
    <div
      className={`w-full max-w-4xl mx-auto my-6 space-y-6 transition-all ${
        dragActive ? 'ring-2 ring-indigo-500/80 rounded-2xl p-1 bg-indigo-500/5' : ''
      }`}
      onDragEnter={handleDrag}
      onDragLeave={handleDrag}
      onDragOver={handleDrag}
      onDrop={handleDrop}
    >
      {renderServerFolderModal()}
      {isScanningFolder && scanStatusMsg && (
        <div className="p-3.5 bg-purple-950/50 border border-purple-500/40 rounded-xl flex items-center space-x-2.5 text-purple-200 text-xs animate-pulse">
          <Loader2 className="w-4 h-4 animate-spin text-purple-400 flex-shrink-0" />
          <span>{scanStatusMsg}</span>
        </div>
      )}
      {/* Top Header & Append Controls */}
      <div className="flex flex-col gap-4 p-5 bg-slate-900 border border-slate-800 rounded-2xl shadow-xl">
        {/* Top Row: Title, Count Badges & Description */}
        <div className="flex items-start space-x-3.5">
          <div className="p-2.5 bg-indigo-500/15 text-indigo-400 rounded-xl border border-indigo-500/30 flex-shrink-0 mt-0.5">
            <Layers className="w-5 h-5" />
          </div>
          <div className="min-w-0 flex-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-bold text-white whitespace-nowrap">동영상 작업 대기열</h2>
              <span className="px-2.5 py-0.5 rounded-full text-xs font-semibold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30 whitespace-nowrap">
                총 {visibleQueue.length}건
              </span>
              {activeItem && (
                <span className="px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 whitespace-nowrap">
                  1건 진행 중
                </span>
              )}
              {waitingCount > 0 && (
                <span className="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-purple-500/20 text-purple-300 border border-purple-500/30 whitespace-nowrap">
                  {waitingCount}건 대기 중
                </span>
              )}
              {failedItems.length > 0 && (
                <span className="px-2.5 py-0.5 rounded-full text-[11px] font-medium bg-rose-500/20 text-rose-300 border border-rose-500/30 whitespace-nowrap">
                  {failedItems.length}건 오류
                </span>
              )}
            </div>
            <p className="text-xs text-slate-400 mt-1.5 leading-relaxed">
              자막 생성이 완료된 항목은 목록에서 자동 제거되어 [작업 완료 보관함]으로 이동하며, 오류 발생 시 자동으로 다음 영상으로 넘어갑니다.
            </p>
          </div>
        </div>

        {/* Bottom Row: Action Toolbar Buttons */}
        <div className="flex flex-wrap items-center justify-between gap-2 pt-3 border-t border-slate-800/80">
          <input
            ref={appendFileInputRef}
            type="file"
            accept="video/*,.mp4,.mkv,.mov,.webm,.avi,.wmv,.asf,.flv,.ts,.m4v"
            multiple
            className="hidden"
            onChange={handleChange}
          />
          <input
            ref={appendFolderInputRef}
            type="file"
            webkitdirectory=""
            directory=""
            multiple
            className="hidden"
            onChange={handleChange}
          />
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={() => appendFileInputRef.current?.click()}
              className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white font-semibold text-xs transition shadow-md shadow-indigo-600/25 whitespace-nowrap"
              title="개별 동영상 파일 추가"
            >
              <Plus className="w-3.5 h-3.5 flex-shrink-0" />
              <span>영상 추가</span>
            </button>
            <button
              type="button"
              onClick={() => handleSelectFolderRecursive(appendFolderInputRef)}
              className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 text-white font-semibold text-xs transition shadow-md shadow-purple-600/25 whitespace-nowrap"
              title="폴더를 선택하면 모든 하위 폴더를 검색하여 영상을 일괄 추가합니다"
            >
              <FolderUp className="w-3.5 h-3.5 flex-shrink-0" />
              <span>폴더 추가 (하위 포함)</span>
            </button>
            <button
              type="button"
              onClick={() => openServerFolderBrowser('')}
              className="flex items-center space-x-1.5 px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-purple-300 border border-purple-500/30 font-semibold text-xs transition whitespace-nowrap"
              title="로컬 디스크 폴더를 직접 탐색하여 하위 폴더 포함 전체 영상을 추가합니다"
            >
              <FolderSearch className="w-3.5 h-3.5 text-purple-400 flex-shrink-0" />
              <span>디스크 폴더 탐색</span>
            </button>
          </div>

          {failedItems.length > 0 && (
            <div className="flex flex-wrap items-center gap-2">
              <button
                type="button"
                onClick={handleCopyAllErrors}
                className={`flex items-center space-x-1.5 px-3 py-2 text-xs font-semibold rounded-xl border transition whitespace-nowrap ${
                  copiedErrorId === 'ALL_ERRORS'
                    ? 'bg-emerald-600/20 text-emerald-300 border-emerald-500/40'
                    : 'bg-rose-500/15 hover:bg-rose-500/25 text-rose-300 border-rose-500/30'
                }`}
                title="오류가 발생한 모든 항목의 상세 오류 내용을 클립보드에 복사"
              >
                {copiedErrorId === 'ALL_ERRORS' ? (
                  <>
                    <Check className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
                    <span>전체 오류 복사됨!</span>
                  </>
                ) : (
                  <>
                    <Copy className="w-3.5 h-3.5 flex-shrink-0" />
                    <span>전체 오류 복사</span>
                  </>
                )}
              </button>
              <button
                type="button"
                onClick={onClearCompleted}
                className="px-3 py-2 text-xs font-medium text-slate-400 hover:text-slate-200 bg-slate-800 hover:bg-slate-700 rounded-xl transition whitespace-nowrap"
                title="오류가 발생한 항목을 대기열 목록에서 정리"
              >
                오류건 정리
              </button>
            </div>
          )}
        </div>
      </div>

      {infoMsg && (
        <div className="p-3.5 bg-emerald-500/10 border border-emerald-500/30 rounded-xl flex items-center space-x-2.5 text-emerald-300 text-xs animate-in fade-in">
          <CheckCircle2 className="w-4 h-4 flex-shrink-0" />
          <span>{infoMsg}</span>
        </div>
      )}

      {warningMsg && (
        <div className="p-3.5 bg-amber-500/10 border border-amber-500/30 rounded-xl flex items-center space-x-2.5 text-amber-300 text-xs">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          <span className="whitespace-pre-line">{warningMsg}</span>
        </div>
      )}

      {/* 1. CURRENT ACTIVE ITEM (UPLOADING or PROCESSING) */}
      {activeItem && (
        <div className="p-6 rounded-2xl bg-gradient-to-br from-slate-900 via-indigo-950/40 to-slate-900 border-2 border-indigo-500/50 shadow-2xl space-y-5 relative overflow-hidden animate-in fade-in duration-300">
          {/* Subtle animated background gradient pulse */}
          <div className="absolute inset-0 bg-gradient-to-r from-indigo-500/5 via-purple-500/5 to-emerald-500/5 animate-pulse pointer-events-none" />

          {/* Top Row: Icon, Title, Status & Progress */}
          <div className="relative flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div className="flex items-start sm:items-center space-x-3.5 min-w-0">
              <div className="w-12 h-12 rounded-2xl bg-indigo-500/20 border border-indigo-500/40 flex items-center justify-center text-indigo-400 flex-shrink-0 shadow-lg shadow-indigo-950/50">
                {activeItem.status === 'UPLOADING' ? (
                  <UploadCloud className="w-6 h-6 animate-bounce text-indigo-400" />
                ) : (
                  <Loader2 className="w-6 h-6 animate-spin text-indigo-400" />
                )}
              </div>
              <div className="min-w-0">
                <div className="flex items-center space-x-2 flex-wrap gap-y-1">
                  <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold uppercase tracking-wider bg-indigo-500 text-white shadow-sm flex items-center space-x-1.5">
                    <span className="w-1.5 h-1.5 rounded-full bg-white animate-ping" />
                    <span>{activeItem.status === 'UPLOADING' ? '업로드 진행 중' : 'AI 파이프라인 가동 중'}</span>
                  </span>
                  <h3 className="text-base font-bold text-white truncate max-w-sm sm:max-w-md" title={activeItem.filename}>
                    {activeItem.filename}
                  </h3>
                </div>
                <p className="text-xs text-slate-300 mt-1 flex items-center space-x-2">
                  {activeItem.size > 0 && <span className="text-slate-400">{formatSize(activeItem.size)} •</span>}
                  <span className="text-indigo-300 font-semibold truncate">
                    {activeItem.status === 'UPLOADING'
                      ? `네트워크 스트리밍 전송 (${activeItem.uploadProgress}%)`
                      : activeItem.taskData?.stage || '파이프라인 분석 준비 중...'}
                  </span>
                </p>
              </div>
            </div>

            <div className="text-right flex-shrink-0 flex sm:flex-col items-center sm:items-end justify-between">
              <span className="text-3xl font-black text-indigo-400 font-mono tracking-tight">
                {activeItem.status === 'UPLOADING'
                  ? `${activeItem.uploadProgress}%`
                  : `${activeItem.taskData?.progress || 10}%`}
              </span>
              <span className="text-[11px] text-slate-400 font-medium">
                {activeItem.status === 'UPLOADING' ? '전송 진행률' : '전체 완료율'}
              </span>
            </div>
          </div>

          {/* Animated Progress Bar */}
          <div className="relative w-full bg-slate-950/80 rounded-full h-3.5 overflow-hidden border border-slate-700/80 p-0.5 shadow-inner">
            <div
              className={`h-full rounded-full transition-all duration-300 relative ${
                activeItem.status === 'UPLOADING'
                  ? 'bg-gradient-to-r from-teal-500 to-indigo-500'
                  : 'bg-gradient-to-r from-indigo-500 via-purple-500 to-emerald-400'
              }`}
              style={{
                width: `${
                  activeItem.status === 'UPLOADING'
                    ? activeItem.uploadProgress
                    : activeItem.taskData?.progress || 10
                }%`
              }}
            >
              <div className="absolute inset-0 bg-white/20 animate-pulse" />
            </div>
          </div>

          {/* Real-time Status & Live Timer Grid (3 Cards) */}
          <div className="relative grid grid-cols-1 sm:grid-cols-3 gap-2.5 pt-1">
            <div className="p-3 rounded-xl bg-slate-950/70 border border-indigo-500/30 flex items-center space-x-3 shadow-sm">
              <div className="p-2 rounded-lg bg-indigo-500/15 text-indigo-400">
                <Clock className="w-4 h-4 animate-spin" style={{ animationDuration: '4s' }} />
              </div>
              <div>
                <span className="text-[10px] uppercase font-bold text-slate-400 block tracking-wider">진행 경과 시간</span>
                <span className="text-xs font-bold text-white font-mono">{formatElapsed(elapsedSeconds)}</span>
              </div>
            </div>

            <div className="p-3 rounded-xl bg-slate-950/70 border border-purple-500/30 flex items-center space-x-3 shadow-sm">
              <div className="p-2 rounded-lg bg-purple-500/15 text-purple-400">
                <Activity className="w-4 h-4 animate-pulse" />
              </div>
              <div className="min-w-0">
                <span className="text-[10px] uppercase font-bold text-slate-400 block tracking-wider">현재 처리 단계</span>
                <span className="text-xs font-bold text-purple-300 truncate block">
                  {activeItem.status === 'UPLOADING' ? '영상 데이터 스트리밍' : activeItem.taskData?.stage?.split('...')[0] || 'AI 분석 중'}
                </span>
              </div>
            </div>

            <div className="p-3 rounded-xl bg-slate-950/70 border border-teal-500/30 flex items-center space-x-3 shadow-sm">
              <div className="p-2 rounded-lg bg-teal-500/15 text-teal-400">
                <Zap className="w-4 h-4 text-teal-400" />
              </div>
              <div>
                <span className="text-[10px] uppercase font-bold text-slate-400 block tracking-wider">하드웨어 가속</span>
                <span className="text-xs font-bold text-teal-300">CUDA GPU 가속 (RTX 4070 Ti)</span>
              </div>
            </div>
          </div>

          {/* 4 Pipeline Stages Stepper */}
          <div className="relative pt-1">
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
              {PIPELINE_STAGES.map((s) => {
                const Icon = s.icon;
                const currentPct = activeItem.status === 'UPLOADING' ? 5 : (activeItem.taskData?.progress || 10);
                const isDone = currentPct >= s.minPct;
                const isCurrent = !isDone && currentPct >= s.minPct - 25;

                return (
                  <div
                    key={s.id}
                    className={`p-2.5 rounded-xl border transition-all ${
                      isDone
                        ? 'bg-emerald-500/10 border-emerald-500/30 text-emerald-300'
                        : isCurrent
                        ? 'bg-indigo-500/20 border-indigo-500/60 text-indigo-300 shadow-md shadow-indigo-950/40 ring-1 ring-indigo-500/40'
                        : 'bg-slate-950/40 border-slate-800 text-slate-500'
                    }`}
                  >
                    <div className="flex items-center space-x-2 mb-1">
                      {isDone ? (
                        <Check className="w-3.5 h-3.5 text-emerald-400 flex-shrink-0" />
                      ) : isCurrent ? (
                        <Loader2 className="w-3.5 h-3.5 text-indigo-400 animate-spin flex-shrink-0" />
                      ) : (
                        <Icon className="w-3.5 h-3.5 text-slate-500 flex-shrink-0" />
                      )}
                      <span className="text-xs font-bold truncate">{s.name}</span>
                    </div>
                    <p className="text-[10px] text-slate-400 truncate">{s.desc}</p>
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* 2. QUEUE LIST (WAITING & FAILED; COMPLETED ITEMS AUTO-REMOVED) */}
      <div className="space-y-2.5">
        <div className="flex items-center justify-between px-1 text-xs font-semibold text-slate-400">
          <span>대기열 목록 ({visibleQueue.length}개)</span>
          <span className="text-[11px] text-slate-500">완료 시 자동 제거 • 오류 발생 시 다음 작업 자동 진행</span>
        </div>

        <div className="space-y-2">
          {visibleQueue.map((item, idx) => {
            const isCurrent = item.id === activeItem?.id;
            const isWaiting = item.status === 'WAITING';
            const isFailed = item.status === 'FAILED';
            const errMessage = item.error || item.taskData?.error || '동영상 처리 중 알 수 없는 오류가 발생했습니다.';
            const isErrorCopied = copiedErrorId === item.id;

            return (
              <div
                key={item.id}
                className={`p-3.5 rounded-xl border transition-all flex flex-col gap-2.5 ${
                  isCurrent
                    ? 'bg-indigo-950/20 border-indigo-500/40 shadow-md'
                    : isFailed
                    ? 'bg-rose-950/20 border-rose-500/35'
                    : 'bg-slate-900/80 border-slate-800 hover:border-slate-700'
                }`}
              >
                <div className="flex items-center justify-between gap-3">
                  {/* Left: Index badge & Filename */}
                  <div className="flex items-center space-x-3 min-w-0">
                    <div
                      className={`w-7 h-7 rounded-lg flex items-center justify-center text-xs font-bold font-mono flex-shrink-0 ${
                        isCurrent
                          ? 'bg-indigo-600 text-white animate-pulse'
                          : isFailed
                          ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30'
                          : 'bg-slate-800 text-slate-400'
                      }`}
                    >
                      {isFailed ? '!' : idx + 1}
                    </div>

                    <div className="min-w-0">
                      <p className="text-xs font-semibold text-slate-200 truncate max-w-sm sm:max-w-md" title={item.filename}>
                        {item.filename}
                      </p>
                      <div className="flex items-center space-x-2 text-[11px] text-slate-500">
                        {item.size > 0 && (
                          <>
                            <span>{formatSize(item.size)}</span>
                            <span>•</span>
                          </>
                        )}
                        {isWaiting && (
                          <span className="text-purple-400 font-medium">
                            {item.file ? '분석 시작 시 업로드 대기 중' : '작업 순서 대기 중'}
                          </span>
                        )}
                        {isCurrent && (
                          <span className="text-indigo-400 font-medium">
                            {item.status === 'UPLOADING' ? '업로드 중' : '분석 중'}
                          </span>
                        )}
                        {isFailed && (
                          <span className="text-rose-400 font-semibold">
                            작업 오류 발생 (다음 대기 작업으로 자동 이동됨)
                          </span>
                        )}
                      </div>
                    </div>
                  </div>

                  {/* Right: Actions */}
                  <div className="flex items-center space-x-2 flex-shrink-0">
                    {isWaiting && (
                      <span className="px-2.5 py-1 rounded-lg text-[10px] font-semibold bg-purple-500/15 text-purple-300 border border-purple-500/30">
                        대기 중
                      </span>
                    )}
                    {isFailed && (
                      <button
                        type="button"
                        onClick={() => handleCopyError(item)}
                        className={`flex items-center space-x-1.5 px-3 py-1.5 rounded-lg text-xs font-semibold border transition shadow-sm ${
                          isErrorCopied
                            ? 'bg-emerald-600 text-white border-emerald-500'
                            : 'bg-rose-600/25 hover:bg-rose-600/40 text-rose-200 border-rose-500/40'
                        }`}
                        title="오류 상세 내용을 복사하여 질문하기"
                      >
                        {isErrorCopied ? (
                          <>
                            <Check className="w-3.5 h-3.5" />
                            <span>복사됨!</span>
                          </>
                        ) : (
                          <>
                            <Copy className="w-3.5 h-3.5" />
                            <span>오류 복사</span>
                          </>
                        )}
                      </button>
                    )}
                    {!isCurrent && (
                      <button
                        type="button"
                        onClick={() => onRemoveItem && onRemoveItem(item.id)}
                        className="p-1.5 rounded-lg text-slate-500 hover:text-rose-400 hover:bg-slate-800 transition"
                        title="대기열에서 제거"
                      >
                        <Trash2 className="w-3.5 h-3.5" />
                      </button>
                    )}
                  </div>
                </div>

                {/* Detailed Error Message Box for FAILED items */}
                {isFailed && (
                  <div className="ml-10 p-2.5 rounded-lg bg-rose-950/50 border border-rose-500/30 flex items-start justify-between gap-2 text-xs text-rose-200/90">
                    <div className="flex items-start space-x-2 min-w-0">
                      <AlertCircle className="w-3.5 h-3.5 text-rose-400 flex-shrink-0 mt-0.5" />
                      <div className="font-mono text-[11px] leading-relaxed break-all whitespace-pre-wrap">
                        {errMessage}
                      </div>
                    </div>
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
