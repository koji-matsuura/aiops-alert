"""
Slack Interactive Webhook Handler テストコード

テストカバレッジ:
- get_slack_credentials() - Secrets Manager 連携
- verify_slack_signature() - HMAC-SHA256 署名検証
- parse_slack_interactive_event() - Slack ペイロード解析
- save_approval_decision() - S3 保存
- send_slack_response() - HTTP 応答
- webhook_handler() - 統合
- lambda_handler() - Lambda エントリーポイント
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os
import hmac
import hashlib
import time
from datetime import datetime

# パスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../lib'))


@pytest.fixture
def mock_aws_clients():
    """AWS クライアントのモック"""
    # キャッシュをリセット
    import slack_webhook_handler
    slack_webhook_handler._slack_credentials_cache = None
    
    with patch('slack_webhook_handler.s3_client') as mock_s3, \
         patch('slack_webhook_handler.secrets_manager_client') as mock_secrets:
          
        yield {
            's3': mock_s3,
            'secrets_manager': mock_secrets
        }
        
        # クリーンアップ: キャッシュをリセット
        slack_webhook_handler._slack_credentials_cache = None


@pytest.fixture
def mock_context():
    """AWS Lambda Context のモック"""
    context = Mock()
    context.aws_request_id = 'test-request-id'
    context.function_name = 'slack-webhook-handler'
    context.invoked_function_arn = 'arn:aws:lambda:ap-northeast-1:123456789012:function:slack-webhook'
    return context


@pytest.fixture
def slack_credentials():
    """Slack 認証情報"""
    return {
        'signing_secret': 'test-signing-secret-12345',
        'bot_token': 'xoxb-test-token-12345'
    }


def create_slack_signature(body, timestamp, signing_secret):
    """Slack 署名を生成（テスト用）"""
    sig_basestring = f'v0:{timestamp}:{body}'.encode('utf-8')
    signature = hmac.new(
        signing_secret.encode('utf-8'),
        sig_basestring,
        hashlib.sha256
    ).hexdigest()
    return f'v0={signature}'


class TestGetSlackCredentials:
    """get_slack_credentials() 関数のテスト"""

    def test_get_slack_credentials_success(self, mock_aws_clients, slack_credentials):
        """認証情報取得成功のテスト"""
        from slack_webhook_handler import get_slack_credentials
        
        # Secrets Manager からの応答をモック
        mock_aws_clients['secrets_manager'].get_secret_value.return_value = {
            'SecretString': json.dumps(slack_credentials)
        }
        
        with patch.dict(os.environ, {
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }):
            result = get_slack_credentials()
            
            assert result['signing_secret'] == slack_credentials['signing_secret']
            assert result['bot_token'] == slack_credentials['bot_token']

    def test_get_slack_credentials_cache(self, mock_aws_clients, slack_credentials):
        """キャッシュ機能のテスト"""
        from slack_webhook_handler import get_slack_credentials
        
        mock_aws_clients['secrets_manager'].get_secret_value.return_value = {
            'SecretString': json.dumps(slack_credentials)
        }
        
        with patch.dict(os.environ, {
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }):
            # 1 回目の呼び出し
            result1 = get_slack_credentials()
            
            # 2 回目の呼び出し（キャッシュから取得）
            result2 = get_slack_credentials()
            
            # Secrets Manager は 1 回だけ呼ばれるはず
            assert mock_aws_clients['secrets_manager'].get_secret_value.call_count == 1
            assert result1 == result2

    def test_get_slack_credentials_missing_secret_arn(self, mock_aws_clients):
        """環境変数未設定のテスト"""
        from slack_webhook_handler import get_slack_credentials
        
        with patch.dict(os.environ, {}, clear=True):
            with pytest.raises(ValueError):
                get_slack_credentials()

    def test_get_slack_credentials_secrets_manager_error(self, mock_aws_clients):
        """Secrets Manager エラーのテスト"""
        from slack_webhook_handler import get_slack_credentials
        
        mock_aws_clients['secrets_manager'].get_secret_value.side_effect = Exception("Access Denied")
        
        with patch.dict(os.environ, {
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }):
            with pytest.raises(Exception):
                get_slack_credentials()

    def test_get_slack_credentials_invalid_json(self, mock_aws_clients):
        """JSON パース失敗のテスト"""
        from slack_webhook_handler import get_slack_credentials
        
        mock_aws_clients['secrets_manager'].get_secret_value.return_value = {
            'SecretString': 'invalid-json-{{'
        }
        
        with patch.dict(os.environ, {
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }):
            with pytest.raises(Exception):
                get_slack_credentials()


class TestVerifySlackSignature:
    """verify_slack_signature() 関数のテスト"""

    def test_verify_slack_signature_valid(self, mock_aws_clients, slack_credentials):
        """署名検証成功のテスト"""
        from slack_webhook_handler import verify_slack_signature
        
        # Slack 認証情報をモック
        mock_aws_clients['secrets_manager'].get_secret_value.return_value = {
            'SecretString': json.dumps(slack_credentials)
        }
        
        request_body = json.dumps({'type': 'block_actions', 'actions': []})
        timestamp = str(int(time.time()))
        signature = create_slack_signature(request_body, timestamp, slack_credentials['signing_secret'])
        
        with patch.dict(os.environ, {
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }):
            result = verify_slack_signature(request_body, timestamp, signature)
            
            assert result is True

    def test_verify_slack_signature_invalid(self, mock_aws_clients, slack_credentials):
        """署名検証失敗のテスト"""
        from slack_webhook_handler import verify_slack_signature
        
        mock_aws_clients['secrets_manager'].get_secret_value.return_value = {
            'SecretString': json.dumps(slack_credentials)
        }
        
        request_body = json.dumps({'type': 'block_actions'})
        timestamp = str(int(time.time()))
        signature = 'v0=invalid-signature-12345'
        
        with patch.dict(os.environ, {
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }):
            result = verify_slack_signature(request_body, timestamp, signature)
            
            assert result is False

    def test_verify_slack_signature_old_timestamp(self, mock_aws_clients, slack_credentials):
        """古いタイムスタンプのテスト（5分以上前）"""
        from slack_webhook_handler import verify_slack_signature
        
        mock_aws_clients['secrets_manager'].get_secret_value.return_value = {
            'SecretString': json.dumps(slack_credentials)
        }
        
        request_body = json.dumps({'type': 'block_actions'})
        # 6 分前のタイムスタンプ
        timestamp = str(int(time.time()) - 360)
        signature = create_slack_signature(request_body, timestamp, slack_credentials['signing_secret'])
        
        with patch.dict(os.environ, {
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }):
            result = verify_slack_signature(request_body, timestamp, signature)
            
            assert result is False

    def test_verify_slack_signature_within_5_minutes(self, mock_aws_clients, slack_credentials):
        """5分以内のタイムスタンプのテスト"""
        from slack_webhook_handler import verify_slack_signature
        
        mock_aws_clients['secrets_manager'].get_secret_value.return_value = {
            'SecretString': json.dumps(slack_credentials)
        }
        
        request_body = json.dumps({'type': 'block_actions'})
        # 4 分前のタイムスタンプ
        timestamp = str(int(time.time()) - 240)
        signature = create_slack_signature(request_body, timestamp, slack_credentials['signing_secret'])
        
        with patch.dict(os.environ, {
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }):
            result = verify_slack_signature(request_body, timestamp, signature)
            
            assert result is True


class TestParseSlackInteractiveEvent:
    """parse_slack_interactive_event() 関数のテスト"""

    def test_parse_slack_interactive_event_approve(self):
        """Approve アクション解析のテスト"""
        from slack_webhook_handler import parse_slack_interactive_event
        
        event_body = {
            'type': 'block_actions',
            'actions': [
                {
                    'type': 'button',
                    'action_id': 'approve_button',
                    'value': 'approve'
                }
            ],
            'response_url': 'https://hooks.slack.com/actions/T00000/B00000/xxxx',
            'trigger_id': 'test-trigger-id',
            'user': {
                'id': 'U12345',
                'username': 'test-user'
            },
            'team': {
                'id': 'T12345'
            }
        }
        
        thread_id, user_id, action, report_id, approval_status = parse_slack_interactive_event(event_body)
        
        assert action == 'approve'
        assert user_id == 'U12345'

    def test_parse_slack_interactive_event_cancel(self):
        """Cancel アクション解析のテスト"""
        from slack_webhook_handler import parse_slack_interactive_event
        
        event_body = {
            'type': 'block_actions',
            'actions': [
                {
                    'type': 'button',
                    'action_id': 'cancel_button',
                    'value': 'cancel'
                }
            ],
            'response_url': 'https://hooks.slack.com/actions/T00000/B00000/xxxx',
            'user': {
                'id': 'U12345'
            }
        }
        
        thread_id, user_id, action, report_id, approval_status = parse_slack_interactive_event(event_body)
        
        assert action == 'cancel'

    def test_parse_slack_interactive_event_missing_fields(self):
        """必須フィールド不足のテスト"""
        from slack_webhook_handler import parse_slack_interactive_event
        
        event_body = {
            'type': 'block_actions',
            'actions': []
        }
        
        with pytest.raises(Exception):
            parse_slack_interactive_event(event_body)


class TestSaveApprovalDecision:
    """save_approval_decision() 関数のテスト"""

    def test_save_approval_decision_success(self, mock_aws_clients):
        """承認判定保存成功のテスト"""
        from slack_webhook_handler import save_approval_decision
        
        mock_aws_clients['s3'].put_object.return_value = {}
        
        with patch.dict(os.environ, {'S3_BUCKET': 'test-bucket'}):
            result = save_approval_decision(
                report_id='report-001',
                user_id='U12345',
                action='approve',
                thread_id='ts-123'
            )
            
            assert result is not None
            mock_aws_clients['s3'].put_object.assert_called_once()

    def test_save_approval_decision_s3_error(self, mock_aws_clients):
        """S3 エラーのテスト"""
        from slack_webhook_handler import save_approval_decision
        
        mock_aws_clients['s3'].put_object.side_effect = Exception("S3 Error")
        
        with patch.dict(os.environ, {'S3_BUCKET': 'test-bucket'}):
            with pytest.raises(Exception):
                save_approval_decision(
                    report_id='report-001',
                    user_id='U12345',
                    action='approve',
                    thread_id='ts-123'
                )

    def test_save_approval_decision_json_serialization(self, mock_aws_clients):
        """JSON シリアライズのテスト"""
        from slack_webhook_handler import save_approval_decision
        
        mock_aws_clients['s3'].put_object.return_value = {}
        
        with patch.dict(os.environ, {'S3_BUCKET': 'test-bucket'}):
            result = save_approval_decision(
                report_id='report-001',
                user_id='U12345',
                action='cancel',
                thread_id='ts-123'
            )
            
            # put_object が呼ばれたことを確認
            assert mock_aws_clients['s3'].put_object.called


class TestSendSlackResponse:
    """send_slack_response() 関数のテスト"""

    def test_send_slack_response_success(self):
        """Slack 応答送信成功のテスト"""
        from slack_webhook_handler import send_slack_response
        
        with patch('slack_webhook_handler.requests.post') as mock_post:
            mock_post.return_value = Mock(status_code=200)
            
            result = send_slack_response(
                response_url='https://hooks.slack.com/actions/T00000/B00000/xxxx',
                message_text='Operation completed'
            )
            
            assert result is True
            mock_post.assert_called_once()

    def test_send_slack_response_invalid_url(self):
        """不正な response_url のテスト"""
        from slack_webhook_handler import send_slack_response
        
        with patch('slack_webhook_handler.requests.post') as mock_post:
            mock_post.return_value = Mock(status_code=404)
            
            result = send_slack_response(
                response_url='https://invalid-url.example.com',
                message_text='Operation completed'
            )
            
            assert result is False

    def test_send_slack_response_timeout(self):
        """タイムアウトのテスト"""
        from slack_webhook_handler import send_slack_response
        
        with patch('slack_webhook_handler.requests.post') as mock_post:
            mock_post.side_effect = Exception("Request timeout")
            
            with pytest.raises(Exception):
                send_slack_response(
                    response_url='https://hooks.slack.com/actions/T00000/B00000/xxxx',
                    message_text='Operation completed'
                )


class TestWebhookHandler:
    """webhook_handler() 関数の統合テスト"""

    def test_webhook_handler_approve_action(self, mock_aws_clients, mock_context, slack_credentials):
        """Approve アクション統合テスト"""
        from slack_webhook_handler import webhook_handler
        
        # Slack 認証情報をモック
        mock_aws_clients['secrets_manager'].get_secret_value.return_value = {
            'SecretString': json.dumps(slack_credentials)
        }
        
        # S3 保存をモック
        mock_aws_clients['s3'].put_object.return_value = {}
        
        request_body = json.dumps({
            'type': 'block_actions',
            'actions': [
                {'type': 'button', 'action_id': 'approve_button', 'value': 'approve'}
            ],
            'response_url': 'https://hooks.slack.com/actions/T00000/B00000/xxxx',
            'user': {'id': 'U12345'},
            'team': {'id': 'T12345'}
        })
        
        timestamp = str(int(time.time()))
        signature = create_slack_signature(request_body, timestamp, slack_credentials['signing_secret'])
        
        event = {
            'body': request_body,
            'headers': {
                'X-Slack-Request-Timestamp': timestamp,
                'X-Slack-Signature': signature
            }
        }
        
        with patch.dict(os.environ, {
            'S3_BUCKET': 'test-bucket',
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }), patch('slack_webhook_handler.requests.post') as mock_post:
            mock_post.return_value = Mock(status_code=200)
            
            result = webhook_handler(event, mock_context)
            
            assert result is not None

    def test_webhook_handler_signature_verification_failed(self, mock_aws_clients, mock_context, slack_credentials):
        """署名検証失敗のテスト"""
        from slack_webhook_handler import webhook_handler
        
        mock_aws_clients['secrets_manager'].get_secret_value.return_value = {
            'SecretString': json.dumps(slack_credentials)
        }
        
        request_body = json.dumps({'type': 'block_actions'})
        timestamp = str(int(time.time()))
        signature = 'v0=invalid-signature'
        
        event = {
            'body': request_body,
            'headers': {
                'X-Slack-Request-Timestamp': timestamp,
                'X-Slack-Signature': signature
            }
        }
        
        with patch.dict(os.environ, {
            'S3_BUCKET': 'test-bucket',
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }):
            result = webhook_handler(event, mock_context)
            
            # 署名検証失敗時は 403 を返す
            assert result['statusCode'] == 403

    def test_webhook_handler_cancel_action(self, mock_aws_clients, mock_context, slack_credentials):
        """Cancel アクション統合テスト"""
        from slack_webhook_handler import webhook_handler
        
        mock_aws_clients['secrets_manager'].get_secret_value.return_value = {
            'SecretString': json.dumps(slack_credentials)
        }
        mock_aws_clients['s3'].put_object.return_value = {}
        
        request_body = json.dumps({
            'type': 'block_actions',
            'actions': [
                {'type': 'button', 'action_id': 'cancel_button', 'value': 'cancel'}
            ],
            'response_url': 'https://hooks.slack.com/actions/T00000/B00000/xxxx',
            'user': {'id': 'U12345'},
            'team': {'id': 'T12345'}
        })
        
        timestamp = str(int(time.time()))
        signature = create_slack_signature(request_body, timestamp, slack_credentials['signing_secret'])
        
        event = {
            'body': request_body,
            'headers': {
                'X-Slack-Request-Timestamp': timestamp,
                'X-Slack-Signature': signature
            }
        }
        
        with patch.dict(os.environ, {
            'S3_BUCKET': 'test-bucket',
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }), patch('slack_webhook_handler.requests.post') as mock_post:
            mock_post.return_value = Mock(status_code=200)
            
            result = webhook_handler(event, mock_context)
            
            assert result is not None


class TestLambdaHandler:
    """lambda_handler() 関数のテスト"""

    def test_lambda_handler_api_gateway_event(self, mock_aws_clients, mock_context, slack_credentials):
        """API Gateway イベント処理のテスト"""
        from slack_webhook_handler import lambda_handler
        
        mock_aws_clients['secrets_manager'].get_secret_value.return_value = {
            'SecretString': json.dumps(slack_credentials)
        }
        mock_aws_clients['s3'].put_object.return_value = {}
        
        request_body = json.dumps({
            'type': 'block_actions',
            'actions': [
                {'type': 'button', 'action_id': 'approve_button', 'value': 'approve'}
            ],
            'response_url': 'https://hooks.slack.com/actions/T00000/B00000/xxxx',
            'user': {'id': 'U12345'},
            'team': {'id': 'T12345'}
        })
        
        timestamp = str(int(time.time()))
        signature = create_slack_signature(request_body, timestamp, slack_credentials['signing_secret'])
        
        event = {
            'body': request_body,
            'headers': {
                'X-Slack-Request-Timestamp': timestamp,
                'X-Slack-Signature': signature
            }
        }
        
        with patch.dict(os.environ, {
            'S3_BUCKET': 'test-bucket',
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }), patch('slack_webhook_handler.requests.post') as mock_post:
            mock_post.return_value = Mock(status_code=200)
            
            result = lambda_handler(event, mock_context)
            
            assert result is not None

    def test_lambda_handler_exception(self, mock_aws_clients, mock_context):
        """例外処理のテスト"""
        from slack_webhook_handler import lambda_handler
        
        event = {'body': None}
        
        with patch.dict(os.environ, {
            'S3_BUCKET': 'test-bucket',
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }):
            # エラーハンドリングを確認
            result = lambda_handler(event, mock_context)
            
            # 500 エラーが返されるはず
            assert result['statusCode'] == 500 or result['statusCode'] == 403


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
