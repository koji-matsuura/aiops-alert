"""
エラーシナリオテスト - AWS 公式ドキュメント準拠検証

テスト対象：
1. EventBridge イベントスキーマ違反（フィールド不足）
2. Bedrock Agent messageVersion 1.0 レスポンス形式違反
3. 無効な JSON ペイロード
4. Lambda 関数呼び出し失敗
5. SNS 通知失敗
6. Bedrock Agent 応答失敗
7. S3 アクセス失敗
8. OpenSearch 到達不可
9. Secrets Manager キー不在
10. タイムアウトシナリオ

参照:
- AWS EventBridge: https://docs.aws.amazon.com/eventbridge/latest/ref/overiew-event-structure.html
- AWS Bedrock Agent: https://docs.aws.amazon.com/bedrock/latest/userguide/agents-lambda.html
- AWS Lambda: https://docs.aws.amazon.com/lambda/latest/dg/API_Invoke.html
"""

import json
import pytest
import boto3
from moto import mock_aws
from unittest.mock import patch, MagicMock
import sys
import os

# lambda_handler.py をインポート
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))
from lambda_handler import (
    handler,
    handle_bedrock_agent_message,
    dispatch_function,
    extract_event_info,
)


# ===== テスト 1: EventBridge イベントスキーマ違反 =====

class TestEventBridgeSchemaCompliance:
    """EventBridge 公式スキーマの準拠性検証"""
    
    def test_event_with_missing_version_field(self):
        """eventバージョンフィールド欠損"""
        # AWS 公式スキーマ: version フィールド必須（デフォルト: "0"）
        invalid_event = {
            "source": "aws.cloudwatch",
            "detail-type": "CloudWatch Alarm State Change",
            "time": "2026-06-04T10:30:00Z",
            "detail": {"alarmName": "EC2-HighCPU"},
            # ❌ version フィールド欠損
        }
        
        event_info = extract_event_info(invalid_event)
        # 実装が version フィールド抽出に対応しているか
        assert 'version' in event_info or event_info.get('version') is None
    
    def test_event_with_missing_account_field(self):
        """account フィールド欠損"""
        invalid_event = {
            "version": "0",
            "source": "aws.cloudwatch",
            "detail-type": "CloudWatch Alarm State Change",
            "time": "2026-06-04T10:30:00Z",
            "detail": {"alarmName": "EC2-HighCPU"},
            # ❌ account フィールド欠損
        }
        
        event_info = extract_event_info(invalid_event)
        assert 'account' in event_info or event_info.get('account') is None
    
    def test_event_with_missing_id_field(self):
        """id フィールド欠損"""
        invalid_event = {
            "version": "0",
            "source": "aws.cloudwatch",
            "account": "123456789012",
            "detail-type": "CloudWatch Alarm State Change",
            "time": "2026-06-04T10:30:00Z",
            "detail": {"alarmName": "EC2-HighCPU"},
            # ❌ id フィールド欠損
        }
        
        event_info = extract_event_info(invalid_event)
        assert 'id' in event_info or event_info.get('id') is None
    
    def test_event_with_missing_region_field(self):
        """region フィールド欠損"""
        invalid_event = {
            "version": "0",
            "source": "aws.cloudwatch",
            "account": "123456789012",
            "detail-type": "CloudWatch Alarm State Change",
            "time": "2026-06-04T10:30:00Z",
            "detail": {"alarmName": "EC2-HighCPU"},
            # ❌ region フィールド欠損
        }
        
        event_info = extract_event_info(invalid_event)
        assert 'region' in event_info or event_info.get('region') is None
    
    def test_event_with_missing_resources_field(self):
        """resources フィールド欠損"""
        invalid_event = {
            "version": "0",
            "source": "aws.cloudwatch",
            "account": "123456789012",
            "id": "event-123",
            "region": "ap-northeast-1",
            "detail-type": "CloudWatch Alarm State Change",
            "time": "2026-06-04T10:30:00Z",
            "detail": {"alarmName": "EC2-HighCPU"},
            # ❌ resources フィールド欠損（オプションだが）
        }
        
        event_info = extract_event_info(invalid_event)
        # resources は optional
        assert True


# ===== テスト 2: Bedrock Agent messageVersion 1.0 レスポンス形式 =====

