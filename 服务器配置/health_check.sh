#!/usr/bin/env bash
set -euo pipefail

curl -fsS --max-time 5 http://127.0.0.1:8118/v1/models
printf '\n'
curl -fsS --max-time 5 http://127.0.0.1:6006/
printf '\n'
ps -eo pid,lstart,etime,args | grep -E '[u]vicorn app:app.*--port 6006|[p]addlex_genai_server.*--port 8118'
