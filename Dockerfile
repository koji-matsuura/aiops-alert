# AgentCore Runtime コンテナ
# ARM64 必須（runtime-troubleshooting.md 確認済み）
# ビルド時: docker build --platform linux/arm64 -t aiops-agentcore .
# ポート 8080: HTTP プロトコル（get_runtime_guide() Protocol Contracts より）
# /ping エンドポイント: BedrockAgentCoreApp が自動実装

FROM public.ecr.aws/docker/library/python:3.12-slim

WORKDIR /app

# Layer 1: pip 更新
RUN pip install --upgrade pip setuptools wheel

# Layer 2: 依存パッケージ
# boto3 >= 1.39.8 必須（runtime-troubleshooting.md 確認済み）
COPY requirements-agentcore.txt .
RUN pip install --no-cache-dir -r requirements-agentcore.txt

# Layer 3: AgentCore Runtime コード（agentcore/ のみ）
# lambda/ はここに含めない（Lambda thin proxy と AgentCore の分離を維持）
COPY agentcore/ ./agentcore/

# Layer 4: エントリポイント
COPY agentcore/app.py ./app.py

EXPOSE 8080

ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# BedrockAgentCoreApp が /ping と /invocations を自動実装する
ENTRYPOINT ["python", "app.py"]
