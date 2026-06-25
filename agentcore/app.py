"""
agentcore/app.py - AgentCore Runtime エントリポイント

役割: BedrockAgentCoreApp として動作し、Lambda から受け取ったイベントに対して
     Knowledge Base でランブックを検索し、Claude で状況を分析・FR 関数を選択し、
     AWS API を直接呼び出して SNS に通知する。

参照実装: cfn-infra-base/app.py のパターン
"""

import json
import logging
import os

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp

from agentcore.tools.fr_tools import (
    log_investigation_fr01,
    bottleneck_investigation_fr02,
    create_db_snapshot_fr03,
    maintenance_window_display_fr04,
    slow_query_detection_fr05,
    high_load_query_detection_fr06,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 環境変数
KNOWLEDGE_BASE_ID = os.environ.get('KNOWLEDGE_BASE_ID', '')
SNS_REPORT_ARN = os.environ.get('SNS_REPORT_ARN', '')
BEDROCK_KB_MODEL_ARN = os.environ.get(
    'BEDROCK_KB_MODEL_ARN',
    'arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0'
)

# リージョン設定
_REGION = os.environ.get('AWS_REGION') or os.environ.get('AWS_DEFAULT_REGION') or 'ap-northeast-1'

# boto3 クライアント（boto3 >= 1.39.8 必須）
# region_name を明示指定: コンテナ起動時に AWS_REGION がない場合でも NoRegionError を防ぐ
bedrock_agent_runtime = boto3.client('bedrock-agent-runtime', region_name=_REGION)
bedrock_runtime_client = boto3.client('bedrock-runtime', region_name=_REGION)
sns_client = boto3.client('sns', region_name=_REGION)

# BedrockAgentCoreApp インスタンス
# debug=True: ログを有効化（CloudWatch Logs への起動ログ出力のため）
app = BedrockAgentCoreApp(debug=True)

# FR 関数マッピング
FR_FUNCTIONS = {
    'LogInvestigation': log_investigation_fr01,
    'BottleneckAnalysis': bottleneck_investigation_fr02,
    'CreateSnapshot': create_db_snapshot_fr03,
    'MaintenanceDisplay': maintenance_window_display_fr04,
    'SlowQueryDetection': slow_query_detection_fr05,
    'HighLoadQueryAnalysis': high_load_query_detection_fr06,
}

# アラーム種別 → applicable_to メタデータマッピング
ALARM_TO_APPLICABLE = {
    'EC2-HighCPU': 'EC2',
    'RDS-HighCPU': 'RDS',
    'RDS-HighConnections': 'RDS',
    'RDS-ReplicationLag': 'RDS',
    'Lambda-ErrorRate': 'Lambda',
    'Lambda-Throttle': 'Lambda',
}


@app.entrypoint
def invoke(payload: dict) -> dict:
    """
    AgentCore Runtime エントリポイント。

    処理フロー:
    1. Lambda から受け取った payload を解析
    2. Knowledge Base でランブックを検索（メタデータフィルタ使用）
    3. Claude で状況分析・実行 FR 関数を判定
    4. FR 関数（AWS API）を実行
    5. SNS に結果通知

    参照: cfn-infra-base/app.py 行58-132 のパターン
    """
    try:
        prompt = payload.get('prompt', '')
        event_info = payload.get('event_info', {})
        detail = event_info.get('detail', {})
        alarm_name = detail.get('alarmName', '')

        logger.info(f"Processing alarm: {alarm_name}, detail_type: {event_info.get('detail_type', '')}")

        # 1. applicable_to フィルタを決定
        applicable_to = _get_applicable_to(alarm_name)

        # 2. Knowledge Base でランブックを検索
        kb_results = _retrieve_runbooks(prompt, applicable_to)

        # 3. Claude で状況分析・FR 関数を選択
        analysis = _analyze_with_claude(prompt, event_info, kb_results)

        # 4. FR 関数を実行
        fr_name = analysis.get('fr_function', 'LogInvestigation')
        fr_params = analysis.get('fr_params', {})
        fr_result = _execute_fr(fr_name, fr_params)

        # 5. SNS 通知
        _notify_result(alarm_name, analysis, fr_result)

        return {
            'status': 'success',
            'alarm': alarm_name,
            'fr_executed': fr_name,
            'result': fr_result,
        }

    except Exception as e:
        logger.error(f"AgentCore app error: {e}", exc_info=True)
        _notify_error(str(e), payload)
        return {'status': 'error', 'error': str(e)}


def _get_applicable_to(alarm_name: str) -> str:
    """アラーム名プレフィックスから Knowledge Base フィルタ値を決定する。"""
    for prefix, applicable in ALARM_TO_APPLICABLE.items():
        if alarm_name.startswith(prefix):
            return applicable
    return 'EC2'  # デフォルト


def _retrieve_runbooks(prompt: str, applicable_to: str) -> list:
    """
    Knowledge Base からランブックを検索する。

    metadata フィルタ: applicable_to（EC2/RDS/Lambda）
    参照: IMPLEMENTATION.md Knowledge Base メタデータフィルタリング
    """
    if not KNOWLEDGE_BASE_ID:
        logger.warning("KNOWLEDGE_BASE_ID not set, skipping KB retrieval")
        return []

    try:
        retrieval_config = {
            'vectorSearchConfiguration': {
                'numberOfResults': 3,
                'filter': {
                    'equals': {
                        'key': 'applicable_to',
                        'value': {'stringValue': applicable_to},
                    }
                },
            }
        }

        response = bedrock_agent_runtime.retrieve(
            knowledgeBaseId=KNOWLEDGE_BASE_ID,
            retrievalQuery={'text': prompt},
            retrievalConfiguration=retrieval_config,
        )

        results = response.get('retrievalResults', [])
        logger.info(f"KB retrieved {len(results)} runbooks for applicable_to={applicable_to}")
        return results

    except Exception as e:
        logger.warning(f"KB retrieval error: {e}")
        return []


def _analyze_with_claude(prompt: str, event_info: dict, kb_results: list) -> dict:
    """
    Claude Haiku で状況分析・実行する FR 関数を判定する。

    参照: cfn-infra-base/src/bedrock_runtime.py 行38-156 のパターン
    """
    # KB 検索結果をテキスト化
    kb_context = '\n'.join([
        r.get('content', {}).get('text', '')
        for r in kb_results
        if r.get('content', {}).get('text')
    ])

    detail = event_info.get('detail', {})
    alarm_name = detail.get('alarmName', 'unknown')

    system_prompt = """あなたは AWS インフラ自動運用（AIOps）アシスタントです。
CloudWatch アラームを受信し、Knowledge Base のランブックに基づいて適切な調査・対応アクションを判定します。

利用可能な FR 関数:
- LogInvestigation: CloudWatch Logs からエラーを調査（FR-01）
- BottleneckAnalysis: CPU/メモリ/接続数のボトルネックを調査（FR-02）
- CreateSnapshot: RDS スナップショットを作成（FR-03、緊急時のみ）
- MaintenanceDisplay: RDS メンテナンスウィンドウを確認（FR-04）
- SlowQueryDetection: RDS スロークエリを検出（FR-05）
- HighLoadQueryAnalysis: 高負荷クエリを分析（FR-06）

必ず JSON 形式で回答してください:
{
  "fr_function": "実行する FR 関数名",
  "fr_params": {"パラメータ名": "値"},
  "analysis": "状況分析テキスト",
  "priority": "HIGH/MEDIUM/LOW"
}"""

    user_prompt = f"""
アラーム名: {alarm_name}
イベント詳細: {json.dumps(detail, ensure_ascii=False, indent=2)}

【Knowledge Base ランブック】
{kb_context if kb_context else 'ランブックが見つかりませんでした'}

上記の情報を分析し、適切な FR 関数と必要なパラメータを JSON で返してください。
"""

    try:
        model_id = BEDROCK_KB_MODEL_ARN.split('foundation-model/')[-1] if 'foundation-model/' in BEDROCK_KB_MODEL_ARN else BEDROCK_KB_MODEL_ARN

        response = bedrock_runtime_client.invoke_model(
            modelId=model_id,
            body=json.dumps({
                'anthropic_version': 'bedrock-2023-05-31',
                'max_tokens': 1024,
                'system': system_prompt,
                'messages': [{'role': 'user', 'content': user_prompt}],
            }),
            contentType='application/json',
            accept='application/json',
        )

        response_body = json.loads(response['body'].read())
        response_text = response_body['content'][0]['text']

        # JSON 抽出
        import re
        json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
        if json_match:
            return json.loads(json_match.group())

        logger.warning(f"Claude response is not valid JSON: {response_text[:200]}")
        return {'fr_function': 'LogInvestigation', 'fr_params': {}, 'analysis': response_text, 'priority': 'MEDIUM'}

    except Exception as e:
        logger.error(f"Claude analysis error: {e}", exc_info=True)
        return {'fr_function': 'LogInvestigation', 'fr_params': {}, 'analysis': f'Analysis failed: {e}', 'priority': 'MEDIUM'}


def _execute_fr(fr_name: str, fr_params: dict) -> dict:
    """指定された FR 関数を実行する。"""
    fr_func = FR_FUNCTIONS.get(fr_name)
    if not fr_func:
        logger.warning(f"Unknown FR function: {fr_name}, falling back to LogInvestigation")
        fr_func = log_investigation_fr01

    logger.info(f"Executing {fr_name} with params: {fr_params}")
    return fr_func(**fr_params)


def _notify_result(alarm_name: str, analysis: dict, fr_result: dict) -> None:
    """調査結果を SNS に通知する。"""
    if not SNS_REPORT_ARN:
        logger.warning("SNS_REPORT_ARN not set, skipping notification")
        return

    try:
        message = {
            'alarm': alarm_name,
            'analysis': analysis.get('analysis', ''),
            'priority': analysis.get('priority', 'MEDIUM'),
            'fr_executed': analysis.get('fr_function', ''),
            'fr_result': fr_result,
        }
        sns_client.publish(
            TopicArn=SNS_REPORT_ARN,
            Subject=f'AIOps Report: {alarm_name}',
            Message=json.dumps(message, ensure_ascii=False, indent=2, default=str),
        )
        logger.info(f"SNS notification sent for alarm: {alarm_name}")
    except Exception as e:
        logger.error(f"SNS notification error: {e}")


def _notify_error(error_msg: str, payload: dict) -> None:
    """エラーを SNS に通知する（ベストエフォート）。"""
    if not SNS_REPORT_ARN:
        return
    try:
        sns_client.publish(
            TopicArn=SNS_REPORT_ARN,
            Subject='AIOps AgentCore Error',
            Message=json.dumps({'error': error_msg, 'payload_keys': list(payload.keys())}, ensure_ascii=False),
        )
    except Exception:
        pass


if __name__ == '__main__':
    # host='0.0.0.0' を明示指定する
    # デフォルトの自動検知では AgentCore Runtime microVM 環境を
    # Docker と判定できず 127.0.0.1 でリッスンして NotStabilized になる
    # ソース: bedrock_agentcore/runtime/app.py run() の host 判定ロジック
    #   if os.path.exists("/.dockerenv") or os.environ.get("DOCKER_CONTAINER"):
    #       host = "0.0.0.0"
    #   else:
    #       host = "127.0.0.1"  ← microVM はここに入る
    app.run(host='0.0.0.0', port=8080)
