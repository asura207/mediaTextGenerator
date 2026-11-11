import { useState, useEffect, useRef, useCallback } from 'react';
import {
  uploadVideo,
  getTaskStatus,
  getStudioQueue,
  syncStudioQueue,
  deleteStudioQueueItem,
  clearCompletedStudioQueue,
  startNextStudioQueueItem,
  addFolderToStudioQueue
} from '../api/client';
import { requestNotificationPermission } from '../utils/notification';

export const VALID_EXTENSIONS = [
  'mp4', 'mkv', 'mov', 'avi', 'webm', 'flv', 'wmv', 'asf',
  'ts', 'm4v', 'mpg', 'mpeg', 'm2ts', 'mts', 'vob', 'ogv', '3gp'
];
const MAX_BATCH_SIZE = 5000;

export function useStudioQueue({ onTaskCompleted }) {
  const [queue, setQueue] = useState([]);
  const [isLoadingQueue, setIsLoadingQueue] = useState(true);
  const [activeItemState, setActiveItemState] = useState(null);
  const activeItemRef = useRef(null);
  const queueRef = useRef([]);
  queueRef.current = queue;

  // Persistent map of browser File objects so async server merges never wipe out File references
  const fileMapRef = useRef(new Map());

  const updateActiveItem = useCallback((item) => {
    activeItemRef.current = item;
    setActiveItemState(item);
  }, []);

  const onTaskCompletedRef = useRef(onTaskCompleted);
  onTaskCompletedRef.current = onTaskCompleted;

  const isWorkingRef = useRef(false);
  const isPollingRef = useRef(false);
  const clientIdRef = useRef(`client_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`);
  const notifiedTaskIdsRef = useRef(new Set());

  // Add video files to queue (Supports recursive subfolder scanning & multi-file selection)
  const addVideos = useCallback((fileList) => {
    requestNotificationPermission().catch(() => {});

    const rawFiles = Array.from(fileList || []);
    if (rawFiles.length === 0) return { count: 0, warning: null, info: null };

    const getRelPath = (file) =>
      (file.webkitRelativePath || file.relativePath || file.name || '')
        .replace(/\\/g, '/')
        .replace(/^\/+/, '');

    const videoFiles = [];
    const nonVideoFiles = [];

    rawFiles.forEach((file) => {
      const ext = file.name.split('.').pop().toLowerCase();
      if (VALID_EXTENSIONS.includes(ext)) {
        videoFiles.push(file);
      } else {
        nonVideoFiles.push(file.name);
      }
    });

    if (videoFiles.length === 0) {
      return {
        count: 0,
        warning: '선택한 폴더(하위 폴더 포함) 또는 파일에 지원되는 동영상 파일이 없습니다.',
        info: null
      };
    }

    // Natural alphanumeric sorting by full relative subfolder path + filename
    videoFiles.sort((a, b) =>
      getRelPath(a).localeCompare(getRelPath(b), undefined, { numeric: true, sensitivity: 'base' })
    );

    let filesToAdd = videoFiles;
    let warning = null;

    if (videoFiles.length > MAX_BATCH_SIZE) {
      filesToAdd = videoFiles.slice(0, MAX_BATCH_SIZE);
      warning = `한 번에 최대 ${MAX_BATCH_SIZE}개 영상까지 등록할 수 있어 상위 ${MAX_BATCH_SIZE}개가 대기열에 추가되었습니다.`;
    }

    // Count distinct subfolders
    const subfolderSet = new Set();
    filesToAdd.forEach((file) => {
      const rel = getRelPath(file);
      const parts = rel.split('/');
      if (parts.length > 1) {
        subfolderSet.add(parts.slice(0, -1).join('/'));
      }
    });
    const hasNestedSubfolders =
      subfolderSet.size > 1 ||
      filesToAdd.some((f) => getRelPath(f).split('/').length > 2);

    const validItems = filesToAdd.map((file, idx) => {
      const id = `studio_${Date.now()}_${idx}_${Math.random().toString(36).substring(2, 8)}`;
      const rel = getRelPath(file);
      const displayFilename = hasNestedSubfolders && rel.includes('/') ? rel : file.name;

      fileMapRef.current.set(id, file);
      fileMapRef.current.set(displayFilename, file);
      fileMapRef.current.set(rel, file);
      fileMapRef.current.set(`${displayFilename}_${file.size}`, file);
      fileMapRef.current.set(`${file.name}_${file.size}`, file);
      if (!hasNestedSubfolders) {
        fileMapRef.current.set(file.name, file);
      }

      return {
        id,
        file,
        filename: displayFilename,
        relativePath: rel,
        size: file.size,
        status: 'WAITING', // WAITING | UPLOADING | PROCESSING | COMPLETED | FAILED
        uploadProgress: 0,
        taskId: null,
        taskData: null,
        error: null,
        addedAt: new Date().toISOString(),
        clientId: clientIdRef.current
      };
    });

    setQueue((prev) => {
      const updated = [...prev.filter((it) => it.status !== 'COMPLETED'), ...validItems];
      queueRef.current = updated;
      // Immediately sync with backend so other tabs/browsers can see the newly queued items
      syncStudioQueue(updated, clientIdRef.current).catch(() => {});
      return updated;
    });

    const folderInfo =
      subfolderSet.size > 1
        ? `하위 폴더 ${subfolderSet.size}곳을 모두 검색하여 동영상 총 ${validItems.length}개가 대기열에 등록되었습니다.`
        : `동영상 ${validItems.length}개가 대기열에 등록되었습니다.`;

    return {
      count: validItems.length,
      warning,
      info: folderInfo
    };
  }, []);

  // Add all videos from a server/local folder path (recursively scans all subfolders via backend os.walk)
  const addServerFolder = useCallback(
    async (folderPath) => {
      requestNotificationPermission().catch(() => {});
      const res = await addFolderToStudioQueue(folderPath, clientIdRef.current);
      if (res?.queue_state?.queue) {
        const filtered = res.queue_state.queue.filter((it) => it.status !== 'COMPLETED');
        queueRef.current = filtered;
        setQueue(filtered);
        if (res.queue_state.activeItem) {
          updateActiveItem(res.queue_state.activeItem);
        }
      }
      return res;
    },
    [updateActiveItem]
  );

  // Remove item from queue (syncs with backend)
  const removeQueueItem = useCallback((id) => {
    setQueue((prev) => {
      const next = prev.filter((item) => item.id !== id);
      queueRef.current = next;
      return next;
    });
    deleteStudioQueueItem(id).catch(() => {});
  }, []);

  // Clear completed or failed items (syncs with backend)
  const clearCompleted = useCallback(() => {
    setQueue((prev) => {
      const next = prev.filter((item) => item.status !== 'COMPLETED' && item.status !== 'FAILED');
      queueRef.current = next;
      return next;
    });
    clearCompletedStudioQueue().catch(() => {});
  }, []);

  // Main Queue Worker & Server Sync Effect
  useEffect(() => {
    let isMounted = true;

    const processQueue = async () => {
      if (!isMounted || isPollingRef.current) return;
      isPollingRef.current = true;

      try {
        const prevActiveBeforeSync = activeItemRef.current;

        // 1. Fetch unified server queue (includes active tasks running on server and waiting items)
        try {
          const serverData = await getStudioQueue();
          if (!isMounted) return;

          if (serverData && Array.isArray(serverData.queue)) {
            // Read fresh queueRef.current AFTER await so newly added files are never overwritten
            const latestQueue = queueRef.current;
            const prevMap = new Map(latestQueue.map((it) => [it.id, it]));
            const prevTaskMap = new Map(
              latestQueue.filter((it) => it.taskId).map((it) => [it.taskId, it])
            );

            // Merge server queue items and strip COMPLETED items
            const merged = [];
            for (const sItem of serverData.queue) {
              const local = prevMap.get(sItem.id) || (sItem.taskId ? prevTaskMap.get(sItem.taskId) : null);
              const isLocalUploading = local?.status === 'UPLOADING' && local?.file && isWorkingRef.current;

              // Notify completion and remove from studio queue if COMPLETED
              if (sItem.status === 'COMPLETED') {
                if (sItem.taskId && !notifiedTaskIdsRef.current.has(sItem.taskId)) {
                  notifiedTaskIdsRef.current.add(sItem.taskId);
                  if (onTaskCompletedRef.current) {
                    onTaskCompletedRef.current(sItem.taskData || { task_id: sItem.taskId, filename: sItem.filename });
                  }
                }
                deleteStudioQueueItem(sItem.id).catch(() => {});
                continue;
              }

              const restoredFile =
                local?.file ||
                fileMapRef.current.get(sItem.id) ||
                fileMapRef.current.get(`${sItem.filename}_${sItem.size}`) ||
                fileMapRef.current.get(sItem.filename) ||
                null;

              const resolvedError =
                sItem.error ||
                sItem.taskData?.error ||
                local?.error ||
                local?.taskData?.error ||
                null;

              merged.push({
                ...sItem,
                file: restoredFile,
                status: isLocalUploading ? 'UPLOADING' : sItem.status,
                uploadProgress: isLocalUploading ? local.uploadProgress : sItem.uploadProgress,
                error: resolvedError,
                taskData: sItem.status === 'WAITING' ? null : (sItem.taskData || local?.taskData || null)
              });
            }

            // Preserve local WAITING/UPLOADING items that were just added and not yet in server response
            const serverIds = new Set(merged.map((it) => it.id));
            latestQueue.forEach((local) => {
              if (!serverIds.has(local.id) && (local.status === 'WAITING' || local.status === 'UPLOADING')) {
                const f =
                  local.file ||
                  fileMapRef.current.get(local.id) ||
                  fileMapRef.current.get(`${local.filename}_${local.size}`) ||
                  fileMapRef.current.get(local.filename) ||
                  null;
                merged.push({ ...local, file: f });
              }
            });

            queueRef.current = merged;
            setQueue(merged);

            // Check if previous active item finished and was auto-removed on the server
            if (
              prevActiveBeforeSync?.taskId &&
              (!serverData.activeItem || serverData.activeItem.taskId !== prevActiveBeforeSync.taskId) &&
              !notifiedTaskIdsRef.current.has(prevActiveBeforeSync.taskId)
            ) {
              getTaskStatus(prevActiveBeforeSync.taskId)
                .then((st) => {
                  if (st?.status === 'COMPLETED' && !notifiedTaskIdsRef.current.has(prevActiveBeforeSync.taskId)) {
                    notifiedTaskIdsRef.current.add(prevActiveBeforeSync.taskId);
                    if (onTaskCompletedRef.current) {
                      onTaskCompletedRef.current(st);
                    }
                  }
                })
                .catch(() => {});
            }

            // Update activeItem synchronously
            if (serverData.activeItem && serverData.activeItem.status !== 'COMPLETED' && serverData.activeItem.status !== 'FAILED') {
              updateActiveItem(serverData.activeItem);
            } else {
              const stillActive = merged.find(
                (it) => it.status === 'PROCESSING' || (it.status === 'UPLOADING' && isWorkingRef.current)
              );
              updateActiveItem(stillActive || null);
            }
          }
        } catch (err) {
          // Continue queue processing if network temporarily fails
        } finally {
          if (isMounted) {
            setIsLoadingQueue(false);
          }
        }

        let currentQueue = queueRef.current;

        // 2. Check current active items using locked state or queue reference
        let activeItem =
          activeItemRef.current ||
          currentQueue.find(
            (it) => it.status === 'PROCESSING' || (it.status === 'UPLOADING' && isWorkingRef.current)
          );

        // Self-heal: If an item in queue has status 'UPLOADING' but no upload is running, reset to 'WAITING'
        if (!isWorkingRef.current) {
          const stuckItems = currentQueue.filter((it) => it.status === 'UPLOADING' && !it.taskId);
          if (stuckItems.length > 0) {
            currentQueue = currentQueue.map((it) =>
              it.status === 'UPLOADING' && !it.taskId ? { ...it, status: 'WAITING', uploadProgress: 0 } : it
            );
            queueRef.current = currentQueue;
            setQueue(currentQueue);
            syncStudioQueue(currentQueue, clientIdRef.current).catch(() => {});
            activeItem = activeItemRef.current || currentQueue.find((it) => it.status === 'PROCESSING');
          }
        }

        // 3. If an item is actively processing on this client with taskId, poll status directly
        if (activeItem && activeItem.status === 'PROCESSING' && activeItem.taskId) {
          try {
            const statusData = await getTaskStatus(activeItem.taskId);
            if (!isMounted) return;

            if (statusData.status === 'COMPLETED') {
              if (!notifiedTaskIdsRef.current.has(activeItem.taskId)) {
                notifiedTaskIdsRef.current.add(activeItem.taskId);
                if (onTaskCompletedRef.current) {
                  onTaskCompletedRef.current(statusData);
                }
              }

              // Remove completed item from studio queue immediately
              const completedId = activeItem.id;
              currentQueue = queueRef.current.filter(
                (it) => it.id !== completedId && it.taskId !== activeItem.taskId && it.status !== 'COMPLETED'
              );
              queueRef.current = currentQueue;
              setQueue(currentQueue);
              updateActiveItem(null);
              deleteStudioQueueItem(completedId).catch(() => {});

              // Clear activeItem so Step 4 immediately starts the next waiting item
              activeItem = null;
            } else if (statusData.status === 'FAILED') {
              const errMsg = statusData.error || activeItem.error || '동영상 처리 중 오류가 발생했습니다.';
              currentQueue = queueRef.current.map((it) =>
                it.id === activeItem.id || it.taskId === activeItem.taskId
                  ? {
                      ...it,
                      taskData: statusData,
                      status: 'FAILED',
                      error: errMsg
                    }
                  : it
              );
              queueRef.current = currentQueue;
              setQueue(currentQueue);
              updateActiveItem(null);
              syncStudioQueue(currentQueue, clientIdRef.current).catch(() => {});

              // Clear activeItem so Step 4 immediately advances to the next waiting item!
              activeItem = null;
            } else {
              // Still processing, update progress
              const updatedActive = {
                ...activeItem,
                taskData: statusData,
                status: statusData.status || activeItem.status
              };
              updateActiveItem(updatedActive);

              currentQueue = queueRef.current.map((it) =>
                it.id === activeItem.id || it.taskId === activeItem.taskId
                  ? { ...it, taskData: statusData, status: statusData.status || it.status }
                  : it
              );
              queueRef.current = currentQueue;
              setQueue(currentQueue);
              return;
            }
          } catch (err) {
            return;
          }
        }

        // 4. If nothing is uploading or processing, start next WAITING item automatically!
        if (!activeItem && !isWorkingRef.current) {
          const nextItem = currentQueue.find((it) => it.status === 'WAITING');
          if (nextItem) {
            // First check if server can auto-start next waiting item directly from local/server disk
            let startedOnServer = false;
            try {
              const res = await startNextStudioQueueItem();
              if (res && res.started && res.task_id) {
                startedOnServer = true;
                const targetId = res.queue_id || nextItem.id;
                currentQueue = queueRef.current.map((it) =>
                  it.id === targetId || (res.filename && it.filename === res.filename && it.status === 'WAITING')
                    ? {
                        ...it,
                        taskId: res.task_id,
                        status: 'PROCESSING',
                        uploadProgress: 100
                      }
                    : it
                );
                queueRef.current = currentQueue;
                setQueue(currentQueue);
                const newActive = currentQueue.find((it) => it.taskId === res.task_id);
                if (newActive) {
                  updateActiveItem(newActive);
                }
              }
            } catch (_) {}

            if (!startedOnServer) {
              const fileObj =
                nextItem.file ||
                fileMapRef.current.get(nextItem.id) ||
                fileMapRef.current.get(`${nextItem.filename}_${nextItem.size}`) ||
                fileMapRef.current.get(nextItem.filename) ||
                null;

              // Case 4A: Local client holds File object -> Stream upload on demand!
              if (fileObj) {
                isWorkingRef.current = true;

                // Mark as UPLOADING locally and notify server
                currentQueue = queueRef.current.map((it) =>
                  it.id === nextItem.id ? { ...it, file: fileObj, status: 'UPLOADING', uploadProgress: 0 } : it
                );
                queueRef.current = currentQueue;
                setQueue(currentQueue);
                updateActiveItem({ ...nextItem, file: fileObj, status: 'UPLOADING', uploadProgress: 0 });
                syncStudioQueue(currentQueue, clientIdRef.current).catch(() => {});

                try {
                  // Upload the file on demand (Deferred Upload)
                  const uploadRes = await uploadVideo(
                    fileObj,
                    (pct) => {
                      if (!isMounted) return;
                      setQueue((prev) => {
                        const next = prev.map((it) => (it.id === nextItem.id ? { ...it, uploadProgress: pct } : it));
                        queueRef.current = next;
                        return next;
                      });
                    },
                    { queueId: nextItem.id, relativePath: nextItem.filename }
                  );

                  if (!isMounted) return;

                  // Transition to PROCESSING and sync taskId to server
                  currentQueue = queueRef.current.map((it) =>
                    it.id === nextItem.id
                      ? {
                          ...it,
                          taskId: uploadRes.task_id,
                          status: 'PROCESSING',
                          uploadProgress: 100
                        }
                      : it
                  );
                  queueRef.current = currentQueue;
                  setQueue(currentQueue);
                  const startedItem = currentQueue.find((it) => it.id === nextItem.id);
                  if (startedItem) {
                    updateActiveItem(startedItem);
                  }
                  syncStudioQueue(currentQueue, clientIdRef.current).catch(() => {});
                } catch (err) {
                  if (!isMounted) return;
                  const uploadErrMsg = err.response?.data?.detail || err.message || '동영상 파일 업로드 실패';
                  currentQueue = queueRef.current.map((it) =>
                    it.id === nextItem.id
                      ? {
                          ...it,
                          status: 'FAILED',
                          error: uploadErrMsg
                        }
                      : it
                  );
                  queueRef.current = currentQueue;
                  setQueue(currentQueue);
                  updateActiveItem(null);
                  syncStudioQueue(currentQueue, clientIdRef.current).catch(() => {});
                } finally {
                  isWorkingRef.current = false;
                }
              }
            }
          }
        }
      } finally {
        isPollingRef.current = false;
      }
    };

    // Initial immediate sync on mount
    processQueue();
    const timerId = setInterval(processQueue, 1500);

    return () => {
      isMounted = false;
      clearInterval(timerId);
    };
  }, [updateActiveItem]);

  const activeItem = activeItemState || queue.find((it) => it.status === 'UPLOADING' || it.status === 'PROCESSING') || null;
  const waitingCount = queue.filter((it) => it.status === 'WAITING').length;
  const isBusy = !!activeItem;

  return {
    queue,
    activeItem,
    waitingCount,
    isBusy,
    isLoadingQueue,
    addVideos,
    addServerFolder,
    removeQueueItem,
    clearCompleted
  };
}

