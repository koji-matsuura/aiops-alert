"""
FR-01～FR-06 実装検証テスト

moto v5.0+ を使用した AWS API 呼び出し検証
参照: https://docs.getmoto.org/
"""

import unittest
import sys
import os
from datetime import datetime, timedelta
from unittest.mock import patch, MagicMock
import json

# Add lib directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'lib'))

from moto import mock_aws
import boto3


class TestFR01LogInvestigation(unittest.TestCase):
    """FR-01: ログ調査 - CloudWatch Logs API 検証"""
    
    @mock_aws
    def test_fr01_get_log_events_api_call(self):
        """FR-01: get_log_events API 呼び出し検証
        
        AWS 仕様準拠テスト:
        - 参照: https://docs.aws.amazon.com/AmazonCloudWatchLogs/latest/APIReference/API_GetLogEvents.html
        - moto v5.2.2 で get_log_events AWS 準拠動作確認済み
        - テスト時刻とイベント投入時刻を同期する必要がある
        """
        # Import after mock is applied
        from lambda_handler import log_investigation_fr01
        import time
        
        # CloudWatch Logs クライアント初期化
        logs_client = boto3.client('logs', region_name='ap-northeast-1')
        
        # テスト用ログ グループ・ストリーム作成
        log_group = '/aws/lambda/test-function'
        log_stream = 'latest'
        
        logs_client.create_log_group(logGroupName=log_group)
        logs_client.create_log_stream(logGroupName=log_group, logStreamName=log_stream)
        
        # AWS 仕様: get_log_events のタイムスタンプはミリ秒（重要）
        # テスト時刻とイベント投入時刻を同期する（双方が同じ time.time() を使用）
        now_ms = int(time.time() * 1000)
        
        logs_client.put_log_events(
            logGroupName=log_group,
            logStreamName=log_stream,
            logEvents=[
                {
                    'timestamp': now_ms - 300000,  # 5 分前
                    'message': 'INFO: Application started'
                },
                {
                    'timestamp': now_ms - 240000,  # 4 分前
                    'message': 'ERROR: Database connection failed'
                },
                {
                    'timestamp': now_ms - 180000,  # 3 分前
                    'message': 'Exception: Timeout occurred'
                },
                {
                    'timestamp': now_ms,  # 現在
                    'message': 'INFO: Application running'
                }
            ]
        )
        
        # FR-01 実行
        # 実装内で time.time() * 1000 を使用するため、テスト側でも同じロジックを再現
        result = log_investigation_fr01(
            log_group_name=log_group,
            log_stream_name=log_stream,
            time_range_seconds=3600
        )
        
        # 検証
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['function'], 'FR-01')
        self.assertEqual(result['log_group'], log_group)
        self.assertEqual(result['log_stream'], log_stream)
        self.assertGreaterEqual(result['total_events'], 3)
        self.assertGreaterEqual(result['error_events'], 2)  # ERROR と Exception
        self.assertGreater(len(result['errors_sample']), 0)
        
        print(f"✅ FR-01 test passed: {result['error_events']} errors detected")
    
    @mock_aws
    def test_fr01_resource_not_found(self):
        """FR-01: ログ グループが存在しない場合のエラーハンドリング"""
        from lambda_handler import log_investigation_fr01
        
        result = log_investigation_fr01(
            log_group_name='/non/existent/group',
            log_stream_name='latest',
            time_range_seconds=3600
        )
        
        self.assertEqual(result['status'], 'error')
        self.assertIn('error', result)
        print(f"✅ FR-01 error handling test passed: {result['error']}")


