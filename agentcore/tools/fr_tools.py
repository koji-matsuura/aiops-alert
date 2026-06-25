"""
agentcore/tools/fr_tools.py - FR-01〜FR-06 AWS API 呼び出し関数

ソース: lib/lambda_handler.py 行1519-2198 から移行
各関数の AWS API 呼び出し実装はそのまま維持し、boto3 クライアントを本モジュールで管理する。
"""

import json
import logging
import time
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional

import boto3

logger = logging.getLogger(__name__)

# boto3 クライアント（boto3 >= 1.39.8 必須）
# ソース: lib/lambda_handler.py 行24-31
logs_client = boto3.client('logs')
cloudwatch_client = boto3.client('cloudwatch')
rds_client = boto3.client('rds')
pi_client = boto3.client('pi')
sns_client = boto3.client('sns')


# ============================================================================
# FR-01: ログ調査
# ソース: lib/lambda_handler.py 行1519-1589
# ============================================================================

def log_investigation_fr01(**kwargs) -> Dict[str, Any]:
    """
    FR-01: Log Investigation - CloudWatch Logs API 統合実装

    CloudWatch Logs から最近のエラーログを取得し、パターン分析を実施

    参照: https://docs.aws.amazon.com/boto3/latest/reference/services/logs/client/get_log_events.html
    """
    try:
        log_group_name = kwargs.get('log_group_name', '/aws/lambda/default')
        log_stream_name = kwargs.get('log_stream_name', 'latest')
        time_range_seconds = int(kwargs.get('time_range_seconds', 3600))

        logger.info(f"FR-01: Investigating logs from {log_group_name}/{log_stream_name}")

        end_time = int(time.time() * 1000)
        start_time = end_time - (time_range_seconds * 1000)

        response = logs_client.get_log_events(
            logGroupName=log_group_name,
            logStreamName=log_stream_name,
            startTime=start_time,
            endTime=end_time,
            limit=100,
            startFromHead=True,
        )

        events = response.get('events', [])
        error_logs = [
            event for event in events
            if 'ERROR' in event.get('message', '') or 'Exception' in event.get('message', '')
        ]

        result = {
            'status': 'success',
            'function': 'FR-01',
            'log_group': log_group_name,
            'log_stream': log_stream_name,
            'total_events': len(events),
            'error_events': len(error_logs),
            'errors_sample': [
                {
                    'timestamp': event.get('timestamp'),
                    'message': event.get('message', '')[:200],
                }
                for event in error_logs[:5]
            ],
            'investigation_period_seconds': time_range_seconds,
        }

        logger.info(f"FR-01 completed: {len(error_logs)} errors found")
        return result

    except logs_client.exceptions.ResourceNotFoundException as e:
        logger.error(f"FR-01: Log group or stream not found: {e}")
        return {'status': 'error', 'function': 'FR-01', 'error': f"Log resource not found: {e}"}
    except Exception as e:
        logger.error(f"FR-01: Exception occurred: {e}", exc_info=True)
        return {'status': 'error', 'function': 'FR-01', 'error': str(e)}


# ============================================================================
# FR-02: ボトルネック調査
# ソース: lib/lambda_handler.py 行1591-1656
# ============================================================================

