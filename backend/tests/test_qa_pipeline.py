import os
import sys
import tempfile
import unittest
from pathlib import Path
from typing import List, Dict, Any

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from sqlalchemy import create_engine

import app.database as db_module
from app.database import (
    init_db,
    add_dictionary_entry,
    get_dictionary_entries,
    update_dictionary_entry,
    delete_dictionary_entry,
    batch_delete_dictionary_entries,
    get_all_dictionary_map,
)
from app.api.routes import parse_srt_segments_multi_encoding as parse_srt_file_to_segments
from app.services.srt_generator import (
    optimize_subtitle_timing,
    generate_srt_file,
    format_timestamp_ms,
    to_ms,
)
from app.services.subtitle_translator import (
    apply_dictionary_postprocess,
    build_dictionary_prompt_section,
)


def _fmt_seg_log(segments: List[Dict[str, Any]]) -> str:
    parts = []
    for idx, s in enumerate(segments, start=1):
        st_ms = to_ms(s["start"])
        ed_ms = to_ms(s["end"])
        txt = (s.get("refined_text") or s.get("text") or s.get("raw_text") or "").replace("\n", "\\n")
        parts.append(
            f"#{idx} [{s['start']:.3f}s ~ {s['end']:.3f}s ({format_timestamp_ms(st_ms)} --> {format_timestamp_ms(ed_ms)})] \"{txt}\""
        )
    return " | ".join(parts)