class TestFR02BottleneckInvestigation(unittest.TestCase):
    """FR-02: ボトルネック調査 - CloudWatch メトリクス検証"""
    
    @mock_aws
    def test_fr02_get_metric_statistics_api_call(self):
        """FR-02: get_metric_statistics API 呼び出し検証"""
        from lambda_handler import bottleneck_investigation_fr02, get_rds_metrics
        
        # CloudWatch クライアント初期化
        cw_client = boto3.client('cloudwatch', region_name='ap-northeast-1')
        
        # テスト用 RDS インスタンス作成（moto）
        rds_client = boto3.client('rds', region_name='ap-northeast-1')
        rds_client.create_db_instance(
            DBInstanceIdentifier='test-db-instance',
            DBInstanceClass='db.t3.micro',
            Engine='mysql',
            MasterUsername='admin',
            MasterUserPassword='password123',
            AllocatedStorage=20
        )
        
        # テスト用メトリクス データ投入
        now = datetime.utcnow()
        cw_client.put_metric_data(
            Namespace='AWS/RDS',
            MetricData=[
                {
                    'MetricName': 'CPUUtilization',
                    'Value': 85.5,
                    'Timestamp': now - timedelta(minutes=5),
                    'Dimensions': [{'Name': 'DBInstanceIdentifier', 'Value': 'test-db-instance'}]
                },
                {
                    'MetricName': 'DatabaseConnections',
                    'Value': 150,
                    'Timestamp': now - timedelta(minutes=4),
                    'Dimensions': [{'Name': 'DBInstanceIdentifier', 'Value': 'test-db-instance'}]
                }
            ]
        )
        
        # FR-02 実行
        result = bottleneck_investigation_fr02(
            db_instance_id='test-db-instance',
            time_range_seconds=3600,
            thresholds={'cpu_percent': 80, 'connections': 100}
        )
        
        # 検証
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['function'], 'FR-02')
        self.assertGreater(result['bottleneck_count'], 0)
        
        print(f"✅ FR-02 test passed: {result['bottleneck_count']} bottlenecks detected")


class TestFR03CreateSnapshot(unittest.TestCase):
    """FR-03: DB スナップショット作成 - RDS API 検証"""
    
    @mock_aws
    def test_fr03_create_db_snapshot_api_call(self):
        """FR-03: create_db_snapshot API 呼び出し検証"""
        from lambda_handler import create_db_snapshot_fr03
        
        # RDS クライアント初期化
        rds_client = boto3.client('rds', region_name='ap-northeast-1')
        
        # テスト用 RDS インスタンス作成
        rds_client.create_db_instance(
            DBInstanceIdentifier='test-db-prod',
            DBInstanceClass='db.t3.micro',
            Engine='mysql',
            MasterUsername='admin',
            MasterUserPassword='password123',
            AllocatedStorage=20
        )
        
        # FR-03 実行
        result = create_db_snapshot_fr03(
            db_instance_id='test-db-prod',
            snapshot_id='snapshot-test-001'
        )
        
        # 検証
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['function'], 'FR-03')
        self.assertEqual(result['snapshot_id'], 'snapshot-test-001')
        self.assertEqual(result['db_instance_id'], 'test-db-prod')
        self.assertIn('snapshot_status', result)
        
        print(f"✅ FR-03 test passed: Snapshot {result['snapshot_id']} created")
    
    @mock_aws
    def test_fr03_db_instance_not_found(self):
        """FR-03: DB インスタンスが存在しない場合のエラーハンドリング"""
        from lambda_handler import create_db_snapshot_fr03
        
        result = create_db_snapshot_fr03(
            db_instance_id='non-existent-db',
            snapshot_id='snapshot-test'
        )
        
        self.assertEqual(result['status'], 'error')
        self.assertIn('error', result)
        print(f"✅ FR-03 error handling test passed: {result['error']}")


