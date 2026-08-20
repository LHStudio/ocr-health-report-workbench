"""Production entrypoint that serves the Vue build and local API on one port."""
import os
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from local_service import JOB_ROOT, app as local_api


ROOT = Path(__file__).resolve().parent
WEB_ROOT = Path(os.environ.get("OCR_WEB_ROOT", ROOT / "dist")).resolve()
INDEX_FILE = WEB_ROOT / "index.html"

app = FastAPI(title="OCR 健康报告工作台")
app.mount("/local-api", local_api)
app.mount("/local-files", StaticFiles(directory=JOB_ROOT), name="local-files")

if (WEB_ROOT / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=WEB_ROOT / "assets"), name="web-assets")


@app.get("/healthz")
def healthz() -> dict[str, str]:
    return {"status": "ok", "version": "2026-08-15-v4.2.0"}


@app.get("/{requested_path:path}", include_in_schema=False)
def frontend(requested_path: str):
    if not INDEX_FILE.is_file():
        raise HTTPException(status_code=503, detail="前端构建文件不存在，请先执行 npm run build")

    candidate = (WEB_ROOT / requested_path).resolve()
    if requested_path and candidate.is_relative_to(WEB_ROOT) and candidate.is_file():
        return FileResponse(candidate)
    return FileResponse(INDEX_FILE)