def bottleneck_investigation_fr02(**kwargs) -> Dict[str, Any]:
    """
    FR-02: Bottleneck Investigation - CloudWatch メトリクス統合実装

    RDS / EC2 のボトルネックを特定（CPU、接続数、メモリ）

    参照: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/monitoring-cloudwatch.html
    """
    try:
        db_instance_id = kwargs.get('db_instance_id', '')
        ec2_instance_id = kwargs.get('ec2_instance_id', '')
        time_range_seconds = int(kwargs.get('time_range_seconds', 3600))
        thresholds = kwargs.get('thresholds', {'cpu_percent': 80, 'connections': 100, 'memory_percent': 85})

        logger.info(f"FR-02: Investigating bottlenecks for RDS={db_instance_id}, EC2={ec2_instance_id}")

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(seconds=time_range_seconds)
        bottlenecks = []

        if db_instance_id:
            rds_metrics = _get_rds_metrics(db_instance_id, start_time, end_time, thresholds)
            bottlenecks.extend(rds_metrics.get('bottlenecks', []))

        if ec2_instance_id:
            ec2_metrics = _get_ec2_metrics(ec2_instance_id, start_time, end_time, thresholds)
            bottlenecks.extend(ec2_metrics.get('bottlenecks', []))

        result = {
            'status': 'success',
            'function': 'FR-02',
            'investigation_period_seconds': time_range_seconds,
            'bottleneck_count': len(bottlenecks),
            'bottlenecks': bottlenecks,
            'critical': any(b.get('severity') == 'CRITICAL' for b in bottlenecks),
            'thresholds_used': thresholds,
        }

        logger.info(f"FR-02 completed: {len(bottlenecks)} bottlenecks identified")
        return result

    except Exception as e:
        logger.error(f"FR-02: Exception occurred: {e}", exc_info=True)
        return {'status': 'error', 'function': 'FR-02', 'error': str(e)}


def _get_rds_metrics(db_instance_id: str, start_time, end_time, thresholds: Dict) -> Dict[str, Any]:
    """RDS メトリクスを CloudWatch から取得。ソース: lib/lambda_handler.py 行1659-1716"""
    try:
        bottlenecks = []

        cpu_response = cloudwatch_client.get_metric_statistics(
            Namespace='AWS/RDS',
            MetricName='CPUUtilization',
            Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=['Average', 'Maximum'],
        )
        for point in cpu_response.get('Datapoints', []):
            max_cpu = point.get('Maximum', 0)
            if max_cpu > thresholds.get('cpu_percent', 80):
                bottlenecks.append({
                    'type': 'HIGH_CPU',
                    'value': round(max_cpu, 2),
                    'threshold': thresholds.get('cpu_percent'),
                    'timestamp': point.get('Timestamp'),
                    'severity': 'CRITICAL' if max_cpu > 95 else 'HIGH',
                })

        connections_response = cloudwatch_client.get_metric_statistics(
            Namespace='AWS/RDS',
            MetricName='DatabaseConnections',
            Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=['Average', 'Maximum'],
        )
        for point in connections_response.get('Datapoints', []):
            max_connections = point.get('Maximum', 0)
            if max_connections > thresholds.get('connections', 100):
                bottlenecks.append({
                    'type': 'HIGH_CONNECTIONS',
                    'value': int(max_connections),
                    'threshold': thresholds.get('connections'),
                    'timestamp': point.get('Timestamp'),
                    'severity': 'HIGH',
                })

        return {'bottlenecks': bottlenecks}
    except Exception as e:
        logger.error(f"get_rds_metrics error: {e}", exc_info=True)
        return {'bottlenecks': []}


def _get_ec2_metrics(instance_id: str, start_time, end_time, thresholds: Dict) -> Dict[str, Any]:
    """EC2 メトリクスを CloudWatch から取得。ソース: lib/lambda_handler.py 行1719-1750"""
    try:
        bottlenecks = []
        cpu_response = cloudwatch_client.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='CPUUtilization',
            Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=['Average', 'Maximum'],
        )
        for point in cpu_response.get('Datapoints', []):
            max_cpu = point.get('Maximum', 0)
            if max_cpu > thresholds.get('cpu_percent', 80):
                bottlenecks.append({
                    'type': 'EC2_HIGH_CPU',
                    'value': round(max_cpu, 2),
                    'threshold': thresholds.get('cpu_percent'),
                    'timestamp': point.get('Timestamp'),
                    'severity': 'CRITICAL' if max_cpu > 95 else 'HIGH',
                })
        return {'bottlenecks': bottlenecks}
    except Exception as e:
        logger.error(f"get_ec2_metrics error: {e}", exc_info=True)
        return {'bottlenecks': []}


# ============================================================================
# FR-03: DB スナップショット作成
# ソース: lib/lambda_handler.py 行1752-1823
# ============================================================================

