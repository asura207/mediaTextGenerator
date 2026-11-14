import axios from 'axios';
import { saveAs } from 'file-saver';

const api = axios.create({
  baseURL: '/api',
});

export const uploadVideo = async (file, onUploadProgress, options = {}) => {
  const formData = new FormData();
  formData.append('file', file);
  if (options.queueId) {
    formData.append('queue_id', options.queueId);
  }
  if (options.relativePath) {
    formData.append('relative_path', options.relativePath);
  }

  const response = await api.post('/upload', formData, {
    headers: {
      'Content-Type': 'multipart/form-data',
    },
    signal: options.signal,
    onUploadProgress: (progressEvent) => {
      const total = progressEvent.total || file?.size || 0;
      if (total > 0 && typeof onUploadProgress === 'function') {
        const percentCompleted = Math.min(
          100,
          Math.max(0, Math.round((progressEvent.loaded * 100) / total))
        );
        onUploadProgress(percentCompleted);
      }
    },
  });
  return response.data;
};

export const getTaskStatus = async (taskId) => {
  const response = await api.get(`/tasks/${taskId}`);
  return response.data;
};

export const resumeTask = async (taskId) => {
  const response = await api.post(`/tasks/${taskId}/resume`);
  return response.data;
};

export const getCompletedTasks = async (taskType = null) => {
  const isString = typeof taskType === 'string' && taskType.trim() !== '';
  const params = isString ? { task_type: taskType } : {};
  const response = await api.get('/completed-tasks', { params });
  return response.data;
};

export const syncCompletedTasksFromDisk = async () => {
  const response = await api.post('/completed-tasks/sync-disk');
  return response.data;
};

export const updateSubtitles = async (taskId, subtitles) => {
  const response = await api.put(`/tasks/${taskId}/subtitles`, { subtitles });
  return response.data;
};

export const downloadSrtFile = async (taskId, filename = 'subtitles.srt') => {
  const response = await api.get(`/download/${taskId}`, {
    responseType: 'blob',
  });

  let targetFilename = filename;
  const disposition = response.headers?.['content-disposition'];
  if (disposition) {
    const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match && utf8Match[1]) {
      try {
        targetFilename = decodeURIComponent(utf8Match[1]);
      } catch (e) {
        // keep fallback
      }
    } else {
      const standardMatch = disposition.match(/filename="?([^";]+)"?/i);
      if (standardMatch && standardMatch[1] && standardMatch[1] !== 'subtitles.srt') {
        targetFilename = standardMatch[1];
      }
    }
  }

  saveAs(response.data, targetFilename);
};

export const detectLanguage = async ({ file, taskId }) => {
  const formData = new FormData();
  if (file) {
    formData.append('file', file);
  }
  if (taskId) {
    formData.append('task_id', taskId);
  }
  const response = await api.post('/translate/detect', formData);
  return response.data;
};

export const startTranslation = async ({ file, taskId, targetLang = 'ko' }) => {
  const formData = new FormData();
  if (file) {
    formData.append('file', file);
  }
  if (taskId) {
    formData.append('task_id', taskId);
  }
  formData.append('target_lang', targetLang);
  const response = await api.post('/translate/start', formData);
  return response.data;
};

export const getActiveTranslationTask = async () => {
  const response = await api.get('/translate/active');
  return response.data;
};

export const deleteTask = async (taskId) => {
  const response = await api.delete(`/tasks/${taskId}`);
  return response.data;
};

export const batchDeleteTasks = async (taskIds) => {
  const response = await api.post('/tasks/batch-delete', { task_ids: taskIds });
  return response.data;
};

export const deleteAllTasks = async (taskType = null) => {
  const params = taskType && taskType !== 'all' ? { task_type: taskType } : {};
  const response = await api.delete('/tasks/all', { params });
  return response.data;
};

export const trackTaskDownload = async (taskId) => {
  const response = await api.post(`/tasks/${taskId}/download-track`);
  return response.data;
};

export const batchDownloadAll = async (taskIds = null, taskType = null) => {
  const response = await api.post(
    '/download/batch-all',
    { task_ids: taskIds, task_type: taskType },
    { responseType: 'blob' }
  );

  let targetFilename = `transm_all_subtitles_${new Date().toISOString().slice(0, 10)}.zip`;
  const disposition = response.headers?.['content-disposition'];
  if (disposition) {
    const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match && utf8Match[1]) {
      try {
        targetFilename = decodeURIComponent(utf8Match[1]);
      } catch (e) {
        // fallback
      }
    } else {
      const standardMatch = disposition.match(/filename="?([^";]+)"?/i);
      if (standardMatch && standardMatch[1] && standardMatch[1] !== 'transm_subtitles.zip') {
        targetFilename = standardMatch[1];
      }
    }
  }

  saveAs(response.data, targetFilename);
  return response;
};

