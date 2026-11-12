import React, { useState, useEffect, useCallback } from 'react';
import {
  BookOpen,
  Plus,
  Trash2,
  Edit2,
  Search,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ArrowRight,
  FileText,
  X,
  Save
} from 'lucide-react';
import {
  getDictionaryEntries,
  addDictionaryEntry,
  updateDictionaryEntry,
  deleteDictionaryEntry,
  batchDeleteDictionaryEntries
} from '../api/client';

export default function ProperNounDictionary() {
  const [items, setItems] = useState([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [totalPages, setTotalPages] = useState(1);
  const size = 50; // Requirement: 50 items per page

  const [searchQuery, setSearchQuery] = useState('');
  const [activeQuery, setActiveQuery] = useState('');
  const [loading, setLoading] = useState(false);
  const [selectedIds, setSelectedIds] = useState(new Set());

  // Modal states
  const [showAddModal, setShowAddModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);
  const [editingItem, setEditingItem] = useState(null);

  // Form states
  const [formSourceWord, setFormSourceWord] = useState('');
  const [formTargetWord, setFormTargetWord] = useState('');
  const [formNotes, setFormNotes] = useState('');
  const [submitting, setSubmitting] = useState(false);

  // Toast / status feedback
  const [statusMsg, setStatusMsg] = useState(null);

  const showToast = (type, text) => {
    setStatusMsg({ type, text });
    setTimeout(() => {
      setStatusMsg((prev) => (prev?.text === text ? null : prev));
    }, 4000);
  };

  const loadData = useCallback(async (targetPage = page, query = activeQuery) => {
    setLoading(true);
    try {
      const data = await getDictionaryEntries(targetPage, size, query);
      setItems(data.items || []);
      setTotal(data.total || 0);
      setPage(data.page || 1);
      setTotalPages(data.total_pages || 1);
      setSelectedIds(new Set());
    } catch (err) {
      showToast('error', err.response?.data?.detail || '고유명사 사전을 불러오지 못했습니다.');
    } finally {
      setLoading(false);
    }
  }, [page, activeQuery, size]);

  useEffect(() => {
    loadData(page, activeQuery);
  }, [page, activeQuery]);

  const handleSearch = (e) => {
    if (e) e.preventDefault();
    setPage(1);
    setActiveQuery(searchQuery.trim());
  };

  const handleClearSearch = () => {
    setSearchQuery('');
    setActiveQuery('');
    setPage(1);
  };

  const handleToggleSelectAll = () => {
    if (selectedIds.size === items.length && items.length > 0) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(items.map((it) => it.id)));
    }
  };

  const handleToggleSelect = (id) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) {
        next.delete(id);
      } else {
        next.add(id);
      }
      return next;
    });
  };

  const openAddModal = () => {
    setFormSourceWord('');
    setFormTargetWord('');
    setFormNotes('');
    setShowAddModal(true);
  };

  const handleAddSubmit = async (e) => {
    e.preventDefault();
    if (!formSourceWord.trim() || !formTargetWord.trim()) {
      showToast('error', '원문 단어와 번역 단어를 모두 입력해 주세요.');
      return;
    }
    setSubmitting(true);
    try {
      await addDictionaryEntry({
        source_word: formSourceWord.trim(),
        target_word: formTargetWord.trim(),
        notes: formNotes.trim(),
      });
      showToast('success', `'${formSourceWord.trim()}' 고유명사가 사전에 등록되었습니다.`);
      setShowAddModal(false);
      loadData(page, activeQuery);
    } catch (err) {
      showToast('error', err.response?.data?.detail || '고유명사 등록에 실패했습니다.');
    } finally {
      setSubmitting(false);
    }
  };

  const openEditModal = (item) => {
    setEditingItem(item);
    setFormSourceWord(item.source_word);
    setFormTargetWord(item.target_word);
    setFormNotes(item.notes || '');
    setShowEditModal(true);
  };

  const handleEditSubmit = async (e) => {
    e.preventDefault();
    if (!formSourceWord.trim() || !formTargetWord.trim()) {
      showToast('error', '원문 단어와 번역 단어를 모두 입력해 주세요.');
      return;
    }
    setSubmitting(true);
    try {
      await updateDictionaryEntry(editingItem.id, {
        source_word: formSourceWord.trim(),
        target_word: formTargetWord.trim(),
        notes: formNotes.trim(),
      });
      showToast('success', `'${formSourceWord.trim()}' 고유명사 정보가 수정되었습니다.`);
      setShowEditModal(false);
      setEditingItem(null);
      loadData(page, activeQuery);
    } catch (err) {
      showToast('error', err.response?.data?.detail || '고유명사 수정에 실패했습니다.');
    } finally {
      setSubmitting(false);
    }
  };

  const handleDeleteOne = async (id, sourceWord) => {
    if (!window.confirm(`'${sourceWord}' 단어를 고유명사 사전에서 삭제하시겠습니까?`)) {
      return;
    }
    try {
      await deleteDictionaryEntry(id);
      showToast('success', `'${sourceWord}' 단어가 삭제되었습니다.`);
      loadData(page, activeQuery);
    } catch (err) {
      showToast('error', err.response?.data?.detail || '단어 삭제에 실패했습니다.');
    }
  };

  const handleBatchDelete = async () => {
    if (selectedIds.size === 0) return;
    if (!window.confirm(`선택한 ${selectedIds.size}개의 고유명사 단어를 일괄 삭제하시겠습니까?`)) {
      return;
    }
    try {
      const res = await batchDeleteDictionaryEntries(Array.from(selectedIds));
      showToast('success', `${res.deleted_count || selectedIds.size}건의 고유명사가 삭제되었습니다.`);
      setSelectedIds(new Set());
      loadData(page, activeQuery);
    } catch (err) {
      showToast('error', err.response?.data?.detail || '일괄 삭제에 실패했습니다.');
    }
  };

  return (
    <div className="w-full max-w-5xl mx-auto space-y-6 pb-12 animate-in fade-in duration-300">
      {/* Top Banner / Header */}
      <div className="p-6 rounded-2xl bg-gradient-to-r from-slate-900 via-indigo-950/40 to-slate-900 border border-slate-800 shadow-xl flex flex-col sm:flex-row sm:items-center justify-between gap-4">
        <div className="flex items-start space-x-4">
          <div className="w-12 h-12 rounded-2xl bg-indigo-500/20 border border-indigo-500/40 flex items-center justify-center text-indigo-400 flex-shrink-0 shadow-lg">
            <BookOpen className="w-6 h-6" />
          </div>
          <div>
            <div className="flex items-center space-x-2">
              <h1 className="text-xl font-extrabold text-white">
                고유명사 사전 관리
              </h1>
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-indigo-500/20 text-indigo-300 border border-indigo-500/30">
                총 {total}건 등록됨
              </span>
              <span className="px-2.5 py-0.5 rounded-full text-[11px] font-bold bg-emerald-500/20 text-emerald-300 border border-emerald-500/30">
                페이지당 50건
              </span>
            </div>
            <p className="text-xs text-slate-400 mt-1 leading-relaxed">
              인명, 캐릭터 이름, 지명, 고유 스킬명 등 인공지능이 임의로 오역하지 않도록 강제할 <strong>원문 단어 ➔ 지정 번역 단어</strong> 사전을 관리합니다. 번역 시 최우선 반영됩니다.
            </p>
          </div>
        </div>

        <div className="flex items-center space-x-2.5 self-start sm:self-center">
          <button
            type="button"
            onClick={openAddModal}
            className="px-4 py-2.5 rounded-xl bg-indigo-600 hover:bg-indigo-500 text-white text-xs font-bold flex items-center space-x-2 transition shadow-lg shadow-indigo-600/30"
          >
            <Plus className="w-4 h-4" />
            <span>신규 단어 등록</span>
          </button>

          <button
            type="button"
            onClick={() => loadData(page, activeQuery)}
            disabled={loading}
            className="p-2.5 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-700 transition"
            title="새로고침"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin text-indigo-400' : ''}`} />
          </button>
        </div>
      </div>

      {/* Status Message Alert */}
      {statusMsg && (
        <div
          className={`p-4 rounded-2xl border flex items-center justify-between gap-3 text-xs font-medium shadow-lg animate-in fade-in ${
            statusMsg.type === 'success'
              ? 'bg-emerald-950/50 border-emerald-500/40 text-emerald-200'
              : 'bg-rose-950/50 border-rose-500/40 text-rose-200'
          }`}
        >
          <div className="flex items-center space-x-2.5">
            {statusMsg.type === 'success' ? (
              <CheckCircle2 className="w-4 h-4 text-emerald-400 flex-shrink-0" />
            ) : (
              <AlertCircle className="w-4 h-4 text-rose-400 flex-shrink-0" />
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

      {/* Control Bar: Search & Batch Actions */}
      <div className="p-4 rounded-2xl bg-slate-900 border border-slate-800 shadow-md flex flex-col sm:flex-row sm:items-center justify-between gap-3">
        <form onSubmit={handleSearch} className="flex items-center space-x-2 flex-1 max-w-md">
          <div className="relative flex-1">
            <Search className="w-4 h-4 text-slate-500 absolute left-3.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="원문 단어 또는 번역 단어 검색..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="w-full pl-9 pr-8 py-2 rounded-xl bg-slate-950 border border-slate-700 text-xs text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            {searchQuery && (
              <button
                type="button"
                onClick={handleClearSearch}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-500 hover:text-slate-300"
              >
                <X className="w-3.5 h-3.5" />
              </button>
            )}
          </div>
          <button
            type="submit"
            className="px-3.5 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-200 text-xs font-semibold border border-slate-700 transition"
          >
            검색
          </button>
        </form>

        <div className="flex items-center space-x-2">
          {selectedIds.size > 0 && (
            <button
              type="button"
              onClick={handleBatchDelete}
              className="px-3.5 py-2 rounded-xl bg-rose-600/90 hover:bg-rose-500 text-white text-xs font-bold flex items-center space-x-1.5 transition shadow"
            >
              <Trash2 className="w-3.5 h-3.5" />
              <span>선택 {selectedIds.size}개 일괄 삭제</span>
            </button>
          )}

          <div className="text-xs text-slate-400 font-mono pl-2">
            페이지 <strong className="text-white">{page}</strong> / {totalPages} (총 {total}건)
          </div>
        </div>
      </div>

      {/* Main Table */}
      <div className="rounded-2xl bg-slate-900 border border-slate-800 shadow-xl overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-left text-xs border-collapse">
            <thead>
              <tr className="bg-slate-950/80 border-b border-slate-800 text-slate-400 font-semibold select-none">
                <th className="py-3.5 px-4 w-12 text-center">
                  <input
                    type="checkbox"
                    checked={items.length > 0 && selectedIds.size === items.length}
                    onChange={handleToggleSelectAll}
                    className="rounded bg-slate-800 border-slate-700 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                  />
                </th>
                <th className="py-3.5 px-3 w-16 text-center font-mono">No</th>
                <th className="py-3.5 px-4 font-bold text-slate-200">원문 단어 (Source)</th>
                <th className="py-3.5 px-2 w-8 text-center text-slate-500">➔</th>
                <th className="py-3.5 px-4 font-bold text-slate-200">번역 단어 (Target)</th>
                <th className="py-3.5 px-4 text-slate-400">설명 / 메모</th>
                <th className="py-3.5 px-4 w-36 text-slate-500">등록/수정일</th>
                <th className="py-3.5 px-4 w-24 text-center">관리</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/60 font-medium">
              {items.length === 0 ? (
                <tr>
                  <td colSpan={8} className="py-16 text-center text-slate-500">
                    <BookOpen className="w-10 h-10 mx-auto text-slate-600 mb-2 opacity-50" />
                    <p className="text-sm font-semibold text-slate-400">등록된 고유명사가 없습니다.</p>
                    <p className="text-xs text-slate-500 mt-1">
                      우측 상단 <strong>[신규 단어 등록]</strong> 버튼을 눌러 인명이나 용어를 추가해 보세요.
                    </p>
                  </td>
                </tr>
              ) : (
                items.map((item, idx) => {
                  const isChecked = selectedIds.has(item.id);
                  const displayIndex = (page - 1) * size + idx + 1;
                  const dateStr = item.updated_at
                    ? new Date(item.updated_at).toLocaleString('ko-KR', {
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit'
                      })
                    : '-';

                  return (
                    <tr
                      key={item.id}
                      className={`hover:bg-slate-800/40 transition group ${
                        isChecked ? 'bg-indigo-950/20' : ''
                      }`}
                    >
                      <td className="py-3 px-4 text-center">
                        <input
                          type="checkbox"
                          checked={isChecked}
                          onChange={() => handleToggleSelect(item.id)}
                          className="rounded bg-slate-800 border-slate-700 text-indigo-600 focus:ring-indigo-500 cursor-pointer"
                        />
                      </td>
                      <td className="py-3 px-3 text-center font-mono text-slate-500 text-[11px]">
                        {displayIndex}
                      </td>
                      <td className="py-3 px-4 font-bold text-white">
                        <span className="px-2.5 py-1 rounded-lg bg-slate-950 border border-slate-700/80 text-amber-300 font-mono text-xs inline-block">
                          {item.source_word}
                        </span>
                      </td>
                      <td className="py-3 px-2 text-center text-slate-600 font-bold">
                        <ArrowRight className="w-3.5 h-3.5 mx-auto text-indigo-400/70" />
                      </td>
                      <td className="py-3 px-4 font-bold text-white">
                        <span className="px-2.5 py-1 rounded-lg bg-indigo-950/70 border border-indigo-500/40 text-indigo-200 text-xs inline-block">
                          {item.target_word}
                        </span>
                      </td>
                      <td className="py-3 px-4 text-slate-400 text-xs truncate max-w-xs">
                        {item.notes || <span className="text-slate-600 italic">메모 없음</span>}
                      </td>
                      <td className="py-3 px-4 text-slate-500 text-[11px] font-mono">
                        {dateStr}
                      </td>
                      <td className="py-3 px-4 text-center">
                        <div className="flex items-center justify-center space-x-1">
                          <button
                            type="button"
                            onClick={() => openEditModal(item)}
                            className="p-1.5 rounded-lg text-slate-400 hover:text-indigo-300 hover:bg-slate-800 transition"
                            title="수정"
                          >
                            <Edit2 className="w-3.5 h-3.5" />
                          </button>
                          <button
                            type="button"
                            onClick={() => handleDeleteOne(item.id, item.source_word)}
                            className="p-1.5 rounded-lg text-slate-400 hover:text-rose-400 hover:bg-slate-800 transition"
                            title="삭제"
                          >
                            <Trash2 className="w-3.5 h-3.5" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>

        {/* 50-Item Pagination Bar */}
        {totalPages > 1 && (
          <div className="p-4 bg-slate-950/80 border-t border-slate-800 flex items-center justify-between gap-4">
            <span className="text-xs text-slate-400">
              전체 <strong>{total}</strong>건 중 {(page - 1) * size + 1} - {Math.min(page * size, total)}건 표시 중
            </span>

            <div className="flex items-center space-x-1.5">
              <button
                type="button"
                onClick={() => setPage((p) => Math.max(1, p - 1))}
                disabled={page <= 1 || loading}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-slate-300 text-xs font-semibold flex items-center space-x-1 border border-slate-700 transition"
              >
                <ChevronLeft className="w-4 h-4" />
                <span>이전 (50건)</span>
              </button>

              <div className="px-3 py-1.5 rounded-lg bg-slate-900 border border-slate-800 text-xs font-mono font-bold text-white">
                {page} / {totalPages}
              </div>

              <button
                type="button"
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
                disabled={page >= totalPages || loading}
                className="px-3 py-1.5 rounded-lg bg-slate-800 hover:bg-slate-700 disabled:opacity-40 text-slate-300 text-xs font-semibold flex items-center space-x-1 border border-slate-700 transition"
              >
                <span>다음 (50건)</span>
                <ChevronRight className="w-4 h-4" />
              </button>
            </div>
          </div>
        )}
      </div>

      {/* ADD MODAL */}
      {showAddModal && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-2xl space-y-5 animate-in fade-in zoom-in-95">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center space-x-2.5">
                <div className="p-2 rounded-xl bg-indigo-500/20 text-indigo-400">
                  <Plus className="w-5 h-5" />
                </div>
                <h3 className="text-base font-bold text-white">신규 고유명사 단어 등록</h3>
              </div>
              <button
                type="button"
                onClick={() => setShowAddModal(false)}
                className="text-slate-400 hover:text-white p-1 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleAddSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label className="block text-xs font-bold text-slate-300">
                  원문 단어 (Source Word) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="예: ルフィ, 竈門炭治郎, Naruto 등"
                  value={formSourceWord}
                  onChange={(e) => setFormSourceWord(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <p className="text-[11px] text-slate-500">
                  영상/자막 원문에 등장하는 철자 그대로 입력하세요.
                </p>
              </div>

              <div className="space-y-1.5">
                <label className="block text-xs font-bold text-slate-300">
                  번역 지정 단어 (Target Word) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  placeholder="예: 루피, 카마도 탄지로, 나루토 등"
                  value={formTargetWord}
                  onChange={(e) => setFormTargetWord(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
                <p className="text-[11px] text-slate-500">
                  번역 자막에 최우선 적용할 한국어(또는 대상 언어) 표기를 입력하세요.
                </p>
              </div>

              <div className="space-y-1.5">
                <label className="block text-xs font-bold text-slate-300">
                  설명 / 메모 (선택 사항)
                </label>
                <input
                  type="text"
                  placeholder="예: 주인공, 해적단 선장, 메인 히어로"
                  value={formNotes}
                  onChange={(e) => setFormNotes(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-sm text-white focus:outline-none focus:ring-2 focus:ring-indigo-500"
                />
              </div>

              <div className="flex items-center justify-end space-x-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold"
                >
                  취소
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-5 py-2 rounded-xl bg-indigo-600 hover:bg-indigo-500 disabled:opacity-50 text-white text-xs font-bold flex items-center space-x-1.5 shadow"
                >
                  <Save className="w-3.5 h-3.5" />
                  <span>{submitting ? '저장 중...' : '사전에 추가'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}

      {/* EDIT MODAL */}
      {showEditModal && editingItem && (
        <div className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-lg bg-slate-900 border border-slate-800 rounded-3xl p-6 shadow-2xl space-y-5 animate-in fade-in zoom-in-95">
            <div className="flex items-center justify-between border-b border-slate-800 pb-3">
              <div className="flex items-center space-x-2.5">
                <div className="p-2 rounded-xl bg-purple-500/20 text-purple-400">
                  <Edit2 className="w-5 h-5" />
                </div>
                <h3 className="text-base font-bold text-white">고유명사 단어 정보 수정</h3>
              </div>
              <button
                type="button"
                onClick={() => {
                  setShowEditModal(false);
                  setEditingItem(null);
                }}
                className="text-slate-400 hover:text-white p-1 rounded-lg"
              >
                <X className="w-5 h-5" />
              </button>
            </div>

            <form onSubmit={handleEditSubmit} className="space-y-4">
              <div className="space-y-1.5">
                <label className="block text-xs font-bold text-slate-300">
                  원문 단어 (Source Word) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  value={formSourceWord}
                  onChange={(e) => setFormSourceWord(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                />
              </div>

              <div className="space-y-1.5">
                <label className="block text-xs font-bold text-slate-300">
                  번역 지정 단어 (Target Word) <span className="text-rose-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  value={formTargetWord}
                  onChange={(e) => setFormTargetWord(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-sm font-semibold text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                />
              </div>

              <div className="space-y-1.5">
                <label className="block text-xs font-bold text-slate-300">
                  설명 / 메모
                </label>
                <input
                  type="text"
                  value={formNotes}
                  onChange={(e) => setFormNotes(e.target.value)}
                  className="w-full px-4 py-2.5 rounded-xl bg-slate-950 border border-slate-700 text-sm text-white focus:outline-none focus:ring-2 focus:ring-purple-500"
                />
              </div>

              <div className="flex items-center justify-end space-x-2 pt-2 border-t border-slate-800">
                <button
                  type="button"
                  onClick={() => {
                    setShowEditModal(false);
                    setEditingItem(null);
                  }}
                  className="px-4 py-2 rounded-xl bg-slate-800 hover:bg-slate-700 text-slate-300 text-xs font-semibold"
                >
                  취소
                </button>
                <button
                  type="submit"
                  disabled={submitting}
                  className="px-5 py-2 rounded-xl bg-purple-600 hover:bg-purple-500 disabled:opacity-50 text-white text-xs font-bold flex items-center space-x-1.5 shadow"
                >
                  <Save className="w-3.5 h-3.5" />
                  <span>{submitting ? '수정 중...' : '변경 사항 저장'}</span>
                </button>
              </div>
            </form>
          </div>
        </div>
      )}
    </div>
  );
}

