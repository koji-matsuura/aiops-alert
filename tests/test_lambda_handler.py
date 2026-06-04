"""
Lambda ハンドラのテストコード
各機能（FR‑01～FR‑06）のテストケースを含む
"""

import json
import pytest
from unittest.mock import Mock, patch, MagicMock
import sys
import os

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
         patch('lambda_handler.ec2_client') as mock_ec2:
        
        yield {
            'logs': mock_logs,
            'cloudwatch': mock_cloudwatch,
            'sns': mock_sns,
            's3': mock_s3,
            'rds': mock_rds,
            'pi': mock_pi,
            'ec2': mock_ec2
        }


class TestFR01LogInvestigation:
    """FR‑01: ログ調査機能のテスト"""

    def test_log_investigation_basic(self, mock_aws_clients):
        """基本的なログ調査のテスト"""
        from lambda_handler import lambda_handler

        event = {
            'action': 'log_investigation',
            'log_group_prefix': '/aws/lambda/',
            'time_range_seconds': 900,
            'filter_pattern': '?ERROR *',
            'max_results': 100
        }

        # Mock のセットアップ
        mock_aws_clients['logs'].describe_log_groups.return_value = {
            'logGroups': [
                {'logGroupName': '/aws/lambda/function1'},
                {'logGroupName': '/aws/lambda/function2'}
            ]
        }

        mock_aws_clients['logs'].filter_log_events.return_value = {
            'events': [
                {
                    'timestamp': 1717000000000,
                    'message': 'ERROR: NullPointerException',
                    'logStreamName': 'stream1',
                    'eventId': 'evt1'
                }
            ]
        }

        result = lambda_handler(event, None)

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert 'report' in body


class TestFR02BottleneckInvestigation:
    """FR‑02: ボトルネック調査機能のテスト"""

    def test_bottleneck_investigation_basic(self, mock_aws_clients):
        """基本的なボトルネック調査のテスト"""
        from lambda_handler import lambda_handler

        event = {
            'action': 'bottleneck_investigation',
            'time_range_seconds': 900,
            'thresholds': {'CPUUtilization': 90},
            'resource_arns': [
                'arn:aws:rds:ap-northeast-1:123456789012:db:mydb'
            ]
        }

        # Mock のセットアップ
        mock_aws_clients['cloudwatch'].get_metric_statistics.return_value = {
            'Datapoints': [
                {
                    'Average': 95.0,
                    'Timestamp': MagicMock()
                }
            ]
        }

        result = lambda_handler(event, None)

        assert result['statusCode'] == 200


class TestFR03CreateSnapshot:
    """FR‑03: DBスナップショット作成機能のテスト"""

    def test_create_snapshot_basic(self, mock_aws_clients):
        """基本的なスナップショット作成のテスト"""
        from lambda_handler import lambda_handler

        event = {
            'action': 'create_snapshot',
            'db_instance_identifier': 'mydb',
            'tags': {'IncidentId': 'INC-001'}
        }

        # Mock のセットアップ
        mock_aws_clients['rds'].create_db_snapshot.return_value = {
            'DBSnapshot': {
                'DBSnapshotArn': 'arn:aws:rds:ap-northeast-1:123456789012:snapshot:snap-001',
                'DBSnapshotIdentifier': 'snap-001'
            }
        }

        result = lambda_handler(event, None)

        assert result['statusCode'] == 200
        body = json.loads(result['body'])
        assert 'report' in body

    def test_create_snapshot_missing_db_id(self, mock_aws_clients):
        """DBインスタンス ID なしのテスト"""
        from lambda_handler import lambda_handler

        event = {
            'action': 'create_snapshot'
        }

        result = lambda_handler(event, None)

        assert result['statusCode'] == 400


class TestFR04MaintenanceDisplay:
    """FR‑04: メンテナンスウィンドウ表示機能のテスト"""

    def test_maintenance_display_basic(self, mock_aws_clients):
        """基本的なメンテナンスウィンドウ取得のテスト"""
        from lambda_handler import lambda_handler
        from datetime import datetime

        event = {
            'action': 'maintenance_display',
            'service_name': 'RDS',
            'resource_arn': 'arn:aws:rds:ap-northeast-1:123456789012:db:mydb'
        }

        # Mock のセットアップ
        mock_aws_clients['rds'].describe_db_instances.return_value = {
            'DBInstances': [
                {
                    'DBInstanceIdentifier': 'mydb',
                    'PreferredMaintenanceWindow': 'sun:00:00-sun:03:00',
                    'LatestRestorableTime': datetime.utcnow(),
                    'PendingModifiedValues': {}
                }
            ]
        }

        result = lambda_handler(event, None)

        assert result['statusCode'] == 200


class TestFR05SlowQueryDetection:
    """FR‑05: 遅いクエリ検出機能のテスト"""

    def test_slow_query_detection_basic(self, mock_aws_clients):
        """基本的な遅いクエリ検出のテスト"""
        from lambda_handler import lambda_handler
        from datetime import datetime

        event = {
            'action': 'slow_query_detection',
            'db_resource_id': 'db-ABCDEFGHIJKLMNOP',
            'duration': 86400,
            'slow_query_threshold_ms': 2000
        }

        # Mock のセットアップ
        mock_aws_clients['pi'].get_resource_metrics.return_value = {
            'MetricList': [
                {
                    'Key': {'Metric': 'db.load.avg'},
                    'DataPoints': [
                        {
                            'Value': 2.5,
                            'Timestamp': datetime.utcnow()
                        }
                    ]
                }
            ]
        }

        result = lambda_handler(event, None)

        assert result['statusCode'] == 200


class TestFR06HighLoadQueryDetection:
    """FR‑06: 高負荷クエリ分析機能のテスト"""

    def test_high_load_query_detection_basic(self, mock_aws_clients):
        """基本的な高負荷クエリ検出のテスト"""
        from lambda_handler import lambda_handler
        from datetime import datetime

        event = {
            'action': 'high_load_query_detection',
            'db_resource_id': 'db-ABCDEFGHIJKLMNOP',
            'duration': 86400,
            'threshold_percent': 90.0,
            'metrics': ['CPUUtilization', 'DiskIOPS']
        }

        # Mock のセットアップ
        mock_aws_clients['pi'].get_resource_metrics.return_value = {
            'MetricList': [
                {
                    'Key': {'Metric': 'CPUUtilization'},
                    'DataPoints': [
                        {
                            'Value': 95.0,
                            'Timestamp': datetime.utcnow()
                        }
                    ]
                }
            ]
        }

        result = lambda_handler(event, None)

        assert result['statusCode'] == 200


class TestErrorHandling:
    """エラーハンドリングのテスト"""

    def test_unknown_action(self, mock_aws_clients):
        """未知のアクションのテスト"""
        from lambda_handler import lambda_handler

        event = {
            'action': 'unknown_action'
        }

        result = lambda_handler(event, None)

        assert result['statusCode'] == 400

    def test_exception_handling(self, mock_aws_clients):
        """例外処理のテスト"""
        from lambda_handler import lambda_handler

        mock_aws_clients['logs'].describe_log_groups.side_effect = Exception("API Error")

        event = {
            'action': 'log_investigation'
        }

        result = lambda_handler(event, None)

        assert result['statusCode'] == 500


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