class TestFR04MaintenanceWindow(unittest.TestCase):
    """FR-04: メンテナンスウィンドウ表示 - RDS API 検証"""
    
    @mock_aws
    def test_fr04_describe_db_instances_api_call(self):
        """FR-04: describe_db_instances + describe_pending_maintenance_actions API 呼び出し検証
        
        AWS 仕様準拠テスト:
        - describe_db_instances: moto で実装済み
        - describe_pending_maintenance_actions: moto 未実装 → patch + MagicMock で補う
        
        参照:
        - https://docs.aws.amazon.com/AmazonRDS/latest/APIReference/API_DescribeDBInstances.html
        - https://docs.aws.amazon.com/AmazonRDS/latest/APIReference/API_DescribePendingMaintenanceActions.html
        """
        from unittest.mock import patch, MagicMock
        from lambda_handler import maintenance_window_display_fr04
        
        # RDS クライアント初期化
        rds_client = boto3.client('rds', region_name='ap-northeast-1')
        
        # テスト用 RDS インスタンス作成
        rds_client.create_db_instance(
            DBInstanceIdentifier='test-db-maint',
            DBInstanceClass='db.t3.micro',
            Engine='mysql',
            MasterUsername='admin',
            MasterUserPassword='password123',
            AllocatedStorage=20,
            PreferredMaintenanceWindow='sun:03:00-sun:04:00',
            BackupRetentionPeriod=7
        )
        
        # describe_pending_maintenance_actions をモック
        # AWS 公式 API 仕様に基づく戻り値構造
        with patch('lambda_handler.rds_client.describe_pending_maintenance_actions') as mock_pending:
            mock_pending.return_value = {
                'PendingMaintenanceActions': [
                    {
                        'ResourceIdentifier': 'arn:aws:rds:ap-northeast-1:123456789012:db:test-db-maint',
                        'PendingMaintenanceActionDetails': [
                            {
                                'Action': 'system-update',
                                'AutoAppliedAfterDate': '2026-06-15T00:00:00Z',
                                'ForcedApplyDate': '2026-06-22T00:00:00Z',
                                'OptInStatus': 'next-maintenance',
                                'CurrentApplyScheduledTime': '2026-06-15T01:00:00Z'
                            }
                        ]
                    }
                ]
            }
            
            # FR-04 実行
            result = maintenance_window_display_fr04(
                db_instance_id='test-db-maint'
            )
        
        # 検証
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['function'], 'FR-04')
        self.assertEqual(result['db_instance_id'], 'test-db-maint')
        self.assertEqual(result['preferred_maintenance_window'], 'sun:03:00-sun:04:00')
        self.assertEqual(result['backup_retention_period'], 7)
        self.assertIsInstance(result['pending_maintenance_actions'], list)
        self.assertGreater(len(result['pending_maintenance_actions']), 0)
        self.assertEqual(result['pending_maintenance_actions'][0]['action'], 'system-update')
        
        print(f"✅ FR-04 test passed: Maintenance window + pending actions retrieved")


class TestFR05SlowQueryDetection(unittest.TestCase):
    """FR-05: スロークエリ検出 - Performance Insights API 検証"""
    
    @mock_aws
    def test_fr05_slow_query_detection_cloudwatch_logs_fallback(self):
        """FR-05: CloudWatch Logs フォールバック検証"""
        from lambda_handler import slow_query_detection_fr05
        
        # RDS クライアント初期化
        rds_client = boto3.client('rds', region_name='ap-northeast-1')
        
        # テスト用 RDS インスタンス作成
        response = rds_client.create_db_instance(
            DBInstanceIdentifier='test-db-slow',
            DBInstanceClass='db.t3.micro',
            Engine='mysql',
            MasterUsername='admin',
            MasterUserPassword='password123',
            AllocatedStorage=20
        )
        
        dbi_resource_id = response['DBInstance'].get('DbiResourceId', 'dbi-test-123456789')
        
        # FR-05 実行（Performance Insights 不可の場合、CloudWatch Logs にフォールバック）
        result = slow_query_detection_fr05(
            db_instance_id='test-db-slow',
            dbi_resource_id=dbi_resource_id,
            duration_seconds=3600
        )
        
        # 検証
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['function'], 'FR-05')
        self.assertEqual(result['db_instance_id'], 'test-db-slow')
        self.assertIsInstance(result['slow_queries_from_pi'], list)
        self.assertIsInstance(result['cloudwatch_slow_queries'], list)
        
        print(f"✅ FR-05 test passed: Slow query detection executed")


