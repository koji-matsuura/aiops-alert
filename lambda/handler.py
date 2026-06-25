"""
lambda/handler.py - AIOps Lambda thin proxy

役割: EventBridge アラームイベントを受け取り AgentCore Runtime に転送する。
     AI 推論・KB 検索・AWS API 呼び出しは AgentCore Runtime 側が担当する。

ソース: lib/lambda_handler.py 行48-230 から移行
"""

import json
import os
import logging
from datetime import datetime

import boto3

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# 環境変数
AGENTCORE_RUNTIME_ARN = os.environ.get('AGENTCORE_RUNTIME_ARN', '')
SNS_REPORT_ARN = os.environ.get('SNS_REPORT_ARN', '')

# boto3 クライアント
# boto3 >= 1.39.8 必須（runtime-troubleshooting.md 確認済み）
bedrock_agentcore = boto3.client('bedrock-agentcore')
sns_client = boto3.client('sns')


def handler(event, context):
    """
    Lambda エントリポイント（thin proxy）

    EventBridge → Lambda → AgentCore Runtime の橋渡しのみ担当。
    AI 推論・KB 検索・AWS API 呼び出しは AgentCore Runtime 側が行う。
    """
    try:
        logger.info(f"Received event: {json.dumps(event)}")

        event_info = extract_event_info(event)
        prompt = build_prompt(event_info)

        result = invoke_agent_runtime(prompt, event_info, context.aws_request_id)

        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'AIOps investigation invoked',
                'session_id': context.aws_request_id,
                'source': event_info['source'],
            })
        }

    except Exception as e:
        logger.error(f"Lambda handler error: {e}", exc_info=True)
        _notify_error(str(e), event)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


def extract_event_info(event: dict) -> dict:
    """
    AWS 公式 EventBridge イベント構造からフィールドを抽出する。

    参照: https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-event-patterns.html
    ソース: lib/lambda_handler.py 行106-138
    """
    return {
        'source': event.get('source', 'unknown'),
        'detail_type': event.get('detail-type', 'unknown'),
        'time': event.get('time', datetime.utcnow().isoformat()),
        'account': event.get('account', 'unknown'),
        'region': event.get('region', 'ap-northeast-1'),
        'resources': event.get('resources', []),
        'detail': event.get('detail', {}),
    }


def build_prompt(event_info: dict) -> str:
    """
    AgentCore Runtime 向けプロンプトを構築する。

    ソース: lib/lambda_handler.py 行142-175
    """
    return f"""
【イベント受信】
イベントソース: {event_info['source']}
イベント種別: {event_info['detail_type']}
タイムスタンプ: {event_info['time']}
イベント詳細:
{json.dumps(event_info['detail'], indent=2, ensure_ascii=False)}

Knowledge Base から関連ランブックを検索し、状況を分析して必要な調査・対応アクションを実行してください。
実行結果を SNS に通知してください。
""".strip()


def invoke_agent_runtime(prompt: str, event_info: dict, session_id: str) -> dict:
    """
    AgentCore Runtime を呼び出す。

    ストリーミングレスポンスに対応。
    参照: https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-invoke-agent.html
    """
    if not AGENTCORE_RUNTIME_ARN:
        logger.warning("AGENTCORE_RUNTIME_ARN not configured, skipping invocation")
        return {'message': 'AgentCore Runtime not configured'}

    payload = json.dumps({
        'prompt': prompt,
        'event_info': event_info,
    }).encode('utf-8')

    logger.info(f"Invoking AgentCore Runtime: {AGENTCORE_RUNTIME_ARN}, session: {session_id}")

    response = bedrock_agentcore.invoke_agent_runtime(
        agentRuntimeArn=AGENTCORE_RUNTIME_ARN,
        runtimeSessionId=session_id,
        payload=payload,
    )

    # ストリーミングレスポンス処理
    # 参照: runtime-invoke-agent.md「returns a streaming response」
    content_type = response.get('contentType', '')
    content_parts = []

    if 'text/event-stream' in content_type:
        for line in response['response'].iter_lines(chunk_size=10):
            if line:
                decoded = line.decode('utf-8')
                if decoded.startswith('data: '):
                    content_parts.append(decoded[6:])
    elif 'application/json' in content_type:
        for chunk in response.get('response', []):
            if isinstance(chunk, bytes):
                content_parts.append(chunk.decode('utf-8'))
    else:
        logger.info(f"Response contentType: {content_type}")

    result_text = '\n'.join(content_parts)
    logger.info(f"AgentCore Runtime response length: {len(result_text)} chars")

    return {
        'content': result_text,
        'session_id': session_id,
    }


def _notify_error(error_msg: str, event: dict) -> None:
    """Lambda 処理エラーを SNS に通知する（ベストエフォート）。"""
    if not SNS_REPORT_ARN:
        return
    try:
        sns_client.publish(
            TopicArn=SNS_REPORT_ARN,
            Subject='AIOps Lambda Error',
            Message=json.dumps({
                'error': error_msg,
                'event_source': event.get('source', 'unknown'),
                'detail_type': event.get('detail-type', 'unknown'),
            }, ensure_ascii=False),
        )
    except Exception as e:
        logger.error(f"Failed to notify error: {e}")