def create_db_snapshot_fr03(**kwargs) -> Dict[str, Any]:
    """
    FR-03: Create DB Snapshot - RDS API 統合実装

    参照: https://docs.aws.amazon.com/boto3/latest/reference/services/rds/client/create_db_snapshot.html
    """
    try:
        db_instance_id = kwargs.get('db_instance_id', '')
        snapshot_id = kwargs.get('snapshot_id', f"snapshot-{int(time.time())}")

        if not db_instance_id:
            return {'status': 'error', 'function': 'FR-03', 'error': 'db_instance_id is required'}

        logger.info(f"FR-03: Creating snapshot {snapshot_id} for {db_instance_id}")

        response = rds_client.create_db_snapshot(
            DBSnapshotIdentifier=snapshot_id,
            DBInstanceIdentifier=db_instance_id,
            Tags=[
                {'Key': 'CreatedBy', 'Value': 'AIOps-AgentCore'},
                {'Key': 'CreatedAt', 'Value': datetime.utcnow().isoformat()},
            ],
        )

        db_snapshot = response.get('DBSnapshot', {})
        result = {
            'status': 'success',
            'function': 'FR-03',
            'snapshot_id': db_snapshot.get('DBSnapshotIdentifier'),
            'db_instance_id': db_snapshot.get('DBInstanceIdentifier'),
            'snapshot_status': db_snapshot.get('Status'),
            'engine': db_snapshot.get('Engine'),
            'snapshot_arn': db_snapshot.get('DBSnapshotArn'),
        }

        logger.info(f"FR-03 completed: Snapshot {snapshot_id} initiated")
        return result

    except rds_client.exceptions.DBInstanceNotFoundFault as e:
        return {'status': 'error', 'function': 'FR-03', 'error': f"DB instance not found: {e}"}
    except rds_client.exceptions.DBSnapshotAlreadyExistsFault as e:
        return {'status': 'error', 'function': 'FR-03', 'error': f"Snapshot already exists: {e}"}
    except Exception as e:
        logger.error(f"FR-03: Exception occurred: {e}", exc_info=True)
        return {'status': 'error', 'function': 'FR-03', 'error': str(e)}


# ============================================================================
# FR-04: メンテナンスウィンドウ表示
# ソース: lib/lambda_handler.py 行1825-1910
# ============================================================================

def maintenance_window_display_fr04(**kwargs) -> Dict[str, Any]:
    """
    FR-04: Maintenance Window Display - RDS API 統合実装

    参照: https://docs.aws.amazon.com/boto3/latest/reference/services/rds/client/describe_db_instances.html
    """
    try:
        db_instance_id = kwargs.get('db_instance_id', '')

        if not db_instance_id:
            return {'status': 'error', 'function': 'FR-04', 'error': 'db_instance_id is required'}

        logger.info(f"FR-04: Retrieving maintenance info for {db_instance_id}")

        instances_response = rds_client.describe_db_instances(DBInstanceIdentifier=db_instance_id)

        if not instances_response.get('DBInstances'):
            return {'status': 'error', 'function': 'FR-04', 'error': f"DB instance {db_instance_id} not found"}

        db_instance = instances_response['DBInstances'][0]

        pending_response = rds_client.describe_pending_maintenance_actions(
            ResourceIdentifier=db_instance.get('DBInstanceArn', '')
        )

        pending_actions = []
        for action_set in pending_response.get('PendingMaintenanceActions', []):
            for action in action_set.get('PendingMaintenanceActionDetails', []):
                pending_actions.append({
                    'action': action.get('Action', ''),
                    'auto_applied_after': str(action.get('AutoAppliedAfterDate', '')),
                    'forced_apply_date': str(action.get('ForcedApplyDate', '')),
                    'opt_in_status': action.get('OptInStatus', ''),
                })

        result = {
            'status': 'success',
            'function': 'FR-04',
            'db_instance_id': db_instance.get('DBInstanceIdentifier'),
            'db_instance_status': db_instance.get('DBInstanceStatus'),
            'engine': db_instance.get('Engine'),
            'engine_version': db_instance.get('EngineVersion'),
            'preferred_maintenance_window': db_instance.get('PreferredMaintenanceWindow'),
            'backup_retention_period': db_instance.get('BackupRetentionPeriod'),
            'multi_az': db_instance.get('MultiAZ', False),
            'pending_maintenance_actions': pending_actions,
            'has_pending_actions': len(pending_actions) > 0,
        }

        logger.info(f"FR-04 completed: {len(pending_actions)} pending actions found")
        return result

    except rds_client.exceptions.DBInstanceNotFoundFault as e:
        return {'status': 'error', 'function': 'FR-04', 'error': f"DB instance not found: {e}"}
    except Exception as e:
        logger.error(f"FR-04: Exception occurred: {e}", exc_info=True)
        return {'status': 'error', 'function': 'FR-04', 'error': str(e)}


