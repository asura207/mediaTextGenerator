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