export const batchDownloadUndownloaded = async (taskIds = null, taskType = null) => {
  const response = await api.post(
    '/download/batch-undownloaded',
    { task_ids: taskIds, task_type: taskType },
    { responseType: 'blob' }
  );

  let targetFilename = `transm_subtitles_${new Date().toISOString().slice(0, 10)}.zip`;
  const disposition = response.headers?.['content-disposition'];
  if (disposition) {
    const utf8Match = disposition.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match && utf8Match[1]) {
      try {
        targetFilename = decodeURIComponent(utf8Match[1]);
      } catch (e) {
        // fallback
      }
    } else {
      const standardMatch = disposition.match(/filename="?([^";]+)"?/i);
      if (standardMatch && standardMatch[1] && standardMatch[1] !== 'transm_subtitles.zip') {
        targetFilename = standardMatch[1];
      }
    }
  }

  saveAs(response.data, targetFilename);
  return response;
};

export const getActiveSummary = async () => {
  const response = await api.get('/active-summary');
  return response.data;
};

export const getStudioQueue = async () => {
  const response = await api.get('/studio-queue');
  return response.data;
};

export const syncStudioQueue = async (items, clientId = null) => {
  const payload = {
    client_id: clientId,
    items: items.map((it) => ({
      id: it.id,
      filename: it.filename,
      size: it.size,
      status: it.status,
      upload_progress: it.uploadProgress || 0,
      task_id: it.taskId || null,
      error: it.error || null,
      client_id: clientId
    }))
  };
  const response = await api.post('/studio-queue/sync', payload);
  return response.data;
};

export const deleteStudioQueueItem = async (queueId) => {
  const response = await api.delete(`/studio-queue/${queueId}`);
  return response.data;
};

export const clearCompletedStudioQueue = async () => {
  const response = await api.post('/studio-queue/clear-completed');
  return response.data;
};

export const startNextStudioQueueItem = async () => {
  const response = await api.post('/studio-queue/start-next');
  return response.data;
};

export const getSystemSettings = async () => {
  const response = await api.get('/settings');
  return response.data;
};

export const updateSystemSettings = async (settings) => {
  const response = await api.post('/settings', settings);
  return response.data;
};

export const pullOllamaModel = async (modelName) => {
  const response = await api.post('/settings/pull-model', { model_name: modelName });
  return response.data;
};

export const requeueCompletedStudioQueue = async (resetProcessing = false) => {
  const response = await api.post('/studio-queue/requeue-completed', { reset_processing: resetProcessing });
  return response.data;
};

export const browseLocalFolders = async (path = '') => {
  const response = await api.get('/studio-queue/browse-folders', {
    params: path ? { path } : {}
  });
  return response.data;
};

export const addFolderToStudioQueue = async (folderPath, clientId = null) => {
  const response = await api.post('/studio-queue/add-folder', {
    folder_path: folderPath,
    client_id: clientId
  });
  return response.data;
};

// ==============================================================================
// Multi-Cloud LLM Connectivity Test API
// ==============================================================================

export const testCloudLLM = async ({ provider, apiKey = '', model = '' }) => {
  const response = await api.post('/settings/test-cloud-llm', {
    provider,
    api_key: apiKey,
    model,
  });
  return response.data;
};

// ==============================================================================
// Proper Noun Dictionary API (고유명사 사전)
// ==============================================================================

export const getDictionaryEntries = async (page = 1, size = 50, query = '') => {
  const params = { page, size };
  if (query && query.trim()) {
    params.query = query.trim();
  }
  const response = await api.get('/dictionary', { params });
  return response.data;
};

export const addDictionaryEntry = async ({ source_word, target_word, notes = '' }) => {
  const response = await api.post('/dictionary', {
    source_word,
    target_word,
    notes,
  });
  return response.data;
};

export const updateDictionaryEntry = async (entryId, { source_word, target_word, notes = '' }) => {
  const response = await api.put(`/dictionary/${entryId}`, {
    source_word,
    target_word,
    notes,
  });
  return response.data;
};

export const deleteDictionaryEntry = async (entryId) => {
  const response = await api.delete(`/dictionary/${entryId}`);
  return response.data;
};

export const batchDeleteDictionaryEntries = async (ids) => {
  const response = await api.post('/dictionary/batch-delete', { ids });
  return response.data;
};

export default api;