# ============================================================================
# FR-05: スロークエリ検出
# ソース: lib/lambda_handler.py 行1912-2034
# ============================================================================

def slow_query_detection_fr05(**kwargs) -> Dict[str, Any]:
    """
    FR-05: Slow Query Detection - Performance Insights + CloudWatch Logs 統合実装

    参照: https://docs.aws.amazon.com/boto3/latest/reference/services/pi/client/get_resource_metrics.html
    """
    try:
        db_instance_id = kwargs.get('db_instance_id', '')
        dbi_resource_id = kwargs.get('dbi_resource_id', '')
        duration_seconds = int(kwargs.get('duration_seconds', 3600))

        if not dbi_resource_id and db_instance_id:
            instances = rds_client.describe_db_instances(DBInstanceIdentifier=db_instance_id)
            if instances.get('DBInstances'):
                dbi_resource_id = instances['DBInstances'][0].get('DbiResourceId', '')

        if not dbi_resource_id:
            return {'status': 'error', 'function': 'FR-05', 'error': 'dbi_resource_id is required'}

        logger.info(f"FR-05: Detecting slow queries for {db_instance_id} ({dbi_resource_id})")

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(seconds=duration_seconds)

        slow_queries = []
        try:
            pi_response = pi_client.get_resource_metrics(
                ServiceType='RDS',
                Identifier=dbi_resource_id,
                MetricQueries=[{'Metric': 'db.load.avg', 'GroupBy': {'Group': 'db.sql', 'Limit': 10}}],
                StartTime=start_time,
                EndTime=end_time,
                PeriodInSeconds=60,
            )
            for metric_data in pi_response.get('MetricList', []):
                for point in metric_data.get('DataPoints', []):
                    for dim_group in point.get('DimensionGroup', []):
                        query_text = dim_group.get('Dimensions', {}).get('db.sql', '')
                        load_value = point.get('Value', 0)
                        if load_value > 0:
                            slow_queries.append({'query': query_text[:500], 'db_load_avg': round(load_value, 4)})
        except Exception as pi_error:
            logger.warning(f"FR-05: PI API error: {pi_error}")

        cloudwatch_slow_queries = []
        try:
            log_group_name = f"/aws/rds/instance/{db_instance_id}/slowquery"
            streams = logs_client.describe_log_streams(logGroupName=log_group_name)
            for stream in streams.get('logStreams', [])[:5]:
                events = logs_client.get_log_events(
                    logGroupName=log_group_name,
                    logStreamName=stream.get('logStreamName', ''),
                    startTime=int(start_time.timestamp() * 1000),
                    endTime=int(end_time.timestamp() * 1000),
                    limit=50,
                )
                for event in events.get('events', []):
                    if 'Query_time' in event.get('message', ''):
                        cloudwatch_slow_queries.append({'log_message': event.get('message', '')[:300]})
        except logs_client.exceptions.ResourceNotFoundException:
            pass
        except Exception as log_error:
            logger.warning(f"FR-05: CW Logs error: {log_error}")

        result = {
            'status': 'success',
            'function': 'FR-05',
            'db_instance_id': db_instance_id,
            'duration_seconds': duration_seconds,
            'slow_queries_from_pi': slow_queries[:10],
            'pi_query_count': len(slow_queries),
            'cloudwatch_slow_queries': cloudwatch_slow_queries[:5],
            'cloudwatch_query_count': len(cloudwatch_slow_queries),
            'total_slow_queries': len(slow_queries) + len(cloudwatch_slow_queries),
        }

        logger.info(f"FR-05 completed: {len(slow_queries)} PI queries, {len(cloudwatch_slow_queries)} CW logs")
        return result

    except Exception as e:
        logger.error(f"FR-05: Exception occurred: {e}", exc_info=True)
        return {'status': 'error', 'function': 'FR-05', 'error': str(e)}


