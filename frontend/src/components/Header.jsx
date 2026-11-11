import React from 'react';
import { Film, Cpu, Sparkles, FolderCheck, PlusCircle, Languages } from 'lucide-react';

export default function Header({ activeTab, onTabChange, completedCount = 0, isTranslating = false }) {
  return (
    <header className="border-b border-slate-800 bg-slate-900/90 backdrop-blur sticky top-0 z-50">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
        {/* Left: Logo */}
        <div className="flex items-center space-x-3 cursor-pointer" onClick={() => onTabChange && onTabChange('studio')}>
          <div className="w-10 h-10 rounded-xl bg-gradient-to-tr from-brand-600 to-indigo-500 flex items-center justify-center shadow-lg shadow-indigo-500/20">
            <Film className="w-5 h-5 text-white" />
          </div>
          <div>
            <span className="text-xl font-bold bg-gradient-to-r from-white via-slate-200 to-indigo-300 bg-clip-text text-transparent">
              TransM Studio
            </span>
            <span className="text-xs text-slate-400 block -mt-1">
              AI 비디오 자동 자막 & 다국어 번역
            </span>
          </div>
        </div>

        {/* Center: Navigation Menus */}
        <nav className="flex items-center space-x-1.5 p-1 bg-slate-800/60 border border-slate-700/60 rounded-xl text-xs font-medium">
          <button
            onClick={() => onTabChange && onTabChange('studio')}
            className={`flex items-center space-x-1.5 px-3.5 py-1.5 rounded-lg transition-all ${
              activeTab === 'studio'
                ? 'bg-indigo-600 text-white shadow-sm font-semibold'
                : 'text-slate-300 hover:text-white hover:bg-slate-700/50'
            }`}
          >
            <PlusCircle className="w-3.5 h-3.5" />
            <span>자막 제작 스튜디오</span>
          </button>

          <button
            onClick={() => onTabChange && onTabChange('translate')}
            className={`flex items-center space-x-1.5 px-3.5 py-1.5 rounded-lg transition-all ${
              activeTab === 'translate'
                ? 'bg-indigo-600 text-white shadow-sm font-semibold'
                : 'text-slate-300 hover:text-white hover:bg-slate-700/50'
            }`}
          >
            <Languages className={`w-3.5 h-3.5 ${isTranslating ? 'text-teal-300 animate-spin' : 'text-indigo-300'}`} />
            <span>자막 번역기</span>
            {isTranslating && (
              <span className="inline-flex items-center px-1.5 py-0.5 rounded-full text-[9px] font-bold bg-teal-400/20 text-teal-300 border border-teal-400/30 animate-pulse">
                진행중
              </span>
            )}
          </button>

          <button
            onClick={() => onTabChange && onTabChange('completed')}
            className={`flex items-center space-x-1.5 px-3.5 py-1.5 rounded-lg transition-all ${
              activeTab === 'completed'
                ? 'bg-indigo-600 text-white shadow-sm font-semibold'
                : 'text-slate-300 hover:text-white hover:bg-slate-700/50'
            }`}
          >
            <FolderCheck className="w-3.5 h-3.5" />
            <span>작업 완료 보관함</span>
            {completedCount > 0 && (
              <span className={`px-1.5 py-0.5 text-[10px] rounded-full font-bold ${
                activeTab === 'completed'
                  ? 'bg-white/20 text-white'
                  : 'bg-emerald-500/20 text-emerald-300'
              }`}>
                {completedCount}
              </span>
            )}
          </button>
        </nav>

        {/* Right: Tech Stack Badges */}
        <div className="hidden md:flex items-center space-x-2.5 text-xs">
          <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-slate-800/80 border border-slate-700 text-slate-300">
            <Cpu className="w-3 h-3 text-emerald-400" />
            <span>faster-whisper</span>
          </div>
          <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-full bg-slate-800/80 border border-slate-700 text-slate-300">
            <Sparkles className="w-3 h-3 text-purple-400" />
            <span>Ollama 12B</span>
          </div>
        </div>
      </div>
    </header>
  );
}

