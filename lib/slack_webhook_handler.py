"""
Slack Interactive Webhook Handler
Slack ボタンクリック (Approve/Cancel) を受け取って処理
- Slack 署名検証（リプレイ攻撃防止）
- pending_confirmation に保存
- Slack スレッドに確認状況を返信
"""

import json
import os
import boto3
import logging
import hmac
import hashlib
import time
from datetime import datetime, timedelta
from typing import Dict, Any, Tuple

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS クライアント
s3_client = boto3.client('s3')
secrets_manager_client = boto3.client('secretsmanager')

# 環境変数
S3_BUCKET = os.environ.get('S3_BUCKET', 'aiops-kb-default')
SLACK_CREDENTIALS_SECRET_ARN = os.environ.get('SLACK_CREDENTIALS_SECRET_ARN', '')
ENVIRONMENT = os.environ.get('ENVIRONMENT', 'dev')

# ⭐ キャッシュ（1回の実行内で複数回 Secrets Manager を呼ばないようにキャッシュ）
_slack_credentials_cache = None


def get_slack_credentials() -> Dict[str, str]:
    """
    Secrets Manager から Slack 認証情報を取得
    （実行時取得により、環境変数に秘密を保存しない）
    
    Returns:
        dict: {'signing_secret': '...', 'bot_token': '...'}
    
    根拠: AWS Secrets Manager Best Practices
    https://docs.aws.amazon.com/secretsmanager/latest/userguide/cloudformation.html
    """
    global _slack_credentials_cache
    
    # キャッシュがあれば使用
    if _slack_credentials_cache:
        logger.debug("Using cached Slack credentials")
        return _slack_credentials_cache
    
    try:
        if not SLACK_CREDENTIALS_SECRET_ARN:
            raise ValueError("SLACK_CREDENTIALS_SECRET_ARN environment variable not set")
        
        logger.info(f"Retrieving Slack credentials from Secrets Manager: {SLACK_CREDENTIALS_SECRET_ARN}")
        
        response = secrets_manager_client.get_secret_value(
            SecretId=SLACK_CREDENTIALS_SECRET_ARN
        )
        
        # SecretString がある場合（JSON 形式）
        if 'SecretString' in response:
            secret_dict = json.loads(response['SecretString'])
            _slack_credentials_cache = {
                'signing_secret': secret_dict.get('signing_secret', ''),
                'bot_token': secret_dict.get('bot_token', '')
            }
            logger.info("Slack credentials retrieved successfully from Secrets Manager")
            return _slack_credentials_cache
        else:
            raise ValueError("Secret is not in SecretString format")
    
    except Exception as e:
        logger.error(f"Failed to retrieve Slack credentials from Secrets Manager: {str(e)}")
        raise