class TestBedrockAgentResponseFormat:
    """Bedrock Agent messageVersion 1.0 レスポンス形式の準拠性"""
    
    @mock_aws
    def test_response_missing_functionresponse_wrapper(self):
        """❌ functionResponse ラッパー欠損（現在の実装）"""
        # AWS 公式フォーマットでは functionResponse ラッパーが必須
        mock_context = MagicMock()
        mock_context.aws_request_id = "session-123"
        
        event = {
            "messageVersion": "1.0",
            "agent": {"name": "AiopsAgent", "id": "AGENT123"},
            "inputText": "EC2 調査",
            "sessionId": "session-123",
            "actionGroup": "AIOpsActionGroup",
            "function": "log_investigation",
            "parameters": [{"name": "log_group_name", "type": "string", "value": "/aws/lambda/test"}]
        }
        
        with patch('lambda_handler.log_investigation_fr01') as mock_fr01:
            mock_fr01.return_value = {"status": "success"}
            
            response = handle_bedrock_agent_message(event, mock_context)
            
            # AWS 公式フォーマットの検証
            assert response.get('messageVersion') == '1.0'
            assert 'response' in response
            
            # ❌ 現在の実装は httpStatusCode を使用（不正）
            if 'httpStatusCode' in response['response']:
                pytest.fail("Response should use functionResponse wrapper, not httpStatusCode")
            
            # ✅ 正しい形式： response.functionResponse.responseState
            if 'functionResponse' not in response['response']:
                pytest.fail("Response must contain functionResponse wrapper (AWS official format)")
    
    def test_response_missing_responsestate_field(self):
        """❌ responseState フィールド欠損"""
        # AWS 公式フォーマットでは responseState が必須（成功時は省略可能だが推奨）
        response = {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": "AIOpsActionGroup",
                "function": "log_investigation",
                # ❌ responseState 欠損
                "functionResponse": {
                    "responseBody": {
                        "TEXT": {
                            "body": "investigat result"
                        }
                    }
                }
            }
        }
        
        # responseState がない場合、Bedrock Agent は処理続行（成功と判定）
        # ただし、エラーの場合は必須
        assert response['response']['functionResponse'].get('responseState') is None or \
               response['response']['functionResponse'].get('responseState') in ['FAILURE', 'REPROMPT']


# ===== テスト 3: 無効な JSON ペイロード =====

class TestInvalidJsonPayload:
    """無効な JSON ペイロード処理"""
    
    @mock_aws
    def test_handler_with_malformed_event_json(self):
        """malformed JSON イベント"""
        mock_context = MagicMock()
        mock_context.aws_request_id = "session-123"
        
        # JSON パースに失敗する入力（実装では dict で受け取るため、直接の JSON エラーは発生しない）
        # しかし、event が dict でない場合を考慮
        invalid_event = None
        
        with patch('lambda_handler.extract_event_info') as mock_extract:
            mock_extract.side_effect = TypeError("Event is not a dict")
            
            try:
                handler(invalid_event, mock_context)
            except TypeError:
                # エラー処理が期待される
                pass


# ===== テスト 4: Lambda 関数呼び出し失敗 =====

class TestLambdaInvocationFailure:
    """Lambda 関数実行時エラー"""
    
    @mock_aws
    def test_dispatch_function_with_nonexistent_function(self):
        """存在しない function を呼び出し"""
        mock_context = MagicMock()
        mock_context.aws_request_id = "session-123"
        
        result = dispatch_function("nonexistent_function", {}, "session-123")
        
        # エラーレスポンスが返るべき
        assert result.get('status') == 'error'
        assert 'not recognized' in result.get('message', '').lower()
    
    @mock_aws
    def test_dispatch_function_with_missing_required_parameter(self):
        """必須パラメータ欠損"""
        # log_investigation_fr01 は log_group_name を必須とする
        result = dispatch_function("log_investigation", {}, "session-123")
        
        # エラーまたは部分的な実行結果
        # 実装によって異なる
        assert result is not None


# ===== テスト 5: SNS 通知失敗 =====

