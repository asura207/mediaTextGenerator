import { useState, useEffect, useRef, useCallback } from 'react';
import { startTranslation, getTaskStatus } from '../api/client';
import { requestNotificationPermission } from '../utils/notification';

const MAX_BATCH_SIZE = 10;

export function useTranslatorQueue({ onTaskCompleted }) {
  const [queue, setQueue] = useState([]);
  const isStartingRef = useRef(false);

  // Add multiple SRT files (Max 10 per batch)
  const addSrtFiles = useCallback((fileList, targetLang = 'ko') => {
    requestNotificationPermission().catch(() => {});
    const rawFiles = Array.from(fileList || []);
    if (rawFiles.length === 0) return { count: 0, warning: null };

    let filesToAdd = rawFiles;
    let warning = null;

    if (rawFiles.length > MAX_BATCH_SIZE) {
      filesToAdd = rawFiles.slice(0, MAX_BATCH_SIZE);
      warning = `한 번에 최대 ${MAX_BATCH_SIZE}개 파일까지 등록할 수 있어 상위 ${MAX_BATCH_SIZE}개 파일이 대기열에 추가되었습니다.`;
    }

    const validItems = [];
    const invalidNames = [];

    filesToAdd.forEach((file) => {
      if (file.name.toLowerCase().endsWith('.srt')) {
        validItems.push({
          id: `trans_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`,
          file,
          sourceTaskId: null,
          filename: file.name,
          targetLang,
          status: 'WAITING', // WAITING | STARTING | PROCESSING | COMPLETED | FAILED
          taskId: null,
          taskData: null,
          error: null,
          addedAt: new Date()
        });
      } else {
        invalidNames.push(file.name);
      }
    });

    if (invalidNames.length > 0) {
      const extWarning = `SRT 자막 파일이 아닌 항목 (${invalidNames.join(', ')})은 제외되었습니다.`;
      warning = warning ? `${warning}\n${extWarning}` : extWarning;
    }

    if (validItems.length > 0) {
      setQueue((prev) => [...prev, ...validItems]);
    }

    return { count: validItems.length, warning };
  }, []);

  // Add an existing task from studio to translation queue
  const addExistingTask = useCallback((taskId, filename, targetLang = 'ko') => {
    if (!taskId) return;
    const newItem = {
      id: `trans_${Date.now()}_${Math.random().toString(36).substring(2, 9)}`,
      file: null,
      sourceTaskId: taskId,
      filename: filename || '영상 자막',
      targetLang,
      status: 'WAITING',
      taskId: null,
      taskData: null,
      error: null,
      addedAt: new Date()
    };
    setQueue((prev) => [...prev, newItem]);
  }, []);

  // Remove item from queue
  const removeQueueItem = useCallback((id) => {
    setQueue((prev) => prev.filter((item) => item.id !== id));
  }, []);

  // Clear completed/failed items
  const clearCompleted = useCallback(() => {
    setQueue((prev) => prev.filter((item) => item.status !== 'COMPLETED' && item.status !== 'FAILED'));
  }, []);

  // Main Translation Queue Worker
  useEffect(() => {
    let timerId = null;

    const processQueue = async () => {
      const activeItem = queue.find((it) => it.status === 'STARTING' || it.status === 'PROCESSING');

      // 1. If an item is processing, poll status
      if (activeItem && activeItem.status === 'PROCESSING' && activeItem.taskId) {
        try {
          const statusData = await getTaskStatus(activeItem.taskId);
          setQueue((prev) =>
            prev.map((it) =>
              it.id === activeItem.id
                ? {
                    ...it,
                    taskData: statusData,
                    status:
                      statusData.status === 'COMPLETED'
                        ? 'COMPLETED'
                        : statusData.status === 'FAILED'
                        ? 'FAILED'
                        : 'PROCESSING',
                    error: statusData.error || it.error
                  }
                : it
            )
          );

          if (statusData.status === 'COMPLETED' && onTaskCompleted) {
            onTaskCompleted(statusData);
          }
        } catch (err) {
          // Continue polling
        }
        return;
      }

      // 2. If nothing is starting/processing, start next WAITING item
      if (!activeItem && !isStartingRef.current) {
        const nextItem = queue.find((it) => it.status === 'WAITING');
        if (nextItem) {
          isStartingRef.current = true;
          setQueue((prev) =>
            prev.map((it) => (it.id === nextItem.id ? { ...it, status: 'STARTING' } : it))
          );

          try {
            const res = await startTranslation({
              file: nextItem.file,
              taskId: nextItem.sourceTaskId,
              targetLang: nextItem.targetLang || 'ko'
            });

            setQueue((prev) =>
              prev.map((it) =>
                it.id === nextItem.id
                  ? {
                      ...it,
                      taskId: res.task_id,
                      status: 'PROCESSING'
                    }
                  : it
              )
            );
          } catch (err) {
            setQueue((prev) =>
              prev.map((it) =>
                it.id === nextItem.id
                  ? {
                      ...it,
                      status: 'FAILED',
                      error: err.response?.data?.detail || err.message || '번역 시작 실패'
                    }
                  : it
              )
            );
          } finally {
            isStartingRef.current = false;
          }
        }
      }
    };

    timerId = setInterval(processQueue, 1500);
    processQueue();

    return () => {
      if (timerId) clearInterval(timerId);
    };
  }, [queue, onTaskCompleted]);

  const activeItem = queue.find((it) => it.status === 'STARTING' || it.status === 'PROCESSING') || null;
  const waitingCount = queue.filter((it) => it.status === 'WAITING').length;
  const isBusy = !!activeItem;

  return {
    queue,
    activeItem,
    waitingCount,
    isBusy,
    addSrtFiles,
    addExistingTask,
    removeQueueItem,
    clearCompleted
  };
}

