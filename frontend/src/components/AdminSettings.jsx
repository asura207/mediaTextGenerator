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
  Layers
} from 'lucide-react';
import { getSystemSettings, updateSystemSettings, pullOllamaModel, requeueCompletedStudioQueue } from '../api/client';

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

  // Form state
  const [selectedOllamaModel, setSelectedOllamaModel] = useState('qwen2.5:14b');
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
        setSelectedOllamaModel(data.current.ollama_model || 'qwen2.5:14b');
        setSelectedBatchSize(data.current.llm_batch_size || 10);
        setSelectedWhisperModel(data.current.whisper_model_size || 'large-v3-turbo');
        setSelectedWhisperDevice(data.current.whisper_device || 'cuda');
        setSelectedWhisperCompute(data.current.whisper_compute_type || 'float16');
      }
      if (data?.ollama_models) setOllamaModels(data.ollama_models);
      if (data?.installed_ollama_models) setInstalledModels(data.installed_ollama_models);
      if (data?.whisper_models) setWhisperModels(data.whisper_models);
      if (data?.whisper_devices) setWhisperDevices(data.whisper_devices);
      if (data?.whisper_compute_types) setWhisperComputeTypes(data.whisper_compute_types);
      if (data?.ollama_host) setOllamaHost(data.ollama_host);
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

  const handleSave = async (e) => {
    if (e) e.preventDefault();
    setSaving(true);
    setStatusMsg(null);
    try {
      const payload = {
        ollama_model: selectedOllamaModel,
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
    setSelectedOllamaModel('qwen2.5:14b');
    setSelectedBatchSize(10);
    setSelectedWhisperModel('large-v3-turbo');
    setSelectedWhisperDevice('cuda');
    setSelectedWhisperCompute('float16');
    setStatusMsg({
      type: 'info',
      text: 'RTX 4070 Ti 환경에 최적화된 추천 설정(Qwen 2.5 14B + Whisper large-v3-turbo)이 선택되었습니다. [설정 저장 및 즉시 적용] 버튼을 눌러 반영하세요.'
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
                AI 엔진 및 모델 환경 설정 (관리자)
              </h1>
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                실시간 즉시 반영
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1 leading-relaxed">
              자막 품질과 직결되는 <strong>LLM 문맥 교정/번역 모델</strong>과 <strong>Whisper 음성 인식(STT) 모델 및 가속 모드</strong>를 자유롭게 선택하고 즉시 적용할 수 있습니다.
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
        {/* SECTION 1: LLM Model Configuration */}
        <div className="p-6 rounded-2xl bg-slate-900 border border-slate-800 shadow-xl space-y-5">
          <div className="flex items-center justify-between border-b border-slate-800 pb-4">
            <div className="flex items-center space-x-3">
              <div className="p-2.5 rounded-xl bg-purple-500/15 text-purple-400 border border-purple-500/30">
                <Sparkles className="w-5 h-5" />
              </div>
              <div>
                <h2 className="text-base font-bold text-white">
                  1. Ollama LLM 자막 교정 및 번역 모델 설정
                </h2>
                <p className="text-xs text-slate-400 mt-0.5">
                  추출된 자막을 자연스러운 일상 구어체로 다듬고 외국어를 한국어로 번역하는 인공지능 모델을 선택합니다.
                </p>
              </div>
            </div>
            <span className="hidden sm:inline-flex items-center space-x-1.5 px-3 py-1 rounded-lg bg-slate-950 border border-slate-800 text-[11px] text-slate-400 font-mono">
              <Server className="w-3.5 h-3.5 text-purple-400" />
              <span>{ollamaHost}</span>
            </span>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-3 gap-5">
            {/* LLM Model Select Box */}
            <div className="md:col-span-2 space-y-2">
              <label className="block text-xs font-bold text-slate-300">
                LLM 모델 선택 (Select Box)
              </label>
              <select
                value={selectedOllamaModel}
                onChange={(e) => setSelectedOllamaModel(e.target.value)}
                className="w-full px-4 py-3 rounded-xl bg-slate-950 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent transition cursor-pointer"
              >
                {ollamaModels.map((m) => (
                  <option key={m.name} value={m.name} className="bg-slate-900 text-white py-2">
                    {m.installed ? '✅ [설치됨] ' : '⬇️ [미설치] '}
                    {m.label || m.name}
                  </option>
                ))}
              </select>

              {/* Selected Model Details Box */}
              {currentOllamaObj && (
                <div className="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800/90 flex flex-col sm:flex-row sm:items-center justify-between gap-3 mt-2">
                  <div className="space-y-1">
                    <div className="flex items-center space-x-2">
                      <span className="text-xs font-bold text-purple-300 font-mono">
                        {currentOllamaObj.name}
                      </span>
                      <span className="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                        크기: {currentOllamaObj.size_str}
                      </span>
                      {isSelectedOllamaInstalled ? (
                        <span className="text-[11px] px-2 py-0.5 rounded bg-emerald-500/20 text-emerald-300 border border-emerald-500/30 font-semibold">
                          설치 완료 (즉시 사용 가능)
                        </span>
                      ) : (
                        <span className="text-[11px] px-2 py-0.5 rounded bg-amber-500/20 text-amber-300 border border-amber-500/30 font-semibold">
                          미설치 (다운로드 필요)
                        </span>
                      )}
                    </div>
                    <p className="text-xs text-slate-400">
                      {currentOllamaObj.desc}
                    </p>
                  </div>

                  {!isSelectedOllamaInstalled && (
                    <button
                      type="button"
                      onClick={() => handlePullModel(currentOllamaObj.name)}
                      disabled={pulling}
                      className="px-3.5 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white text-xs font-bold flex items-center space-x-1.5 transition shadow-md flex-shrink-0"
                    >
                      <Download className={`w-3.5 h-3.5 ${pulling ? 'animate-bounce' : ''}`} />
                      <span>
                        {pulling && pullTarget === currentOllamaObj.name
                          ? '다운로드 중...'
                          : '이 모델 다운로드'}
                      </span>
                    </button>
                  )}
                </div>
              )}
            </div>

            {/* Batch Size Select Box */}
            <div className="space-y-2">
              <label className="block text-xs font-bold text-slate-300">
                1회 묶음 교정 단위 (Batch Size)
              </label>
              <select
                value={selectedBatchSize}
                onChange={(e) => setSelectedBatchSize(Number(e.target.value))}
                className="w-full px-4 py-3 rounded-xl bg-slate-950 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-purple-500 focus:border-transparent transition cursor-pointer"
              >
                <option value={5} className="bg-slate-900 text-white">5문장씩 (세밀 교정 / 저용량 VRAM)</option>
                <option value={10} className="bg-slate-900 text-white">10문장씩 (★ 기본 권장 - 문맥/속도 최적)</option>
                <option value={15} className="bg-slate-900 text-white">15문장씩 (고속 문맥 처리)</option>
                <option value={20} className="bg-slate-900 text-white">20문장씩 (대량 고속 처리)</option>
              </select>
              <p className="text-[11px] text-slate-400 leading-relaxed pt-1">
                한 번에 LLM에게 전달할 자막 줄 수입니다. <strong>10문장</strong>이 앞뒤 대화 맥락 파악과 응답 안정성 면에서 가장 뛰어납니다.
              </p>
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
              <span>RTX 4070 Ti 지원</span>
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
                {whisperModels.map((wm) => (
                  <option key={wm.name} value={wm.name} className="bg-slate-900 text-white py-2">
                    {wm.label} [VRAM: {wm.vram}]
                  </option>
                ))}
              </select>

              {currentWhisperObj && (
                <div className="p-3.5 rounded-xl bg-slate-950/80 border border-slate-800/90 flex items-center justify-between gap-3 mt-2">
                  <div className="space-y-0.5">
                    <div className="flex items-center space-x-2">
                      <span className="text-xs font-bold text-teal-300 font-mono">
                        모델: {currentWhisperObj.name}
                      </span>
                      <span className="text-[11px] px-2 py-0.5 rounded bg-slate-800 text-slate-300 font-mono">
                        예상 VRAM: {currentWhisperObj.vram}
                      </span>
                    </div>
                    <p className="text-xs text-slate-400 pt-0.5">
                      {currentWhisperObj.desc}
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* Whisper Device Mode Select Box */}
            <div className="md:col-span-1 space-y-2">
              <label className="block text-xs font-bold text-slate-300">
                연산 가속 장치 (Device Mode)
              </label>
              <select
                value={selectedWhisperDevice}
                onChange={(e) => setSelectedWhisperDevice(e.target.value)}
                className="w-full px-4 py-3 rounded-xl bg-slate-950 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition cursor-pointer"
              >
                {whisperDevices.map((wd) => (
                  <option key={wd.name} value={wd.name} className="bg-slate-900 text-white">
                    {wd.label}
                  </option>
                ))}
              </select>
            </div>

            {/* Whisper Compute Type Select Box */}
            <div className="md:col-span-2 space-y-2">
              <label className="block text-xs font-bold text-slate-300">
                연산 정밀도 모드 (Compute Type)
              </label>
              <select
                value={selectedWhisperCompute}
                onChange={(e) => setSelectedWhisperCompute(e.target.value)}
                className="w-full px-4 py-3 rounded-xl bg-slate-950 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-teal-500 focus:border-transparent transition cursor-pointer"
              >
                {whisperComputeTypes.map((wc) => (
                  <option key={wc.name} value={wc.name} className="bg-slate-900 text-white">
                    {wc.label}
                  </option>
                ))}
              </select>
            </div>
          </div>
        </div>

        {/* Bottom Save & Action Buttons */}
        <div className="p-5 rounded-2xl bg-slate-900/90 border border-slate-800 shadow-xl space-y-4">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 pb-4 border-b border-slate-800/80">
            <label className="flex items-center space-x-3 cursor-pointer select-none">
              <input
                type="checkbox"
                checked={requeueCompleted}
                onChange={(e) => setRequeueCompleted(e.target.checked)}
                className="w-4 h-4 rounded border-slate-600 text-indigo-600 focus:ring-indigo-500 bg-slate-950"
              />
              <span className="text-xs font-semibold text-slate-200">
                설정 저장 시 기존 작업 완료된 건도 대기열(WAITING)에 다시 등록하여 변경된 설정 기준으로 처음부터 재추출
              </span>
            </label>

            <button
              type="button"
              onClick={handleRequeueCompleted}
              disabled={requeuing || saving || pulling}
              className="px-3.5 py-2 rounded-xl bg-amber-500/15 hover:bg-amber-500/25 border border-amber-500/30 text-amber-300 text-xs font-bold flex items-center space-x-1.5 transition flex-shrink-0"
            >
              <RefreshCw className={`w-3.5 h-3.5 ${requeuing ? 'animate-spin' : ''}`} />
              <span>
                {requeuing ? '대기열 재등록 중...' : '완료된 작업 즉시 대기열 재등록 (전체 재추출)'}
              </span>
            </button>
          </div>

          <div className="flex flex-col sm:flex-row items-center justify-between gap-4">
            <button
              type="button"
              onClick={handleResetRecommended}
              className="w-full sm:w-auto px-4 py-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white text-xs font-semibold flex items-center justify-center space-x-2 transition border border-slate-700"
            >
              <RotateCcw className="w-4 h-4 text-indigo-400" />
              <span>권장 최고 품질 설정으로 불러오기 (Qwen 2.5 14B + large-v3-turbo)</span>
            </button>

            <button
              type="submit"
              disabled={saving || pulling}
              className="w-full sm:w-auto px-6 py-3 rounded-xl bg-gradient-to-r from-indigo-600 via-purple-600 to-indigo-600 hover:from-indigo-500 hover:to-purple-500 disabled:opacity-50 text-white text-sm font-bold flex items-center justify-center space-x-2 transition shadow-lg shadow-indigo-600/30"
            >
              <Save className="w-4 h-4" />
              <span>{saving ? '설정 저장 및 적용 중...' : '설정 저장 및 즉시 적용'}</span>
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}

