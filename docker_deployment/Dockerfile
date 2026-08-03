# API 容器；PaddleOCR-VL 模型服务由目标机现有 Docker/宿主机在 8118 提供。
FROM python:3.12-slim

ARG PADDLE_PACKAGE="paddlepaddle-gpu==3.2.0"
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN pip install --no-cache-dir "${PADDLE_PACKAGE}" \
    && pip install --no-cache-dir -r requirements.txt

COPY app.py ./app.py
COPY questionnaire_templates ./questionnaire_templates
RUN mkdir -p /app/pdf_to_excel_service/uploads /app/pdf_to_excel_service/outputs

EXPOSE 6006
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "6006"]