class TestFR06HighLoadQueryDetection(unittest.TestCase):
    """FR-06: 高負荷クエリ分析 - Performance Insights + CloudWatch API 検証"""
    
    @mock_aws
    def test_fr06_high_load_query_detection(self):
        """FR-06: get_resource_metrics + get_metric_statistics API 呼び出し検証"""
        from lambda_handler import high_load_query_detection_fr06
        
        # RDS クライアント初期化
        rds_client = boto3.client('rds', region_name='ap-northeast-1')
        
        # テスト用 RDS インスタンス作成
        response = rds_client.create_db_instance(
            DBInstanceIdentifier='test-db-load',
            DBInstanceClass='db.t3.micro',
            Engine='mysql',
            MasterUsername='admin',
            MasterUserPassword='password123',
            AllocatedStorage=20
        )
        
        dbi_resource_id = response['DBInstance'].get('DbiResourceId', 'dbi-test-987654321')
        
        # CloudWatch メトリクス投入
        cw_client = boto3.client('cloudwatch', region_name='ap-northeast-1')
        now = datetime.utcnow()
        cw_client.put_metric_data(
            Namespace='AWS/RDS',
            MetricData=[
                {
                    'MetricName': 'CPUUtilization',
                    'Value': 90.0,
                    'Timestamp': now - timedelta(minutes=5),
                    'Dimensions': [{'Name': 'DBInstanceIdentifier', 'Value': 'test-db-load'}]
                },
                {
                    'MetricName': 'ReadThroughput',
                    'Value': 1024000,  # 1MB/s
                    'Timestamp': now - timedelta(minutes=4),
                    'Dimensions': [{'Name': 'DBInstanceIdentifier', 'Value': 'test-db-load'}]
                }
            ]
        )
        
        # FR-06 実行
        result = high_load_query_detection_fr06(
            db_instance_id='test-db-load',
            dbi_resource_id=dbi_resource_id,
            duration_seconds=3600,
            high_load_threshold=2.0
        )
        
        # 検証
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['function'], 'FR-06')
        self.assertEqual(result['db_instance_id'], 'test-db-load')
        self.assertIsInstance(result['high_load_queries'], list)
        self.assertIsInstance(result['wait_events'], list)
        self.assertIn('resource_usage', result)
        
        print(f"✅ FR-06 test passed: High load query detection executed")


