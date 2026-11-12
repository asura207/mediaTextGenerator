import React, { useState, useEffect } from 'react';
import {
  Settings,
  Cpu,
  Sparkles,
  Mic,
  CheckCircle2,
  AlertCircle,
  Download,
  RefreshCw,
  RotateCcw,
  Save,
  Zap,
  Server,
  Layers,
  Database,
  Cloud,
  Key,
  Eye,
  EyeOff,
  Activity,
  Check
} from 'lucide-react';
import {
  getSystemSettings,
  updateSystemSettings,
  pullOllamaModel,
  requeueCompletedStudioQueue,
  testCloudLLM
} from '../api/client';

export default function AdminSettings({ onSettingsUpdated }) {
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [requeuing, setRequeuing] = useState(false);
  const [pulling, setPulling] = useState(false);
  const [pullTarget, setPullTarget] = useState('');

  const [ollamaModels, setOllamaModels] = useState([]);
  const [installedModels, setInstalledModels] = useState([]);
  const [whisperModels, setWhisperModels] = useState([]);
  const [whisperDevices, setWhisperDevices] = useState([]);
  const [whisperComputeTypes, setWhisperComputeTypes] = useState([]);
  const [ollamaHost, setOllamaHost] = useState('http://localhost:11434');
  const [dbInfo, setDbInfo] = useState({ type: 'sqlite', name: 'backend/data/transm.db' });

  // Cloud models catalog
  const [cloudModels, setCloudModels] = useState({
    openai: ['gpt-4o', 'gpt-4o-mini', 'o3-mini', 'gpt-4-turbo'],
    anthropic: ['claude-3-5-sonnet-latest', 'claude-3-5-haiku-latest', 'claude-3-opus-latest'],
    gemini: ['gemini-2.5-flash', 'gemini-2.5-pro', 'gemini-1.5-pro', 'gemini-1.5-flash']
  });

  // LLM Provider state
  const [llmProvider, setLlmProvider] = useState('ollama'); // 'ollama' | 'openai' | 'anthropic' | 'gemini'
  const [selectedOllamaModel, setSelectedOllamaModel] = useState('qwen2.5:14b');
  const [openaiApiKey, setOpenaiApiKey] = useState('');
  const [openaiModel, setOpenaiModel] = useState('gpt-4o');
  const [anthropicApiKey, setAnthropicApiKey] = useState('');
  const [anthropicModel, setAnthropicModel] = useState('claude-3-5-sonnet-latest');
  const [geminiApiKey, setGeminiApiKey] = useState('');
  const [geminiModel, setGeminiModel] = useState('gemini-2.5-flash');

  const [showKeys, setShowKeys] = useState({
    openai: false,
    anthropic: false,
    gemini: false
  });

  // Connectivity Test State
  const [testingProvider, setTestingProvider] = useState(null);
  const [testResults, setTestResults] = useState({});

  // Whisper & Batch form state
  const [selectedBatchSize, setSelectedBatchSize] = useState(10);
  const [selectedWhisperModel, setSelectedWhisperModel] = useState('large-v3-turbo');
  const [selectedWhisperDevice, setSelectedWhisperDevice] = useState('cuda');
  const [selectedWhisperCompute, setSelectedWhisperCompute] = useState('float16');
  const [requeueCompleted, setRequeueCompleted] = useState(true);

  const [statusMsg, setStatusMsg] = useState(null); // { type: 'success' | 'error' | 'info', text: '' }

  const loadSettings = async () => {
    setLoading(true);
    try {
      const data = await getSystemSettings();
      if (data?.current) {
        setLlmProvider(data.current.llm_provider || 'ollama');
        setSelectedOllamaModel(data.current.ollama_model || 'qwen2.5:14b');
        setOpenaiApiKey(data.current.openai_api_key || '');
        setOpenaiModel(data.current.openai_model || 'gpt-4o');
        setAnthropicApiKey(data.current.anthropic_api_key || '');
        setAnthropicModel(data.current.anthropic_model || 'claude-3-5-sonnet-latest');
        setGeminiApiKey(data.current.gemini_api_key || '');
        setGeminiModel(data.current.gemini_model || 'gemini-2.5-flash');

        setSelectedBatchSize(data.current.llm_batch_size || 10);
        setSelectedWhisperModel(data.current.whisper_model_size || 'large-v3-turbo');
        setSelectedWhisperDevice(data.current.whisper_device || 'cuda');
        setSelectedWhisperCompute(data.current.whisper_compute_type || 'float16');
      }
      if (data?.ollama_models) setOllamaModels(data.ollama_models);
      if (data?.installed_ollama_models) setInstalledModels(data.installed_ollama_models);
      if (data?.cloud_models) setCloudModels(data.cloud_models);
      if (data?.whisper_models) setWhisperModels(data.whisper_models);
      if (data?.whisper_devices) setWhisperDevices(data.whisper_devices);
      if (data?.whisper_compute_types) setWhisperComputeTypes(data.whisper_compute_types);
      if (data?.ollama_host) setOllamaHost(data.ollama_host);
      if (data?.db_type) {
        setDbInfo({
          type: data.db_type,
          name: data.connected_db || (data.db_type === 'sqlite' ? 'SQLite 파일 DB' : 'PostgreSQL RDB')
        });
      }
    } catch (err) {
      setStatusMsg({
        type: 'error',
        text: '서버 설정 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.'
      });
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadSettings();
  }, []);

  const handleTestConnection = async (targetProvider) => {
    setTestingProvider(targetProvider);
    setTestResults((prev) => ({ ...prev, [targetProvider]: null }));
    try {
      let apiKey = '';
      let model = '';
      if (targetProvider === 'openai') {
        apiKey = openaiApiKey;
        model = openaiModel;
      } else if (targetProvider === 'anthropic') {
        apiKey = anthropicApiKey;
        model = anthropicModel;
      } else if (targetProvider === 'gemini') {
        apiKey = geminiApiKey;
        model = geminiModel;
      } else if (targetProvider === 'ollama') {
        model = selectedOllamaModel;
      }

      const res = await testCloudLLM({
        provider: targetProvider,
        apiKey,
        model
      });
      setTestResults((prev) => ({
        ...prev,
        [targetProvider]: res
      }));
    } catch (err) {
      setTestResults((prev) => ({
        ...prev,
        [targetProvider]: {
          success: false,
          message: err.response?.data?.detail || err.message || '연결 테스트 요청 실패'
        }
      }));
    } finally {
      setTestingProvider(null);
    }
  };

  const handleSave = async (e) => {
    if (e) e.preventDefault();
    setSaving(true);
    setStatusMsg(null);
    try {
      const payload = {
        llm_provider: llmProvider,
        ollama_model: selectedOllamaModel,
        openai_api_key: openaiApiKey,
        openai_model: openaiModel,
        anthropic_api_key: anthropicApiKey,
        anthropic_model: anthropicModel,
        gemini_api_key: geminiApiKey,
        gemini_model: geminiModel,
        llm_batch_size: Number(selectedBatchSize),
        whisper_model_size: selectedWhisperModel,
        whisper_device: selectedWhisperDevice,
        whisper_compute_type: selectedWhisperCompute,
        requeue_completed: requeueCompleted
      };
      const res = await updateSystemSettings(payload);
      setStatusMsg({
        type: 'success',
        text: res?.message || 'LLM 및 Whisper 설정이 성공적으로 저장되어 즉시 적용되었습니다.'
      });
      if (onSettingsUpdated && res?.current) {
        onSettingsUpdated(res.current);
      }
    } catch (err) {
      setStatusMsg({
        type: 'error',
        text: err.response?.data?.detail || '설정 저장 중 오류가 발생했습니다.'
      });
    } finally {
      setSaving(false);
    }
  };

  const handleRequeueCompleted = async () => {
    if (requeuing) return;
    setRequeuing(true);
    setStatusMsg(null);
    try {
      const res = await requeueCompletedStudioQueue(false);
      setStatusMsg({
        type: 'success',
        text:
          res?.message ||
          `기존 완료 작업 ${res?.requeued_count || 0}건이 작업 대기열(WAITING)에 다시 등록되어 처음부터 자막 재추출을 시작합니다.`
      });
    } catch (err) {
      setStatusMsg({
        type: 'error',
        text: err.response?.data?.detail || '완료 작업 대기열 재등록 중 오류가 발생했습니다.'
      });
    } finally {
      setRequeuing(false);
    }
  };

  const handlePullModel = async (modelName) => {
    if (!modelName || pulling) return;
    setPulling(true);
    setPullTarget(modelName);
    setStatusMsg({
      type: 'info',
      text: `'${modelName}' 모델을 Ollama 서버에서 다운로드 중입니다. 모델 용량에 따라 1~3분 정도 소요될 수 있습니다...`
    });
    try {
      const res = await pullOllamaModel(modelName);
      setStatusMsg({
        type: 'success',
        text: res?.message || `'${modelName}' 모델 설치가 완료되었습니다!`
      });
      await loadSettings();
    } catch (err) {
      setStatusMsg({
        type: 'error',
        text: err.response?.data?.detail || `'${modelName}' 모델 다운로드에 실패했습니다.`
      });
    } finally {
      setPulling(false);
      setPullTarget('');
    }
  };

  const handleResetRecommended = () => {
    setLlmProvider('ollama');
    setSelectedOllamaModel('qwen2.5:14b');
    setSelectedBatchSize(10);
    setSelectedWhisperModel('large-v3-turbo');
    setSelectedWhisperDevice('cuda');
    setSelectedWhisperCompute('float16');
    setStatusMsg({
      type: 'info',
      text: 'RTX 4070 Ti 환경에 최적화된 로컬 추천 설정(Qwen 2.5 14B + Whisper large-v3-turbo)이 선택되었습니다. [설정 저장 및 즉시 적용] 버튼을 눌러 반영하세요.'
    });
  };

  const currentOllamaObj = ollamaModels.find((m) => m.name === selectedOllamaModel);
  const currentWhisperObj = whisperModels.find((m) => m.name === selectedWhisperModel);
  const isSelectedOllamaInstalled =
    installedModels.includes(selectedOllamaModel) || currentOllamaObj?.installed;

  if (loading) {
    return (
      <div className="w-full max-w-4xl mx-auto my-12 p-12 bg-slate-900/70 border border-slate-800 rounded-3xl flex flex-col items-center justify-center space-y-4 shadow-xl">
        <RefreshCw className="w-8 h-8 text-indigo-400 animate-spin" />
        <p className="text-sm font-semibold text-slate-300">
          AI 엔진 및 모델 설정 정보를 불러오는 중...
        </p>
      </div>
    );
  }

  return (
    <div className="w-full max-w-4xl mx-auto space-y-6 pb-12 animate-in fade-in duration-300">
      {/* Top Page Header */}
      <div className="p-6 rounded-2xl bg-gradient-to-r from-slate-900 via-indigo-950/30 to-slate-900 border border-slate-800 shadow-xl flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-start space-x-4">
          <div className="w-12 h-12 rounded-2xl bg-indigo-500/20 border border-indigo-500/40 flex items-center justify-center text-indigo-400 flex-shrink-0 shadow-lg">
            <Settings className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-xl font-extrabold text-white">
                AI 엔진 및 멀티 클라우드 환경 설정
              </h1>
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                실시간 즉시 반영
              </span>
              <span
                className={`px-2.5 py-0.5 rounded-full text-[11px] font-bold flex items-center border ${
                  dbInfo.type === 'sqlite'
                    ? 'bg-emerald-500/20 text-emerald-300 border-emerald-500/30'
                    : 'bg-cyan-500/20 text-cyan-300 border-cyan-500/30'
                }`}
              >
                <Database className="w-3 h-3 mr-1 inline" />
                <span>DB: {dbInfo.type === 'sqlite' ? 'SQLite (파일 DB)' : 'PostgreSQL'}</span>
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1 leading-relaxed">
              <strong>로컬 Ollama</strong>뿐만 아니라 <strong>OpenAI(GPT), Anthropic(Claude), Google(Gemini)</strong> 클라우드 LLM과 <strong>Whisper 음성 인식 모델</strong>을 선택하여 고품질 자막을 생성합니다.
            </p>
          </div>
        </div>

        <button
          type="button"
          onClick={loadSettings}
          disabled={loading || saving || pulling}
          className="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-xs font-semibold flex items-center space-x-1.5 transition self-start sm:self-center border border-slate-700"
        >
          <RefreshCw className={`w-3.5 h-3.5 ${loading ? 'animate-spin' : ''}`} />
          <span>목록 새로고침</span>
        </button>
      </div>

      {/* Status Alert Banner */}
      {statusMsg && (
        <div
          className={`p-4 rounded-2xl border flex items-center justify-between gap-3 text-xs font-medium shadow-lg animate-in fade-in ${
            statusMsg.type === 'success'
              ? 'bg-emerald-950/50 border-emerald-500/40 text-emerald-200'
              : statusMsg.type === 'error'
              ? 'bg-rose-950/50 border-rose-500/40 text-rose-200'
              : 'bg-indigo-950/50 border-indigo-500/40 text-indigo-200'
          }`}
        >
          <div className="flex items-center space-x-2.5">
            {statusMsg.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
            ) : statusMsg.type === 'error' ? (
              <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
            ) : (
              <RefreshCw className={`w-4 h-4 text-indigo-400 flex-shrink-0 ${pulling ? 'animate-spin' : ''}`} />
            )}
            <span>{statusMsg.text}</span>
          </div>
          <button
            type="button"
            onClick={() => setStatusMsg(null)}
            className="text-slate-400 hover:text-white px-2 py-0.5 rounded"
          >
            ✕
          </button>
        </div>
      )}

      <form onSubmit={handleSave} className="space-y-6">
        {/* SECTION 1: LLM Engine & Provider Configuration */}
        <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl space-y-5">
          <div className="flex items-center justify-between border-b border-slate-800 pb-4">
            <div className="flex items-center space-x-3">
              <div className="p-2.5 rounded-xl bg-purple-500/15 text-purple-400 border border-purple-500/30">
                <Sparkles className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-base font-bold text-white">
                  1. LLM 자막 교정 및 번역 엔진 (로컬 & 클라우드 선택)
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  자막을 20년 차 베테랑 시니어 번역가 스타일로 유려하게 번역할 인공지능 엔진을 선택합니다.
                </p>
              </div>
            </div>
            <span className="hidden sm:inline-flex items-center space-x-1.5 px-3 py-1 rounded-lg bg-slate-950 border border-slate-800 text-[11px] text-purple-300 font-bold">
              <span>현재 활성: {llmProvider.toUpperCase()}</span>
            </span>
          </div>

          {/* Provider Selection Tabs */}
          <div className="space-y-2">
            <label className="block text-xs font-bold text-slate-300">
              사용할 AI Provider 선택
            </label>
            <div className="grid grid-cols-2 sm:grid-cols-4 gap-2.5">
              {[
                { id: 'ollama', label: '로컬 Ollama', sub: 'Qwen 2.5 / 무료', badge: 'GPU 로컬' },
                { id: 'openai', label: 'OpenAI (GPT)', sub: 'GPT-4o / 클라우드', badge: '고성능' },
                { id: 'anthropic', label: 'Claude (Anthropic)', sub: '3.5 Sonnet / 문학적', badge: '최고 번역력' },
                { id: 'gemini', label: 'Google (Gemini)', sub: '2.5 Flash / 초고속', badge: '가성비/고속' }
              ].map((p) => {
                const isActive = llmProvider === p.id;
                return (
                  <button
                    key={p.id}
                    type="button"
                    onClick={() => setLlmProvider(p.id)}
                    className={`p-3.5 rounded-2xl border text-left transition flex flex-col justify-between ${
                      isActive
                        ? 'bg-purple-950/40 border-purple-500 ring-2 ring-purple-500/30 text-white shadow-lg'
                        : 'bg-slate-950 hover:bg-slate-800/60 border-slate-800 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    <div className="flex items-center justify-between">
                      <span className="text-xs font-bold text-white">{p.label}</span>
                      <span
                        className={`text-[10px] px-1.5 py-0.5 rounded font-mono ${
                          isActive
                            ? 'bg-purple-500/30 text-purple-200 border border-purple-400/40'
                            : 'bg-slate-800 text-slate-400'
                        }`}
                      >
                        {p.badge}
                      </span>
                    </div>
                    <span className="text-[11px] text-slate-400 mt-1">{p.sub}</span>
                  </button>
                );
              })}
            </div>
          </div>

          {/* Provider-Specific Settings Panel */}
          {llmProvider === 'ollama' && (
            <div className="p-4 rounded-2xl bg-slate-950 border border-slate-800 space-y-4 animate-in fade-in">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-200 flex items-center space-x-1.5">
                  <Server className="w-3.5 h-3.5 text-purple-400" />
                  <span>로컬 Ollama 모델 설정 (호스트: {ollamaHost})</span>
                </span>
                <button
                  type="button"
                  onClick={() => handleTestConnection('ollama')}
                  disabled={testingProvider === 'ollama'}
                  className="px-3 py-1 rounded-lg bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold border border-slate-700 transition flex items-center space-x-1"
                >
                  <Activity className={`w-3 h-3 ${testingProvider === 'ollama' ? 'animate-spin' : ''}`} />
                  <span>연결 테스트</span>
                </button>
              </div>

              <div className="space-y-2">
                <label className="block text-xs text-slate-400">설치 및 권장 모델 선택</label>
                <select
                  value={selectedOllamaModel}
                  onChange={(e) => setSelectedOllamaModel(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-slate-900 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-purple-500 cursor-pointer"
                >
                  {ollamaModels.map((m) => (
                    <option key={m.name} value={m.name} className="bg-slate-900 text-white">
                      {m.installed ? '✅ [설치됨] ' : '⬇️ [미설치] '}
                      {m.label || m.name}
                    </option>
                  ))}
                </select>
              </div>

              {currentOllamaObj && (
                <div className="p-3 rounded-xl bg-slate-900/80 border border-slate-800 flex flex-col sm:flex-row sm:items-center justify-between gap-2">
                  <div className="text-xs text-slate-300">
                    <span className="font-mono text-purple-300 font-bold">{currentOllamaObj.name}</span>
                    <span className="ml-2 text-slate-400 text-[11px]">({currentOllamaObj.size_str})</span>
                    <p className="text-slate-400 text-[11px] mt-0.5">{currentOllamaObj.desc}</p>
                  </div>
                  {!isSelectedOllamaInstalled && (
                    <button
                      type="button"
                      onClick={() => handlePullModel(currentOllamaObj.name)}
                      disabled={pulling}
                      className="px-3 py-1.5 rounded-xl bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white text-xs font-bold flex items-center space-x-1 shadow flex-shrink-0"
                    >
                      <Download className={`w-3.5 h-3.5 ${pulling ? 'animate-bounce' : ''}`} />
                      <span>{pulling && pullTarget === currentOllamaObj.name ? '다운로드 중...' : '모델 다운로드'}</span>
                    </button>
                  )}
                </div>
              )}
            </div>
          )}

          {llmProvider === 'openai' && (
            <div className="p-4 rounded-2xl bg-slate-950 border border-slate-800 space-y-4 animate-in fade-in">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-200 flex items-center space-x-1.5">
                  <Cloud className="w-3.5 h-3.5 text-emerald-400" />
                  <span>OpenAI (ChatGPT) API 연동 설정</span>
                </span>
                <button
                  type="button"
                  onClick={() => handleTestConnection('openai')}
                  disabled={testingProvider === 'openai'}
                  className="px-3 py-1 rounded-lg bg-emerald-600/30 hover:bg-emerald-600/50 text-emerald-200 text-xs font-semibold border border-emerald-500/40 transition flex items-center space-x-1"
                >
                  <Activity className={`w-3 h-3 ${testingProvider === 'openai' ? 'animate-spin' : ''}`} />
                  <span>API 연결 테스트</span>
                </button>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-slate-300">
                    OpenAI API Key <span className="text-rose-400">*</span>
                  </label>
                  <div className="relative">
                    <input
                      type={showKeys.openai ? 'text' : 'password'}
                      placeholder="sk-proj-..."
                      value={openaiApiKey}
                      onChange={(e) => setOpenaiApiKey(e.target.value)}
                      className="w-full pl-4 pr-10 py-2.5 rounded-xl bg-slate-900 border border-slate-700 text-sm font-mono text-white focus:outline-none focus:ring-2 focus:ring-emerald-500"
                    />
                    <button
                      type="button"
                      onClick={() => setShowKeys((prev) => ({ ...prev, openai: !prev.openai }))}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                    >
                      {showKeys.openai ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-slate-300">OpenAI 모델 선택</label>
                  <select
                    value={openaiModel}
                    onChange={(e) => setOpenaiModel(e.target.value)}
                    className="w-full px-4 py-2.5 rounded-xl bg-slate-900 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-emerald-500 cursor-pointer"
                  >
                    {(cloudModels.openai || ['gpt-4o', 'gpt-4o-mini', 'o3-mini']).map((m) => (
                      <option key={m} value={m} className="bg-slate-900 text-white">
                        {m} {m === 'gpt-4o' ? '(권장 최상위 플래그십)' : m === 'gpt-4o-mini' ? '(고속/경제적)' : ''}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </div>
          )}

          {llmProvider === 'anthropic' && (
            <div className="p-4 rounded-2xl bg-slate-950 border border-slate-800 space-y-4 animate-in fade-in">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-200 flex items-center space-x-1.5">
                  <Sparkles className="w-3.5 h-3.5 text-amber-400" />
                  <span>Anthropic Claude API 연동 설정</span>
                </span>
                <button
                  type="button"
                  onClick={() => handleTestConnection('anthropic')}
                  disabled={testingProvider === 'anthropic'}
                  className="px-3 py-1 rounded-lg bg-amber-600/30 hover:bg-amber-600/50 text-amber-200 text-xs font-semibold border border-amber-500/40 transition flex items-center space-x-1"
                >
                  <Activity className={`w-3 h-3 ${testingProvider === 'anthropic' ? 'animate-spin' : ''}`} />
                  <span>API 연결 테스트</span>
                </button>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-slate-300">
                    Anthropic API Key <span className="text-rose-400">*</span>
                  </label>
                  <div className="relative">
                    <input
                      type={showKeys.anthropic ? 'text' : 'password'}
                      placeholder="sk-ant-..."
                      value={anthropicApiKey}
                      onChange={(e) => setAnthropicApiKey(e.target.value)}
                      className="w-full pl-4 pr-10 py-2.5 rounded-xl bg-slate-900 border border-slate-700 text-sm font-mono text-white focus:outline-none focus:ring-2 focus:ring-amber-500"
                    />
                    <button
                      type="button"
                      onClick={() => setShowKeys((prev) => ({ ...prev, anthropic: !prev.anthropic }))}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                    >
                      {showKeys.anthropic ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-slate-300">Claude 모델 선택</label>
                  <select
                    value={anthropicModel}
                    onChange={(e) => setAnthropicModel(e.target.value)}
                    className="w-full px-4 py-2.5 rounded-xl bg-slate-900 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-amber-500 cursor-pointer"
                  >
                    {(cloudModels.anthropic || ['claude-3-5-sonnet-latest', 'claude-3-5-haiku-latest']).map((m) => (
                      <option key={m} value={m} className="bg-slate-900 text-white">
                        {m} {m.includes('sonnet') ? '(권장 최고 자연스러움)' : m.includes('haiku') ? '(초고속)' : ''}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </div>
          )}

          {llmProvider === 'gemini' && (
            <div className="p-4 rounded-2xl bg-slate-950 border border-slate-800 space-y-4 animate-in fade-in">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-200 flex items-center space-x-1.5">
                  <Zap className="w-3.5 h-3.5 text-cyan-400" />
                  <span>Google Gemini API 연동 설정</span>
                </span>
                <button
                  type="button"
                  onClick={() => handleTestConnection('gemini')}
                  disabled={testingProvider === 'gemini'}
                  className="px-3 py-1 rounded-lg bg-cyan-600/30 hover:bg-cyan-600/50 text-cyan-200 text-xs font-semibold border border-cyan-500/40 transition flex items-center space-x-1"
                >
                  <Activity className={`w-3 h-3 ${testingProvider === 'gemini' ? 'animate-spin' : ''}`} />
                  <span>API 연결 테스트</span>
                </button>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-slate-300">
                    Google AI Studio API Key <span className="text-rose-400">*</span>
                  </label>
                  <div className="relative">
                    <input
                      type={showKeys.gemini ? 'text' : 'password'}
                      placeholder="AIzaSy..."
                      value={geminiApiKey}
                      onChange={(e) => setGeminiApiKey(e.target.value)}
                      className="w-full pl-4 pr-10 py-2.5 rounded-xl bg-slate-900 border border-slate-700 text-sm font-mono text-white focus:outline-none focus:ring-2 focus:ring-cyan-500"
                    />
                    <button
                      type="button"
                      onClick={() => setShowKeys((prev) => ({ ...prev, gemini: !prev.gemini }))}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-slate-400 hover:text-white"
                    >
                      {showKeys.gemini ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                    </button>
                  </div>
                </div>

                <div className="space-y-1.5">
                  <label className="block text-xs font-bold text-slate-300">Gemini 모델 선택</label>
                  <select
                    value={geminiModel}
                    onChange={(e) => setGeminiModel(e.target.value)}
                    className="w-full px-4 py-2.5 rounded-xl bg-slate-900 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-cyan-500 cursor-pointer"
                  >
                    {(cloudModels.gemini || ['gemini-2.5-flash', 'gemini-2.5-pro']).map((m) => (
                      <option key={m} value={m} className="bg-slate-900 text-white">
                        {m} {m.includes('flash') ? '(권장 초고속/초저지연)' : m.includes('pro') ? '(고급 추론)' : ''}
                      </option>
                    ))}
                  </select>
                </div>
              </div>
            </div>
          )}

          {/* Test Result Display */}
          {testResults[llmProvider] && (
            <div
              className={`p-3 rounded-xl border text-xs font-semibold flex items-center justify-between ${
                testResults[llmProvider].success
                  ? 'bg-emerald-950/40 border-emerald-500/40 text-emerald-200'
                  : 'bg-rose-950/40 border-rose-500/40 text-rose-200'
              }`}
            >
              <div className="flex items-center space-x-2">
                {testResults[llmProvider].success ? (
                  <CheckCircle2 className="w-4 h-4 text-emerald-400" />
                ) : (
                  <AlertCircle className="w-4 h-4 text-rose-400" />
                )}
                <span>
                  [{llmProvider.toUpperCase()}] {testResults[llmProvider].message}
                  {testResults[llmProvider].latency_ms && ` (${testResults[llmProvider].latency_ms}ms)`}
                </span>
              </div>
              <button
                type="button"
                onClick={() => setTestResults((prev) => ({ ...prev, [llmProvider]: null }))}
                className="text-slate-400 hover:text-white px-1"
              >
                ✕
              </button>
            </div>
          )}

          {/* Batch Size Selection */}
          <div className="pt-2 border-t border-slate-800">
            <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <div>
                <label className="block text-xs font-bold text-slate-300">
                  1회 묶음 처리 단위 (Batch Size)
                </label>
                <p className="text-[11px] text-slate-400 mt-0.5">
                  한 번의 LLM 요청에 전달할 자막 행 수입니다. 문맥 일관성과 API 비용 절감에 직접 영향을 줍니다.
                </p>
              </div>
              <select
                value={selectedBatchSize}
                onChange={(e) => setSelectedBatchSize(Number(e.target.value))}
                className="px-4 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs font-semibold text-white focus:outline-none focus:ring-2 focus:ring-purple-500 cursor-pointer self-start sm:self-center"
              >
                <option value={5} className="bg-slate-900 text-white">5문장씩 (세밀 교정)</option>
                <option value={10} className="bg-slate-900 text-white">10문장씩 (★ 기본 권장 - 문맥/속도 최적)</option>
                <option value={15} className="bg-slate-900 text-white">15문장씩 (고속 처리)</option>
                <option value={20} className="bg-slate-900 text-white">20문장씩 (대량 묶음)</option>
              </select>
            </div>
          </div>
        </div>

        {/* SECTION 2: Whisper STT Configuration */}
        <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl space-y-5">
          <div className="flex items-center justify-between border-b border-slate-800 pb-4">
            <div className="flex items-center space-x-3">
              <div className="p-2.5 rounded-xl bg-teal-500/15 text-teal-400 border border-teal-500/30">
                <Mic className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-base font-bold text-white">
                  2. faster-whisper 음성 인식(STT) 모델 및 가속 모드 설정
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  영상 속 음성을 추출하여 타임스탬프와 원문 텍스트로 변환하는 Whisper 모델 크기 및 하드웨어 모드를 선택합니다.
                </p>
              </div>
            </div>
            <span className="hidden sm:inline-flex items-center space-x-1.5 px-3 py-1 rounded-lg bg-teal-950/50 border border-teal-500/30 text-[11px] text-teal-300 font-semibold">
              <Zap className="w-3.5 h-3.5 text-teal-400" />
              <span>RTX 4070 Ti 가속</span>
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {/* Whisper Model Size Select Box */}
            <div className="md:col-span-3 space-y-2">
              <label className="block text-xs font-bold text-slate-300">
                Whisper 음성 인식 모델 선택 (Select Box)
              </label>
              <select
                value={selectedWhisperModel}
                onChange={(e) => setSelectedWhisperModel(e.target.value)}
                className="w-full px-4 py-3 rounded-xl bg-slate-950 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition cursor-pointer"
              >
                {whisperModels.map((m) => (
                  <option key={m.name} value={m.name} className="bg-slate-900 text-white py-2">
                    {m.label || m.name}
                  </option>
                ))}
              </select>

              {/* Selected Whisper Details Box */}
              {currentWhisperObj && (
                <div className="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800/90 flex flex-col sm:flex-row sm:items-center justify-between gap-3 mt-2">
                  <div className="space-y-1">
                    <div className="flex items-center space-x-2">
                      <span className="text-xs font-bold text-teal-300 font-mono">
                        {currentWhisperObj.name}
                      </span>
                      <span className="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                        크기: {currentWhisperObj.size_str}
                      </span>
                      {currentWhisperObj.recommended && (
                        <span className="text-[11px] px-2 py-0.5 rounded bg-teal-500/20 text-teal-300 border border-teal-500/30 font-semibold">
                          ★ 추천 모델
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-400">
                      {currentWhisperObj.desc}
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* Device Mode Select Box */}
            <div className="space-y-2">
              <label className="block text-xs font-bold text-slate-300">
                연산 디바이스 (Device)
              </label>
              <select
                value={selectedWhisperDevice}
                onChange={(e) => setSelectedWhisperDevice(e.target.value)}
                className="w-full px-4 py-3 rounded-xl bg-slate-950 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition cursor-pointer"
              >
                {whisperDevices.map((d) => (
                  <option key={d.name} value={d.name} className="bg-slate-900 text-white">
                    {d.label || d.name}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-slate-400">
                NVIDIA 그래픽 카드가 탑재된 환경에서는 <strong>cuda (GPU)</strong> 모드가 수십 배 빠릅니다.
              </p>
            </div>

            {/* Compute Type Select Box */}
            <div className="md:col-span-2 space-y-2">
              <label className="block text-xs font-bold text-slate-300">
                연산 정밀도 (Compute Type)
              </label>
              <select
                value={selectedWhisperCompute}
                onChange={(e) => setSelectedWhisperCompute(e.target.value)}
                className="w-full px-4 py-3 rounded-xl bg-slate-950 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition cursor-pointer"
              >
                {whisperComputeTypes.map((c) => (
                  <option key={c.name} value={c.name} className="bg-slate-900 text-white">
                    {c.label || c.name}
                  </option>
                ))}
              </select>
              <p className="text-[11px] text-slate-400">
                RTX 4070 Ti에서는 <strong>float16</strong> 모드가 Tensor 코어를 100% 활용하여 가장 빠르고 정확합니다.
              </p>
            </div>
          </div>
        </div>

        {/* SECTION 3: Task Requeue & Auto Reprocess Options */}
        <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl space-y-4">
          <div className="flex items-center space-x-3 border-b border-slate-800 pb-3">
            <div className="p-2 rounded-xl bg-amber-500/15 text-amber-400 border border-amber-500/30">
              <RotateCcw className="w-5 h-5" />
            </div>
            <div>
              <h2 className="text-base font-bold text-white">
                3. 모델 변경 시 기존 완료 작업 자동 재추출 옵션
              </h2>
              <p className="text-xs text-slate-400 mt-0.5">
                새로운 AI 모델 설정으로 이미 완료된 자막들을 다시 고품질로 갱신할지 제어합니다.
              </p>
            </div>
          </div>

          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4 p-4 rounded-xl bg-slate-950 border border-slate-800">
            <label className="flex items-start space-x-3 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={requeueCompleted}
                onChange={(e) => setRequeueCompleted(e.target.checked)}
                className="mt-0.5 w-4 h-4 rounded bg-slate-900 border-slate-700 text-indigo-600 focus:ring-indigo-500 focus:ring-offset-slate-900 cursor-pointer"
              />
              <div className="space-y-0.5">
                <span className="text-xs font-bold text-white block">
                  설정 저장 시 완료된 작업들을 작업 대기열(WAITING)로 자동 재등록하여 재추출 시작
                </span>
                <span className="text-[11px] text-slate-400 block leading-relaxed">
                  (기존 업로드된 영상 파일 원본은 안전하게 보존되며, 새로운 LLM 및 Whisper 설정으로 자막만 처음부터 완전히 새로 생성합니다.)
                </span>
              </div>
            </label>

            <button
              type="button"
              onClick={handleRequeueCompleted}
              disabled={requeuing || saving}
              className="px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 disabled:opacity-50 text-amber-300 hover:text-white text-xs font-bold flex items-center space-x-2 transition border border-amber-500/30 shadow flex-shrink-0 self-start sm:self-center"
            >
              <RotateCcw className={`w-3.5 h-3.5 ${requeuing ? 'animate-spin' : ''}`} />
              <span>{requeuing ? '대기열 재등록 중...' : '지금 수동으로 전체 재등록'}</span>
            </button>
          </div>
        </div>

        {/* BOTTOM ACTION BUTTONS */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-4 pt-2">
          <button
            type="button"
            onClick={handleResetRecommended}
            className="w-full sm:w-auto px-4 py-3 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-bold flex items-center justify-center space-x-2 border border-slate-700 transition"
          >
            <Zap className="w-4 h-4 text-amber-400" />
            <span>RTX 4070 Ti 로컬 추천 설정으로 채우기</span>
          </button>

          <div className="flex items-center space-x-3 w-full sm:w-auto">
            <button
              type="submit"
              disabled={saving}
              className="w-full sm:w-auto px-8 py-3.5 rounded-2xl bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-600 hover:from-indigo-500 hover:to-purple-500 disabled:opacity-50 text-white text-sm font-extrabold flex items-center justify-center space-x-2.5 shadow-xl shadow-indigo-600/30 transition transform hover:-translate-y-0.5"
            >
              <Save className={`w-4 h-4 ${saving ? 'animate-spin' : ''}`} />
              <span>{saving ? '설정 저장 및 적용 중...' : '설정 저장 및 즉시 적용'}</span>
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
