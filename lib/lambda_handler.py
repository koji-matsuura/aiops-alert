"""
AIOps Lambda Handler
統合版：FR‑01～FR‑06のすべての機能を実装
"""

import json
import os
import boto3
import logging
from datetime import datetime, timedelta
import time
from typing import Dict, List, Any, Optional

logger = logging.getLogger()
logger.setLevel(logging.INFO)

# AWS クライアント
logs_client = boto3.client('logs')
cloudwatch_client = boto3.client('cloudwatch')
sns_client = boto3.client('sns')
s3_client = boto3.client('s3')
rds_client = boto3.client('rds')
pi_client = boto3.client('pi')
ec2_client = boto3.client('ec2')

# 環境変数
SNS_LOG_INVESTIGATION_ARN = os.environ.get('SNS_LOG_INVESTIGATION_ARN', 'arn:aws:sns:ap-northeast-1:123456789012:LogInvestigationReport')
SNS_BOTTLENECK_ARN = os.environ.get('SNS_BOTTLENECK_ARN', 'arn:aws:sns:ap-northeast-1:123456789012:BottleneckReport')
SNS_SNAPSHOT_ARN = os.environ.get('SNS_SNAPSHOT_ARN', 'arn:aws:sns:ap-northeast-1:123456789012:SnapshotReport')
SNS_MAINTENANCE_ARN = os.environ.get('SNS_MAINTENANCE_ARN', 'arn:aws:sns:ap-northeast-1:123456789012:MaintenanceReport')
SNS_SLOW_QUERY_ARN = os.environ.get('SNS_SLOW_QUERY_ARN', 'arn:aws:sns:ap-northeast-1:123456789012:SlowQueryReport')
SNS_HIGH_LOAD_QUERY_ARN = os.environ.get('SNS_HIGH_LOAD_QUERY_ARN', 'arn:aws:sns:ap-northeast-1:123456789012:HighLoadQueryReport')
S3_BACKUP_BUCKET = os.environ.get('S3_BACKUP_BUCKET', 'aiops-backup')


def lambda_handler(event, context):
    """
    統合 Lambda ハンドラー
    event['action'] で機能を切り分け
    """
    try:
        action = event.get('action', 'log_investigation')
        logger.info(f"Executing action: {action}")

        if action == 'log_investigation':
            return handle_log_investigation(event)
        elif action == 'bottleneck_investigation':
            return handle_bottleneck_investigation(event)
        elif action == 'create_snapshot':
            return handle_create_snapshot(event)
        elif action == 'maintenance_display':
            return handle_maintenance_display(event)
        elif action == 'slow_query_detection':
            return handle_slow_query_detection(event)
        elif action == 'high_load_query_detection':
            return handle_high_load_query_detection(event)
        else:
            return {
                'statusCode': 400,
                'body': json.dumps({'error': f'Unknown action: {action}'})
            }

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


# ============================================================================
# FR‑01: ログ調査機能
# ============================================================================

