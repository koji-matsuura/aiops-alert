import json
import logging
import os
import boto3
# PingStatus をインポート
from bedrock_agentcore import BedrockAgentCoreApp, PingStatus

os.environ['DOCKER_CONTAINER'] = 'true'
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# BedrockAgentCoreApp の初期化
app = BedrockAgentCoreApp(debug=True)

# --- 【修正】明示的な /ping エンドポイントの定義 ---
@app.ping
def handle_ping() -> PingStatus:
    return PingStatus.HEALTHY

# --- 【修正】boto3 クライアントはグローバルに置かず、呼び出し時（遅延初期化）にする ---
_clients = {}
def get_client(service_name):
    if service_name not in _clients:
        region = os.environ.get('AWS_REGION') or 'ap-northeast-1'
        _clients[service_name] = boto3.client(service_name, region_name=region)
    return _clients[service_name]

@app.entrypoint
def invoke(payload: dict) -> dict:
    # 実際の処理の中で get_client('bedrock-agent-runtime') のように呼び出す
    # ... (省略)
    return {"status": "success"}

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=8080)