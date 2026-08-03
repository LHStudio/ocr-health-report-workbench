from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

import requests


def main() -> None:
    parser = argparse.ArgumentParser(description="Submit and monitor a complete medical OCR batch through local port 8000.")
    parser.add_argument("--reports-root", type=Path, required=True)
    parser.add_argument("--template", type=Path, required=True)
    parser.add_argument("--cloud-url", required=True)
    parser.add_argument("--local-url", default="http://127.0.0.1:8000")
    parser.add_argument("--parse-mode", choices=("markdown", "excel"), default="markdown")
    parser.add_argument("--processing-mode", choices=("fast", "accurate"), default="fast")
    parser.add_argument("--timeout", type=int, default=3600)
    args = parser.parse_args()

    reports_root = args.reports_root.resolve()
    template = args.template.resolve()
    pdf_paths = sorted(reports_root.rglob("*.pdf"), key=lambda path: path.as_posix())
    if not pdf_paths:
        raise RuntimeError(f"No PDFs found under {reports_root}")
    if not template.is_file():
        raise FileNotFoundError(template)

    handles = [path.open("rb") for path in pdf_paths]
    template_handle = template.open("rb")
    started = time.perf_counter()
    started_at = datetime.now().isoformat(timespec="seconds")
    try:
        files = [("files", (path.name, handle, "application/pdf")) for path, handle in zip(pdf_paths, handles)]
        files.append(("template", (template.name, template_handle, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")))
        data: list[tuple[str, str]] = [
            ("ocr_url", args.cloud_url),
            ("parse_mode", args.parse_mode),
            ("processing_mode", args.processing_mode),
        ]
        data.extend(
            ("relative_paths", (Path(reports_root.name) / path.relative_to(reports_root)).as_posix())
            for path in pdf_paths
        )
        response = requests.post(f"{args.local_url.rstrip('/')}/process", files=files, data=data, timeout=180)
    finally:
        template_handle.close()
        for handle in handles:
            handle.close()

    payload = response.json()
    if not response.ok or not payload.get("success"):
        raise RuntimeError(payload.get("detail") or f"Batch submission failed: HTTP {response.status_code}")
    job_id = payload["job_id"]
    print(json.dumps({"job_id": job_id, "files": len(pdf_paths), "people": payload.get("people_count")}, ensure_ascii=False))

    deadline = time.monotonic() + args.timeout
    last_completed = -1
    final_state: dict = {}
    while time.monotonic() < deadline:
        state_response = requests.get(f"{args.local_url.rstrip('/')}/jobs/{job_id}", timeout=30)
        state = state_response.json()
        if not state_response.ok:
            raise RuntimeError(state.get("detail") or f"Status request failed: HTTP {state_response.status_code}")
        completed = int(state.get("completed_files") or 0)
        if completed != last_completed:
            print(
                json.dumps(
                    {
                        "completed": completed,
                        "total": state.get("total_files"),
                        "person": state.get("current_person"),
                        "file": state.get("current_file"),
                        "elapsed_seconds": round(time.perf_counter() - started, 2),
                    },
                    ensure_ascii=False,
                )
            )
            last_completed = completed
        if state.get("status") in {"completed", "failed"}:
            final_state = state
            break
        time.sleep(1)
    else:
        raise TimeoutError(f"Batch {job_id} did not finish within {args.timeout} seconds")

    record = {
        "job_id": job_id,
        "started_at": started_at,
        "finished_at": datetime.now().isoformat(timespec="seconds"),
        "elapsed_seconds": round(time.perf_counter() - started, 2),
        "reports_root": str(reports_root),
        "template": str(template),
        "cloud_url": args.cloud_url,
        "parse_mode": args.parse_mode,
        "processing_mode": args.processing_mode,
        "files": len(pdf_paths),
        "people": payload.get("people_count"),
        "status": final_state.get("status"),
        "message": final_state.get("message"),
        "output_url": final_state.get("output_url"),
    }
    project_root = Path(__file__).resolve().parents[1]
    record_path = project_root / "data" / "jobs" / job_id / "batch_run.json"
    record_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(record, ensure_ascii=False, indent=2))
    if final_state.get("status") != "completed":
        raise RuntimeError(final_state.get("message") or f"Batch {job_id} failed")


if __name__ == "__main__":
    main()