def handle_log_investigation(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    CloudWatch Logs を検索し、エラーやセキュリティ異常を検出
    """
    try:
        log_group_prefix = event.get('log_group_prefix', '/aws/lambda/')
        time_range_seconds = event.get('time_range_seconds', 900)  # 15 min
        filter_pattern = event.get('filter_pattern', '?ERROR *')
        max_results = event.get('max_results', 1000)

        logger.info(f"Investigating logs for prefix: {log_group_prefix}")

        # ロググループ一覧を取得
        log_groups = get_log_groups_by_prefix(log_group_prefix)

        alerts = []
        for log_group in log_groups:
            group_alerts = search_logs(
                log_group_name=log_group,
                time_range_seconds=time_range_seconds,
                filter_pattern=filter_pattern,
                max_results=max_results
            )
            alerts.extend(group_alerts)

        # レポート生成
        report = {
            'type': 'logInvestigation',
            'runAt': datetime.utcnow().isoformat() + 'Z',
            'alertCount': len(alerts),
            'alerts': alerts[:50]  # 最大50件
        }

        # SNS に publish
        publish_sns_message(SNS_LOG_INVESTIGATION_ARN, report)

        # S3 にバックアップ
        backup_report_to_s3(f'logs/log-investigation/{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.json', report)

        # CloudWatch Metric 更新
        put_metric_data('LogErrors', len(alerts))

        return {
            'statusCode': 200,
            'body': json.dumps({'message': f'Found {len(alerts)} alerts', 'report': report})
        }

    except Exception as e:
        logger.error(f"Error in log investigation: {str(e)}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def get_log_groups_by_prefix(prefix: str) -> List[str]:
    """ロググループをプレフィックスで取得"""
    try:
        response = logs_client.describe_log_groups(
            logGroupNamePrefix=prefix,
            limit=50
        )
        return [lg['logGroupName'] for lg in response.get('logGroups', [])]
    except Exception as e:
        logger.error(f"Error getting log groups: {str(e)}")
        return []


def search_logs(log_group_name: str, time_range_seconds: int, 
                filter_pattern: str, max_results: int) -> List[Dict[str, Any]]:
    """ロググループをフィルタリングして検索"""
    try:
        end_time = int(time.time() * 1000)
        start_time = end_time - (time_range_seconds * 1000)

        response = logs_client.filter_log_events(
            logGroupName=log_group_name,
            startTime=start_time,
            endTime=end_time,
            filterPattern=filter_pattern,
            limit=max_results
        )

        alerts = []
        for event in response.get('events', []):
            message = event.get('message', '')
            alerts.append({
                'level': 'ERROR',
                'message': message[:500],  # 最初の500文字
                'timestamp': datetime.fromtimestamp(event['timestamp'] / 1000).isoformat() + 'Z',
                'logGroup': log_group_name,
                'logStream': event.get('logStreamName'),
                'eventId': event.get('eventId')
            })

        return alerts
    except Exception as e:
        logger.error(f"Error searching logs in {log_group_name}: {str(e)}")
        return []


# ============================================================================
# FR‑02: ボトルネック調査機能
# ============================================================================

def handle_bottleneck_investigation(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    CloudWatch Metrics を取得しボトルネックを検出
    """
    try:
        time_range_seconds = event.get('time_range_seconds', 900)
        thresholds = event.get('thresholds', {'CPUUtilization': 90, 'FreeStorageSpace': 100000})
        resource_arns = event.get('resource_arns', [])

        logger.info(f"Investigating bottlenecks for {len(resource_arns)} resources")

        bottlenecks = []

        # RDS メトリクス取得
        for arn in resource_arns:
            if 'rds' in arn.lower():
                db_metrics = get_rds_metrics(arn, time_range_seconds, thresholds)
                bottlenecks.extend(db_metrics)

        # EC2 メトリクス取得
        for arn in resource_arns:
            if 'ec2' in arn.lower():
                ec2_metrics = get_ec2_metrics(arn, time_range_seconds, thresholds)
                bottlenecks.extend(ec2_metrics)

        # レポート生成
        report = {
            'type': 'bottleneckInvestigation',
            'runAt': datetime.utcnow().isoformat() + 'Z',
            'bottleneckCount': len(bottlenecks),
            'bottlenecks': bottlenecks
        }

        # SNS に publish
        publish_sns_message(SNS_BOTTLENECK_ARN, report)

        # S3 にバックアップ
        backup_report_to_s3(f'bottleneck/{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.json', report)

        return {
            'statusCode': 200,
            'body': json.dumps({'message': f'Found {len(bottlenecks)} bottlenecks', 'report': report})
        }

    except Exception as e:
        logger.error(f"Error in bottleneck investigation: {str(e)}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


def get_rds_metrics(arn: str, time_range_seconds: int, thresholds: Dict) -> List[Dict[str, Any]]:
    """RDS のメトリクスを取得"""
    try:
        db_instance_id = arn.split(':')[-1]
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(seconds=time_range_seconds)

        bottlenecks = []

        # CPU メトリクス
        cpu_response = cloudwatch_client.get_metric_statistics(
            Namespace='AWS/RDS',
            MetricName='CPUUtilization',
            Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=60,
            Statistics=['Average']
        )

        for dp in cpu_response.get('Datapoints', []):
            if dp['Average'] > thresholds.get('CPUUtilization', 90):
                bottlenecks.append({
                    'resourceArn': arn,
                    'resourceType': 'RDS',
                    'metricName': 'CPUUtilization',
                    'metricValue': dp['Average'],
                    'threshold': thresholds.get('CPUUtilization', 90),
                    'timestamp': dp['Timestamp'].isoformat() + 'Z',
                    'recommendation': 'スケールアップまたはスケールアウトを検討してください'
                })

        return bottlenecks
    except Exception as e:
        logger.error(f"Error getting RDS metrics: {str(e)}")
        return []


def get_ec2_metrics(arn: str, time_range_seconds: int, thresholds: Dict) -> List[Dict[str, Any]]:
    """EC2 のメトリクスを取得"""
    try:
        instance_id = arn.split('/')[-1]
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(seconds=time_range_seconds)

        bottlenecks = []

        # CPU メトリクス
        cpu_response = cloudwatch_client.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='CPUUtilization',
            Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=60,
            Statistics=['Average']
        )

        for dp in cpu_response.get('Datapoints', []):
            if dp['Average'] > thresholds.get('CPUUtilization', 90):
                bottlenecks.append({
                    'resourceArn': arn,
                    'resourceType': 'EC2',
                    'metricName': 'CPUUtilization',
                    'metricValue': dp['Average'],
                    'threshold': thresholds.get('CPUUtilization', 90),
                    'timestamp': dp['Timestamp'].isoformat() + 'Z',
                    'recommendation': 'インスタンスサイズのアップグレードを検討してください'
                })

        return bottlenecks
    except Exception as e:
        logger.error(f"Error getting EC2 metrics: {str(e)}")
        return []


# ============================================================================
# FR‑03: DBスナップショット作成機能
# ============================================================================

def handle_create_snapshot(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    RDS インスタンスのスナップショットを作成
    """
    try:
        db_instance_id = event.get('db_instance_identifier')
        if not db_instance_id:
            return {'statusCode': 400, 'body': json.dumps({'error': 'db_instance_identifier required'})}

        snapshot_id = event.get('snapshot_id')
        if not snapshot_id:
            snapshot_id = f"snap-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{db_instance_id}"

        tags = event.get('tags', {})

        logger.info(f"Creating snapshot {snapshot_id} for {db_instance_id}")

        # スナップショット作成
        response = rds_client.create_db_snapshot(
            DBSnapshotIdentifier=snapshot_id,
            DBInstanceIdentifier=db_instance_id,
            Tags=[{'Key': k, 'Value': v} for k, v in tags.items()]
        )

        snapshot_arn = response['DBSnapshot']['DBSnapshotArn']

        report = {
            'type': 'snapshotCreated',
            'runAt': datetime.utcnow().isoformat() + 'Z',
            'snapshotId': snapshot_id,
            'snapshotArn': snapshot_arn,
            'dbInstanceId': db_instance_id,
            'status': 'creating'
        }

        # SNS に publish
        publish_sns_message(SNS_SNAPSHOT_ARN, report)

        return {
            'statusCode': 200,
            'body': json.dumps({'message': f'Snapshot {snapshot_id} creation started', 'report': report})
        }

    except Exception as e:
        logger.error(f"Error creating snapshot: {str(e)}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


# ============================================================================
# FR‑04: メンテナンスウィンドウ表示機能
# ============================================================================

def handle_maintenance_display(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    RDS のメンテナンスウィンドウ情報を取得・表示
    """
    try:
        service_name = event.get('service_name', 'RDS')
        resource_arn = event.get('resource_arn')

        logger.info(f"Getting maintenance window for {service_name}")

        maintenance_info = {}

        if service_name == 'RDS':
            db_instance_id = resource_arn.split(':')[-1]
            response = rds_client.describe_db_instances(
                DBInstanceIdentifier=db_instance_id
            )

            db_instance = response['DBInstances'][0]
            maintenance_info = {
                'dbInstanceId': db_instance_id,
                'preferredMaintenanceWindow': db_instance.get('PreferredMaintenanceWindow'),
                'latestRestorableTime': db_instance.get('LatestRestorableTime').isoformat() if db_instance.get('LatestRestorableTime') else None,
                'pendingModifiedValues': db_instance.get('PendingModifiedValues', {})
            }

        report = {
            'type': 'maintenanceDisplay',
            'runAt': datetime.utcnow().isoformat() + 'Z',
            'serviceName': service_name,
            'maintenanceInfo': maintenance_info
        }

        # SNS に publish
        publish_sns_message(SNS_MAINTENANCE_ARN, report)

        return {
            'statusCode': 200,
            'body': json.dumps({'message': 'Maintenance window retrieved', 'report': report})
        }

    except Exception as e:
        logger.error(f"Error getting maintenance window: {str(e)}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


# ============================================================================
# FR‑05: 遅いクエリ検出機能
# ============================================================================

def handle_slow_query_detection(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    RDS Performance Insights から遅いクエリを検出
    """
    try:
        duration_seconds = event.get('duration', 86400)  # 24h
        max_results = event.get('max_results', 100)
        slow_query_threshold_ms = event.get('slow_query_threshold_ms', 2000)
        db_resource_id = event.get('db_resource_id')

        if not db_resource_id:
            return {'statusCode': 400, 'body': json.dumps({'error': 'db_resource_id required'})}

        logger.info(f"Detecting slow queries for {db_resource_id}")

        # Performance Insights API で遅いクエリを取得
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(seconds=duration_seconds)

        response = pi_client.get_resource_metrics(
            ServiceType='RDS',
            Identifier=db_resource_id,
            MetricQueries=[
                {'Metric': 'db.load.avg'},
                {'Metric': 'db.sql_tokenized.db.load.avg'}
            ],
            PeriodInSeconds=60,
            StartTime=start_time,
            EndTime=end_time,
            MaxResults=max_results
        )

        slow_queries = []
        for metric_record in response.get('MetricList', []):
            for data_point in metric_record.get('DataPoints', []):
                if data_point.get('Value', 0) > (slow_query_threshold_ms / 1000):
                    slow_queries.append({
                        'metric': metric_record.get('Key', {}).get('Metric'),
                        'value': data_point.get('Value'),
                        'timestamp': data_point.get('Timestamp').isoformat() if data_point.get('Timestamp') else None
                    })

        report = {
            'type': 'slowQueryDetection',
            'runAt': datetime.utcnow().isoformat() + 'Z',
            'dbResourceId': db_resource_id,
            'slowQueryCount': len(slow_queries),
            'slowQueries': slow_queries[:50]
        }

        # SNS に publish
        publish_sns_message(SNS_SLOW_QUERY_ARN, report)

        # S3 にバックアップ
        backup_report_to_s3(f'slow-queries/{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.json', report)

        return {
            'statusCode': 200,
            'body': json.dumps({'message': f'Found {len(slow_queries)} slow queries', 'report': report})
        }

    except Exception as e:
        logger.error(f"Error detecting slow queries: {str(e)}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


# ============================================================================
# FR‑06: 高負荷クエリ分析機能
# ============================================================================

def handle_high_load_query_detection(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    RDS Performance Insights から高負荷クエリを検出
    """
    try:
        duration_seconds = event.get('duration', 86400)  # 24h
        threshold_percent = event.get('threshold_percent', 90.0)
        metrics = event.get('metrics', ['CPUUtilization', 'DiskIOPS', 'NetworkTransmitThroughput'])
        db_resource_id = event.get('db_resource_id')

        if not db_resource_id:
            return {'statusCode': 400, 'body': json.dumps({'error': 'db_resource_id required'})}

        logger.info(f"Detecting high-load queries for {db_resource_id}")

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(seconds=duration_seconds)

        high_load_queries = []

        for metric_name in metrics:
            try:
                response = pi_client.get_resource_metrics(
                    ServiceType='RDS',
                    Identifier=db_resource_id,
                    MetricQueries=[{'Metric': metric_name}],
                    PeriodInSeconds=60,
                    StartTime=start_time,
                    EndTime=end_time,
                    MaxResults=100
                )

                for metric_record in response.get('MetricList', []):
                    for data_point in metric_record.get('DataPoints', []):
                        value = data_point.get('Value', 0)
                        # 値がパーセンテージの場合、しきい値と比較
                        if value >= threshold_percent:
                            high_load_queries.append({
                                'metric': metric_name,
                                'value': value,
                                'threshold': threshold_percent,
                                'timestamp': data_point.get('Timestamp').isoformat() if data_point.get('Timestamp') else None
                            })
            except Exception as e:
                logger.warning(f"Error getting metric {metric_name}: {str(e)}")

        report = {
            'type': 'highLoadQueryDetection',
            'runAt': datetime.utcnow().isoformat() + 'Z',
            'dbResourceId': db_resource_id,
            'threshold': threshold_percent,
            'highLoadQueryCount': len(high_load_queries),
            'highLoadQueries': high_load_queries[:100]
        }

        # SNS に publish
        publish_sns_message(SNS_HIGH_LOAD_QUERY_ARN, report)

        # S3 にバックアップ
        backup_report_to_s3(f'high-load-queries/{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.json', report)

        return {
            'statusCode': 200,
            'body': json.dumps({'message': f'Found {len(high_load_queries)} high-load queries', 'report': report})
        }

    except Exception as e:
        logger.error(f"Error detecting high-load queries: {str(e)}")
        return {'statusCode': 500, 'body': json.dumps({'error': str(e)})}


# ============================================================================
# ユーティリティ関数
# ============================================================================

def publish_sns_message(topic_arn: str, message: Dict[str, Any]) -> bool:
    """SNS メッセージを発行"""
    try:
        sns_client.publish(
            TopicArn=topic_arn,
            Subject=f"AIOps Alert: {message.get('type', 'unknown')}",
            Message=json.dumps(message, default=str, indent=2)
        )
        logger.info(f"Published message to {topic_arn}")
        return True
    except Exception as e:
        logger.error(f"Error publishing to SNS: {str(e)}")
        return False


def backup_report_to_s3(key: str, report: Dict[str, Any]) -> bool:
    """レポートを S3 にバックアップ"""
    try:
        s3_client.put_object(
            Bucket=S3_BACKUP_BUCKET,
            Key=key,
            Body=json.dumps(report, default=str, indent=2),
            ContentType='application/json',
            ServerSideEncryption='AES256'
        )
        logger.info(f"Backed up report to s3://{S3_BACKUP_BUCKET}/{key}")
        return True
    except Exception as e:
        logger.error(f"Error backing up to S3: {str(e)}")
        return False


def put_metric_data(metric_name: str, value: float) -> bool:
    """CloudWatch にメトリクスデータを送信"""
    try:
        cloudwatch_client.put_metric_data(
            Namespace='AIOps',
            MetricData=[
                {
                    'MetricName': metric_name,
                    'Value': value,
                    'Unit': 'Count',
                    'Timestamp': datetime.utcnow()
                }
            ]
        )
        logger.info(f"Put metric {metric_name} = {value}")
        return True
    except Exception as e:
        logger.error(f"Error putting metric: {str(e)}")
        return False