# ============================================================================
# FR-06: 高負荷クエリ分析
# ソース: lib/lambda_handler.py 行2036-2198
# ============================================================================

def high_load_query_detection_fr06(**kwargs) -> Dict[str, Any]:
    """
    FR-06: High Load Query Detection - Performance Insights + CloudWatch メトリクス統合実装

    参照: https://docs.aws.amazon.com/boto3/latest/reference/services/pi/client/get_resource_metrics.html
    """
    try:
        db_instance_id = kwargs.get('db_instance_id', '')
        dbi_resource_id = kwargs.get('dbi_resource_id', '')
        duration_seconds = int(kwargs.get('duration_seconds', 3600))
        high_load_threshold = float(kwargs.get('high_load_threshold', 2.0))

        if not dbi_resource_id and db_instance_id:
            instances = rds_client.describe_db_instances(DBInstanceIdentifier=db_instance_id)
            if instances.get('DBInstances'):
                dbi_resource_id = instances['DBInstances'][0].get('DbiResourceId', '')

        if not dbi_resource_id:
            return {'status': 'error', 'function': 'FR-06', 'error': 'dbi_resource_id is required'}

        logger.info(f"FR-06: Analyzing high load queries for {db_instance_id} ({dbi_resource_id})")

        end_time = datetime.utcnow()
        start_time = end_time - timedelta(seconds=duration_seconds)

        high_load_queries = []
        wait_events = []

        try:
            pi_response = pi_client.get_resource_metrics(
                ServiceType='RDS',
                Identifier=dbi_resource_id,
                MetricQueries=[
                    {'Metric': 'db.load.avg', 'GroupBy': {'Group': 'db.sql', 'Limit': 10}},
                    {'Metric': 'db.load.avg', 'GroupBy': {'Group': 'db.wait_event_type', 'Limit': 5}},
                ],
                StartTime=start_time,
                EndTime=end_time,
                PeriodInSeconds=60,
            )
            for metric_data in pi_response.get('MetricList', []):
                for point in metric_data.get('DataPoints', []):
                    value = point.get('Value', 0)
                    if value > high_load_threshold:
                        for dim_group in point.get('DimensionGroup', []):
                            dims = dim_group.get('Dimensions', {})
                            if 'db.sql' in dims:
                                high_load_queries.append({'query': dims.get('db.sql', '')[:500], 'db_load_avg': round(value, 4)})
                            elif 'db.wait_event_type' in dims:
                                wait_events.append({'wait_event_type': dims.get('db.wait_event_type', ''), 'db_load_avg': round(value, 4)})
        except Exception as pi_error:
            logger.warning(f"FR-06: PI API error: {pi_error}")

        resource_usage = {}
        try:
            cpu_response = cloudwatch_client.get_metric_statistics(
                Namespace='AWS/RDS',
                MetricName='CPUUtilization',
                Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=300,
                Statistics=['Average', 'Maximum'],
            )
            if cpu_response.get('Datapoints'):
                max_cpu = max([p.get('Maximum', 0) for p in cpu_response.get('Datapoints', [])])
                resource_usage['cpu_max_percent'] = round(max_cpu, 2)
        except Exception as cpu_error:
            logger.warning(f"FR-06: CPU metric error: {cpu_error}")

        result = {
            'status': 'success',
            'function': 'FR-06',
            'db_instance_id': db_instance_id,
            'duration_seconds': duration_seconds,
            'high_load_threshold': high_load_threshold,
            'high_load_queries': high_load_queries[:10],
            'high_load_query_count': len(high_load_queries),
            'wait_events': wait_events[:5],
            'wait_event_count': len(wait_events),
            'resource_usage': resource_usage,
        }

        logger.info(f"FR-06 completed: {len(high_load_queries)} high-load queries, {len(wait_events)} wait events")
        return result

    except Exception as e:
        logger.error(f"FR-06: Exception occurred: {e}", exc_info=True)
        return {'status': 'error', 'function': 'FR-06', 'error': str(e)}