def verify_slack_signature(request_body: str, timestamp: str, signature: str) -> bool:
    """
    Slack リクエスト署名を検証（リプレイ攻撃防止）
    
    Args:
        request_body: リクエストボディ（JSON文字列）
        timestamp: X-Slack-Request-Timestamp ヘッダー
        signature: X-Slack-Signature ヘッダー
    
    Returns:
        bool: 署名が有効な場合 True
    
    根拠: Slack Security Documentation
    https://api.slack.com/authentication/verifying-requests-from-slack
    """
    try:
        # ⭐ Secrets Manager から Slack credentials を取得
        credentials = get_slack_credentials()
        slack_signing_secret = credentials['signing_secret']
        
        # タイムスタンプが5分以上古い場合は拒否（リプレイ攻撃防止）
        current_time = int(time.time())
        request_time = int(timestamp)
        if abs(current_time - request_time) > 300:
            logger.warning(f"Request timestamp too old: {current_time} vs {request_time}")
            return False
        
        # 署名を構築: "v0=sha256_hash(v0:{timestamp}:{request_body})"
        sig_basestring = f"v0:{timestamp}:{request_body}"
        computed_signature = "v0=" + hmac.new(
            slack_signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()
        
        # 署名を比較（タイミング攻撃対策として hmac.compare_digest を使用）
        is_valid = hmac.compare_digest(computed_signature, signature)
        
        if is_valid:
            logger.info("Slack signature verified successfully")
        else:
            logger.warning(f"Slack signature mismatch. Expected: {computed_signature}, Got: {signature}")
        
        return is_valid
    
    except Exception as e:
        logger.error(f"Error verifying Slack signature: {str(e)}")
        return False


def parse_slack_interactive_event(event_body: Dict[str, Any]) -> Tuple[str, str, str, str, str]:
    """
    Slack Interactive イベント（ボタンクリック）をパース
    
    Args:
        event_body: Slack イベント JSON
    
    Returns:
        Tuple: (action_id, trigger_id, user_id, report_id, response_url)
    
    例:
        {
            "type": "block_actions",
            "actions": [
                {
                    "type": "button",
                    "action_id": "approve_action",
                    "block_id": "actions_block",
                    "text": {"type": "plain_text", "text": "✅ Approve"},
                    "value": "report-12345-1234567890"
                }
            ],
            "trigger_id": "...",
            "user": {"id": "U1234567890"},
            "response_url": "https://hooks.slack.com/..."
        }
    """
    try:
        actions = event_body.get('actions', [])
        if not actions:
            raise ValueError("No actions in event")
        
        action = actions[0]
        action_id = action.get('action_id', '')
        trigger_id = event_body.get('trigger_id', '')
        user_id = event_body.get('user', {}).get('id', 'unknown')
        report_id = action.get('value', '')
        response_url = event_body.get('response_url', '')
        
        logger.info(f"Parsed Slack action: {action_id} from user {user_id}, report {report_id}")
        
        return action_id, trigger_id, user_id, report_id, response_url
    
    except Exception as e:
        logger.error(f"Error parsing Slack interactive event: {str(e)}")
        raise


def save_approval_decision(
    report_id: str,
    action: str,  # "approve" or "cancel"
    user_id: str,
    timestamp: str = None
) -> str:
    """
    確認決定を S3 (pending-confirmations/) に保存
    
    Args:
        report_id: レポート ID
        action: アクション ("approve" or "cancel")
        user_id: Slack ユーザー ID
        timestamp: ISO8601 タイムスタンプ（デフォルト: 現在時刻）
    
    Returns:
        str: S3 キー
    """
    if timestamp is None:
        timestamp = datetime.utcnow().isoformat() + "Z"
    
    confirmation_record = {
        "report_id": report_id,
        "action": action,
        "user_id": user_id,
        "timestamp": timestamp,
        "status": "confirmed",
        "ttl": int((datetime.utcnow() + timedelta(hours=1)).timestamp())  # 1時間後に有効期限
    }
    
    # S3 キー: pending-confirmations/{report_id}-{timestamp}.json
    s3_key = f"pending-confirmations/{report_id}-{int(time.time())}.json"
    
    try:
        s3_client.put_object(
            Bucket=S3_BUCKET,
            Key=s3_key,
            Body=json.dumps(confirmation_record, indent=2),
            ContentType='application/json',
            Metadata={
                'report-id': report_id,
                'user-id': user_id,
                'action': action
            }
        )
        logger.info(f"Saved approval decision to {s3_key}")
        return s3_key
    
    except Exception as e:
        logger.error(f"Error saving approval decision to S3: {str(e)}")
        raise


def send_slack_response(response_url: str, message_text: str) -> bool:
    """
    Slack に確認状況を返信（response_url 経由）
    
    Args:
        response_url: Slack Webhook URL
        message_text: メッセージテキスト
    
    Returns:
        bool: 成功した場合 True
    
    注: AWS Lambda から response_url への POST は requests ライブラリを使用
    """
    try:
        import urllib3
        http = urllib3.PoolManager()
        
        payload = {
            "text": message_text,
            "response_type": "in_channel"
        }
        
        encoded_body = json.dumps(payload).encode('utf-8')
        response = http.request(
            'POST',
            response_url,
            body=encoded_body,
            headers={'Content-Type': 'application/json'}
        )
        
        if response.status == 200:
            logger.info(f"Slack response sent successfully")
            return True
        else:
            logger.warning(f"Slack response failed with status {response.status}")
            return False
    
    except Exception as e:
        logger.error(f"Error sending Slack response: {str(e)}")
        return False


def webhook_handler(event, context):
    """
    Slack Interactive Webhook ハンドラー（API Gateway + Lambda）
    
    イベント構造（API Gateway からの入力）:
        {
            "body": "{...Slack イベント JSON...}",
            "headers": {
                "X-Slack-Request-Timestamp": "1234567890",
                "X-Slack-Signature": "v0=..."
            }
        }
    """
    try:
        logger.info(f"Received webhook event: {json.dumps(event, indent=2)}")
        
        # API Gateway からのヘッダー取得
        headers = event.get('headers', {})
        timestamp = headers.get('X-Slack-Request-Timestamp', '')
        signature = headers.get('X-Slack-Signature', '')
        body = event.get('body', '')
        
        # ボディが文字列の場合、パース
        if isinstance(body, str):
            request_body = body
            body_json = json.loads(body)
        else:
            request_body = json.dumps(body)
            body_json = body
        
        # ===== ステップ 1: Slack 署名検証 =====
        if not verify_slack_signature(request_body, timestamp, signature):
            logger.error("Slack signature verification failed")
            return {
                "statusCode": 401,
                "body": json.dumps({"error": "Unauthorized"})
            }
        
        # ===== ステップ 2: イベントタイプの確認 =====
        event_type = body_json.get('type', '')
        
        # URL Verification リクエスト（Slack のセットアップ時に送信）
        if event_type == 'url_verification':
            challenge = body_json.get('challenge', '')
            logger.info(f"URL verification challenge received: {challenge}")
            return {
                "statusCode": 200,
                "body": challenge
            }
        
        # ===== ステップ 3: Interactive イベント処理 =====
        if event_type == 'block_actions':
            # Slack ボタンクリックイベント
            action_id, trigger_id, user_id, report_id, response_url = parse_slack_interactive_event(body_json)
            
            # ===== ステップ 4: 決定を S3 に保存 =====
            action = "approve" if action_id == "approve_action" else "cancel"
            s3_key = save_approval_decision(report_id, action, user_id)
            
            # ===== ステップ 5: Slack に確認応答を送信 =====
            message_text = f"✅ Approval recorded: `{action}` for report `{report_id}`"
            send_slack_response(response_url, message_text)
            
            return {
                "statusCode": 200,
                "body": json.dumps({
                    "status": "ok",
                    "action": action,
                    "report_id": report_id,
                    "s3_key": s3_key
                })
            }
        
        # ===== その他のイベント =====
        logger.warning(f"Unhandled event type: {event_type}")
        return {
            "statusCode": 400,
            "body": json.dumps({"error": f"Unhandled event type: {event_type}"})
        }
    
    except Exception as e:
        logger.error(f"Error processing webhook: {str(e)}", exc_info=True)
        return {
            "statusCode": 500,
            "body": json.dumps({"error": str(e)})
        }


def lambda_handler(event, context):
    """
    Lambda ハンドラー（メインエントリーポイント）
    """
    return webhook_handler(event, context)
