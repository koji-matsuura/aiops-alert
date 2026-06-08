"""
Lambda ハンドラのテストコード
各機能（FR‑01～FR‑06）のテストケースを含む
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os
from datetime import datetime

# パスを追加
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../lib'))

# テスト用のモック設定
@pytest.fixture
def mock_aws_clients():
    with patch('lambda_handler.logs_client') as mock_logs, \
         patch('lambda_handler.cloudwatch_client') as mock_cloudwatch, \
         patch('lambda_handler.sns_client') as mock_sns, \
         patch('lambda_handler.s3_client') as mock_s3, \
         patch('lambda_handler.rds_client') as mock_rds, \
         patch('lambda_handler.pi_client') as mock_pi, \
         patch('lambda_handler.ec2_client') as mock_ec2, \
         patch('lambda_handler.bedrock_agent_runtime') as mock_bedrock:
         
         yield {
             'logs': mock_logs,
             'cloudwatch': mock_cloudwatch,
             'sns': mock_sns,
             's3': mock_s3,
             'rds': mock_rds,
             'pi': mock_pi,
             'ec2': mock_ec2,
             'bedrock': mock_bedrock
         }


@pytest.fixture
def mock_context():
    """AWS Lambda Context のモック"""
    context = Mock()
    context.aws_request_id = 'test-session-id-12345'
    context.function_name = 'aiops-lambda'
    context.function_version = '1'
    context.invoked_function_arn = 'arn:aws:lambda:ap-northeast-1:123456789012:function:aiops-lambda'
    context.memory_limit_in_mb = 256
    context.log_group_name = '/aws/lambda/aiops-lambda'
    context.log_stream_name = '2026/06/08/[$LATEST]abc123'
    context.get_remaining_time_in_millis = Mock(return_value=30000)
    return context


class TestExtractEventInfo:
    """extract_event_info() 関数のテスト"""

    def test_extract_cloudwatch_alarm_event(self):
        """CloudWatch Alarms イベント抽出のテスト"""
        from lambda_handler import extract_event_info

        event = {
            "source": "aws.cloudwatch",
            "detail-type": "CloudWatch Alarm State Change",
            "detail": {
                "alarmName": "EC2-HighCPU-i-12345",
                "state": {"value": "ALARM"}
            },
            "time": "2026-06-08T10:30:00Z"
        }

        result = extract_event_info(event)

        assert result["source"] == "aws.cloudwatch"
        assert result["detail_type"] == "CloudWatch Alarm State Change"
        assert result["detail"]["alarmName"] == "EC2-HighCPU-i-12345"
        assert result["time"] == "2026-06-08T10:30:00Z"

    def test_extract_scheduled_event(self):
        """EventBridge Scheduled Event 抽出のテスト"""
        from lambda_handler import extract_event_info

        event = {
            "source": "aws.events",
            "detail-type": "Scheduled Event",
            "detail": {},
            "time": "2026-06-08T00:00:00Z"
        }

        result = extract_event_info(event)

        assert result["source"] == "aws.events"
        assert result["detail_type"] == "Scheduled Event"
        assert result["detail"] == {}

    def test_extract_missing_fields(self):
        """不足フィールド時のテスト"""
        from lambda_handler import extract_event_info

        event = {"raw": "data"}
        result = extract_event_info(event)

        assert result["source"] == "unknown"
        assert result["detail_type"] == "unknown"
        assert result["raw_event"] == event


class TestBuildPrompt:
    """build_prompt() 関数のテスト"""

    def test_build_prompt_cloudwatch_alarm(self):
        """CloudWatch Alarms prompt 構築のテスト"""
        from lambda_handler import build_prompt

        event_info = {
            "source": "aws.cloudwatch",
            "detail_type": "CloudWatch Alarm State Change",
            "detail": {"alarmName": "EC2-HighCPU-i-12345"},
            "time": "2026-06-08T10:30:00Z"
        }

        prompt = build_prompt(event_info)

        assert "【イベント受信】" in prompt
        assert "aws.cloudwatch" in prompt
        assert "EC2-HighCPU-i-12345" in prompt
        assert "Knowledge Base" in prompt

    def test_build_prompt_scheduled_event(self):
        """Scheduled Event prompt 構築のテスト"""
        from lambda_handler import build_prompt

        event_info = {
            "source": "aws.events",
            "detail_type": "Scheduled Event",
            "detail": {},
            "time": "2026-06-08T00:00:00Z"
        }

        prompt = build_prompt(event_info)

        assert "【イベント受信】" in prompt
        assert "aws.events" in prompt
        assert "Knowledge Base" in prompt


class TestLambdaHandler:
    """lambda_handler() 関数のテスト"""

    def test_lambda_handler_cloudwatch_alarm(self, mock_aws_clients, mock_context):
        """CloudWatch Alarms イベント処理のテスト"""
        from lambda_handler import handler

        event = {
            "source": "aws.cloudwatch",
            "detail-type": "CloudWatch Alarm State Change",
            "detail": {"alarmName": "EC2-HighCPU-i-12345"},
            "time": "2026-06-08T10:30:00Z"
        }

        # Bedrock Agent を非呼び出し（BEDROCK_AGENT_ID なし）でテスト
        result = handler(event, mock_context)

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['message'] == 'AIOps investigation completed'
        assert body['source'] == 'aws.cloudwatch'

    def test_lambda_handler_scheduled_event(self, mock_aws_clients, mock_context):
        """Scheduled Event 処理のテスト"""
        from lambda_handler import handler

        event = {
            "source": "aws.events",
            "detail-type": "Scheduled Event",
            "detail": {},
            "time": "2026-06-08T00:00:00Z"
        }

        result = handler(event, mock_context)

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert body['source'] == 'aws.events'

    def test_lambda_handler_exception(self, mock_aws_clients, mock_context):
        """例外処理のテスト"""
        from lambda_handler import handler

        # SNS publish で例外を発生させる
        mock_aws_clients['sns'].publish.side_effect = Exception("SNS Error")

        event = {
            "source": "aws.cloudwatch",
            "detail-type": "CloudWatch Alarm State Change",
            "detail": {"alarmName": "EC2-HighCPU"},
            "time": "2026-06-08T10:30:00Z"
        }

        result = handler(event, mock_context)

        # SNS 通知失敗してもハンドラーは成功
        assert result['statusCode'] == 200


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
