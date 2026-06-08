"""
Lambda ハンドラのテストコード
各機能（FR‑01～FR‑06）のテストケースを含む

テストカバレッジ目標:
- lambda_handler.py: 22 関数すべてをテスト
- FR-01～FR-06: ビジネスロジック
- Bedrock Agent: 統合・messageVersion 1.0
- ユーティリティ: AWS サービス連携
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock, call
import sys
import os
from datetime import datetime
import base64
import hmac
import hashlib

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


class TestBedrockAgentIntegration:
    """Bedrock Agent 統合テスト"""

    def test_invoke_bedrock_agent_success(self, mock_aws_clients, mock_context):
        """Bedrock Agent 呼び出し成功のテスト"""
        from lambda_handler import invoke_bedrock_agent
        
        # Bedrock Agent のモック応答
        mock_aws_clients['bedrock'].invoke_agent.return_value = {
            'ResponseMetadata': {'HTTPStatusCode': 200},
            'actionGroupInvocationOutput': {
                'text': 'Investigation completed'
            }
        }
        
        prompt = "【イベント受信】テストプロンプト"
        session_id = "test-session-123"
        
        result = invoke_bedrock_agent(prompt=prompt, session_id=session_id)
        
        assert result is not None
        assert 'ResponseMetadata' in result

    def test_invoke_bedrock_agent_no_agent_id(self, mock_aws_clients, mock_context):
        """Agent ID が未設定時のテスト"""
        from lambda_handler import invoke_bedrock_agent
        
        with patch.dict(os.environ, {'BEDROCK_AGENT_ID': ''}):
            prompt = "Test prompt"
            result = invoke_bedrock_agent(prompt=prompt, session_id="test")
            
            # Agent ID なしの場合はスキップ
            assert result is None

    def test_handle_bedrock_agent_message_fr01(self, mock_aws_clients, mock_context):
        """messageVersion 1.0 処理 (FR-01) のテスト"""
        from lambda_handler import handle_bedrock_agent_message
        
        event = {
            'messageVersion': '1.0',
            'invocationId': 'inv-123',
            'actionGroup': 'AIOpsActions',
            'function': 'handle_log_investigation',
            'parameters': {
                'log_group_name': '/aws/lambda/test'
            }
        }
        
        with patch('lambda_handler.handle_log_investigation') as mock_handler:
            mock_handler.return_value = {'logs': []}
            result = handle_bedrock_agent_message(event, mock_context)
            
            assert result is not None

    def test_handle_bedrock_agent_message_invalid_function(self, mock_aws_clients, mock_context):
        """不正な関数名のテスト"""
        from lambda_handler import handle_bedrock_agent_message
        
        event = {
            'messageVersion': '1.0',
            'invocationId': 'inv-123',
            'actionGroup': 'AIOpsActions',
            'function': 'invalid_function',
            'parameters': {}
        }
        
        # エラーハンドリング
        with pytest.raises(Exception):
            handle_bedrock_agent_message(event, mock_context)

    def test_dispatch_function_fr01(self, mock_aws_clients, mock_context):
        """dispatch_function FR-01 のテスト"""
        from lambda_handler import dispatch_function
        
        with patch('lambda_handler.handle_log_investigation') as mock_fr01:
            mock_fr01.return_value = {'logs': []}
            
            result = dispatch_function('handle_log_investigation', {'log_group_name': '/test'})
            
            assert result == {'logs': []}
            mock_fr01.assert_called_once()

    def test_dispatch_function_fr02(self, mock_aws_clients, mock_context):
        """dispatch_function FR-02 のテスト"""
        from lambda_handler import dispatch_function
        
        with patch('lambda_handler.handle_bottleneck_investigation') as mock_fr02:
            mock_fr02.return_value = {'bottlenecks': []}
            
            result = dispatch_function('handle_bottleneck_investigation', {'resource_type': 'ec2'})
            
            assert result == {'bottlenecks': []}
            mock_fr02.assert_called_once()


class TestFR01LogInvestigation:
    """FR-01 ログ調査のテスト"""

    def test_handle_log_investigation_success(self, mock_aws_clients, mock_context):
        """ログ調査成功のテスト"""
        from lambda_handler import handle_log_investigation
        
        # CloudWatch Logs のモック応答
        mock_aws_clients['logs'].describe_log_groups.return_value = {
            'logGroups': [
                {'logGroupName': '/aws/lambda/test-function'}
            ]
        }
        
        mock_aws_clients['logs'].filter_log_events.return_value = {
            'events': [
                {'message': 'ERROR: Something went wrong'}
            ]
        }
        
        params = {'log_group_name': '/aws/lambda/test-function'}
        result = handle_log_investigation(params)
        
        assert result is not None

    def test_handle_log_investigation_no_logs(self, mock_aws_clients, mock_context):
        """ログなしのテスト"""
        from lambda_handler import handle_log_investigation
        
        mock_aws_clients['logs'].filter_log_events.return_value = {'events': []}
        
        params = {'log_group_name': '/aws/lambda/test-function'}
        result = handle_log_investigation(params)
        
        assert result is not None

    def test_handle_log_investigation_api_error(self, mock_aws_clients, mock_context):
        """API エラーのテスト"""
        from lambda_handler import handle_log_investigation
        
        mock_aws_clients['logs'].filter_log_events.side_effect = Exception("API Error")
        
        params = {'log_group_name': '/aws/lambda/test-function'}
        
        with pytest.raises(Exception):
            handle_log_investigation(params)


class TestFR02BottleneckInvestigation:
    """FR-02 ボトルネック調査のテスト"""

    def test_handle_bottleneck_investigation_rds(self, mock_aws_clients, mock_context):
        """RDS ボトルネック調査のテスト"""
        from lambda_handler import handle_bottleneck_investigation
        
        mock_aws_clients['rds'].describe_db_instances.return_value = {
            'DBInstances': [
                {
                    'DBInstanceIdentifier': 'prod-db-1',
                    'DBInstanceClass': 'db.r5.2xlarge'
                }
            ]
        }
        
        mock_aws_clients['pi'].get_resource_metrics.return_value = {
            'MetricList': [
                {
                    'Key': {'Metric': 'db_load'},
                    'DataPoints': [[datetime.utcnow(), 75.5]]
                }
            ]
        }
        
        params = {'resource_type': 'rds'}
        result = handle_bottleneck_investigation(params)
        
        assert result is not None

    def test_handle_bottleneck_investigation_ec2(self, mock_aws_clients, mock_context):
        """EC2 ボトルネック調査のテスト"""
        from lambda_handler import handle_bottleneck_investigation
        
        mock_aws_clients['ec2'].describe_instances.return_value = {
            'Reservations': [
                {
                    'Instances': [
                        {'InstanceId': 'i-12345', 'InstanceType': 't3.large'}
                    ]
                }
            ]
        }
        
        params = {'resource_type': 'ec2'}
        result = handle_bottleneck_investigation(params)
        
        assert result is not None

    def test_handle_bottleneck_investigation_no_data(self, mock_aws_clients, mock_context):
        """データなしのテスト"""
        from lambda_handler import handle_bottleneck_investigation
        
        mock_aws_clients['rds'].describe_db_instances.return_value = {'DBInstances': []}
        
        params = {'resource_type': 'rds'}
        result = handle_bottleneck_investigation(params)
        
        assert result is not None


class TestFR03CreateSnapshot:
    """FR-03 DB スナップショット作成のテスト"""

    def test_handle_create_snapshot_success(self, mock_aws_clients, mock_context):
        """スナップショット作成成功のテスト"""
        from lambda_handler import handle_create_snapshot
        
        mock_aws_clients['rds'].create_db_snapshot.return_value = {
            'DBSnapshot': {
                'DBSnapshotIdentifier': 'snapshot-20260608-1'
            }
        }
        
        params = {'db_instance_identifier': 'prod-db-1'}
        result = handle_create_snapshot(params)
        
        assert result is not None

    def test_handle_create_snapshot_already_exists(self, mock_aws_clients, mock_context):
        """既存スナップショットのテスト"""
        from lambda_handler import handle_create_snapshot
        
        mock_aws_clients['rds'].create_db_snapshot.side_effect = Exception("Snapshot already exists")
        
        params = {'db_instance_identifier': 'prod-db-1'}
        
        with pytest.raises(Exception):
            handle_create_snapshot(params)


class TestFR04MaintenanceDisplay:
    """FR-04 メンテナンスウィンドウ表示のテスト"""

    def test_handle_maintenance_display_rds(self, mock_aws_clients, mock_context):
        """RDS メンテナンスウィンドウのテスト"""
        from lambda_handler import handle_maintenance_display
        
        mock_aws_clients['rds'].describe_db_instances.return_value = {
            'DBInstances': [
                {
                    'DBInstanceIdentifier': 'prod-db-1',
                    'PreferredMaintenanceWindow': 'sun:04:00-sun:05:00'
                }
            ]
        }
        
        params = {'resource_type': 'rds'}
        result = handle_maintenance_display(params)
        
        assert result is not None

    def test_handle_maintenance_display_no_data(self, mock_aws_clients, mock_context):
        """メンテナンスデータなしのテスト"""
        from lambda_handler import handle_maintenance_display
        
        mock_aws_clients['rds'].describe_db_instances.return_value = {'DBInstances': []}
        
        params = {'resource_type': 'rds'}
        result = handle_maintenance_display(params)
        
        assert result is not None


class TestFR05SlowQueryDetection:
    """FR-05 遅いクエリ検出のテスト"""

    def test_handle_slow_query_detection_queries_found(self, mock_aws_clients, mock_context):
        """遅いクエリ検出のテスト"""
        from lambda_handler import handle_slow_query_detection
        
        mock_aws_clients['pi'].get_resource_metrics.return_value = {
            'MetricList': [
                {
                    'Key': {'Metric': 'os.processList'},
                    'DataPoints': [[datetime.utcnow(), 'SELECT * FROM table']]
                }
            ]
        }
        
        params = {'db_resource_id': 'db-ABC123'}
        result = handle_slow_query_detection(params)
        
        assert result is not None

    def test_handle_slow_query_detection_no_queries(self, mock_aws_clients, mock_context):
        """クエリなしのテスト"""
        from lambda_handler import handle_slow_query_detection
        
        mock_aws_clients['pi'].get_resource_metrics.return_value = {'MetricList': []}
        
        params = {'db_resource_id': 'db-ABC123'}
        result = handle_slow_query_detection(params)
        
        assert result is not None


class TestFR06HighLoadQueryDetection:
    """FR-06 高負荷クエリ分析のテスト"""

    def test_handle_high_load_query_detection_queries_found(self, mock_aws_clients, mock_context):
        """高負荷クエリ検出のテスト"""
        from lambda_handler import handle_high_load_query_detection
        
        mock_aws_clients['pi'].get_resource_metrics.return_value = {
            'MetricList': [
                {
                    'Key': {'Metric': 'db_load_by_host'},
                    'DataPoints': [[datetime.utcnow(), {'SELECT': 85.5}]]
                }
            ]
        }
        
        params = {'db_resource_id': 'db-ABC123'}
        result = handle_high_load_query_detection(params)
        
        assert result is not None

    def test_handle_high_load_query_detection_no_queries(self, mock_aws_clients, mock_context):
        """クエリなしのテスト"""
        from lambda_handler import handle_high_load_query_detection
        
        mock_aws_clients['pi'].get_resource_metrics.return_value = {'MetricList': []}
        
        params = {'db_resource_id': 'db-ABC123'}
        result = handle_high_load_query_detection(params)
        
        assert result is not None


class TestUtilityFunctions:
    """ユーティリティ関数のテスト"""

    def test_notify_result_success(self, mock_aws_clients, mock_context):
        """SNS 通知成功のテスト"""
        from lambda_handler import notify_result
        
        mock_aws_clients['sns'].publish.return_value = {'MessageId': 'msg-123'}
        
        agent_response = {'investigation': 'completed'}
        result = notify_result(agent_response)
        
        assert result is not None

    def test_notify_result_error(self, mock_aws_clients, mock_context):
        """SNS 通知エラーのテスト"""
        from lambda_handler import notify_result
        
        mock_aws_clients['sns'].publish.side_effect = Exception("SNS Error")
        
        agent_response = {'investigation': 'completed'}
        
        with pytest.raises(Exception):
            notify_result(agent_response)

    def test_get_log_groups_by_prefix(self, mock_aws_clients, mock_context):
        """ログループ取得のテスト"""
        from lambda_handler import get_log_groups_by_prefix
        
        mock_aws_clients['logs'].describe_log_groups.return_value = {
            'logGroups': [
                {'logGroupName': '/aws/lambda/test-1'},
                {'logGroupName': '/aws/lambda/test-2'}
            ]
        }
        
        result = get_log_groups_by_prefix('/aws/lambda/test')
        
        assert result is not None
        assert len(result) > 0

    def test_search_logs(self, mock_aws_clients, mock_context):
        """ログ検索のテスト"""
        from lambda_handler import search_logs
        
        mock_aws_clients['logs'].filter_log_events.return_value = {
            'events': [
                {'message': 'ERROR: Test error'}
            ]
        }
        
        result = search_logs('/aws/lambda/test', 'ERROR')
        
        assert result is not None
        assert len(result) > 0

    def test_get_rds_metrics(self, mock_aws_clients, mock_context):
        """RDS メトリクス取得のテスト"""
        from lambda_handler import get_rds_metrics
        
        mock_aws_clients['cloudwatch'].get_metric_statistics.return_value = {
            'Datapoints': [
                {
                    'Timestamp': datetime.utcnow(),
                    'Average': 65.5
                }
            ]
        }
        
        result = get_rds_metrics('prod-db-1', 'CPUUtilization')
        
        assert result is not None

    def test_get_ec2_metrics(self, mock_aws_clients, mock_context):
        """EC2 メトリクス取得のテスト"""
        from lambda_handler import get_ec2_metrics
        
        mock_aws_clients['cloudwatch'].get_metric_statistics.return_value = {
            'Datapoints': [
                {
                    'Timestamp': datetime.utcnow(),
                    'Average': 45.2
                }
            ]
        }
        
        result = get_ec2_metrics('i-12345', 'CPUUtilization')
        
        assert result is not None

    def test_publish_sns_message(self, mock_aws_clients, mock_context):
        """SNS メッセージ発行のテスト"""
        from lambda_handler import publish_sns_message
        
        mock_aws_clients['sns'].publish.return_value = {'MessageId': 'msg-123'}
        
        result = publish_sns_message(
            topic_arn='arn:aws:sns:ap-northeast-1:123456789012:test-topic',
            message='Test message'
        )
        
        assert result is not None

    def test_backup_report_to_s3(self, mock_aws_clients, mock_context):
        """S3 バックアップのテスト"""
        from lambda_handler import backup_report_to_s3
        
        mock_aws_clients['s3'].put_object.return_value = {'ETag': '"abc123"'}
        
        with patch.dict(os.environ, {'S3_BUCKET': 'test-bucket'}):
            result = backup_report_to_s3('test-report', 'report-001')
            
            assert result is not None

    def test_put_metric_data(self, mock_aws_clients, mock_context):
        """CloudWatch メトリクス発行のテスト"""
        from lambda_handler import put_metric_data
        
        mock_aws_clients['cloudwatch'].put_metric_data.return_value = {}
        
        result = put_metric_data('TestMetric', 75.5)
        
        assert result is None or result == {}


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
