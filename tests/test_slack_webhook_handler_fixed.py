"""
Slack Interactive Webhook Handler テストコード（修正版）

AWS 公式推奨のテスト方式を採用:
- moto による AWS サービスモック
- patch() による外部依存モック
- 実行時環境変数読み込みで @patch.dict() に対応
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
        # 意図的に誤った署名を生成
        invalid_signature = 'v0=invalid'
        
        with patch.dict(os.environ, {
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }):
            result = verify_slack_signature(request_body, timestamp, invalid_signature)
            
            assert result is False

    def test_verify_slack_signature_old_timestamp(self, mock_aws_clients, slack_credentials):
        """古いタイムスタンプのテスト"""
        from slack_webhook_handler import verify_slack_signature
        
        mock_aws_clients['secrets_manager'].get_secret_value.return_value = {
            'SecretString': json.dumps(slack_credentials)
        }
        
        request_body = json.dumps({'type': 'block_actions'})
        # 10 分前のタイムスタンプ
        timestamp = str(int(time.time()) - 600)
        signature = create_slack_signature(request_body, timestamp, slack_credentials['signing_secret'])
        
        with patch.dict(os.environ, {
            'SLACK_CREDENTIALS_SECRET_ARN': 'arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:slack-creds'
        }):
            result = verify_slack_signature(request_body, timestamp, signature)
            
            assert result is False


class TestParseSlackInteractiveEvent:
    """parse_slack_interactive_event() 関数のテスト"""

    def test_parse_slack_interactive_event_approve(self):
        """Approve ボタンクリックの解析テスト"""
        from slack_webhook_handler import parse_slack_interactive_event
        
        payload = {
            'type': 'block_actions',
            'actions': [
                {
                    'type': 'button',
                    'action_id': 'approve_button',
                    'value': 'report-12345'
                }
            ],
            'user': {'id': 'U12345'},
            'team': {'id': 'T12345'},
            'response_url': 'https://hooks.slack.com/actions/T00000/B00000/xxxx',
            'trigger_id': 'trigger-123'
        }
        
        result = parse_slack_interactive_event(payload)
        
        # 戻り値は Tuple: (action_id, trigger_id, user_id, report_id, response_url)
        assert result[0] == 'approve_button'  # action_id
        assert result[2] == 'U12345'          # user_id
        assert result[3] == 'report-12345'    # report_id

    def test_parse_slack_interactive_event_cancel(self):
        """Cancel ボタンクリックの解析テスト"""
        from slack_webhook_handler import parse_slack_interactive_event
        
        payload = {
            'type': 'block_actions',
            'actions': [
                {
                    'type': 'button',
                    'action_id': 'cancel_button',
                    'value': 'report-12345'
                }
            ],
            'user': {'id': 'U12345'},
            'team': {'id': 'T12345'},
            'response_url': 'https://hooks.slack.com/actions/T00000/B00000/xxxx',
            'trigger_id': 'trigger-123'
        }
        
        result = parse_slack_interactive_event(payload)
        
        # 戻り値は Tuple: (action_id, trigger_id, user_id, report_id, response_url)
        assert result[0] == 'cancel_button'   # action_id
        assert result[2] == 'U12345'          # user_id
        assert result[3] == 'report-12345'    # report_id


class TestSaveApprovalDecision:
    """save_approval_decision() 関数のテスト"""

    def test_save_approval_decision_success(self, mock_aws_clients):
        """承認決定 S3 保存成功のテスト"""
        from slack_webhook_handler import save_approval_decision
        
        mock_aws_clients['s3'].put_object.return_value = {}
        
        with patch.dict(os.environ, {'S3_BUCKET': 'test-bucket'}):
            result = save_approval_decision(
                report_id='report-001',
                action='approve',
                user_id='U12345'
            )
            
            assert result is not None
            mock_aws_clients['s3'].put_object.assert_called_once()

    def test_save_approval_decision_s3_error(self, mock_aws_clients):
        """S3 エラーのテスト"""
        from slack_webhook_handler import save_approval_decision
        
        mock_aws_clients['s3'].put_object.side_effect = Exception("S3 error")
        
        with patch.dict(os.environ, {'S3_BUCKET': 'test-bucket'}):
            with pytest.raises(Exception):
                save_approval_decision(
                    report_id='report-001',
                    action='approve',
                    user_id='U12345'
                )


class TestSendSlackResponse:
    """send_slack_response() 関数のテスト"""

    @patch('urllib3.PoolManager')
    def test_send_slack_response_success(self, mock_pool_manager):
        """Slack 応答送信成功のテスト"""
        from slack_webhook_handler import send_slack_response
        
        # urllib3 のモックを設定
        mock_http = Mock()
        mock_http.request.return_value = Mock(status=200)
        mock_pool_manager.return_value = mock_http
        
        result = send_slack_response(
            response_url='https://hooks.slack.com/actions/T00000/B00000/xxxx',
            message_text='Operation completed'
        )
        
        assert result is True
        mock_http.request.assert_called_once()

    @patch('urllib3.PoolManager')
    def test_send_slack_response_invalid_url(self, mock_pool_manager):
        """不正な response_url のテスト"""
        from slack_webhook_handler import send_slack_response
        
        # urllib3 のモックを設定（404 応答）
        mock_http = Mock()
        mock_http.request.return_value = Mock(status=404)
        mock_pool_manager.return_value = mock_http
        
        result = send_slack_response(
            response_url='https://invalid-url.example.com',
            message_text='Operation completed'
        )
        
        assert result is False

    @patch('urllib3.PoolManager')
    def test_send_slack_response_timeout(self, mock_pool_manager):
        """タイムアウトのテスト"""
        from slack_webhook_handler import send_slack_response
        
        # urllib3 のモックを設定（例外を発生）
        mock_http = Mock()
        mock_http.request.side_effect = Exception("Request timeout")
        mock_pool_manager.return_value = mock_http
        
        result = send_slack_response(
            response_url='https://hooks.slack.com/actions/T00000/B00000/xxxx',
            message_text='Operation completed'
        )
        
        # エラーをキャッチして False を返す
        assert result is False


class TestWebhookHandler:
    """webhook_handler() 関数の統合テスト"""

    def test_webhook_handler_approve_action(self, mock_aws_clients, slack_credentials):
        """Approve アクション統合テスト"""
        from slack_webhook_handler import webhook_handler
        
        # Lambda Context のモック
        mock_context = Mock()
        mock_context.aws_request_id = 'test-request-id'
        
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
        }), patch('requests.post') as mock_post:
            
            mock_post.return_value = Mock(status_code=200)
            
            result = webhook_handler(event, mock_context)
            
            assert result['statusCode'] == 200


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