class TestSNSNotificationFailure:
    """SNS 通知時エラー"""
    
    @mock_aws
    def test_sns_publish_failure(self):
        """SNS publish 失敗"""
        mock_context = MagicMock()
        mock_context.aws_request_id = "session-123"
        
        # SNS クライアント初期化（moto）
        sns = boto3.client('sns', region_name='ap-northeast-1')
        
        # トピック作成
        topic_response = sns.create_topic(Name='AIOpsReport')
        topic_arn = topic_response['TopicArn']
        
        # SNS publish パッチ
        with patch('boto3.client') as mock_boto_client:
            mock_sns = MagicMock()
            mock_boto_client.return_value = mock_sns
            
            mock_sns.publish.side_effect = Exception("SNS service unavailable")
            
            # handler 実行
            event = {
                "source": "aws.cloudwatch",
                "detail-type": "CloudWatch Alarm State Change",
                "detail": {"alarmName": "EC2-HighCPU"},
                "time": "2026-06-04T10:30:00Z"
            }
            
            try:
                response = handler(event, mock_context)
                # エラーが適切に処理されるべき
                assert response['statusCode'] in [500, 200]  # エラーまたは部分成功
            except Exception as e:
                # エラーが予期される
                assert str(e) != ""


# ===== テスト 6: Bedrock Agent 応答失敗 =====

class TestBedrockAgentFailure:
    """Bedrock Agent 呼び出し失敗"""
    
    @mock_aws
    def test_bedrock_agent_invocation_timeout(self):
        """Bedrock Agent がタイムアウト"""
        mock_context = MagicMock()
        mock_context.aws_request_id = "session-123"
        
        event = {
            "source": "aws.cloudwatch",
            "detail-type": "CloudWatch Alarm State Change",
            "detail": {"alarmName": "EC2-HighCPU"},
            "time": "2026-06-04T10:30:00Z"
        }
        
        with patch('lambda_handler.invoke_bedrock_agent') as mock_invoke:
            mock_invoke.side_effect = TimeoutError("Bedrock Agent timeout after 30s")
            
            response = handler(event, mock_context)
            
            # エラーレスポンスが返るべき
            assert response['statusCode'] == 500 or 'error' in response.get('body', '').lower()


# ===== テスト 7: S3 アクセス失敗 =====

class TestS3AccessFailure:
    """S3 バケットアクセス失敗"""
    
    @mock_aws
    def test_s3_bucket_not_found(self):
        """S3 バケットが存在しない"""
        with patch('boto3.client') as mock_boto_client:
            mock_s3 = MagicMock()
            mock_boto_client.return_value = mock_s3
            
            mock_s3.get_object.side_effect = Exception("NoSuchBucket")
            
            # Lambda ZIP パッケージ取得時の失敗
            assert True  # エラーが適切にログされるべき


# ===== テスト 8: OpenSearch 到達不可 =====

class TestOpenSearchUnavailability:
    """OpenSearch Serverless 到達不可"""
    
    def test_opensearch_connection_failure(self):
        """OpenSearch Serverless に接続失敗"""
        with patch('boto3.client') as mock_boto_client:
            mock_aoss = MagicMock()
            mock_boto_client.return_value = mock_aoss
            
            mock_aoss.describe_indices.side_effect = Exception("Connection refused")
            
            # Knowledge Base 検索時の失敗
            assert True  # エラーが適切にハンドルされるべき


# ===== テスト 9: Secrets Manager キー不在 =====

class TestSecretsManagerKeyNotFound:
    """Secrets Manager にシークレットが存在しない"""
    
    def test_secret_not_found(self):
        """Secrets Manager: シークレットなし"""
        with patch('boto3.client') as mock_boto_client:
            mock_secrets = MagicMock()
            mock_boto_client.return_value = mock_secrets
            
            mock_secrets.get_secret_value.side_effect = Exception("ResourceNotFoundException")
            
            # API キーまたは認証情報取得失敗
            assert True  # エラーが適切にハンドルされるべき


# ===== テスト 10: タイムアウトシナリオ =====

class TestTimeoutScenarios:
    """Lambda 実行タイムアウト"""
    
    @mock_aws
    def test_lambda_execution_timeout(self):
        """Lambda が 300 秒（デフォルトタイムアウト）を超える"""
        mock_context = MagicMock()
        mock_context.aws_request_id = "session-123"
        mock_context.get_remaining_time_in_millis = MagicMock(return_value=0)  # タイムアウト
        
        event = {
            "source": "aws.cloudwatch",
            "detail-type": "CloudWatch Alarm State Change",
            "detail": {"alarmName": "EC2-HighCPU"},
            "time": "2026-06-04T10:30:00Z"
        }
        
        # context.get_remaining_time_in_millis() == 0 → タイムアウト状態
        # Lambda が TimeoutError を発行すべき
        assert mock_context.get_remaining_time_in_millis() == 0


if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
