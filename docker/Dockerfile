# Physics-informed Pass1/Pass2 agent (AIA / EPB / ULF) — build from Agent-Pipeline root:
#   docker build --platform linux/amd64 -f docker/Dockerfile -t space-science-agent:latest .
# 赛题评测环境为 x86_64；必须产出 linux/amd64，不可用本机默认 arm64。
FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    LANG=C.UTF-8 \
    LC_ALL=C.UTF-8 \
    MODEL_DISABLE_THINKING=1 \
    AGENT_PIPELINE_ROOT=/app/Agent-Pipeline \
    PIPELINE_PROFILE=roadshow_rules

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app/Agent-Pipeline

COPY package/agent_modules/requirements.txt /tmp/requirements.txt
RUN pip install --no-cache-dir -r /tmp/requirements.txt

COPY package/agent_modules/ /app/Agent-Pipeline/package/agent_modules/
COPY package/scripts/ /app/Agent-Pipeline/package/scripts/
COPY package/roadshow_paths.py /app/Agent-Pipeline/package/roadshow_paths.py
COPY agent/ /app/Agent-Pipeline/agent/
COPY smoke/ /app/Agent-Pipeline/smoke/
COPY docs/ /app/Agent-Pipeline/docs/

ENV PYTHONPATH=/app/Agent-Pipeline/package/agent_modules:/app/Agent-Pipeline/package/scripts
ENV ROADSHOW_RESULTS=/app/Agent-Pipeline/results

# Mount ROADSHOW_DATA + secrets.yaml at run time:
#   docker run -v .../路演数据:/data -e ROADSHOW_DATA=/data \
#     -v .../secrets.yaml:/app/secrets.yaml space-science-agent \
#     python smoke/smoke_test.py

ENTRYPOINT ["python"]
CMD ["smoke/smoke_test.py"]