class QAPipelineTestSuite(unittest.TestCase):
    """
    Automated QA Unit Test Suite for TransM Subtitle Timing Engine & Proper Noun Dictionary Pipeline.
    Covers Cases 1 ~ 5 specified in the QA verification requirements.
    """

    REPORT_ROWS: List[Dict[str, str]] = []

    def test_1_timing_order_false_overlap_defense(self):
        """
        [Case 1] 타이밍 연산 순서 검증 (False Overlap 방어):
        세그먼트 1(01.000 ~ 02.000, '첫 번째 대사')과 세그먼트 2(02.200 ~ 03.500, '두 번째 대사') 입력 시,
        2줄로 병합되지 않고 세그먼트 1의 종료 시간이 02.150(2.200 - 0.050)으로 클램핑 연장되는지 검증.
        """
        raw_input = [
            {"index": 1, "start": 1.000, "end": 2.000, "text": "첫 번째 대사"},
            {"index": 2, "start": 2.200, "end": 3.500, "text": "두 번째 대사"},
        ]
        in_log = _fmt_seg_log(raw_input)

        output = optimize_subtitle_timing(raw_input)
        out_log = _fmt_seg_log(output)

        self.assertEqual(len(output), 2, "일반 연속 대사가 가짜 중첩으로 병합되면 안 됩니다.")
        self.assertNotIn("\n", output[0]["text"], "세그먼트 1에 줄바꿈(2줄 병합)이 발생하면 안 됩니다.")
        self.assertAlmostEqual(output[0]["start"], 1.000, places=3)
        self.assertAlmostEqual(output[0]["end"], 2.150, places=3)
        self.assertAlmostEqual(output[1]["start"], 2.200, places=3)
        self.assertAlmostEqual(output[1]["end"], 3.800, places=3)
        self.assertAlmostEqual(output[1]["start"] - output[0]["end"], 0.050, places=3)

        self.__class__.REPORT_ROWS.append({
            "case": "1. 타이밍 연산 순서 (False Overlap 방어)",
            "status": "PASS",
            "input": in_log,
            "output": out_log,
            "detail": "2줄 오병합 없음, #1 종료 2.150s(2.200-0.050) 클램핑 연장 & 50ms 갭 유지",
        })

    def test_2_ample_gap_plus_300ms_extension(self):
        """
        [Case 2] 여유 구간 +0.3초 연장 검증:
        다음 세그먼트와 1초 이상 떨어진 세그먼트의 종료 시간이 정확히 +300ms 연장되는지 검증.
        """
        raw_input = [
            {"index": 1, "start": 1.000, "end": 2.000, "text": "여유 있는 첫 번째 대사"},
            {"index": 2, "start": 3.500, "end": 4.500, "text": "1.5초 뒤 시작하는 두 번째 대사"},
        ]
        in_log = _fmt_seg_log(raw_input)

        output = optimize_subtitle_timing(raw_input)
        out_log = _fmt_seg_log(output)

        self.assertEqual(len(output), 2)
        self.assertAlmostEqual(output[0]["start"], 1.000, places=3)
        self.assertAlmostEqual(output[0]["end"], 2.300, places=3)
        self.assertAlmostEqual(output[1]["start"], 3.500, places=3)
        self.assertAlmostEqual(output[1]["end"], 4.800, places=3)

        self.__class__.REPORT_ROWS.append({
            "case": "2. 여유 구간 +0.3초(+300ms) 연장",
            "status": "PASS",
            "input": in_log,
            "output": out_log,
            "detail": "1.5s 간격 여유 구간에서 #1(2.000->2.300s), #2(4.500->4.800s) 정확히 +300ms 연장",
        })

    def test_3_micro_overlap_vs_true_speaker_overlap(self):
        """
        [Case 3] 미세 중첩 분리 vs 실제 화자 중첩 2줄 병합 검증:
        - 3A (80ms 미세 중첩): 2줄 병합 대신 50ms 갭으로 분리되는지 검증.
        - 3B (500ms 이상 실제 중첩): '- 화자1\\n- 화자2' 형태의 2줄 자막으로 정상 병합되며 start < end 무결성이 유지되는지 검증.
        """
        # 3A: 80ms micro-overlap (1.000~2.080 vs 2.000~3.000) -> overlap = 80ms (< 150ms threshold)
        micro_input = [
            {"index": 1, "start": 1.000, "end": 2.080, "text": "앞 화자 미세 겹침 대사"},
            {"index": 2, "start": 2.000, "end": 3.000, "text": "뒤 화자 연속 시작 대사"},
        ]
        micro_in_log = _fmt_seg_log(micro_input)
        micro_output = optimize_subtitle_timing(micro_input)
        micro_out_log = _fmt_seg_log(micro_output)

        self.assertEqual(len(micro_output), 2, "80ms 미세 중첩은 2줄 병합되면 안 됩니다.")
        self.assertNotIn("\n", micro_output[0]["text"])
        self.assertNotIn("\n", micro_output[1]["text"])
        self.assertAlmostEqual(micro_output[0]["start"], 1.000, places=3)
        self.assertAlmostEqual(micro_output[0]["end"], 1.950, places=3)  # 2.000 - 0.050
        self.assertAlmostEqual(micro_output[1]["start"], 2.000, places=3)
        self.assertAlmostEqual(micro_output[1]["end"], 3.300, places=3)
        for seg in micro_output:
            self.assertLess(seg["start"], seg["end"], "start < end 무결성 위반")

        self.__class__.REPORT_ROWS.append({
            "case": "3-A. 미세 중첩(80ms) 분리 검증",
            "status": "PASS",
            "input": micro_in_log,
            "output": micro_out_log,
            "detail": "80ms(<150ms) 미세 중첩을 2줄 병합하지 않고 #1 종료 1.950s(50ms 갭)로 분리",
        })

        # 3B: 1500ms (>= 500ms) real overlap with solo pre-segment (1.000~3.000 vs 1.500~3.000)
        # Pre-solo = 500ms (>= 350ms), overlap = 1500ms (>= 500ms), post-solo = 0ms
        true_overlap_input = [
            {"index": 1, "start": 1.000, "end": 3.000, "text": "화자1 대사"},
            {"index": 2, "start": 1.500, "end": 3.000, "text": "화자2 대사"},
        ]
        true_in_log = _fmt_seg_log(true_overlap_input)
        true_output = optimize_subtitle_timing(true_overlap_input)
        true_out_log = _fmt_seg_log(true_output)

        self.assertEqual(len(true_output), 2)
        # First segment: solo speaker 1 (1.000 ~ 1.450)
        self.assertAlmostEqual(true_output[0]["start"], 1.000, places=3)
        self.assertAlmostEqual(true_output[0]["end"], 1.450, places=3)
        self.assertEqual(true_output[0]["text"], "화자1 대사")
        # Second segment: merged 2-line overlap (1.500 ~ 3.300)
        self.assertAlmostEqual(true_output[1]["start"], 1.500, places=3)
        self.assertAlmostEqual(true_output[1]["end"], 3.300, places=3)
        self.assertEqual(true_output[1]["text"], "- 화자1 대사\n- 화자2 대사")
        for idx, seg in enumerate(true_output):
            self.assertLess(seg["start"], seg["end"], f"세그먼트 #{idx + 1} start < end 무결성 위반")
            if idx > 0:
                self.assertGreaterEqual(
                    round(seg["start"] - true_output[idx - 1]["end"], 3),
                    0.050,
                    "세그먼트 간 50ms 갭 미달",
                )

        self.__class__.REPORT_ROWS.append({
            "case": "3-B. 실제 화자 중첩(1500ms) 2줄 병합",
            "status": "PASS",
            "input": true_in_log,
            "output": true_out_log,
            "detail": "단독 구간(1.000~1.450s) 분할 + 중첩 구간(1.500~3.300s) '- 화자1 대사\\n- 화자2 대사' 병합 및 start < end 보장",
        })

    def test_4_idempotency_on_resave_and_retranslation(self):
        """
        [Case 4] 재저장/재번역 시 +0.3초 중복 누적 방지(멱등성) 검증:
        이미 타이밍 최적화가 적용된 SRT 세그먼트를 다시 저장하거나 재번역 파이프라인에 통과시킬 때
        종료 시간이 추가로 늘어나지 않는지 검증.
        """
        initial_raw = [
            {"index": 1, "start": 1.000, "end": 2.000, "text": "첫 번째 자막"},
            {"index": 2, "start": 4.000, "end": 5.000, "text": "두 번째 자막"},
        ]
        # 1차 최적화 (STT 직후 1회 적용: 2.000 -> 2.300, 5.000 -> 5.300)
        first_optimized = optimize_subtitle_timing(initial_raw, apply_timing_optimization=True)
        first_log = _fmt_seg_log(first_optimized)
        self.assertAlmostEqual(first_optimized[0]["end"], 2.300, places=3)
        self.assertAlmostEqual(first_optimized[1]["end"], 5.300, places=3)

        # 2차 호출 A: _timing_optimized 플래그가 있는 세그먼트를 optimize_subtitle_timing에 재전달
        second_pass_flag = optimize_subtitle_timing(first_optimized, apply_timing_optimization=True)
        self.assertAlmostEqual(second_pass_flag[0]["end"], 2.300, places=3)
        self.assertAlmostEqual(second_pass_flag[1]["end"], 5.300, places=3)

        # 2차 호출 B: SRT 파일로 저장 후 다시 파싱하여 재저장/재번역(apply_timing_optimization=False) 수행
        with tempfile.TemporaryDirectory() as tmpdir:
            srt_file = Path(tmpdir) / "test_idempotent.srt"
            generate_srt_file(first_optimized, srt_file, optimize=False, apply_timing_optimization=False)
            reloaded_segments = parse_srt_file_to_segments(srt_file)
            resaved_segments = optimize_subtitle_timing(
                reloaded_segments,
                extend_sec=0.0,
                apply_timing_optimization=False,
            )
            generate_srt_file(resaved_segments, srt_file, optimize=False, apply_timing_optimization=False)
            final_segments = parse_srt_file_to_segments(srt_file)

        final_log = _fmt_seg_log(final_segments)
        self.assertAlmostEqual(final_segments[0]["start"], 1.000, places=3)
        self.assertAlmostEqual(final_segments[0]["end"], 2.300, places=3, msg="+0.3초가 중복 누적되었습니다!")
        self.assertAlmostEqual(final_segments[1]["start"], 4.000, places=3)
        self.assertAlmostEqual(final_segments[1]["end"], 5.300, places=3, msg="+0.3초가 중복 누적되었습니다!")

        self.__class__.REPORT_ROWS.append({
            "case": "4. 재저장/재번역 +0.3s 중복 누적 방지(멱등성)",
            "status": "PASS",
            "input": f"[1차 최적화 후] {first_log}",
            "output": f"[재저장/재번역 후] {final_log}",
            "detail": "1차 최적화(2.300s, 5.300s) 이후 재호출·SRT 재저장 시 +0.6s/+0.9s 누적 없이 2.300s, 5.300s 유지",
        })

    def test_5_dictionary_crud_50_pagination_and_replacement(self):
        """
        [Case 5] SQLite / PostgreSQL 고유명사 사전 CRUD 및 50건 페이징 검증:
        고유명사 단어 등록, 조회(size=50), 수정, 삭제 및 번역 텍스트 내 고유명사 치환 함수(조사 보정·단어 경계 방어 포함)가
        정상 작동하는지 검증.
        """
        # Isolate database in a temporary SQLite file so production data is never mutated
        orig_engine = db_module._engine
        orig_is_sqlite = db_module._is_sqlite
        orig_db_name = db_module._connected_db_name

        with tempfile.TemporaryDirectory() as tmpdir:
            temp_db_path = Path(tmpdir) / "qa_test_dict.sqlite3"
            try:
                test_engine = create_engine(
                    f"sqlite:///{temp_db_path.as_posix()}",
                    connect_args={"check_same_thread": False, "timeout": 30.0},
                )
                db_module._configure_sqlite_pragma(test_engine)
                db_module._engine = test_engine
                db_module._is_sqlite = True
                db_module._connected_db_name = str(temp_db_path)

                init_db()

                # 1. 65건 고유명사 등록 (50건 페이징 검증용)
                created_ids = []
                for i in range(1, 66):
                    entry = add_dictionary_entry(
                        source_word=f"ProperTerm_{i:03d}",
                        target_word=f"고유명사_{i:03d}",
                        notes=f"QA 테스트 항목 #{i}",
                    )
                    self.assertIn("id", entry)
                    created_ids.append(entry["id"])

                # 실전 고유명사 추가 (조사 결합 및 짧은 영문 오치환 방어 검증용)
                e_harry = add_dictionary_entry("Harry Potter", "해리 포터", "주인공")
                e_hogwarts = add_dictionary_entry("Hogwarts", "호그와트", "마법학교")
                e_al = add_dictionary_entry("Al", "알폰스", "짧은 대문자 인명")
                created_ids.extend([e_harry["id"], e_hogwarts["id"], e_al["id"]])

                total_expected = 68

                # 2. 조회 (size=50, page=1 & page=2)
                page1 = get_dictionary_entries(page=1, size=50)
                page2 = get_dictionary_entries(page=2, size=50)
                self.assertEqual(page1["total"], total_expected)
                self.assertEqual(page1["size"], 50)
                self.assertEqual(page1["page"], 1)
                self.assertEqual(page1["total_pages"], 2)
                self.assertEqual(len(page1["items"]), 50)
                self.assertEqual(len(page2["items"]), 18)

                # 검색 쿼리 검증
                search_res = get_dictionary_entries(page=1, size=50, query="Hogwarts")
                self.assertEqual(search_res["total"], 1)
                self.assertEqual(search_res["items"][0]["target_word"], "호그와트")

                # 3. 수정 (Update) 검증
                updated = update_dictionary_entry(
                    e_hogwarts["id"],
                    source_word="Hogwarts",
                    target_word="호그와트 마법학교",
                    notes="명칭 구체화",
                )
                self.assertIsNotNone(updated)
                self.assertEqual(updated["target_word"], "호그와트 마법학교")

                # 다시 '호그와트'로 복원하여 치환 테스트 진행
                update_dictionary_entry(e_hogwarts["id"], "Hogwarts", "호그와트", "마법학교")

                # 4. 번역 텍스트 내 고유명사 치환 및 조사 보정 검증
                dict_map = get_all_dictionary_map()
                self.assertGreaterEqual(len(dict_map), total_expected)

                orig_line = "Harry Potter is going to Hogwarts with Al in the morning."
                # LLM이 일부 고유명사를 원문으로 남기거나 받침이 맞지 않는 조사를 붙인 상황 시뮬레이션
                raw_trans = "Harry Potter은 Hogwarts을 향해 Al와 함께 아침에 출발했다."
                replaced = apply_dictionary_postprocess(orig_line, raw_trans, dict_map)

                # '해리 포터'(무받침) + 은 -> 는, '호그와트'(무받침) + 을 -> 를, '알폰스'(무받침) + 와 -> 와
                self.assertEqual(
                    replaced,
                    "해리 포터는 호그와트를 향해 알폰스와 함께 아침에 출발했다.",
                )

                # 짧은 대문자 고유명사('Al')가 일반 영단어('all', 'already')나 소문자('in')를 오치환하지 않는지 검증
                non_match_orig = "All students are already in the hall."
                non_match_trans = "모든 학생들이 이미 홀 안에 모여 있다."
                self.assertEqual(
                    apply_dictionary_postprocess(non_match_orig, non_match_trans, dict_map),
                    non_match_trans,
                )

                # 프롬프트 사전 섹션 빌더 검증
                prompt_sec = build_dictionary_prompt_section([{"text": orig_line}], dict_map)
                self.assertIn("Harry Potter -> 해리 포터", prompt_sec)
                self.assertIn("Hogwarts -> 호그와트", prompt_sec)

                # 5. 단건 삭제 & 일괄 삭제 검증
                delete_dictionary_entry(e_harry["id"])
                after_single_del = get_dictionary_entries(page=1, size=50)
                self.assertEqual(after_single_del["total"], total_expected - 1)

                remaining_ids = [cid for cid in created_ids if cid != e_harry["id"]]
                deleted_count = batch_delete_dictionary_entries(remaining_ids)
                self.assertEqual(deleted_count, total_expected - 1)

                final_page = get_dictionary_entries(page=1, size=50)
                self.assertEqual(final_page["total"], 0)

                test_engine.dispose()
            finally:
                db_module._engine = orig_engine
                db_module._is_sqlite = orig_is_sqlite
                db_module._connected_db_name = orig_db_name

        self.__class__.REPORT_ROWS.append({
            "case": "5. 고유명사 사전 CRUD · 50건 페이징 · 치환",
            "status": "PASS",
            "input": f"등록 68건 조회(size=50) & 원문: \"{orig_line}\" / 치환 전: \"{raw_trans}\"",
            "output": f"Page1=50건, Page2=18건(total=68) / 치환 후: \"{replaced}\" / 삭제 후 잔여=0건",
            "detail": "등록·수정·50건 페이징·단어경계 치환·받침 조사 보정(은->는, 을->를)·삭제 완벽 통과",
        })

    def test_6_batch_download_selected_zip(self):
        """
        [Case 6] 선택 항목(1건 이상) ZIP 일괄 다운로드 검증:
        체크된 task_ids가 1건일 때와 다건(2건)일 때 모두 /api/download/batch-selected가
        UTF-8 BOM(.srt)을 포함한 정상 ZIP 압축 파일만 반환하고, 선택되지 않은 항목은 제외되는지 검증.
        """
        import asyncio
        import io
        import zipfile
        from fastapi import HTTPException
        from app.api.routes import batch_download_selected, BatchDownloadRequest

        orig_engine = db_module._engine
        orig_is_sqlite = db_module._is_sqlite
        orig_db_name = db_module._connected_db_name

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            temp_db_path = tmp_path / "qa_test_zip.sqlite3"
            try:
                test_engine = create_engine(
                    f"sqlite:///{temp_db_path.as_posix()}",
                    connect_args={"check_same_thread": False, "timeout": 30.0},
                )
                db_module._configure_sqlite_pragma(test_engine)
                db_module._engine = test_engine
                db_module._is_sqlite = True
                db_module._connected_db_name = str(temp_db_path)
                init_db()

                srt1 = tmp_path / "t_sel_1.srt"
                srt2 = tmp_path / "t_sel_2.srt"
                srt3 = tmp_path / "t_unselected.srt"
                generate_srt_file([{"index": 1, "start": 1.0, "end": 2.0, "text": "첫 번째 선택 자막"}], srt1)
                generate_srt_file([{"index": 1, "start": 1.0, "end": 2.0, "text": "두 번째 선택 자막"}], srt2)
                generate_srt_file([{"index": 1, "start": 1.0, "end": 2.0, "text": "미선택 자막"}], srt3)

                db_module.add_completed_task("task_sel_1", "movie_one.mp4", 1, str(srt1), "/api/download/task_sel_1", "studio")
                db_module.add_completed_task("task_sel_2", "movie_two.mp4", 1, str(srt2), "/api/download/task_sel_2", "studio")
                db_module.add_completed_task("task_unsel", "movie_three.mp4", 1, str(srt3), "/api/download/task_unsel", "studio")

                # 0건 요청 시 400 방어
                with self.assertRaises(HTTPException) as ctx:
                    asyncio.run(batch_download_selected(BatchDownloadRequest(task_ids=[])))
                self.assertEqual(ctx.exception.status_code, 400)

                # 1건 선택 시에도 ZIP 반환 검증
                resp_one = asyncio.run(batch_download_selected(BatchDownloadRequest(task_ids=["task_sel_1"])))
                self.assertEqual(resp_one.media_type, "application/zip")
                with zipfile.ZipFile(io.BytesIO(resp_one.body), "r") as zf1:
                    self.assertEqual(zf1.namelist(), ["movie_one.srt"])
                    self.assertTrue(zf1.read("movie_one.srt").startswith(b"\xef\xbb\xbf"))

                # 2건 선택 시 정확히 선택된 2건만 ZIP 반환 검증
                resp_two = asyncio.run(batch_download_selected(BatchDownloadRequest(task_ids=["task_sel_1", "task_sel_2"])))
                self.assertEqual(resp_two.media_type, "application/zip")
                with zipfile.ZipFile(io.BytesIO(resp_two.body), "r") as zf2:
                    self.assertEqual(sorted(zf2.namelist()), ["movie_one.srt", "movie_two.srt"])
                    self.assertNotIn("movie_three.srt", zf2.namelist())

                test_engine.dispose()
            finally:
                db_module._engine = orig_engine
                db_module._is_sqlite = orig_is_sqlite
                db_module._connected_db_name = orig_db_name

        self.__class__.REPORT_ROWS.append({
            "case": "6. 선택 항목(>=1건) ZIP 다운로드 API 검증",
            "status": "PASS",
            "input": "1건(['task_sel_1']) 및 2건(['task_sel_1', 'task_sel_2']) 선택 요청",
            "output": "1건 -> ['movie_one.srt'](ZIP, BOM), 2건 -> ['movie_one.srt', 'movie_two.srt'](미선택 제외)",
            "detail": "1건 이상 선택 시 ZIP 생성·UTF-8 BOM 유지·미선택 항목 제외·0건 요청 400 방어 통과",
        })

    def test_7_anti_chinese_leak_and_kana_recovery(self):
        """
        [Case 7] 중국어 누출 방어 · 전각 기호 보존 · 다중 턴 자가 교정 재시도 · 가나 음차 폴백 검증:
        배치 LLM이 일본어 원문에서 중국어('喂，这个吗？...')를 잘못 출력하더라도
        자가 교정 다중 턴 피드백으로 순수 한국어로 복구되고, 전각 기호(、？)가 포함된 한국어 문장이
        '...'로 소실되지 않으며, 순수 가나 인명('ユメちゃん')도 한글 음차('유메짱')로 보존되는지 검증.
        """
        import json
        from unittest.mock import patch
        from app.services.llm_refiner import (
            refine_subtitles_batch,
            sanitize_subtitle_text,
            transliterate_kana_to_hangul,
            is_valid_korean_result,
        )

        # 1. CJK fullwidth punctuation in valid Korean translation must NOT truncate or wipe to '...'
        orig_jp = "なぁ、これのこと?え、え、あれ?夢ちゃんと遥香さんは?"
        ko_with_cjk_punct = "이봐、이거 말이야？ 유메랑 하루카 씨는？"
        cleaned_ko = sanitize_subtitle_text(orig_jp, ko_with_cjk_punct)
        self.assertEqual(cleaned_ko, "이봐, 이거 말이야? 유메랑 하루카 씨는?")
        self.assertTrue(is_valid_korean_result(orig_jp, cleaned_ko))

        # 2. Pure-Kana name transliteration fallback
        self.assertEqual(transliterate_kana_to_hangul("ユメちゃん"), "유메짱")
        self.assertEqual(transliterate_kana_to_hangul("ゆめちゃん"), "유메짱")

        # 3. Simulated Qwen Chinese leak in batch -> multi-turn corrective retry succeeds
        batch = [
            {"index": 4, "raw_text": "俺じゃあ、ただの変態じゃん、俺。"},
            {"index": 6, "raw_text": orig_jp},
        ]
        captured_calls = []

        def fake_chat_completion(messages, **kwargs):
            captured_calls.append(messages)
            # First call = batch call returning Chinese leaked text
            if len(captured_calls) == 1:
                return json.dumps({
                    "subtitles": [
                        {"id": 4, "text": "我就是个变态罢了。"},
                        {"id": 6, "text": "喂，这个吗？嗯、嗯，那梦ちゃんと遥香さんは呢？"},
                    ]
                }, ensure_ascii=False)
            # Subsequent single-segment calls must contain the prior rejected Chinese output as assistant turn
            assistant_msgs = [m["content"] for m in messages if m["role"] == "assistant"]
            self.assertTrue(len(assistant_msgs) >= 1, "다중 턴 자가 교정 피드백이 누락되었습니다.")
            user_joined = " ".join(m["content"] for m in messages if m["role"] == "user")
            if '"id": 4' in user_joined:
                return json.dumps({"text": "이러면 나 그냥 변태잖아."}, ensure_ascii=False)
            return json.dumps({"text": "이봐, 이거 말이야? 유메랑 하루카 씨는?"}, ensure_ascii=False)

        with patch("app.services.llm_refiner.chat_completion", side_effect=fake_chat_completion):
            res = refine_subtitles_batch(None, batch, dict_map={}, source_lang_hint="일본어")

        self.assertEqual(res[4], "이러면 나 그냥 변태잖아.")
        self.assertEqual(res[6], "이봐, 이거 말이야? 유메랑 하루카 씨는?")
        self.assertTrue(is_valid_korean_result(batch[0]["raw_text"], res[4]))
        self.assertTrue(is_valid_korean_result(batch[1]["raw_text"], res[6]))

        self.__class__.REPORT_ROWS.append({
            "case": "7. 중국어 누출 방어 · 다중 턴 자가 교정 · 가나 음차",
            "status": "PASS",
            "input": "배치 오출력('我就是个变态罢了。', '喂，这个吗？...'), 'ユメちゃん', '이봐、이거 말이야？'",
            "output": f"#4='{res[4]}' | #6='{res[6]}' | 'ユメちゃん'->'{transliterate_kana_to_hangul('ユメちゃん')}'",
            "detail": "중국어 누출 시 다중 턴 자가 교정 피드백으로 100% 한글 복구 & 전각 기호 정규화 & 가나 음차 폴백 통과",
        })

    def test_8_folder_sync_ignores_subtitles_and_registers_videos_only(self):
        """
        [Case 8] 폴더 동기화 시 smi/srt 등 기존 자막 파일 무시 및 동영상 전용 등록 검증:
        _scan_folder_recursive_sync, find_video_file_on_server, upsert_studio_queue_items가
        .smi/.srt/.ass/.vtt 자막 파일은 완전히 무시하고 영상 파일만 수집·등록하는지 검증.
        """
        from unittest.mock import patch
        from app.api.routes import (
            _scan_folder_recursive_sync,
            find_video_file_on_server,
            is_supported_video_filename,
        )

        self.assertTrue(is_supported_video_filename("movie.mp4"))
        self.assertTrue(is_supported_video_filename("sub/episode_01.avi"))
        self.assertFalse(is_supported_video_filename("movie.smi"))
        self.assertFalse(is_supported_video_filename("movie.srt"))
        self.assertFalse(is_supported_video_filename("movie.ass"))
        self.assertFalse(is_supported_video_filename("movie.vtt"))

        orig_engine = db_module._engine
        orig_is_sqlite = db_module._is_sqlite
        orig_db_name = db_module._connected_db_name

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            media_root = tmp_path / "Series"
            sub_dir = media_root / "Season1"
            sub_dir.mkdir(parents=True, exist_ok=True)

            # 영상 + 기존 자막(.smi, .srt, .ass) + 이미지 혼합 생성
            (media_root / "ep01.mkv").write_bytes(b"video_01")
            (media_root / "ep01.smi").write_text("<SAMI></SAMI>", encoding="utf-8")
            (media_root / "ep01.srt").write_text("1\n00:00:01,000 --> 00:00:02,000\nhi\n", encoding="utf-8")
            (sub_dir / "ep02.avi").write_bytes(b"video_02")
            (sub_dir / "ep02.SMI").write_text("<SAMI></SAMI>", encoding="utf-8")
            (sub_dir / "ep02.ass").write_text("[Script Info]\n", encoding="utf-8")
            (sub_dir / "poster.jpg").write_bytes(b"jpg_bytes")

            discovered, subfolders, ignored_sub_count = _scan_folder_recursive_sync(media_root)
            collected_names = [d["base_name"] for d in discovered]

            self.assertEqual(collected_names, ["ep01.mkv", "ep02.avi"])
            self.assertEqual(ignored_sub_count, 4)
            self.assertEqual(subfolders, {"Season1"})

            # find_video_file_on_server가 .smi/.srt 파일은 절대 반환하지 않는지 검증
            with patch("app.api.routes.get_media_scan_dirs", return_value=[media_root]):
                self.assertIsNone(find_video_file_on_server("ep01.smi"))
                self.assertIsNone(find_video_file_on_server("ep01.srt"))
                resolved_ep01 = find_video_file_on_server("ep01.mkv")
                self.assertIsNotNone(resolved_ep01)
                self.assertEqual(resolved_ep01.name, "ep01.mkv")

            # DB upsert_studio_queue_items가 자막 파일을 차단하고 영상만 등록하는지 검증
            temp_db_path = tmp_path / "qa_test_folder_sync.sqlite3"
            try:
                test_engine = create_engine(
                    f"sqlite:///{temp_db_path.as_posix()}",
                    connect_args={"check_same_thread": False, "timeout": 30.0},
                )
                db_module._configure_sqlite_pragma(test_engine)
                db_module._engine = test_engine
                db_module._is_sqlite = True
                db_module._connected_db_name = str(temp_db_path)
                init_db()

                mixed_items = [
                    {"id": "q1", "filename": "ep01.mkv", "size": 8, "status": "WAITING"},
                    {"id": "q2", "filename": "ep01.smi", "size": 13, "status": "WAITING"},
                    {"id": "q3", "filename": "Series/Season1/ep02.avi", "size": 8, "status": "WAITING"},
                    {"id": "q4", "filename": "Series/Season1/ep02.srt", "size": 30, "status": "WAITING"},
                ]
                db_module.upsert_studio_queue_items(mixed_items, client_id="test_sync")
                saved_q = db_module.get_studio_queue()
                saved_names = [it["filename"] for it in saved_q]
                self.assertEqual(saved_names, ["ep01.mkv", "Series/Season1/ep02.avi"])

                test_engine.dispose()
            finally:
                db_module._engine = orig_engine
                db_module._is_sqlite = orig_is_sqlite
                db_module._connected_db_name = orig_db_name

        self.__class__.REPORT_ROWS.append({
            "case": "8. 폴더 동기화 자막(.smi/.srt) 무시 · 영상 전용 등록",
            "status": "PASS",
            "input": "ep01.mkv, ep01.smi, ep01.srt, Season1/ep02.avi, ep02.SMI, ep02.ass, poster.jpg",
            "output": f"수집={collected_names}, 제외자막={ignored_sub_count}건, 큐저장={saved_names}",
            "detail": "재귀 스캔·서버 영상 인덱스·DB 큐 저장 전 계층에서 .smi/.srt/.ass 제외 및 영상 전용 등록 통과",
        })

    def test_9_completed_tasks_video_folder_metadata(self):
        """
        [Case 9] 작업완료 보관함 영상 폴더별 조회용 video_folder 메타데이터 검증:
        get_completed_tasks()가 transm_tasks.video_path, 상대 경로 filename, 디스크 srt_path를
        기준으로 정확한 video_folder 값을 반환하는지 검증.
        """
        orig_engine = db_module._engine
        orig_is_sqlite = db_module._is_sqlite
        orig_db_name = db_module._connected_db_name

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            temp_db_path = tmp_path / "qa_test_folders.sqlite3"
            try:
                test_engine = create_engine(
                    f"sqlite:///{temp_db_path.as_posix()}",
                    connect_args={"check_same_thread": False, "timeout": 30.0},
                )
                db_module._configure_sqlite_pragma(test_engine)
                db_module._engine = test_engine
                db_module._is_sqlite = True
                db_module._connected_db_name = str(temp_db_path)
                init_db()

                # 1. 로컬 디스크 영상 경로가 있는 스튜디오 완료건
                db_module.upsert_task(
                    task_id="t_disk",
                    filename="City Hunter/Angel Heart/ep22.avi",
                    status="COMPLETED",
                    stage="완료",
                    progress=100,
                    video_path=r"D:\애니메이션\City Hunter\Angel Heart\ep22.avi",
                    srt_path=r"D:\dev\sourceCode\transM\backend\data\processed\t_disk.srt",
                )
                db_module.add_completed_task(
                    "t_disk", "City Hunter/Angel Heart/ep22.avi", 10,
                    r"D:\dev\sourceCode\transM\backend\data\processed\t_disk.srt",
                    "/api/download/t_disk", "studio"
                )

                # 2. 브라우저 업로드 경로지만 filename에 하위 폴더가 있는 경우
                db_module.upsert_task(
                    task_id="t_rel",
                    filename="City Hunter/Movie.mkv",
                    status="COMPLETED",
                    stage="완료",
                    progress=100,
                    video_path=r"D:\dev\sourceCode\transM\backend\data\uploads\t_rel_Movie.mkv",
                    srt_path=r"D:\dev\sourceCode\transM\backend\data\processed\t_rel.srt",
                )
                db_module.add_completed_task(
                    "t_rel", "City Hunter/Movie.mkv", 20,
                    r"D:\dev\sourceCode\transM\backend\data\processed\t_rel.srt",
                    "/api/download/t_rel", "studio"
                )

                # 3. 디스크 자막 경로가 있는 경우
                db_module.add_completed_task(
                    "t_srt_disk", "Harry.Potter.mp4", 50,
                    r"D:\영화\해리포터\Harry.Potter.srt",
                    "/api/download/t_srt_disk", "studio"
                )

                # 4. 단일 업로드 파일 (폴더 정보 없음)
                db_module.upsert_task(
                    task_id="t_direct",
                    filename="single.mp4",
                    status="COMPLETED",
                    stage="완료",
                    progress=100,
                    video_path=r"D:\dev\sourceCode\transM\backend\data\uploads\t_direct_single.mp4",
                    srt_path=r"D:\dev\sourceCode\transM\backend\data\processed\t_direct.srt",
                )
                db_module.add_completed_task(
                    "t_direct", "single.mp4", 5,
                    r"D:\dev\sourceCode\transM\backend\data\processed\t_direct.srt",
                    "/api/download/t_direct", "studio"
                )

                rows = db_module.get_completed_tasks(limit=100)
                folder_by_id = {r["task_id"]: r["video_folder"] for r in rows}

                self.assertEqual(folder_by_id["t_disk"], r"D:\애니메이션\City Hunter\Angel Heart")
                self.assertEqual(folder_by_id["t_rel"], "City Hunter")
                self.assertEqual(folder_by_id["t_srt_disk"], r"D:\영화\해리포터")
                self.assertEqual(folder_by_id["t_direct"], "직접 업로드 (uploads)")

                test_engine.dispose()
            finally:
                db_module._engine = orig_engine
                db_module._is_sqlite = orig_is_sqlite
                db_module._connected_db_name = orig_db_name

        self.__class__.REPORT_ROWS.append({
            "case": "9. 작업완료건 영상 폴더별 조회(video_folder) 검증",
            "status": "PASS",
            "input": "디스크경로(D:\\애니메이션\\City Hunter\\Angel Heart), 상대경로(City Hunter/Movie.mkv), 디스크SRT(D:\\영화\\해리포터), 직접업로드(single.mp4)",
            "output": f"t_disk='{folder_by_id['t_disk']}', t_rel='{folder_by_id['t_rel']}', t_srt='{folder_by_id['t_srt_disk']}', t_direct='{folder_by_id['t_direct']}'",
            "detail": "completed_tasks + transm_tasks JOIN 기반 video_folder 자동 분류 및 Selectbox 그룹핑 데이터 검증 통과",
        })

    def test_10_deduplicate_completed_tasks_keeps_latest_only(self):
        """
        [Case 10] 작업완료건 중복 영상 과거 기록 삭제(최신건 유지) 검증:
        동일 영상에 대해 과거 완료건과 최신 완료건이 공존할 때 deduplicate_completed_tasks()와
        add_completed_task()가 과거 항목만 삭제하고 최신 1건만 남기며, sync_disk가 재삽입하지 않는지 검증.
        """
        from sqlalchemy import text

        orig_engine = db_module._engine
        orig_is_sqlite = db_module._is_sqlite
        orig_db_name = db_module._connected_db_name

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            temp_db_path = tmp_path / "qa_test_dedup.sqlite3"
            try:
                test_engine = create_engine(
                    f"sqlite:///{temp_db_path.as_posix()}",
                    connect_args={"check_same_thread": False, "timeout": 30.0},
                )
                db_module._configure_sqlite_pragma(test_engine)
                db_module._engine = test_engine
                db_module._is_sqlite = True
                db_module._connected_db_name = str(temp_db_path)
                init_db()

                with test_engine.begin() as conn:
                    conn.execute(text("""
                        INSERT INTO completed_tasks (task_id, filename, subtitle_count, srt_path, srt_download_url, task_type, completed_at)
                        VALUES
                          ('old_dup_1', 'XVSR-234.mp4', 100, 'D:\\disk\\XVSR-234.srt', '/api/download/old_dup_1', 'studio', '2026-11-13 10:00:00'),
                          ('new_keep_1', 'XVSR-234.mp4', 120, 'D:\\processed\\new_keep_1.srt', '/api/download/new_keep_1', 'studio', '2026-11-15 11:00:00'),
                          ('other_keep', 'MovieA.mp4', 80, 'D:\\processed\\other_keep.srt', '/api/download/other_keep', 'studio', '2026-11-14 09:00:00');
                    """))
                    conn.execute(text("""
                        INSERT INTO transm_tasks (task_id, filename, status, stage, progress, video_path)
                        VALUES
                          ('old_dup_1', 'XVSR-234.mp4', 'COMPLETED', '완료', 100, 'D:\\disk\\XVSR-234.mp4'),
                          ('new_keep_1', 'XVSR-234.mp4', 'COMPLETED', '완료', 100, 'D:\\disk\\XVSR-234.mp4'),
                          ('other_keep', 'MovieA.mp4', 'COMPLETED', '완료', 100, 'D:\\disk\\MovieA.mp4');
                    """))

                res = db_module.deduplicate_completed_tasks()
                self.assertEqual(res["removed_count"], 1)
                self.assertEqual(res["removed_task_ids"], ["old_dup_1"])
                self.assertEqual(res["remaining_count"], 2)

                remaining_ids = [r["task_id"] for r in db_module.get_completed_tasks(limit=100)]
                self.assertEqual(set(remaining_ids), {"new_keep_1", "other_keep"})

                # add_completed_task 호출 시 기존 MovieA.mp4 과거건 자동 대체 검증
                db_module.upsert_task("newer_movie_a", "MovieA.mp4", "COMPLETED", "완료", 100, video_path=r"D:\disk\MovieA.mp4")
                db_module.add_completed_task("newer_movie_a", "MovieA.mp4", 95, r"D:\processed\newer_movie_a.srt", "/api/download/newer_movie_a", "studio")
                final_ids = [r["task_id"] for r in db_module.get_completed_tasks(limit=100)]
                self.assertEqual(set(final_ids), {"new_keep_1", "newer_movie_a"})

                test_engine.dispose()
            finally:
                db_module._engine = orig_engine
                db_module._is_sqlite = orig_is_sqlite
                db_module._connected_db_name = orig_db_name

        self.__class__.REPORT_ROWS.append({
            "case": "10. 작업완료건 중복 영상 과거 기록 삭제 검증",
            "status": "PASS",
            "input": "XVSR-234.mp4(2026-11-13 vs 2026-11-15), MovieA.mp4(기존건 + 신규 재작업)",
            "output": f"일괄정리 삭제={res['removed_task_ids']} / 최종유지={sorted(final_ids)}",
            "detail": "중복 영상 과거건 일괄 삭제 및 신규 완료 시 기존 과거건 자동 대체 통과",
        })

    def test_11_active_llm_config_model_matches_provider(self):
        """
        [Case 11] 활성 LLM 설정의 'model' 키 정합성 검증:
        get_active_llm_config()가 현재 선택된 provider에 맞는 모델명을 'model' 키로 반환하여
        진행 단계 UI('현재 처리 단계')와 설정 모델명이 항상 일치하는지 검증.
        """
        from unittest.mock import patch
        import app.config as cfg_module

        cases = [
            ("ollama", {"llm_provider": "ollama", "ollama_model": "qwen2.5:14b"}, "qwen2.5:14b"),
            ("openai", {"llm_provider": "openai", "openai_model": "gpt-4o-mini"}, "gpt-4o-mini"),
            ("anthropic", {"llm_provider": "anthropic", "anthropic_model": "claude-3-5-haiku-latest"}, "claude-3-5-haiku-latest"),
            ("gemini", {"llm_provider": "gemini", "gemini_model": "gemini-2.5-pro"}, "gemini-2.5-pro"),
        ]
        results = {}
        for prov, fake_settings, expected_model in cases:
            with patch.object(cfg_module, "get_runtime_settings", return_value=fake_settings):
                active = cfg_module.get_active_llm_config()
                self.assertEqual(active["provider"], prov)
                self.assertEqual(active["model"], expected_model)
                results[prov] = active["model"]

        self.__class__.REPORT_ROWS.append({
            "case": "11. 활성 LLM 모델명('model' 키) 표시 일치 검증",
            "status": "PASS",
            "input": "ollama=qwen2.5:14b, openai=gpt-4o-mini, anthropic=claude-3-5-haiku-latest, gemini=gemini-2.5-pro",
            "output": ", ".join(f"{k}={v}" for k, v in results.items()),
            "detail": "get_active_llm_config()['model']이 선택된 provider별 설정 모델명을 정확히 반환함",
        })


def run_and_print_report() -> int:
    suite = unittest.TestLoader().loadTestsFromTestCase(QAPipelineTestSuite)
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)

    print("\n" + "=" * 110)
    print(" [TransM QA 파이프라인 자동화 단위 테스트 리포트]")
    print("=" * 110)
    for row in QAPipelineTestSuite.REPORT_ROWS:
        print(f"- [{row['status']}] {row['case']}")
        print(f"  * 입력: {row['input']}")
        print(f"  * 출력: {row['output']}")
        print(f"  * 검증: {row['detail']}")
    print("=" * 110)
    print(f"총 실행: {result.testsRun}건 | 성공: {result.testsRun - len(result.failures) - len(result.errors)}건 | 실패: {len(result.failures) + len(result.errors)}건")
    print("=" * 110)

    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(run_and_print_report())
