import React, { useState, useRef, useEffect } from 'react';
import { useQuery } from '@tanstack/react-query';
import {
  FileCheck,
  Download,
  ChevronRight,
  ChevronLeft,
  ChevronsLeft,
  ChevronsRight,
  Clock,
  Hash,
  RefreshCw,
  Film,
  Sparkles,
  Languages,
  ArrowLeft,
  Layers,
  Trash2,
  AlertTriangle,
  AlertCircle,
  CheckCheck,
  Check,
  Archive,
  FolderDown
} from 'lucide-react';
import {
  getCompletedTasks,
  downloadSrtFile,
  getTaskStatus,
  deleteTask,
  batchDeleteTasks,
  deleteAllTasks,
  batchDownloadAll,
  batchDownloadUndownloaded
} from '../api/client';
import VideoPreview from './VideoPreview';
import SubtitleEditor from './SubtitleEditor';
import CompletedBanner from './CompletedBanner';

const ITEMS_PER_PAGE = 100;

export default function CompletedList({ onNewTask, onTranslateTask }) {
  const [selectedDetailTaskId, setSelectedDetailTaskId] = useState(null);
  const [activeTab, setActiveTab] = useState('all'); // 'all' | 'studio' | 'translator'
  const [currentPage, setCurrentPage] = useState(1);
  const [selectedIds, setSelectedIds] = useState([]);
  const [deleteModalState, setDeleteModalState] = useState({
    isOpen: false,
    scope: 'single', // 'single' | 'selected' | 'all'
    task: null,
  });
  const [isDeleting, setIsDeleting] = useState(false);
  const [isBatchDownloadingAll, setIsBatchDownloadingAll] = useState(false);
  const [isBatchDownloadingUndownloaded, setIsBatchDownloadingUndownloaded] = useState(false);
  const playerRef = useRef(null);

  // Fetch completed tasks from PostgreSQL
  const { data: tasks, isLoading, refetch, isFetching } = useQuery({
    queryKey: ['completed-tasks'],
    queryFn: () => getCompletedTasks(),
    refetchInterval: 5000,
  });

  // Fetch details for selected completed task
  const { data: detailTask, isLoading: loadingDetail } = useQuery({
    queryKey: ['task', selectedDetailTaskId],
    queryFn: () => getTaskStatus(selectedDetailTaskId),
    enabled: !!selectedDetailTaskId,
  });

  const getTaskType = (task) => {
    if (task.task_type === 'translator' || task.task_type === 'studio') {
      return task.task_type;
    }
    const fn = (task.filename || '').toLowerCase();
    if (fn.endsWith('.srt')) {
      return 'translator';
    }
    return 'studio';
  };

  const allTasks = tasks || [];
  const studioTasks = allTasks.filter((t) => getTaskType(t) === 'studio');
  const translatorTasks = allTasks.filter((t) => getTaskType(t) === 'translator');

  // Only tasks with at least 1 subtitle are eligible for downloading
  const downloadableTasks = allTasks.filter((t) => (t.subtitle_count || 0) > 0);
  const downloadedCount = downloadableTasks.filter((t) => (t.download_count || 0) > 0 || t.downloaded).length;
  const unDownloadedCount = downloadableTasks.length - downloadedCount;

  const filteredTasks =
    activeTab === 'studio'
      ? studioTasks
      : activeTab === 'translator'
      ? translatorTasks
      : allTasks;

  // Pagination calculation (100 items per page)
  const totalPages = Math.max(1, Math.ceil(filteredTasks.length / ITEMS_PER_PAGE));
  const safeCurrentPage = Math.min(Math.max(1, currentPage), totalPages);
  const startIndex = (safeCurrentPage - 1) * ITEMS_PER_PAGE;
  const endIndex = Math.min(startIndex + ITEMS_PER_PAGE, filteredTasks.length);
  const paginatedTasks = filteredTasks.slice(startIndex, endIndex);

  useEffect(() => {
    if (currentPage > totalPages) {
      setCurrentPage(totalPages);
    }
  }, [filteredTasks.length, totalPages, currentPage]);

  const handlePageChange = (newPage) => {
    const target = Math.min(Math.max(1, newPage), totalPages);
    setCurrentPage(target);
    window.scrollTo({ top: 0, behavior: 'smooth' });
  };

  const downloadableInCurrentTab = filteredTasks.filter((t) => (t.subtitle_count || 0) > 0);
  const unDownloadedInCurrentTab = downloadableInCurrentTab.filter(
    (t) => (t.download_count || 0) === 0 && !t.downloaded
  );

  const handleBatchDownloadAll = async () => {
    if (downloadableInCurrentTab.length === 0) {
      alert('현재 선택된 목록에 다운로드할 수 있는 자막(1건 이상)이 없습니다.');
      return;
    }

    setIsBatchDownloadingAll(true);
    try {
      const taskIds = downloadableInCurrentTab.map((t) => t.task_id);
      await batchDownloadAll(taskIds);
      // Immediately refresh task list to update download counts & colors
      await refetch();
    } catch (err) {
      console.error('Batch download all error:', err);
      let errMsg = '전체 일괄 다운로드 중 오류가 발생했습니다.';
      if (err.response?.data instanceof Blob) {
        try {
          const text = await err.response.data.text();
          const json = JSON.parse(text);
          if (json.detail) errMsg = json.detail;
        } catch (_) {}
      } else if (err.response?.data?.detail) {
        errMsg = err.response.data.detail;
      }
      alert(errMsg);
    } finally {
      setIsBatchDownloadingAll(false);
    }
  };

  const handleBatchDownloadUndownloaded = async () => {
    if (unDownloadedInCurrentTab.length === 0) {
      alert('현재 선택된 목록에 아직 다운로드하지 않은 신규 자막이 없습니다.');
      return;
    }

    setIsBatchDownloadingUndownloaded(true);
    try {
      const taskIds = unDownloadedInCurrentTab.map((t) => t.task_id);
      await batchDownloadUndownloaded(taskIds);
      // Immediately refresh task list to update download counts & colors
      await refetch();
    } catch (err) {
      console.error('Batch download undownloaded error:', err);
      let errMsg = '미다운로드건 일괄 다운로드 중 오류가 발생했습니다.';
      if (err.response?.data instanceof Blob) {
        try {
          const text = await err.response.data.text();
          const json = JSON.parse(text);
          if (json.detail) errMsg = json.detail;
        } catch (_) {}
      } else if (err.response?.data?.detail) {
        errMsg = err.response.data.detail;
      }
      alert(errMsg);
    } finally {
      setIsBatchDownloadingUndownloaded(false);
    }
  };

  const handleDownload = async (e, task) => {
    e.stopPropagation();
    const count = task.subtitle_count ?? task.subtitles?.length ?? 0;
    if (count === 0) {
      alert('생성된 자막이 없어 다운로드할 수 없습니다. 상세 보기에서 자막을 먼저 입력하고 저장해 주세요.');
      return;
    }
    try {
      let baseName = task.filename ? task.filename.replace(/\.[^/.]+$/, "") : `subtitles_${task.task_id.slice(0, 8)}`;
      for (const lang of ['_ko', '_en', '_ja', '_zh', '_es']) {
        if (baseName.endsWith(lang)) {
          baseName = baseName.slice(0, -lang.length);
          break;
        }
      }
      const filename = `${baseName}.srt`;
      await downloadSrtFile(task.task_id, filename);
      // Immediately refresh task list to update download count & styling
      refetch();
    } catch (err) {
      console.error('Download error:', err);
      alert('SRT 다운로드 중 오류가 발생했습니다: ' + (err.response?.data?.detail || err.message));
    }
  };

  const handleSeekVideo = (seconds) => {
    if (playerRef.current) {
      playerRef.current.seekTo(seconds, 'seconds');
    }
  };

  const selectedCountInCurrentTab = selectedIds.filter((id) =>
    filteredTasks.some((t) => t.task_id === id)
  ).length;

  const allFilteredSelected =
    filteredTasks.length > 0 &&
    filteredTasks.every((t) => selectedIds.includes(t.task_id));

  const allCurrentPageSelected =
    paginatedTasks.length > 0 &&
    paginatedTasks.every((t) => selectedIds.includes(t.task_id));

  const toggleSelectTask = (taskId) => {
    setSelectedIds((prev) =>
      prev.includes(taskId) ? prev.filter((id) => id !== taskId) : [...prev, taskId]
    );
  };

  const handleToggleSelectCurrentPage = () => {
    const pageIds = paginatedTasks.map((t) => t.task_id);
    if (allCurrentPageSelected) {
      setSelectedIds((prev) => prev.filter((id) => !pageIds.includes(id)));
    } else {
      setSelectedIds((prev) => Array.from(new Set([...prev, ...pageIds])));
    }
  };

  const handleToggleSelectAll = () => {
    const currentTabIds = filteredTasks.map((t) => t.task_id);
    if (allFilteredSelected) {
      setSelectedIds((prev) => prev.filter((id) => !currentTabIds.includes(id)));
    } else {
      setSelectedIds((prev) => Array.from(new Set([...prev, ...currentTabIds])));
    }
  };

  const renderPaginationBar = () => {
    if (filteredTasks.length === 0) return null;

    // Build visible page numbers (up to 7 buttons around safeCurrentPage)
    const maxButtons = 7;
    let startPage = Math.max(1, safeCurrentPage - Math.floor(maxButtons / 2));
    let endPage = Math.min(totalPages, startPage + maxButtons - 1);
    if (endPage - startPage + 1 < maxButtons) {
      startPage = Math.max(1, endPage - maxButtons + 1);
    }
    const pageNumbers = [];
    for (let p = startPage; p <= endPage; p++) {
      pageNumbers.push(p);
    }

    return (
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-4 py-3 bg-slate-900/95 border border-slate-800 rounded-2xl shadow-md">
        <div className="flex items-center space-x-2 text-xs text-slate-300 flex-wrap gap-y-1">
          <span className="font-semibold text-white">
            총 {filteredTasks.length.toLocaleString()}건
          </span>
          <span className="text-slate-600">•</span>
          <span>
            <strong className="text-indigo-400 font-mono">{(startIndex + 1).toLocaleString()}</strong>
            {' ~ '}
            <strong className="text-indigo-400 font-mono">{endIndex.toLocaleString()}</strong>번째 표시
          </span>
          <span className="px-2 py-0.5 rounded-md bg-slate-800 text-slate-400 text-[11px] border border-slate-700 font-mono">
            1페이지당 {ITEMS_PER_PAGE}건 ({safeCurrentPage} / {totalPages} 페이지)
          </span>
        </div>

        <div className="flex items-center space-x-1.5 flex-wrap gap-y-1">
          <button
            type="button"
            onClick={() => handlePageChange(1)}
            disabled={safeCurrentPage <= 1}
            className="p-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:pointer-events-none border border-slate-700 transition"
            title="첫 페이지 (1페이지)"
          >
            <ChevronsLeft className="w-4 h-4" />
          </button>
          <button
            type="button"
            onClick={() => handlePageChange(safeCurrentPage - 1)}
            disabled={safeCurrentPage <= 1}
            className="flex items-center space-x-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:pointer-events-none border border-slate-700 transition"
            title="이전 페이지"
          >
            <ChevronLeft className="w-3.5 h-3.5" />
            <span>이전</span>
          </button>

          {startPage > 1 && (
            <>
              <button
                type="button"
                onClick={() => handlePageChange(1)}
                className="min-w-[32px] h-8 px-2 rounded-lg text-xs font-bold font-mono bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
              >
                1
              </button>
              {startPage > 2 && <span className="text-slate-500 text-xs px-1">…</span>}
            </>
          )}

          {pageNumbers.map((pageNum) => {
            const isActive = pageNum === safeCurrentPage;
            return (
              <button
                key={pageNum}
                type="button"
                onClick={() => handlePageChange(pageNum)}
                className={`min-w-[32px] h-8 px-2.5 rounded-lg text-xs font-bold font-mono transition ${
                  isActive
                    ? 'bg-indigo-600 text-white shadow-md shadow-indigo-600/30 border border-indigo-400'
                    : 'bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700'
                }`}
              >
                {pageNum}
              </button>
            );
          })}

          {endPage < totalPages && (
            <>
              {endPage < totalPages - 1 && <span className="text-slate-500 text-xs px-1">…</span>}
              <button
                type="button"
                onClick={() => handlePageChange(totalPages)}
                className="min-w-[32px] h-8 px-2 rounded-lg text-xs font-bold font-mono bg-slate-800 hover:bg-slate-700 text-slate-300 border border-slate-700 transition"
              >
                {totalPages}
              </button>
            </>
          )}

          <button
            type="button"
            onClick={() => handlePageChange(safeCurrentPage + 1)}
            disabled={safeCurrentPage >= totalPages}
            className="flex items-center space-x-1 px-2.5 py-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:pointer-events-none border border-slate-700 transition"
            title="다음 페이지"
          >
            <span>다음</span>
            <ChevronRight className="w-3.5 h-3.5" />
          </button>
          <button
            type="button"
            onClick={() => handlePageChange(totalPages)}
            disabled={safeCurrentPage >= totalPages}
            className="p-1.5 rounded-lg text-xs font-semibold bg-slate-800 hover:bg-slate-700 text-slate-300 disabled:opacity-40 disabled:pointer-events-none border border-slate-700 transition"
            title={`마지막 페이지 (${totalPages}페이지)`}
          >
            <ChevronsRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    );
  };

  const openSingleDeleteModal = (task) => {
    setDeleteModalState({ isOpen: true, scope: 'single', task });
  };

  const openSelectedDeleteModal = () => {
    setDeleteModalState({ isOpen: true, scope: 'selected', task: null });
  };

  const openAllDeleteModal = () => {
    setDeleteModalState({ isOpen: true, scope: 'all', task: null });
  };

  const closeDeleteModal = () => {
    setDeleteModalState({ isOpen: false, scope: 'single', task: null });
  };

  const executeDelete = async () => {
    const { scope, task } = deleteModalState;
    setIsDeleting(true);
    try {
      if (scope === 'single' && task) {
        await deleteTask(task.task_id);
        setSelectedIds((prev) => prev.filter((id) => id !== task.task_id));
        if (selectedDetailTaskId === task.task_id) {
          setSelectedDetailTaskId(null);
        }
      } else if (scope === 'selected') {
        const idsToDelete = selectedIds.filter((id) => filteredTasks.some((t) => t.task_id === id));
        if (idsToDelete.length > 0) {
          await batchDeleteTasks(idsToDelete);
          setSelectedIds((prev) => prev.filter((id) => !idsToDelete.includes(id)));
          if (selectedDetailTaskId && idsToDelete.includes(selectedDetailTaskId)) {
            setSelectedDetailTaskId(null);
          }
        }
      } else if (scope === 'all') {
        if (activeTab === 'all') {
          await deleteAllTasks('all');
          setSelectedIds([]);
          setSelectedDetailTaskId(null);
        } else {
          const idsToDelete = filteredTasks.map((t) => t.task_id);
          if (idsToDelete.length > 0) {
            await batchDeleteTasks(idsToDelete);
            setSelectedIds((prev) => prev.filter((id) => !idsToDelete.includes(id)));
            if (selectedDetailTaskId && idsToDelete.includes(selectedDetailTaskId)) {
              setSelectedDetailTaskId(null);
            }
          }
        }
      }
      closeDeleteModal();
      await refetch();
    } catch (err) {
      console.error('Delete error:', err);
      alert('삭제 중 오류가 발생했습니다: ' + (err.response?.data?.detail || err.message));
    } finally {
      setIsDeleting(false);
    }
  };

  const renderDeleteModal = () => {
    if (!deleteModalState.isOpen) return null;
    const { scope, task } = deleteModalState;
    const selectedCount = selectedIds.filter((id) => filteredTasks.some((t) => t.task_id === id)).length;
    const allCount = filteredTasks.length;

    let title = '작업 영구 삭제';
    let targetDesc = '';
    let confirmBtnText = '영구 삭제';

    if (scope === 'all') {
      title = activeTab === 'all'
        ? `전체 작업 및 자막 영구 삭제 (${allCount}건)`
        : activeTab === 'studio'
        ? `스튜디오 완료건 전체 삭제 (${allCount}건)`
        : `번역 완료건 전체 삭제 (${allCount}건)`;
      targetDesc = `현재 보관함의 전체 ${allCount}개 작업과 생성된 모든 자막(.srt) 및 목록`;
      confirmBtnText = `전체 영구 삭제 (${allCount}건)`;
    } else if (scope === 'selected') {
      title = `선택한 작업 및 자막 삭제 (${selectedCount}건)`;
      targetDesc = `선택하신 ${selectedCount}개 작업과 생성된 자막(.srt) 및 목록`;
      confirmBtnText = `선택 항목 삭제 (${selectedCount}건)`;
    } else {
      title = '작업 영구 삭제';
      targetDesc = `"${task?.filename || '해당 작업'}"`;
      confirmBtnText = '영구 삭제';
    }

    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/75 backdrop-blur-sm animate-in fade-in">
        <div className="w-full max-w-md p-6 bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl space-y-4">
          <div className="flex items-center space-x-3 text-rose-400">
            <div className="p-2.5 rounded-xl bg-rose-500/15 border border-rose-500/30">
              <AlertTriangle className="w-5 h-5 text-rose-400" />
            </div>
            <h3 className="text-base font-bold text-white">{title}</h3>
          </div>

          <p className="text-xs text-slate-300 leading-relaxed">
            정말로 <strong className="text-rose-300 font-semibold">{targetDesc}</strong>을(를) 모두 영구 삭제하시겠습니까?
          </p>
          <div className="p-3.5 rounded-xl bg-slate-950/70 border border-slate-800/80 text-[11px] text-slate-400 space-y-1.5">
            <p className="font-semibold text-slate-300">🗑️ 삭제 시 수행되는 작업:</p>
            <ul className="list-disc list-inside space-y-0.5 text-slate-400">
              <li>PostgreSQL 데이터베이스의 작업 및 자막 레코드 완전 삭제</li>
              <li>디스크에 저장된 생성 자막 파일(.srt) 및 목록 영구 삭제</li>
              <li>서버 원본 동영상, 추출 오디오(.wav), 중간 캐시 파일(.json) 일괄 정리</li>
            </ul>
          </div>

          <div className="flex items-center justify-end space-x-2.5 pt-2">
            <button
              type="button"
              onClick={closeDeleteModal}
              disabled={isDeleting}
              className="px-4 py-2 text-xs font-medium text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 rounded-xl transition"
            >
              취소
            </button>
            <button
              type="button"
              onClick={executeDelete}
              disabled={isDeleting}
              className="flex items-center space-x-1.5 px-4 py-2 text-xs font-semibold text-white bg-rose-600 hover:bg-rose-500 disabled:opacity-50 rounded-xl transition shadow-lg shadow-rose-600/30"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>{isDeleting ? '삭제 중...' : confirmBtnText}</span>
            </button>
          </div>
        </div>
      </div>
    );
  };

  const formatDate = (isoString) => {
    if (!isoString) return '-';
    try {
      const d = new Date(isoString);
      return d.toLocaleString('ko-KR', {
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
      });
    } catch {
      return isoString;
    }
  };

  // If a completed task is selected, show its full interactive detail view
  if (selectedDetailTaskId) {
    return (
      <div className="py-2 space-y-6">
        {/* Navigation Top Bar */}
        <div className="flex items-center justify-between p-4 bg-slate-900 border border-slate-800 rounded-2xl shadow-lg">
          <button
            type="button"
            onClick={() => setSelectedDetailTaskId(null)}
            className="flex items-center space-x-2 px-3.5 py-2 text-xs font-semibold text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-xl transition-all"
          >
            <ArrowLeft className="w-4 h-4 text-indigo-400" />
            <span>← 완료 보관함 목록으로 돌아가기</span>
          </button>

          <div className="flex items-center space-x-3 text-xs text-slate-400">
            <div className="flex items-center space-x-2">
              <Film className="w-3.5 h-3.5 text-indigo-400" />
              <span className="font-semibold text-slate-200">{detailTask?.filename || '영상 상세'}</span>
              <span>•</span>
              <span>{detailTask?.subtitles?.length || 0}개 자막</span>
            </div>
            {detailTask && (
              <button
                type="button"
                onClick={() => openSingleDeleteModal(detailTask)}
                className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-semibold text-rose-300 hover:text-white bg-rose-500/15 hover:bg-rose-600 border border-rose-500/30 rounded-xl transition-all shadow-sm"
                title="이 완료 작업 영구 삭제"
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>작업 삭제</span>
              </button>
            )}
          </div>
        </div>

        {/* Delete Confirmation Modal for Detail View */}
        {renderDeleteModal()}

        {/* Loading detail */}
        {loadingDetail && (
          <div className="h-64 bg-slate-900/60 rounded-2xl animate-pulse border border-slate-800" />
        )}

        {/* Detail view contents */}
        {detailTask && (
          <div className="space-y-6">
            <CompletedBanner
              task={{
                ...detailTask,
                ...(allTasks.find((t) => t.task_id === selectedDetailTaskId) || {}),
                subtitles: detailTask.subtitles,
                subtitle_count: detailTask.subtitles?.length ?? detailTask.subtitle_count ?? 0,
              }}
              onReset={() => setSelectedDetailTaskId(null)}
              onGoToList={() => setSelectedDetailTaskId(null)}
              onTranslate={() => onTranslateTask && onTranslateTask(selectedDetailTaskId)}
              onDownloaded={() => refetch()}
            />

            <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 items-start">
              {/* Left Column: Video Preview */}
              <div className="lg:col-span-5 lg:sticky lg:top-20 space-y-4">
                <VideoPreview
                  ref={playerRef}
                  videoUrl={`/api/video/${selectedDetailTaskId}`}
                  subtitles={detailTask?.subtitles || []}
                />
                <div className="p-4 rounded-xl bg-slate-900 border border-slate-800 text-xs text-slate-400 space-y-1 shadow-md">
                  <p className="font-semibold text-slate-300">💡 팁:</p>
                  <p>자막 목록의 타임스탬프(예: #1, 00:01 → 00:04)를 클릭하면 영상이 해당 위치로 즉시 이동합니다.</p>
                </div>
              </div>

              {/* Right Column: Subtitle Editor */}
              <div className="lg:col-span-7">
                <SubtitleEditor
                  taskId={selectedDetailTaskId}
                  initialSubtitles={detailTask.subtitles}
                  onSeekVideo={handleSeekVideo}
                  onReset={() => setSelectedDetailTaskId(null)}
                  onSubtitlesUpdated={(newSubs) => {
                    setDetailTask((prev) => ({
                      ...prev,
                      subtitles: newSubs,
                      subtitle_count: newSubs.length,
                    }));
                    refetch();
                  }}
                />
              </div>
            </div>
          </div>
        )}
      </div>
    );
  }

  // Default: Completed Tasks Table List
  return (
    <div className="py-2 space-y-6">
      {/* Header Bar */}
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-6 bg-slate-900 border border-slate-800 rounded-2xl shadow-xl">
        <div>
          <div className="flex items-center space-x-2.5 flex-wrap gap-y-1">
            <div className="p-2 bg-emerald-500/10 text-emerald-400 rounded-xl border border-emerald-500/20">
              <FileCheck className="w-5 h-5" />
            </div>
            <h2 className="text-xl font-bold text-slate-100">자막 작업 완료 보관함</h2>
            <span className="px-2.5 py-0.5 text-xs font-semibold bg-emerald-500/20 text-emerald-300 rounded-full border border-emerald-500/30">
              {allTasks.length}건 완료
            </span>
            {downloadedCount > 0 && (
              <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 text-xs font-semibold bg-blue-500/20 text-blue-300 rounded-full border border-blue-500/30">
                <CheckCheck className="w-3.5 h-3.5 text-blue-400" />
                <span>다운로드 완료 {downloadedCount}건</span>
              </span>
            )}
            {unDownloadedCount > 0 && (
              <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 text-xs font-bold bg-emerald-500/20 text-emerald-300 rounded-full border border-emerald-500/40">
                <Sparkles className="w-3 h-3 text-emerald-400" />
                <span>미다운로드 {unDownloadedCount}건</span>
              </span>
            )}
          </div>
          <p className="text-xs text-slate-400 mt-1">
            PostgreSQL 데이터베이스에 영구 보관된 완성본입니다. 탭별로 스튜디오 추출 자막과 다국어 번역 자막을 분리하여 확인할 수 있습니다.
          </p>
        </div>

        <div className="flex items-center space-x-2.5 flex-wrap gap-y-2">
          {unDownloadedInCurrentTab.length > 0 && (
            <button
              type="button"
              onClick={handleBatchDownloadUndownloaded}
              disabled={isBatchDownloadingUndownloaded || isBatchDownloadingAll}
              className="flex items-center space-x-1.5 px-3.5 py-2 text-xs font-bold text-white bg-gradient-to-r from-emerald-600 via-teal-600 to-emerald-500 hover:from-emerald-500 hover:to-teal-400 rounded-xl transition-all shadow-md shadow-emerald-600/30 hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
              title={`현재 탭의 미다운로드 자막 ${unDownloadedInCurrentTab.length}건만 ZIP으로 일괄 다운로드합니다`}
            >
              {isBatchDownloadingUndownloaded ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin text-white" />
                  <span>미다운로드 압축 중...</span>
                </>
              ) : (
                <>
                  <Sparkles className="w-3.5 h-3.5 text-emerald-200" />
                  <span>미다운로드건 일괄 다운로드 ({unDownloadedInCurrentTab.length}건)</span>
                </>
              )}
            </button>
          )}

          {filteredTasks.length > 0 && (
            <button
              type="button"
              onClick={handleBatchDownloadAll}
              disabled={isBatchDownloadingAll || isBatchDownloadingUndownloaded}
              className="flex items-center space-x-1.5 px-3.5 py-2 text-xs font-bold text-white bg-gradient-to-r from-blue-600 via-indigo-600 to-violet-600 hover:from-blue-500 hover:to-indigo-500 rounded-xl transition-all shadow-md shadow-blue-600/30 hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
              title={`현재 탭의 전체 자막 ${filteredTasks.length}건을 ZIP으로 일괄 다운로드합니다`}
            >
              {isBatchDownloadingAll ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin text-white" />
                  <span>전체 압축 중...</span>
                </>
              ) : (
                <>
                  <Archive className="w-3.5 h-3.5 text-blue-200" />
                  <span>전체 일괄 다운로드 ({filteredTasks.length}건)</span>
                </>
              )}
            </button>
          )}

          <button
            onClick={() => refetch()}
            disabled={isFetching}
            className="flex items-center space-x-1.5 px-3 py-2 text-xs font-medium text-slate-300 hover:text-white bg-slate-800 hover:bg-slate-700 border border-slate-700 rounded-xl transition-all"
            title="새로고침"
          >
            <RefreshCw className={`w-3.5 h-3.5 ${isFetching ? 'animate-spin text-indigo-400' : ''}`} />
            <span>새로고침</span>
          </button>
          {onNewTask && (
            <button
              onClick={onNewTask}
              className="flex items-center space-x-1.5 px-4 py-2 text-xs font-semibold text-white bg-gradient-to-r from-indigo-600 to-indigo-500 hover:from-indigo-500 hover:to-indigo-400 rounded-xl transition-all shadow-md shadow-indigo-600/20"
            >
              <Sparkles className="w-3.5 h-3.5" />
              <span>새 영상 작업하기</span>
            </button>
          )}
        </div>
      </div>

      {/* Category Filter Tabs */}
      <div className="flex flex-wrap items-center gap-2 p-1.5 bg-slate-900 border border-slate-800 rounded-2xl shadow-lg">
        <button
          type="button"
          onClick={() => {
            setActiveTab('all');
            setCurrentPage(1);
          }}
          className={`flex items-center space-x-2 px-4 py-2.5 rounded-xl text-xs font-semibold transition-all ${
            activeTab === 'all'
              ? 'bg-gradient-to-r from-indigo-600 to-indigo-500 text-white shadow-md shadow-indigo-600/20'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
          }`}
        >
          <Layers className="w-4 h-4" />
          <span>전체 완료건</span>
          <span
            className={`px-2 py-0.5 rounded-full text-[11px] font-bold ${
              activeTab === 'all'
                ? 'bg-white/20 text-white'
                : 'bg-slate-800 text-slate-400'
            }`}
          >
            {allTasks.length}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setActiveTab('studio');
            setCurrentPage(1);
          }}
          className={`flex items-center space-x-2 px-4 py-2.5 rounded-xl text-xs font-semibold transition-all ${
            activeTab === 'studio'
              ? 'bg-gradient-to-r from-indigo-600 to-indigo-500 text-white shadow-md shadow-indigo-600/20'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
          }`}
        >
          <Film className="w-4 h-4" />
          <span>자막제작 스튜디오 완료건</span>
          <span
            className={`px-2 py-0.5 rounded-full text-[11px] font-bold ${
              activeTab === 'studio'
                ? 'bg-white/20 text-white'
                : 'bg-slate-800 text-slate-400'
            }`}
          >
            {studioTasks.length}
          </span>
        </button>

        <button
          type="button"
          onClick={() => {
            setActiveTab('translator');
            setCurrentPage(1);
          }}
          className={`flex items-center space-x-2 px-4 py-2.5 rounded-xl text-xs font-semibold transition-all ${
            activeTab === 'translator'
              ? 'bg-gradient-to-r from-sky-600 to-sky-500 text-white shadow-md shadow-sky-600/20'
              : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/60'
          }`}
        >
          <Languages className="w-4 h-4" />
          <span>자막번역기 작업완료건</span>
          <span
            className={`px-2 py-0.5 rounded-full text-[11px] font-bold ${
              activeTab === 'translator'
                ? 'bg-white/20 text-white'
                : 'bg-slate-800 text-slate-400'
            }`}
          >
            {translatorTasks.length}
          </span>
        </button>
      </div>

      {/* Loading Skeleton */}
      {isLoading && (
        <div className="space-y-3">
          {[1, 2, 3].map((n) => (
            <div key={n} className="h-20 bg-slate-900 rounded-2xl animate-pulse border border-slate-800" />
          ))}
        </div>
      )}

      {/* Empty State */}
      {!isLoading && filteredTasks.length === 0 && (
        <div className="text-center py-16 px-4 bg-slate-900/60 border border-dashed border-slate-800 rounded-2xl space-y-4">
          <div className="w-12 h-12 mx-auto rounded-full bg-slate-800 flex items-center justify-center text-slate-500">
            {activeTab === 'translator' ? (
              <Languages className="w-6 h-6 text-sky-400" />
            ) : (
              <Film className="w-6 h-6 text-indigo-400" />
            )}
          </div>
          <div className="space-y-1">
            <p className="text-base font-semibold text-slate-300">
              {activeTab === 'studio'
                ? '자막제작 스튜디오 완료건이 없습니다'
                : activeTab === 'translator'
                ? '자막번역기 작업완료건이 없습니다'
                : '완료된 자막 작업이 없습니다'}
            </p>
            <p className="text-xs text-slate-500 max-w-sm mx-auto">
              {activeTab === 'studio'
                ? '[자막 제작 스튜디오]에서 동영상을 업로드하면 AI 음성인식과 문맥 교정을 거쳐 이곳에 자동 보관됩니다.'
                : activeTab === 'translator'
                ? '[자막 번역기]에서 SRT 파일을 업로드하거나 스튜디오 자막을 다국어로 번역하면 이곳에 보관됩니다.'
                : '스튜디오 작업 또는 자막 번역 작업이 완료되면 이곳에 체계적으로 보관됩니다.'}
            </p>
          </div>
          {activeTab === 'translator' ? (
            onTranslateTask && (
              <button
                onClick={() => onTranslateTask()}
                className="inline-flex items-center space-x-2 px-4 py-2 text-xs font-semibold text-white bg-sky-600 hover:bg-sky-500 rounded-xl transition-all shadow-md"
              >
                <Languages className="w-3.5 h-3.5" />
                <span>자막 번역하러 가기</span>
              </button>
            )
          ) : (
            onNewTask && (
              <button
                onClick={onNewTask}
                className="inline-flex items-center space-x-2 px-4 py-2 text-xs font-semibold text-white bg-indigo-600 hover:bg-indigo-500 rounded-xl transition-all shadow-md"
              >
                <Sparkles className="w-3.5 h-3.5" />
                <span>첫 영상 자막 만들기</span>
              </button>
            )
          )}
        </div>
      )}

      {/* Batch Download Notification Bar */}
      {!isLoading && filteredTasks.length > 0 && (
        <div className="flex flex-col lg:flex-row lg:items-center justify-between gap-4 p-4 bg-gradient-to-r from-slate-900 via-slate-850 to-slate-900 border border-slate-800 rounded-2xl shadow-lg">
          <div className="flex items-center space-x-3 min-w-0">
            <div className="p-2.5 rounded-xl bg-indigo-500/15 border border-indigo-500/30 text-indigo-400 flex-shrink-0">
              <Archive className="w-5 h-5" />
            </div>
            <div>
              <div className="flex items-center space-x-2 flex-wrap">
                <span className="text-xs font-bold text-white">
                  자막 일괄 다운로드
                </span>
                <span className="px-2 py-0.5 text-[10px] font-semibold bg-slate-800 text-slate-300 rounded-full border border-slate-700">
                  총 {filteredTasks.length}건 (자막 보유 {downloadableInCurrentTab.length}건 • 미다운로드 {unDownloadedInCurrentTab.length}건)
                </span>
              </div>
              <p className="text-[11px] text-slate-400 mt-0.5">
                완료된 자막 전체를 한 번에 받거나, 아직 다운로드한 적이 없는 신규 자막만 선택하여 ZIP 압축 파일로 일괄 다운로드할 수 있습니다.
              </p>
            </div>
          </div>
          <div className="flex items-center space-x-2.5 flex-wrap gap-y-2 flex-shrink-0">
            {unDownloadedInCurrentTab.length > 0 && (
              <button
                type="button"
                onClick={handleBatchDownloadUndownloaded}
                disabled={isBatchDownloadingUndownloaded || isBatchDownloadingAll}
                className="flex items-center space-x-1.5 px-3.5 py-2.5 text-xs font-bold text-white bg-gradient-to-r from-emerald-600 to-teal-600 hover:from-emerald-500 hover:to-teal-500 rounded-xl transition-all shadow-md shadow-emerald-600/25 hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
                title={`미다운로드 자막 ${unDownloadedInCurrentTab.length}건만 ZIP으로 일괄 다운로드합니다`}
              >
                {isBatchDownloadingUndownloaded ? (
                  <>
                    <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                    <span>미다운로드 압축 중...</span>
                  </>
                ) : (
                  <>
                    <Sparkles className="w-3.5 h-3.5 text-emerald-200" />
                    <span>미다운로드건 일괄 다운로드 ({unDownloadedInCurrentTab.length}건 .zip)</span>
                  </>
                )}
              </button>
            )}
            <button
              type="button"
              onClick={handleBatchDownloadAll}
              disabled={isBatchDownloadingAll || isBatchDownloadingUndownloaded || downloadableInCurrentTab.length === 0}
              className="flex items-center space-x-1.5 px-3.5 py-2.5 text-xs font-bold text-white bg-gradient-to-r from-blue-600 to-indigo-600 hover:from-blue-500 hover:to-indigo-500 rounded-xl transition-all shadow-md shadow-blue-600/25 hover:scale-[1.02] active:scale-[0.98] disabled:opacity-50"
              title={`현재 탭의 다운로드 가능한 자막 ${downloadableInCurrentTab.length}건을 ZIP으로 일괄 다운로드합니다`}
            >
              {isBatchDownloadingAll ? (
                <>
                  <RefreshCw className="w-3.5 h-3.5 animate-spin" />
                  <span>전체 압축 중...</span>
                </>
              ) : (
                <>
                  <FolderDown className="w-3.5 h-3.5 text-blue-200" />
                  <span>전체 일괄 다운로드 ({downloadableInCurrentTab.length}건 .zip)</span>
                </>
              )}
            </button>
          </div>
        </div>
      )}

      {/* Selection & Batch Delete Management Bar */}
      {!isLoading && filteredTasks.length > 0 && (
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 px-4 py-3 bg-slate-900/90 border border-slate-800 rounded-2xl shadow-md">
          {/* Left: Checkbox Select Current Page / All & Selection Count */}
          <div className="flex items-center space-x-3 flex-wrap gap-y-1.5">
            <label className="flex items-center space-x-2.5 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={allCurrentPageSelected}
                onChange={handleToggleSelectCurrentPage}
                className="w-4 h-4 rounded text-indigo-600 bg-slate-800 border-slate-700 focus:ring-indigo-500 focus:ring-offset-slate-900 cursor-pointer"
              />
              <span className="text-xs font-semibold text-slate-200">
                현재 페이지 전체 선택 ({paginatedTasks.length}건)
              </span>
            </label>

            {totalPages > 1 && (
              <button
                type="button"
                onClick={handleToggleSelectAll}
                className="px-2.5 py-1 text-[11px] font-semibold rounded-lg bg-slate-800 hover:bg-slate-700 text-indigo-300 border border-indigo-500/30 transition"
              >
                {allFilteredSelected
                  ? `전체 페이지 선택 해제 (${filteredTasks.length}건)`
                  : `모든 페이지 전체 선택 (${filteredTasks.length}건)`}
              </button>
            )}

            <span className="text-xs text-slate-600">|</span>

            {selectedCountInCurrentTab > 0 ? (
              <span className="text-xs font-bold text-indigo-400 bg-indigo-500/15 px-2.5 py-0.5 rounded-lg border border-indigo-500/30">
                {selectedCountInCurrentTab}건 선택됨
              </span>
            ) : (
              <span className="text-xs text-slate-400">
                선택된 항목 없음
              </span>
            )}
          </div>

          {/* Right: Delete Action Buttons */}
          <div className="flex items-center space-x-2 flex-wrap gap-y-2">
            {selectedCountInCurrentTab > 0 && (
              <button
                type="button"
                onClick={openSelectedDeleteModal}
                className="flex items-center space-x-1.5 px-3 py-1.5 text-xs font-bold text-rose-300 hover:text-white bg-rose-500/15 hover:bg-rose-600 border border-rose-500/30 rounded-xl transition-all shadow-sm"
                title={`선택된 ${selectedCountInCurrentTab}개 작업과 자막 삭제`}
              >
                <Trash2 className="w-3.5 h-3.5" />
                <span>선택 삭제 ({selectedCountInCurrentTab}건)</span>
              </button>
            )}

            <button
              type="button"
              onClick={openAllDeleteModal}
              className="flex items-center space-x-1.5 px-3.5 py-1.5 text-xs font-bold text-rose-400 hover:text-white bg-rose-500/10 hover:bg-rose-600/90 border border-rose-500/25 hover:border-rose-500 rounded-xl transition-all shadow-sm"
              title="보관함의 모든 작업과 생성된 자막 및 파일 영구 삭제"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>전체 삭제 ({filteredTasks.length}건)</span>
            </button>
          </div>
        </div>
      )}

      {/* Top Pagination Bar (100 items per page) */}
      {!isLoading && filteredTasks.length > 0 && renderPaginationBar()}

      {/* Task Rows List (100 items per page) */}
      {!isLoading && paginatedTasks.length > 0 && (
        <div className="space-y-3">
          {paginatedTasks.map((task, idx) => {
            const itemNumber = startIndex + idx + 1;
            const isSelected = selectedIds.includes(task.task_id);
            const isTranslator = getTaskType(task) === 'translator';
            const isDownloaded = (task.download_count || 0) > 0 || task.downloaded;
            const downloadCount = task.download_count || 0;
            const subCount = task.subtitle_count ?? task.subtitles?.length ?? 0;
            const hasSubtitles = subCount > 0;

            return (
              <div
                key={task.task_id}
                onClick={() => setSelectedDetailTaskId(task.task_id)}
                className={`group p-5 rounded-2xl transition-all cursor-pointer shadow-lg flex flex-col md:flex-row md:items-center justify-between gap-4 border-l-4 ${
                  isSelected
                    ? 'bg-indigo-950/25 border-indigo-500/50 border-l-indigo-500 ring-1 ring-indigo-500/40 shadow-indigo-500/10'
                    : !hasSubtitles
                    ? 'bg-slate-900/60 hover:bg-slate-850/80 border border-amber-500/25 hover:border-amber-500/40 border-l-amber-500'
                    : isDownloaded
                    ? 'bg-slate-900/60 hover:bg-slate-850/80 border border-slate-800/80 hover:border-slate-700 border-l-blue-500 hover:shadow-blue-500/5'
                    : 'bg-gradient-to-r from-slate-900 via-slate-900 to-emerald-950/25 hover:bg-slate-850 border border-emerald-500/35 hover:border-emerald-400/50 border-l-emerald-500 shadow-emerald-500/10'
                }`}
              >
                <div className="flex items-start space-x-3.5 min-w-0">
                  {/* Checkbox for batch selection */}
                  <div
                    onClick={(e) => {
                      e.stopPropagation();
                      toggleSelectTask(task.task_id);
                    }}
                    className="pt-3 pr-1 flex items-center cursor-pointer"
                    title={isSelected ? '선택 해제' : '선택'}
                  >
                    <input
                      type="checkbox"
                      checked={isSelected}
                      onChange={(e) => {
                        e.stopPropagation();
                        toggleSelectTask(task.task_id);
                      }}
                      className="w-4 h-4 rounded text-indigo-600 bg-slate-800 border-slate-700 focus:ring-indigo-500 focus:ring-offset-slate-900 cursor-pointer"
                    />
                  </div>

                  <div
                    className={`p-3 rounded-xl border transition-all flex-shrink-0 mt-0.5 ${
                      !hasSubtitles
                        ? 'bg-amber-500/10 text-amber-400 border-amber-500/20'
                        : isDownloaded
                        ? 'bg-blue-500/10 text-blue-400 group-hover:bg-blue-500/20 group-hover:text-blue-300 border-blue-500/20'
                        : isTranslator
                        ? 'bg-sky-500/10 text-sky-400 group-hover:bg-sky-500/20 group-hover:text-sky-300 border-sky-500/20'
                        : 'bg-emerald-500/10 text-emerald-400 group-hover:bg-emerald-500/20 group-hover:text-emerald-300 border-emerald-500/20'
                    }`}
                  >
                    {!hasSubtitles ? (
                      <AlertCircle className="w-5 h-5" />
                    ) : isDownloaded ? (
                      <CheckCheck className="w-5 h-5" />
                    ) : isTranslator ? (
                      <Languages className="w-5 h-5" />
                    ) : (
                      <Film className="w-5 h-5" />
                    )}
                  </div>
                  <div className="space-y-1.5 min-w-0">
                    <div className="flex items-center space-x-2.5 flex-wrap gap-y-1">
                      <span className="inline-flex items-center px-2 py-0.5 rounded-md text-[11px] font-bold font-mono bg-slate-800 text-slate-400 border border-slate-700">
                        #{itemNumber}
                      </span>
                      {isTranslator ? (
                        <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-md text-[11px] font-semibold bg-sky-500/15 text-sky-300 border border-sky-500/30">
                          <Languages className="w-3 h-3 text-sky-400" />
                          <span>자막 번역</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-md text-[11px] font-semibold bg-indigo-500/15 text-indigo-300 border border-indigo-500/30">
                          <Film className="w-3 h-3 text-indigo-400" />
                          <span>스튜디오 추출</span>
                        </span>
                      )}

                      {/* Download Status Badge with distinct colors */}
                      {!hasSubtitles ? (
                        <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-amber-500/15 text-amber-300 border border-amber-500/30">
                          <AlertCircle className="w-3 h-3 text-amber-400" />
                          <span>자막 미생성 (0건)</span>
                        </span>
                      ) : isDownloaded ? (
                        <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-[11px] font-semibold bg-blue-500/15 text-blue-300 border border-blue-500/30">
                          <CheckCheck className="w-3 h-3 text-blue-400" />
                          <span>다운로드 완료{downloadCount > 1 ? ` (${downloadCount}회)` : ''}</span>
                        </span>
                      ) : (
                        <span className="inline-flex items-center space-x-1 px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/40 animate-pulse">
                          <Sparkles className="w-3 h-3 text-emerald-400" />
                          <span>신규 (미다운로드)</span>
                        </span>
                      )}

                      <h3
                        className={`text-base font-semibold transition-colors truncate max-w-lg ${
                          !hasSubtitles
                            ? 'text-slate-200 group-hover:text-amber-200'
                            : isDownloaded
                            ? 'text-slate-300 group-hover:text-white'
                            : 'text-slate-100 group-hover:text-emerald-200 font-bold'
                        }`}
                      >
                        {task.filename}
                      </h3>
                      <span
                        className={`inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium border ${
                          !hasSubtitles
                            ? 'bg-amber-500/10 text-amber-300 border-amber-500/25'
                            : 'bg-slate-800 text-slate-300 border-slate-700'
                        }`}
                      >
                        {hasSubtitles ? `${subCount.toLocaleString()}개 자막` : '0개 자막'}
                      </span>
                    </div>
                    <div className="flex items-center space-x-4 text-xs text-slate-500 flex-wrap">
                      <span className="flex items-center space-x-1">
                        <Clock className="w-3.5 h-3.5 text-slate-400" />
                        <span>완료일: {formatDate(task.completed_at)}</span>
                      </span>
                      {task.last_downloaded_at && (
                        <span className="flex items-center space-x-1 text-blue-400/80">
                          <CheckCheck className="w-3.5 h-3.5" />
                          <span>최근 다운로드: {formatDate(task.last_downloaded_at)}</span>
                        </span>
                      )}
                      <span className="flex items-center space-x-1 font-mono text-[11px] text-slate-600">
                        <Hash className="w-3 h-3" />
                        <span>{task.task_id.slice(0, 8)}</span>
                      </span>
                    </div>
                  </div>
                </div>

                {/* Actions */}
                <div className="flex items-center space-x-2.5 self-end md:self-center flex-shrink-0">
                  {onTranslateTask && hasSubtitles && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        onTranslateTask(task.task_id);
                      }}
                      className="flex items-center space-x-1.5 px-3 py-2 text-xs font-semibold text-indigo-300 hover:text-white bg-indigo-500/15 hover:bg-indigo-500/25 border border-indigo-500/30 rounded-xl transition-all shadow-sm"
                      title="이 자막을 원하는 언어로 번역"
                    >
                      <Languages className="w-3.5 h-3.5" />
                      <span>다국어 번역</span>
                    </button>
                  )}
                  <button
                    type="button"
                    disabled={!hasSubtitles}
                    onClick={(e) => {
                      e.stopPropagation();
                      if (hasSubtitles) handleDownload(e, task);
                    }}
                    className={`flex items-center space-x-1.5 px-3.5 py-2 text-xs font-semibold rounded-xl transition-all shadow-sm ${
                      !hasSubtitles
                        ? 'opacity-50 cursor-not-allowed bg-slate-800 text-slate-500 border border-slate-700/60 shadow-none'
                        : isDownloaded
                        ? 'text-slate-300 bg-slate-800 hover:bg-slate-700 hover:text-white border border-slate-700'
                        : 'text-white bg-gradient-to-r from-emerald-600 via-teal-600 to-indigo-600 hover:from-emerald-500 hover:to-indigo-500 shadow-md shadow-emerald-600/25 font-bold hover:scale-[1.02]'
                    }`}
                    title={
                      !hasSubtitles
                        ? '생성된 자막이 없어 다운로드할 수 없습니다 (상세 보기에서 자막 추가 가능)'
                        : isDownloaded
                        ? `이미 ${downloadCount}회 다운로드됨 (클릭 시 다시 다운로드)`
                        : 'SRT 자막 파일 다운로드'
                    }
                  >
                    {!hasSubtitles ? (
                      <>
                        <Download className="w-3.5 h-3.5 text-slate-500" />
                        <span>자막 없음</span>
                      </>
                    ) : isDownloaded ? (
                      <>
                        <CheckCheck className="w-3.5 h-3.5 text-blue-400" />
                        <span>재다운로드 ({downloadCount}회)</span>
                      </>
                    ) : (
                      <>
                        <Download className="w-3.5 h-3.5 text-white" />
                        <span>SRT 다운로드</span>
                      </>
                    )}
                  </button>
                  <div className="flex items-center space-x-1 px-3 py-2 text-xs font-medium text-slate-300 group-hover:text-indigo-300 transition-colors">
                    <span>상세 보기 / 편집</span>
                    <ChevronRight className="w-4 h-4 text-slate-500 group-hover:text-indigo-400 group-hover:translate-x-0.5 transition-all" />
                  </div>
                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation();
                      openSingleDeleteModal(task);
                    }}
                    className="p-2 text-rose-400/80 hover:text-white bg-rose-500/10 hover:bg-rose-600/90 border border-rose-500/20 hover:border-rose-500 rounded-xl transition-all shadow-sm"
                    title="이 작업 및 관련 파일 모두 삭제"
                  >
                    <Trash2 className="w-3.5 h-3.5" />
                  </button>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {/* Bottom Pagination Bar (100 items per page) */}
      {!isLoading && filteredTasks.length > 0 && renderPaginationBar()}

      {/* Delete Confirmation Modal for List View */}
      {renderDeleteModal()}
    </div>
  );
}
