import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

import local_service as service


ENDPOINT = "https://ocr.example/parse-file"
TEXT = "病人ID：PID-01\n姓名：张三 性别：女 年龄：23岁\n超声所见：子宫前位。\n内膜厚0.8cm。\n超声诊断：未见明显异常\n时间：2026年07月13日"


def response(status=200, payload=None, html=False):
    result = requests.Response()
    result.status_code = status
    result.url = ENDPOINT
    result.headers["Content-Type"] = "text/html" if html else "application/json"
    result.encoding = "utf-8"
    result._content = ("<!DOCTYPE html><html><title>Not Found</title></html>" if html else json.dumps(payload, ensure_ascii=False)).encode()
    return result


def success():
    return response(payload={"success": True, "markdown": TEXT, "json_text": "{}"})


class ImagingTransportTests(unittest.TestCase):
    def run_batch(self, responses):
        with tempfile.TemporaryDirectory() as root:
            job_dir = Path(root)
            files = []
            for number in range(len(responses)):
                source = job_dir / f"scan-{number}.pdf"
                source.write_bytes(b"synthetic-pdf")
                files.append((source, source.name))
            job_id = "transport-regression"
            state = {"job_id": job_id, "job_dir": job_dir, "output_relative": Path("output/result.xlsx"), "processing_mode": "fast", "total_files": len(files), "completed_files": 0, "records": [], "kind": "imaging"}
            with patch.dict(service.JOBS, {job_id: state}), patch.object(service, "request_cloud_ocr", side_effect=responses) as request:
                service.process_imaging_job(job_id, ENDPOINT, files, "fast")
                return state, request.call_count

    def test_middle_html_404_does_not_discard_success_or_skip_next_file(self):
        state, count = self.run_batch([success(), response(404, html=True), success()])
        self.assertEqual(count, 3)
        self.assertEqual(state["status"], "completed")
        self.assertEqual(state["completed_files"], 3)
        self.assertEqual([record["filename"] for record in state["records"]], ["scan-0.pdf", "scan-2.pdf"])
        self.assertEqual(state["failed_files"], 1)
        error = state["file_errors"][0]
        self.assertEqual(error["filename"], "scan-1.pdf")
        self.assertIn("HTTP 404", error["message"])
        self.assertIn(ENDPOINT, error["message"])
        self.assertIn("映射", error["message"])
        self.assertNotIn("<!DOCTYPE", error["message"])

    def test_all_failed_is_not_reported_as_success(self):
        state, count = self.run_batch([response(404, html=True), response(404, html=True)])
        self.assertEqual(count, 2)
        self.assertEqual(state["status"], "failed")
        self.assertEqual(state["completed_files"], 2)
        self.assertEqual(state["records"], [])
        self.assertEqual(state["failed_files"], 2)
        self.assertEqual(len(state["file_errors"]), 2)
        self.assertNotIn("output_url", state)
        self.assertIn("HTTP 404", state["message"])

    def test_json_array_is_a_readable_file_error_and_batch_continues(self):
        state, count = self.run_batch([response(payload=[]), success()])
        self.assertEqual(count, 2)
        self.assertEqual(state["failed_files"], 1)
        self.assertIn("JSON 对象", state["file_errors"][0]["message"])
        self.assertNotIn("has no attribute", state["file_errors"][0]["message"])
        self.assertEqual(state["records"][0]["filename"], "scan-1.pdf")

    def test_transport_exception_keeps_the_successful_records(self):
        state, count = self.run_batch([success(), RuntimeError("connection reset"), success()])
        self.assertEqual(count, 3)
        self.assertEqual(len(state["records"]), 2)
        self.assertEqual(state["failed_files"], 1)
        self.assertIn("connection reset", state["file_errors"][0]["message"])

    def test_escaped_newlines_in_markdown_and_json_blocks(self):
        expected, _ = service.parse_imaging_fields(TEXT, "{}", "scan.pdf")
        for marker in (r"\n", r"\r\n", r"\\n", "/n", "/n/n"):
            with self.subTest(marker=marker):
                raw = TEXT.replace("\n", marker)
                for markdown, payload in ((raw, "{}"), ("", json.dumps({"parsing_res_list": [{"block_id": 0, "block_content": raw}]}, ensure_ascii=False))):
                    actual, needs_review = service.parse_imaging_fields(markdown, payload, "scan.pdf")
                    self.assertEqual(actual["姓名"], "张三")
                    self.assertEqual(actual["检查时间"], "2026-07-13")
                    self.assertEqual(actual["超声所见"].splitlines(), expected["超声所见"].splitlines())
                    self.assertEqual(actual["超声诊断"], "未见明显异常")
                    self.assertEqual(needs_review, [])

    def test_html_table_and_body_crop_markers_become_real_newlines(self):
        payload = {"parsing_res_list": [{"block_id": 0, "block_content": "<table><tr><td>超声所见：子宫前位。\\n内膜厚0.8cm。</td></tr><tr><td>超声诊断：正常/n请结合临床</td></tr></table>"}]}
        fields, _ = service.parse_imaging_fields("", json.dumps(payload), "scan.pdf")
        self.assertEqual(fields["超声所见"], "子宫前位。\n内膜厚0.8cm。")
        self.assertEqual(fields["超声诊断"], "正常\n请结合临床")
        self.assertEqual(service.imaging_section(r"超声所见：\n子宫前位。\n超声诊断：正常", ("超声所见",), ("超声诊断",)), "子宫前位。")

    def test_real_newlines_and_medical_slashes_are_preserved(self):
        fields, _ = service.parse_imaging_fields(TEXT.replace("子宫前位。", "剂量5mg/ml，路径/normal，中文正常。"), "{}", "scan.pdf")
        self.assertEqual(fields["超声所见"], "剂量5mg/ml，路径/normal，中文正常。\n内膜厚0.8cm。")

    def test_raw_ocr_text_stays_unchanged_in_saved_evidence(self):
        with tempfile.TemporaryDirectory() as root:
            job_dir = Path(root)
            source = job_dir / "scan.pdf"
            source.write_bytes(b"fixture")
            raw = TEXT.replace("\n", r"\n")
            raw_response = response(payload={"success": True, "markdown": raw, "json_text": "{}"})
            state = {"job_dir": job_dir, "output_relative": Path("output/result.xlsx"), "completed_files": 0, "processing_mode": "fast"}
            with patch.dict(service.JOBS, {"raw-evidence": state}), patch.object(service, "request_cloud_ocr", return_value=raw_response):
                service.process_imaging_job("raw-evidence", ENDPOINT, [(source, "scan.pdf")], "fast")
            self.assertEqual(next((job_dir / "imaging_ocr").glob("*.md")).read_text(encoding="utf-8"), raw)
            self.assertEqual(state["records"][0]["fields"]["超声所见"], "子宫前位。\n内膜厚0.8cm。")


if __name__ == "__main__":
    unittest.main()