class TestFRIntegration(unittest.TestCase):
    """FR-01~FR-06 統合テスト with AWS 公式スキーマ準拠モック"""
    
    @mock_aws
    def test_all_fr_functions_integration(self):
        """全 FR 関数の統合テスト
        
        AWS 仕様準拠モック適用:
        - FR-04: describe_pending_maintenance_actions (AWS 公式スキーマ)
        - FR-05: GetResourceMetrics (AWS 公式スキーマ)
        - FR-06: GetResourceMetrics (AWS 公式スキーマ)
        
        参照:
        - https://docs.aws.amazon.com/AmazonRDS/latest/APIReference/API_DescribePendingMaintenanceActions.html
        - https://docs.aws.amazon.com/performance-insights/latest/APIReference/API_GetResourceMetrics.html
        """
        from lambda_handler import (
            log_investigation_fr01,
            bottleneck_investigation_fr02,
            create_db_snapshot_fr03,
            maintenance_window_display_fr04,
            slow_query_detection_fr05,
            high_load_query_detection_fr06
        )
        
        # 初期化
        logs_client = boto3.client('logs', region_name='ap-northeast-1')
        rds_client = boto3.client('rds', region_name='ap-northeast-1')
        cw_client = boto3.client('cloudwatch', region_name='ap-northeast-1')
        
        # テスト用リソース作成
        log_group = '/aws/lambda/integration-test'
        logs_client.create_log_group(logGroupName=log_group)
        logs_client.create_log_stream(logGroupName=log_group, logStreamName='latest')
        logs_client.put_log_events(
            logGroupName=log_group,
            logStreamName='latest',
            logEvents=[
                {
                    'timestamp': int(datetime.utcnow().timestamp() * 1000),
                    'message': 'ERROR: Test error message'
                }
            ]
        )
        
        db_response = rds_client.create_db_instance(
            DBInstanceIdentifier='integration-test-db',
            DBInstanceClass='db.t3.micro',
            Engine='mysql',
            MasterUsername='admin',
            MasterUserPassword='password123',
            AllocatedStorage=20,
            PreferredMaintenanceWindow='sun:03:00-sun:04:00'
        )
        
        dbi_resource_id = db_response['DBInstance'].get('DbiResourceId', 'dbi-integration-test')
        
        # AWS 仕様準拠モック適用
        with patch('lambda_handler.rds_client.describe_pending_maintenance_actions') as mock_pending, \
             patch('lambda_handler.pi_client.get_resource_metrics') as mock_pi_metrics:
            
            # FR-04: DescribePendingMaintenanceActions 戻り値（AWS 公式スキーマ準拠）
            # 参照: https://docs.aws.amazon.com/AmazonRDS/latest/APIReference/API_PendingMaintenanceAction.html
            mock_pending.return_value = {
                'PendingMaintenanceActions': [
                    {
                        'ResourceIdentifier': f'arn:aws:rds:ap-northeast-1:123456789012:db:integration-test-db',
                        'PendingMaintenanceActionDetails': [
                            {
                                'Action': 'system-update',
                                'AutoAppliedAfterDate': datetime.utcnow() + timedelta(days=1),
                                'ForcedApplyDate': datetime.utcnow() + timedelta(days=7),
                                'CurrentApplyDate': datetime.utcnow() + timedelta(days=1),
                                'Description': 'Test system update',
                                'OptInStatus': 'next-maintenance'
                            }
                        ]
                    }
                ]
            }
            
            # FR-05, FR-06: GetResourceMetrics 戻り値（AWS 公式スキーマ準拠）
            # 参照: https://docs.aws.amazon.com/performance-insights/latest/APIReference/API_MetricKeyDataPoints.html
            current_time = datetime.utcnow()
            mock_pi_metrics.return_value = {
                'AlignedStartTime': (current_time - timedelta(hours=1)).timestamp(),
                'AlignedEndTime': current_time.timestamp(),
                'Identifier': dbi_resource_id,
                'MetricList': [
                    {
                        'Key': {
                            'Metric': 'db.load.avg',
                            'Dimensions': {}
                        },
                        'DataPoints': [
                            {
                                'Timestamp': (current_time - timedelta(minutes=5)).timestamp(),
                                'Value': 2.5
                            },
                            {
                                'Timestamp': current_time.timestamp(),
                                'Value': 3.2
                            }
                        ]
                    }
                ]
            }
            
            # 各 FR 関数を順序通り実行
            results = {}
            
            results['FR-01'] = log_investigation_fr01(
                log_group_name=log_group,
                log_stream_name='latest',
                time_range_seconds=3600
            )
            
            results['FR-02'] = bottleneck_investigation_fr02(
                db_instance_id='integration-test-db',
                time_range_seconds=3600
            )
            
            results['FR-03'] = create_db_snapshot_fr03(
                db_instance_id='integration-test-db',
                snapshot_id='integration-snapshot'
            )
            
            results['FR-04'] = maintenance_window_display_fr04(
                db_instance_id='integration-test-db'
            )
            
            results['FR-05'] = slow_query_detection_fr05(
                db_instance_id='integration-test-db',
                dbi_resource_id=dbi_resource_id,
                duration_seconds=3600
            )
            
            results['FR-06'] = high_load_query_detection_fr06(
                db_instance_id='integration-test-db',
                dbi_resource_id=dbi_resource_id,
                duration_seconds=3600
            )
        
        # 全関数が成功したことを検証
        for fr, result in results.items():
            self.assertEqual(result['status'], 'success', f"{fr} failed: {result}")
            self.assertEqual(result['function'], fr)
            print(f"✅ {fr}: {result['function']} executed successfully")
        
        print(f"\n✅ Integration test passed: All FR functions executed successfully")


if __name__ == '__main__':
    unittest.main(verbosity=2)
