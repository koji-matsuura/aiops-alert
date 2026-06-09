"""
AIOps Lambda Handler
ブログ要件に基づく統一実装：
- すべてのトリガーが Bedrock Agent を通過
- ユーザー入力、CloudWatch Alarms、スケジュール実行を統一処理

参照: AWS ブログ "Automate IT operations with Amazon Bedrock Agents"
アーキテクチャ: 複数トリガー → Bedrock Agent (RAG + Action Group) → Lambda (FR-01～06) → SNS
"""

import json
import os
import boto3
import logging
from datetime import datetime, timedelta
import time
from typing import Dict, List, Any, Optional, Tuple
import hashlib

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
bedrock_agent_runtime = boto3.client('bedrock-agent-runtime')

# 環境変数
BEDROCK_AGENT_ID = os.environ.get('BEDROCK_AGENT_ID', '')
BEDROCK_AGENT_ALIAS = os.environ.get('BEDROCK_AGENT_ALIAS', 'TSTALIASID')
SNS_REPORT_ARN = os.environ.get('SNS_REPORT_ARN', 'arn:aws:sns:ap-northeast-1:123456789012:AIOpsReport')
S3_BACKUP_BUCKET = os.environ.get('S3_BACKUP_BUCKET', 'aiops-backup')

# 従来の環境変数（後方互換性）
SNS_LOG_INVESTIGATION_ARN = os.environ.get('SNS_LOG_INVESTIGATION_ARN', SNS_REPORT_ARN)
SNS_BOTTLENECK_ARN = os.environ.get('SNS_BOTTLENECK_ARN', SNS_REPORT_ARN)
SNS_SNAPSHOT_ARN = os.environ.get('SNS_SNAPSHOT_ARN', SNS_REPORT_ARN)
SNS_MAINTENANCE_ARN = os.environ.get('SNS_MAINTENANCE_ARN', SNS_REPORT_ARN)
SNS_SLOW_QUERY_ARN = os.environ.get('SNS_SLOW_QUERY_ARN', SNS_REPORT_ARN)
SNS_HIGH_LOAD_QUERY_ARN = os.environ.get('SNS_HIGH_LOAD_QUERY_ARN', SNS_REPORT_ARN)


def handler(event, context):
    """
    統一 Lambda ハンドラー - Bedrock Agent 統合版
    
    処理フロー:
    1. AWS 公式イベント構造から情報を抽出
    2. Bedrock Agent 用の prompt を構築
    3. Bedrock Agent を呼び出し
    4. Agent が RAG + Action Group で適切な FR-XX を実行
    5. 結果を SNS に通知
    
    参照: https://docs.aws.amazon.com/powertools/python/latest/core/event_handler/bedrock_agents/
    """
    try:
        logger.info(f"Lambda invoked with event: {json.dumps(event)}")
        
        # messageVersion 1.0 フォーマット判定（Bedrock Agent Action Group からの呼び出し）
        # 参照: https://docs.aws.amazon.com/powertools/python/latest/core/event_handler/bedrock_agents/
        if isinstance(event, dict) and event.get('messageVersion') == '1.0':
            logger.info("Detected Bedrock Agent messageVersion 1.0 format")
            return handle_bedrock_agent_message(event, context)
        
        # EventBridge / CloudWatch Alarms / ユーザー入力からの呼び出し
        
        # AWS 公式イベント構造から情報を抽出
        event_info = extract_event_info(event)
        logger.info(f"Extracted event info: source={event_info['source']}, detail_type={event_info['detail_type']}")
        
        # 統一 prompt を構築（Bedrock Agent が判定）
        prompt = build_prompt(event_info)
        logger.info(f"Built prompt: {prompt[:100]}...")
        
        # Bedrock Agent を呼び出し
        agent_response = invoke_bedrock_agent(
            prompt=prompt,
            session_id=context.aws_request_id
        )
        
        # 結果を SNS に通知
        notify_result(agent_response)
        
        return {
            'statusCode': 200,
            'body': json.dumps({
                'message': 'AIOps investigation completed',
                'source': event_info['source'],
                'session_id': context.aws_request_id
            })
        }

    except Exception as e:
        logger.error(f"Error in lambda_handler: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'body': json.dumps({'error': str(e)})
        }


def extract_event_info(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    AWS 公式イベント構造から情報を抽出
    
    AWS EventBridge イベントスキーマに完全準拠:
    参照: https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-eventbridge-targets.html
    
    公式フィールド（トップレベル）:
    - version: EventBridge スキーマバージョン（常に "1.0"）
    - id: イベント ID（UUID）
    - detail-type: イベント種別
    - source: イベントソース ("aws.cloudwatch", "aws.events" など)
    - account: AWS アカウント ID
    - time: イベントのタイムスタンプ (ISO 8601 形式)
    - region: AWS リージョン
    - resources: リソース ARN リスト
    - detail: イベント詳細（ペイロード）
    """
    return {
        # AWS 公式トップレベルフィールド
        "version": event.get("version", "1.0"),
        "id": event.get("id", "unknown"),
        "source": event.get("source", "unknown"),
        "detail_type": event.get("detail-type", "unknown"),
        "account": event.get("account", "unknown"),
        "time": event.get("time", datetime.utcnow().isoformat()),
        "region": event.get("region", "ap-northeast-1"),
        "resources": event.get("resources", []),
        # イベント詳細
        "detail": event.get("detail", {}),
        # 元のイベント（デバッグ用）
        "raw_event": event
    }



def build_prompt(event_info: Dict[str, Any]) -> str:
    """
    Bedrock Agent への統一 prompt を構築
    
    Bedrock Agent が以下を判定します:
    1. このアラームに対応すべきか
    2. 定期メンテナンスを実行すべきか
    3. 実行対象 Lambda (FR-01~FR-06) は何か
    
    参照:
      - AWS ブログ "Solution workflow"
      - Bedrock Agent プロンプト最適化ガイド
    """
    prompt = f"""
【イベント受信】

イベントソース: {event_info['source']}
イベント種別: {event_info['detail_type']}
タイムスタンプ: {event_info['time']}
イベント詳細:
{json.dumps(event_info['detail'], indent=2, ensure_ascii=False)}

このイベントについて:
1. Knowledge Base から関連ランブックを検索してください
2. 状況を分析してください
3. 必要なアクション（調査、対応、メンテナンス実行など）を判定してください
4. 実行結果をまとめて報告してください

ランブック検索のヒント:
- CloudWatch アラーム: EC2, RDS, Lambda, CloudWatch などの運用手順
- 定期メンテナンス: スロークエリ検出、高負荷クエリ分析、パフォーマンス改善
""".strip()
    
    return prompt


def invoke_bedrock_agent(prompt: str, session_id: str) -> Dict[str, Any]:
    """
    Bedrock Agent を呼び出し
    
    参照:
      - AWS Bedrock Agent Runtime API
      - invoke_agent() メソッド
    
    処理:
      1. Agent に prompt を送信
      2. Agent が RAG で Knowledge Base を検索
      3. Agent が Action Group で適切な Lambda を選択
      4. Lambda を実行して結果を取得
      5. 結果を返却
    """
    try:
        if not BEDROCK_AGENT_ID:
            logger.warning("BEDROCK_AGENT_ID not set, returning mock response")
            return {
                'statusCode': 200,
                'message': 'Agent invocation skipped (no agent configured)',
                'prompt': prompt
            }
        
        logger.info(f"Invoking Bedrock Agent: {BEDROCK_AGENT_ID}")
        
        response = bedrock_agent_runtime.invoke_agent(
            agentId=BEDROCK_AGENT_ID,
            agentAliasId=BEDROCK_AGENT_ALIAS,
            sessionId=session_id,
            inputText=prompt,
            enableTrace=True
        )
        
        logger.info(f"Bedrock Agent response: {json.dumps(response, default=str)}")
        
        # レスポンスを整形
        return {
            'statusCode': 200,
            'agentResponse': response,
            'session_id': session_id
        }
    
    except Exception as e:
        logger.error(f"Error invoking Bedrock Agent: {str(e)}", exc_info=True)
        return {
            'statusCode': 500,
            'error': str(e),
            'session_id': session_id
        }


def notify_result(response: Dict[str, Any]) -> None:
    """
    実行結果を SNS に通知
    
    参照:
      - AWS ブログ "Solution workflow" (最終ステップ)
      - SNS 通知フォーマット
    """
    try:
        subject = "AIOps Report"
        message = json.dumps(response, indent=2, default=str)
        
        sns_client.publish(
            TopicArn=SNS_REPORT_ARN,
            Subject=subject,
            Message=message
        )
        
        logger.info("SNS notification sent")
    
    except Exception as e:
        logger.error(f"Error notifying result: {str(e)}", exc_info=True)


# ============================================================================
# FR‑01～FR‑06: 具体的な調査・対応アクション
# 
# これらの関数は、Bedrock Agent の Action Group から呼ばれます。
# 参照: AWS ブログ "Solution workflow" (ステップ 5-6)
#   ステップ 5: OpenAPI specification defines which APIs need to be called
#   ステップ 6: Bedrock Agent uses RAG, action groups, and OpenAPI to determine appropriate API calls
#
# 注釈:
#  - 新しいハンドラー lambda_handler() は prompt を構築して Bedrock Agent を呼び出し
#  - Bedrock Agent が Knowledge Base を検索 (RAG) して関連ランブックを取得
#  - Bedrock Agent が Action Group で以下のいずれかを選択して呼び出し
#  - Lambda は FR-XX に該当するアクション（ログ調査、スナップショット作成など）を実行
#  - 結果を返却 → Agent が結果をまとめて SNS に通知
# ============================================================================



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
        current_time = datetime.utcnow()
        trigger_name = event.get('alarmName', event.get('trigger', 'log_investigation'))
        
        report = {
            'type': 'log_investigation',
            'report_id': generate_report_id('log_investigation', current_time),
            'status': 'completed',
            'trigger': event.get('trigger', 'unknown'),
            'timestamp': current_time.isoformat() + 'Z',
            'findings': [
                {
                    'log_group': alert.get('log_group', 'unknown'),
                    'error_count': len([a for a in alerts if a.get('log_group') == alert.get('log_group')])
                }
                for alert in alerts
            ][:10],  # 最大10グループ
            'recommendation': 'Review error logs in CloudWatch Logs console for detailed troubleshooting'
        }

        # Thread ID を取得（10分枠のスレッドに集約）
        thread_ts = get_thread_id_from_s3(trigger_name, current_time)
        
        # SNS に publish（Block Kit 対応 + Thread ID）
        publish_sns_message(SNS_LOG_INVESTIGATION_ARN, report, use_block_kit=True, thread_ts=thread_ts)
        
        # Thread ID を S3 に保存（最初のメッセージの場合）
        if not thread_ts:
            # Slack から thread_ts を受け取る前提で、今はメッセージ ID で暫定管理
            tentative_thread_id = f"{trigger_name}_{int(current_time.timestamp())}"
            save_thread_id_to_s3(trigger_name, current_time, tentative_thread_id)

        # S3 にバックアップ
        backup_report_to_s3(f'logs/log-investigation/{current_time.strftime("%Y%m%d_%H%M%S")}.json', report)

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
        current_time = datetime.utcnow()
        report = {
            'type': 'bottleneck_investigation',
            'report_id': generate_report_id('bottleneck_investigation', current_time),
            'status': 'completed' if len(bottlenecks) == 0 else 'warning',
            'trigger': event.get('trigger', 'unknown'),
            'timestamp': current_time.isoformat() + 'Z',
            'findings': {
                'cpu_usage': f"{sum(b.get('cpu', 0) for b in bottlenecks) / max(len(bottlenecks), 1):.1f}%" if bottlenecks else 'N/A',
                'memory_usage': f"{sum(b.get('memory', 0) for b in bottlenecks) / max(len(bottlenecks), 1):.1f}%" if bottlenecks else 'N/A',
                'network_in': f"{sum(b.get('network_in', 0) for b in bottlenecks) / max(len(bottlenecks), 1):.0f} MB/s" if bottlenecks else 'N/A'
            },
            'root_cause': 'High resource utilization detected on monitored resources' if bottlenecks else 'No bottlenecks detected',
            'recommendation': 'Review resource metrics in CloudWatch and consider scaling'
        }

        # Thread ID を取得（10分枠のスレッドに集約）
        bottleneck_trigger = event.get('alarmName', 'bottleneck_investigation')
        thread_ts = get_thread_id_from_s3(bottleneck_trigger, current_time)
        
        # SNS に publish（Block Kit 対応 + Thread ID）
        publish_sns_message(SNS_BOTTLENECK_ARN, report, use_block_kit=True, thread_ts=thread_ts)
        
        # Thread ID を S3 に保存（最初のメッセージの場合）
        if not thread_ts:
            tentative_thread_id = f"{bottleneck_trigger}_{int(current_time.timestamp())}"
            save_thread_id_to_s3(bottleneck_trigger, current_time, tentative_thread_id)

        # S3 にバックアップ
        backup_report_to_s3(f'bottleneck/{current_time.strftime("%Y%m%d_%H%M%S")}.json', report)

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

        current_time = datetime.utcnow()
        report = {
            'type': 'create_snapshot',
            'report_id': generate_report_id('create_snapshot', current_time),
            'status': 'completed',
            'trigger': event.get('trigger', 'unknown'),
            'timestamp': current_time.isoformat() + 'Z',
            'database_id': db_instance_id,
            'snapshot_id': snapshot_id,
            'duration_seconds': 0
        }

        # Thread ID を取得（10分枠のスレッドに集約）
        snapshot_trigger = event.get('db_instance_identifier', 'create_snapshot')
        thread_ts = get_thread_id_from_s3(snapshot_trigger, current_time)
        
        # SNS に publish（Block Kit 対応 + Thread ID）
        publish_sns_message(SNS_SNAPSHOT_ARN, report, use_block_kit=True, thread_ts=thread_ts)
        
        # Thread ID を S3 に保存（最初のメッセージの場合）
        if not thread_ts:
            tentative_thread_id = f"{snapshot_trigger}_{int(current_time.timestamp())}"
            save_thread_id_to_s3(snapshot_trigger, current_time, tentative_thread_id)

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
            'type': 'maintenance_display',
            'report_id': generate_report_id('maintenance_display', datetime.utcnow()),
            'status': 'completed',
            'trigger': event.get('trigger', 'unknown'),
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'service_name': service_name,
            'maintenance_info': maintenance_info
        }

        # Thread ID を取得（10分枠のスレッドに集約）
        maintenance_trigger = event.get('service_name', 'maintenance_display')
        maintenance_time = datetime.utcnow()
        thread_ts = get_thread_id_from_s3(maintenance_trigger, maintenance_time)
        
        # SNS に publish（Block Kit 対応 + Thread ID）
        publish_sns_message(SNS_MAINTENANCE_ARN, report, use_block_kit=True, thread_ts=thread_ts)
        
        # Thread ID を S3 に保存（最初のメッセージの場合）
        if not thread_ts:
            tentative_thread_id = f"{maintenance_trigger}_{int(maintenance_time.timestamp())}"
            save_thread_id_to_s3(maintenance_trigger, maintenance_time, tentative_thread_id)

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
                        'query_id': metric_record.get('Key', {}).get('Metric', 'unknown'),
                        'execution_time': f"{data_point.get('Value', 0) * 1000:.0f}",
                        'timestamp': data_point.get('Timestamp').isoformat() if data_point.get('Timestamp') else None
                    })

        current_time = datetime.utcnow()
        report = {
            'type': 'slow_query_detection',
            'report_id': generate_report_id('slow_query_detection', current_time),
            'status': 'completed',
            'trigger': event.get('trigger', 'unknown'),
            'timestamp': current_time.isoformat() + 'Z',
            'top_queries': slow_queries[:5],
            'recommendation': 'Review slow queries and optimize indexing strategy'
        }

        # Thread ID を取得（10分枠のスレッドに集約）
        slow_query_trigger = event.get('db_resource_id', 'slow_query_detection')
        thread_ts = get_thread_id_from_s3(slow_query_trigger, current_time)
        
        # SNS に publish（Block Kit 対応 + Thread ID）
        publish_sns_message(SNS_SLOW_QUERY_ARN, report, use_block_kit=True, thread_ts=thread_ts)
        
        # Thread ID を S3 に保存（最初のメッセージの場合）
        if not thread_ts:
            tentative_thread_id = f"{slow_query_trigger}_{int(current_time.timestamp())}"
            save_thread_id_to_s3(slow_query_trigger, current_time, tentative_thread_id)

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
            'type': 'high_load_query_detection',
            'report_id': generate_report_id('high_load_query_detection', datetime.utcnow()),
            'status': 'completed',
            'trigger': event.get('trigger', 'unknown'),
            'timestamp': datetime.utcnow().isoformat() + 'Z',
            'top_queries': [
                {
                    'query_id': q['metric'],
                    'execution_time': f"{q.get('value', 0):.1f}%"
                }
                for q in high_load_queries[:5]
            ],
            'recommendation': 'Scale resources or optimize queries to handle high load'
        }

        # Thread ID を取得（10分枠のスレッドに集約）
        high_load_trigger = event.get('db_resource_id', 'high_load_query_detection')
        high_load_time = datetime.utcnow()
        thread_ts = get_thread_id_from_s3(high_load_trigger, high_load_time)
        
        # SNS に publish（Block Kit 対応 + Thread ID）
        publish_sns_message(SNS_HIGH_LOAD_QUERY_ARN, report, use_block_kit=True, thread_ts=thread_ts)
        
        # Thread ID を S3 に保存（最初のメッセージの場合）
        if not thread_ts:
            tentative_thread_id = f"{high_load_trigger}_{int(high_load_time.timestamp())}"
            save_thread_id_to_s3(high_load_trigger, high_load_time, tentative_thread_id)

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

def publish_sns_message(topic_arn: str, message: Dict[str, Any], use_block_kit: bool = True, thread_ts: Optional[str] = None) -> bool:
    """
    SNS メッセージを発行
    
    Args:
        topic_arn: SNS Topic ARN
        message: レポート（辞書形式）
        use_block_kit: Block Kit フォーマットを使用するか（デフォルト: True）
        thread_ts: スレッド ID（複数アラーム集約用）
    
    Returns:
        成功: True、失敗: False
    """
    try:
        # Block Kit フォーマットに変換
        if use_block_kit:
            block_kit_payload = convert_to_slack_block_kit(message, thread_ts)
            message_body = json.dumps(block_kit_payload, default=str)
        else:
            message_body = json.dumps(message, default=str, indent=2)
        
        sns_client.publish(
            TopicArn=topic_arn,
            Subject=f"AIOps Alert: {message.get('type', 'unknown')}",
            Message=message_body
        )
        logger.info(f"Published message to {topic_arn} (Block Kit: {use_block_kit})")
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


def convert_to_slack_block_kit(report: Dict[str, Any], thread_ts: Optional[str] = None) -> Dict[str, Any]:
    """
    レポートを Slack Block Kit フォーマットに変換
    
    Args:
        report: Lambda レポート（辞書形式）
        thread_ts: スレッド ID（複数アラーム集約時）
    
    Returns:
        Slack Block Kit メッセージペイロード
    """
    report_type = report.get('type', 'unknown')
    status = report.get('status', 'unknown')
    timestamp = report.get('timestamp', datetime.utcnow().isoformat())
    
    # ステータスに応じた絵文字とカラー
    if status == 'completed':
        emoji = '✅'
        color = '36a64f'  # 緑
    elif status == 'error':
        emoji = '❌'
        color = 'ff0000'  # 赤
    elif status == 'in_progress':
        emoji = '⏳'
        color = 'ffa500'  # オレンジ
    else:
        emoji = 'ℹ️'
        color = '0099ff'  # 青
    
    # メインセクション
    blocks = [
        {
            "type": "header",
            "text": {
                "type": "plain_text",
                "text": f"{emoji} AIOps Alert: {report_type.replace('_', ' ').title()}",
                "emoji": True
            }
        },
        {
            "type": "divider"
        },
        {
            "type": "section",
            "fields": [
                {
                    "type": "mrkdwn",
                    "text": f"*Status:*\n{status.upper()}"
                },
                {
                    "type": "mrkdwn",
                    "text": f"*Timestamp:*\n{timestamp}"
                }
            ]
        }
    ]
    
    # レポート固有情報
    if report_type == 'log_investigation':
        findings_text = "\n".join([
            f"• {f.get('log_group', 'unknown')}: {f.get('error_count', 0)} errors"
            for f in report.get('findings', [])
        ])
        blocks.extend([
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*📋 Log Findings:*\n{findings_text or 'No findings'}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*💡 Recommendation:*\n{report.get('recommendation', 'N/A')}"
                }
            }
        ])
    
    elif report_type == 'bottleneck_investigation':
        findings = report.get('findings', {})
        findings_text = f"""*CPU:* {findings.get('cpu_usage', 'N/A')}
*Memory:* {findings.get('memory_usage', 'N/A')}
*Network In:* {findings.get('network_in', 'N/A')}"""
        blocks.extend([
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*📊 System Metrics:*\n{findings_text}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*🔍 Root Cause:*\n{report.get('root_cause', 'N/A')}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*💡 Recommendation:*\n{report.get('recommendation', 'N/A')}"
                }
            }
        ])
    
    elif report_type == 'create_snapshot':
        blocks.extend([
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*Database:* {report.get('database_id', 'N/A')}\n*Snapshot ID:* {report.get('snapshot_id', 'N/A')}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*⏱️ Duration:* {report.get('duration_seconds', 'N/A')}s"
                }
            }
        ])
    
    elif report_type in ['slow_query_detection', 'high_load_query_detection']:
        queries = report.get('top_queries', [])
        queries_text = "\n".join([
            f"• Query {i+1}: {q.get('query_id', 'unknown')} - {q.get('execution_time', 'N/A')}ms"
            for i, q in enumerate(queries[:5])  # Top 5 のみ表示
        ])
        blocks.extend([
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*🗄️ Top Queries:*\n{queries_text or 'No queries found'}"
                }
            },
            {
                "type": "section",
                "text": {
                    "type": "mrkdwn",
                    "text": f"*💡 Recommendation:*\n{report.get('recommendation', 'N/A')}"
                }
            }
        ])
    
    # アクションセクション（インタラクティブボタン）
    blocks.extend([
        {
            "type": "divider"
        },
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": "*⚠️ Action Required?*\nReview findings and confirm before taking action."
            }
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "✅ Confirm & Execute",
                        "emoji": True
                    },
                    "value": "confirm_action",
                    "action_id": f"btn_confirm_{report.get('report_id', 'unknown')}",
                    "style": "primary"
                },
                {
                    "type": "button",
                    "text": {
                        "type": "plain_text",
                        "text": "❌ Review Details",
                        "emoji": True
                    },
                    "value": "review_action",
                    "action_id": f"btn_review_{report.get('report_id', 'unknown')}",
                    "style": "danger"
                }
            ]
        },
        {
            "type": "context",
            "elements": [
                {
                    "type": "mrkdwn",
                    "text": f"Report ID: `{report.get('report_id', 'unknown')}` | Trigger: `{report.get('trigger', 'unknown')}`"
                }
            ]
        }
    ])
    
    # 返すペイロード
    payload = {
        "blocks": blocks
    }
    
    # スレッド対応
    if thread_ts:
        payload["thread_ts"] = thread_ts
    
    return payload


def generate_report_id(report_type: str, timestamp: datetime) -> str:
    """レポート一意 ID を生成（スレッド化用）"""
    return f"aiops-{report_type}-{timestamp.strftime('%Y%m%d')}-{int(timestamp.timestamp())}"


def generate_thread_id(trigger_name: str, timestamp: datetime) -> str:
    """
    Thread ID を生成（10分ごとのスレッド）
    
    Args:
        trigger_name: トリガー名（例: "EC2-HighCPU-i-xxxxx"）
        timestamp: 現在の時刻
    
    Returns:
        Thread ID（例: "trigger_EC2-HighCPU-i-xxxxx_202606041030"）
    
    説明:
        - トリガーベースで同じアラーム種別のメッセージをグループ化
        - 10分ごとに新しいスレッドを作成
        - 例: "EC2-HighCPU-i-xxxxx" → 10:30-10:40 の間に発生したアラームは同じスレッド
    """
    # 10分単位で時刻を丸める
    minutes_bucket = (timestamp.minute // 10) * 10
    time_bucket = timestamp.strftime(f'%Y%m%d%H') + f'{minutes_bucket:02d}'
    
    # trigger_name をハッシュ化（長さを制限）
    trigger_hash = hashlib.md5(trigger_name.encode()).hexdigest()[:8]
    
    return f"thread_{trigger_hash}_{time_bucket}"


def get_thread_id_from_s3(trigger_name: str, timestamp: datetime) -> Optional[str]:
    """
    S3 から既存のスレッド情報を取得（複数アラーム集約用）
    
    Args:
        trigger_name: トリガー名
        timestamp: 現在の時刻
    
    Returns:
        既存の thread_ts がある場合は返す、ない場合は None
    """
    try:
        thread_info_key = f"thread-mapping/{generate_thread_id(trigger_name, timestamp)}.json"
        
        response = s3_client.get_object(
            Bucket=S3_BACKUP_BUCKET,
            Key=thread_info_key
        )
        
        thread_info = json.loads(response['Body'].read())
        thread_ts = thread_info.get('thread_ts')
        
        logger.info(f"Found existing thread_ts: {thread_ts}")
        return thread_ts
    
    except s3_client.exceptions.NoSuchKey:
        # スレッド情報がまだない
        return None
    except Exception as e:
        logger.warning(f"Error retrieving thread_ts from S3: {str(e)}")
        return None


def save_thread_id_to_s3(trigger_name: str, timestamp: datetime, thread_ts: str) -> bool:
    """
    生成されたスレッド情報を S3 に保存（複数アラーム集約用）
    
    Args:
        trigger_name: トリガー名
        timestamp: 現在の時刻
        thread_ts: Slack スレッド timestamp
    
    Returns:
        成功: True、失敗: False
    """
    try:
        thread_id = generate_thread_id(trigger_name, timestamp)
        thread_info_key = f"thread-mapping/{thread_id}.json"
        
        thread_info = {
            'thread_id': thread_id,
            'thread_ts': thread_ts,
            'trigger_name': trigger_name,
            'created_at': timestamp.isoformat(),
            'expiry': (timestamp + timedelta(minutes=10)).isoformat()
        }
        
        s3_client.put_object(
            Bucket=S3_BACKUP_BUCKET,
            Key=thread_info_key,
            Body=json.dumps(thread_info, indent=2),
            ContentType='application/json',
            ServerSideEncryption='AES256'
        )
        
        logger.info(f"Saved thread_ts to S3: {thread_info_key}")
        return True
    
    except Exception as e:
        logger.error(f"Error saving thread_ts to S3: {str(e)}")
        return False


def check_approval_status(report_id: str) -> Tuple[str, Optional[str]]:
    """
    S3 から確認ステータスをチェック（破壊的アクション用）
    
    Args:
        report_id: レポート ID
    
    Returns:
        Tuple: (status, operator_id)
            - status: "approved" | "denied" | "pending" | "expired" | "not_found"
            - operator_id: 承認したオペレータID（approved の場合のみ）
    
    説明:
        - pending-confirmations/{report_id}-*.json を検索
        - 有効期限（TTL）をチェック
        - 承認/拒否/期限切れの判定
    
    根拠:
        - S3 Lifecycle Policy: 1時間後に自動削除（TTL）
        - 破壊的アクション（FR-02, FR-04, FR-05）が実行前に確認
    """
    try:
        # S3 から pending_confirmation ファイルを検索
        prefix = f"pending-confirmations/{report_id}-"
        
        response = s3_client.list_objects_v2(
            Bucket=S3_BACKUP_BUCKET,
            Prefix=prefix,
            MaxKeys=10
        )
        
        if 'Contents' not in response or len(response['Contents']) == 0:
            logger.warning(f"No pending confirmation found for report_id: {report_id}")
            return ("not_found", None)
        
        # 最新のファイルを取得
        latest_obj = max(response['Contents'], key=lambda x: x['LastModified'])
        
        confirmation_response = s3_client.get_object(
            Bucket=S3_BACKUP_BUCKET,
            Key=latest_obj['Key']
        )
        
        confirmation = json.loads(confirmation_response['Body'].read())
        
        # TTL をチェック
        current_time = int(time.time())
        ttl = confirmation.get('ttl', 0)
        
        if current_time > ttl:
            logger.warning(f"Confirmation has expired for report_id: {report_id}")
            return ("expired", None)
        
        # アクション確認
        action = confirmation.get('action', 'unknown')
        user_id = confirmation.get('user_id', 'unknown')
        
        if action == 'approve':
            logger.info(f"Approval confirmed for report_id: {report_id} by user {user_id}")
            return ("approved", user_id)
        elif action == 'cancel':
            logger.info(f"Approval denied for report_id: {report_id} by user {user_id}")
            return ("denied", user_id)
        else:
            return ("pending", None)
    
    except Exception as e:
        logger.error(f"Error checking approval status: {str(e)}")
        return ("error", None)


def wait_for_approval(report_id: str, timeout_seconds: int = 3600, poll_interval: int = 5) -> Tuple[bool, Optional[str]]:
    """
    承認を待機（オプション：ポーリング型確認フロー）
    
    Args:
        report_id: レポート ID
        timeout_seconds: 最大待機時間（秒）
        poll_interval: ポーリング間隔（秒）
    
    Returns:
        Tuple: (approved, operator_id)
            - approved: True=承認済み、False=承認されず/期限切れ
            - operator_id: 承認したオペレータ ID（approved の場合のみ）
    
    注: Lambda タイムアウト（最大 15 分）に注意
    破壊的アクションはこの関数を使わず、単に check_approval_status() で確認するのみ
    """
    start_time = time.time()
    
    while time.time() - start_time < timeout_seconds:
        status, operator_id = check_approval_status(report_id)
        
        if status == "approved":
            return (True, operator_id)
        elif status in ["denied", "expired"]:
            return (False, None)
        
        # ペンディング中 → 5秒待ってリトライ
        logger.info(f"Approval pending for {report_id}, retrying in {poll_interval}s...")
        time.sleep(poll_interval)
     
    logger.warning(f"Approval timeout for {report_id} after {timeout_seconds}s")
    return (False, None)


# ============================================================================
# messageVersion 1.0 ハンドラー（Bedrock Agent Action Group）
# ============================================================================

def handle_bedrock_agent_message(event: Dict[str, Any], context) -> Dict[str, Any]:
    """
    Bedrock Agent からの messageVersion 1.0 リクエストを処理
    
    Input format (messageVersion 1.0):
    {
        "messageVersion": "1.0",
        "agent": {
            "name": "AiopsAgent",
            "id": "AGENTID123",
            "aliasId": "ALIASID123",
            "version": "DRAFT"
        },
        "inputText": "EC2 の CPU が高いです。調査してください",
        "sessionId": "session-123",
        "actionGroup": "AIOpsActionGroup",
        "function": "bottleneck_investigation",
        "parameters": [
            {
                "name": "instance_id",
                "type": "string",
                "value": "i-1234567890abcdef0"
            }
        ]
    }
    
    Output format (messageVersion 1.0):
    {
        "messageVersion": "1.0",
        "response": {
            "actionGroup": "AIOpsActionGroup",
            "function": "bottleneck_investigation",
            "httpStatusCode": 200,
            "responseBody": {
                "application/json": {
                    "body": "調査結果..."
                }
            }
        }
    }
    
    参照: 
    - AWS Powertools: https://docs.aws.amazon.com/powertools/python/latest/core/event_handler/bedrock_agents/
    - AWS Lambda Bedrock Agents: https://docs.aws.amazon.com/bedrock/latest/userguide/agents-lambda.html
    """
    try:
        logger.info(f"Processing Bedrock Agent messageVersion 1.0 request")
        
        # リクエストから function と parameters を抽出
        function_name = event.get('function', 'unknown')
        parameters = event.get('parameters', [])
        action_group = event.get('actionGroup', 'AIOpsActionGroup')
        session_id = event.get('sessionId', context.aws_request_id)
        
        logger.info(f"Function: {function_name}, Parameters: {json.dumps(parameters)}")
        
        # パラメータを辞書に変換
        param_dict = {}
        for param in parameters:
            if isinstance(param, dict):
                param_dict[param.get('name', '')] = param.get('value', '')
        
        logger.info(f"Converted parameters: {json.dumps(param_dict)}")
        
        # function_name に基づいて適切な FR 関数を実行
        result = dispatch_function(function_name, param_dict, session_id)
        
        # messageVersion 1.0 形式でレスポンスを構築
        response_body = {
            "status": "success",
            "result": result,
            "function": function_name,
            "session_id": session_id
        }
        
        return {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": action_group,
                "function": function_name,
                "functionResponse": {
                    "responseState": "SUCCESS",
                    "responseBody": {
                        "TEXT": {
                            "body": json.dumps(response_body)
                        }
                    }
                }
            }
        }
    
    except Exception as e:
        logger.error(f"Error in handle_bedrock_agent_message: {str(e)}", exc_info=True)
        
        return {
            "messageVersion": "1.0",
            "response": {
                "actionGroup": event.get('actionGroup', 'AIOpsActionGroup'),
                "function": event.get('function', 'unknown'),
                "functionResponse": {
                    "responseState": "FAILURE",
                    "responseBody": {
                        "TEXT": {
                            "body": json.dumps({
                                "status": "error",
                                "error": str(e),
                                "session_id": context.aws_request_id
                            })
                        }
                    }
                }
            }
        }


def dispatch_function(function_name: str, parameters: Dict[str, str], session_id: str) -> Dict[str, Any]:
    """
    Bedrock Agent から指定された function_name に基づいて適切な FR 関数を実行
    
    Args:
        function_name: 実行対象の関数名（例: "log_investigation", "bottleneck_investigation"）
        parameters: 関数に渡すパラメータ
        session_id: セッション ID
    
    Returns:
        関数の実行結果
    """
    logger.info(f"Dispatching function: {function_name}")
    
    # function_name と FR 関数のマッピング
    function_map = {
        'log_investigation': log_investigation_fr01,
        'bottleneck_investigation': bottleneck_investigation_fr02,
        'create_db_snapshot': create_db_snapshot_fr03,
        'maintenance_window_display': maintenance_window_display_fr04,
        'slow_query_detection': slow_query_detection_fr05,
        'high_load_query_detection': high_load_query_detection_fr06,
    }
    
    # 関数が存在するか確認
    if function_name not in function_map:
        logger.warning(f"Unknown function: {function_name}")
        return {
            "status": "error",
            "message": f"Function '{function_name}' is not recognized"
        }
    
    # 関数を実行
    try:
        fn = function_map[function_name]
        result = fn(**parameters)
        logger.info(f"Function {function_name} executed successfully")
        return result
    except Exception as e:
        logger.error(f"Error executing function {function_name}: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "function": function_name,
            "error": str(e)
        }


# ===== FR-01 ～ FR-06 関数スタブ =====
# 実装の詳細は別ファイルまたは拡張予定

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
        
        # 時間範囲（過去 N 秒）を計算
        end_time = int(time.time() * 1000)  # ミリ秒
        start_time = end_time - (time_range_seconds * 1000)
        
        # CloudWatch Logs API: get_log_events
        response = logs_client.get_log_events(
            logGroupName=log_group_name,
            logStreamName=log_stream_name,
            startTime=start_time,
            endTime=end_time,
            limit=100,
            startFromHead=True
        )
        
        events = response.get('events', [])
        
        # ログ分析：エラーレベルのみフィルタ
        error_logs = [
            event for event in events
            if 'ERROR' in event.get('message', '') or 'Exception' in event.get('message', '')
        ]
        
        result = {
            "status": "success",
            "function": "FR-01",
            "log_group": log_group_name,
            "log_stream": log_stream_name,
            "total_events": len(events),
            "error_events": len(error_logs),
            "errors_sample": [
                {
                    "timestamp": event.get('timestamp'),
                    "message": event.get('message', '')[:200]  # 最初の 200 文字
                }
                for event in error_logs[:5]  # 最大 5 件
            ],
            "investigation_period_seconds": time_range_seconds
        }
        
        logger.info(f"FR-01 completed: {len(error_logs)} errors found")
        return result
        
    except logs_client.exceptions.ResourceNotFoundException as e:
        logger.error(f"FR-01: Log group or stream not found: {str(e)}")
        return {
            "status": "error",
            "function": "FR-01",
            "error": f"Log resource not found: {str(e)}"
        }
    except Exception as e:
        logger.error(f"FR-01: Exception occurred: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "function": "FR-01",
            "error": str(e)
        }

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
        thresholds = kwargs.get('thresholds', {
            'cpu_percent': 80,
            'connections': 100,
            'memory_percent': 85
        })
        
        logger.info(f"FR-02: Investigating bottlenecks for RDS={db_instance_id}, EC2={ec2_instance_id}")
        
        # 時間範囲
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(seconds=time_range_seconds)
        
        bottlenecks = []
        
        # RDS ボトルネック分析
        if db_instance_id:
            rds_metrics = get_rds_metrics(
                db_instance_id=db_instance_id,
                start_time=start_time,
                end_time=end_time,
                thresholds=thresholds
            )
            bottlenecks.extend(rds_metrics.get('bottlenecks', []))
        
        # EC2 ボトルネック分析
        if ec2_instance_id:
            ec2_metrics = get_ec2_metrics(
                instance_id=ec2_instance_id,
                start_time=start_time,
                end_time=end_time,
                thresholds=thresholds
            )
            bottlenecks.extend(ec2_metrics.get('bottlenecks', []))
        
        result = {
            "status": "success",
            "function": "FR-02",
            "investigation_period_seconds": time_range_seconds,
            "bottleneck_count": len(bottlenecks),
            "bottlenecks": bottlenecks,
            "critical": any(b.get('severity') == 'CRITICAL' for b in bottlenecks),
            "thresholds_used": thresholds
        }
        
        logger.info(f"FR-02 completed: {len(bottlenecks)} bottlenecks identified")
        return result
        
    except Exception as e:
        logger.error(f"FR-02: Exception occurred: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "function": "FR-02",
            "error": str(e)
        }


def get_rds_metrics(db_instance_id: str, start_time, end_time, thresholds: Dict) -> Dict[str, Any]:
    """
    RDS メトリクスを CloudWatch から取得
    
    参照: https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_GetMetricStatistics.html
    """
    try:
        bottlenecks = []
        
        # CPU 使用率
        cpu_response = cloudwatch_client.get_metric_statistics(
            Namespace='AWS/RDS',
            MetricName='CPUUtilization',
            Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,  # 5 分間隔
            Statistics=['Average', 'Maximum']
        )
        
        for point in cpu_response.get('Datapoints', []):
            max_cpu = point.get('Maximum', 0)
            if max_cpu > thresholds.get('cpu_percent', 80):
                bottlenecks.append({
                    "type": "HIGH_CPU",
                    "value": round(max_cpu, 2),
                    "threshold": thresholds.get('cpu_percent'),
                    "timestamp": point.get('Timestamp'),
                    "severity": "CRITICAL" if max_cpu > 95 else "HIGH"
                })
        
        # DB 接続数
        connections_response = cloudwatch_client.get_metric_statistics(
            Namespace='AWS/RDS',
            MetricName='DatabaseConnections',
            Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=['Average', 'Maximum']
        )
        
        for point in connections_response.get('Datapoints', []):
            max_connections = point.get('Maximum', 0)
            if max_connections > thresholds.get('connections', 100):
                bottlenecks.append({
                    "type": "HIGH_CONNECTIONS",
                    "value": int(max_connections),
                    "threshold": thresholds.get('connections'),
                    "timestamp": point.get('Timestamp'),
                    "severity": "HIGH"
                })
        
        return {"bottlenecks": bottlenecks}
        
    except Exception as e:
        logger.error(f"get_rds_metrics error: {str(e)}", exc_info=True)
        return {"bottlenecks": []}


def get_ec2_metrics(instance_id: str, start_time, end_time, thresholds: Dict) -> Dict[str, Any]:
    """EC2 メトリクスを CloudWatch から取得"""
    try:
        bottlenecks = []
        
        # EC2 CPU 使用率
        cpu_response = cloudwatch_client.get_metric_statistics(
            Namespace='AWS/EC2',
            MetricName='CPUUtilization',
            Dimensions=[{'Name': 'InstanceId', 'Value': instance_id}],
            StartTime=start_time,
            EndTime=end_time,
            Period=300,
            Statistics=['Average', 'Maximum']
        )
        
        for point in cpu_response.get('Datapoints', []):
            max_cpu = point.get('Maximum', 0)
            if max_cpu > thresholds.get('cpu_percent', 80):
                bottlenecks.append({
                    "type": "EC2_HIGH_CPU",
                    "value": round(max_cpu, 2),
                    "threshold": thresholds.get('cpu_percent'),
                    "timestamp": point.get('Timestamp'),
                    "severity": "CRITICAL" if max_cpu > 95 else "HIGH"
                })
        
        return {"bottlenecks": bottlenecks}
        
    except Exception as e:
        logger.error(f"get_ec2_metrics error: {str(e)}", exc_info=True)
        return {"bottlenecks": []}

def create_db_snapshot_fr03(**kwargs) -> Dict[str, Any]:
    """
    FR-03: Create DB Snapshot - RDS API 統合実装
    
    RDS DB インスタンスのスナップショットを作成
    
    参照: https://docs.aws.amazon.com/boto3/latest/reference/services/rds/client/create_db_snapshot.html
    """
    try:
        db_instance_id = kwargs.get('db_instance_id', '')
        snapshot_id = kwargs.get('snapshot_id', f"snapshot-{int(time.time())}")
        
        if not db_instance_id:
            return {
                "status": "error",
                "function": "FR-03",
                "error": "db_instance_id is required"
            }
        
        logger.info(f"FR-03: Creating snapshot {snapshot_id} for RDS instance {db_instance_id}")
        
        # RDS API: create_db_snapshot
        # 必須パラメータ: DBSnapshotIdentifier, DBInstanceIdentifier
        response = rds_client.create_db_snapshot(
            DBSnapshotIdentifier=snapshot_id,
            DBInstanceIdentifier=db_instance_id,
            Tags=[
                {'Key': 'CreatedBy', 'Value': 'AIOps-Agent'},
                {'Key': 'CreatedAt', 'Value': datetime.utcnow().isoformat()}
            ]
        )
        
        db_snapshot = response.get('DBSnapshot', {})
        
        result = {
            "status": "success",
            "function": "FR-03",
            "snapshot_id": db_snapshot.get('DBSnapshotIdentifier'),
            "db_instance_id": db_snapshot.get('DBInstanceIdentifier'),
            "snapshot_status": db_snapshot.get('Status'),  # "creating"
            "engine": db_snapshot.get('Engine'),
            "allocated_storage": db_snapshot.get('AllocatedStorage'),
            "create_time": str(db_snapshot.get('SnapshotCreateTime', '')),
            "progress": db_snapshot.get('PercentProgress', 0),
            "snapshot_arn": db_snapshot.get('DBSnapshotArn'),
            "encrypted": db_snapshot.get('Encrypted', False)
        }
        
        logger.info(f"FR-03 completed: Snapshot {snapshot_id} initiated")
        return result
        
    except rds_client.exceptions.DBInstanceNotFoundFault as e:
        logger.error(f"FR-03: DB instance not found: {str(e)}")
        return {
            "status": "error",
            "function": "FR-03",
            "error": f"DB instance not found: {str(e)}"
        }
    except rds_client.exceptions.DBSnapshotAlreadyExistsFault as e:
        logger.error(f"FR-03: Snapshot already exists: {str(e)}")
        return {
            "status": "error",
            "function": "FR-03",
            "error": f"Snapshot already exists: {str(e)}"
        }
    except Exception as e:
        logger.error(f"FR-03: Exception occurred: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "function": "FR-03",
            "error": str(e)
        }

def maintenance_window_display_fr04(**kwargs) -> Dict[str, Any]:
    """
    FR-04: Maintenance Window Display - RDS API 統合実装
    
    RDS インスタンスのメンテナンスウィンドウと保留中のメンテナンスアクションを表示
    
    参照: https://docs.aws.amazon.com/boto3/latest/reference/services/rds/client/describe_db_instances.html
    参照: https://docs.aws.amazon.com/boto3/latest/reference/services/rds/client/describe_pending_maintenance_actions.html
    """
    try:
        db_instance_id = kwargs.get('db_instance_id', '')
        
        if not db_instance_id:
            return {
                "status": "error",
                "function": "FR-04",
                "error": "db_instance_id is required"
            }
        
        logger.info(f"FR-04: Retrieving maintenance info for RDS instance {db_instance_id}")
        
        # RDS API: describe_db_instances
        # PreferredMaintenanceWindow を取得
        instances_response = rds_client.describe_db_instances(
            DBInstanceIdentifier=db_instance_id
        )
        
        if not instances_response.get('DBInstances'):
            return {
                "status": "error",
                "function": "FR-04",
                "error": f"DB instance {db_instance_id} not found"
            }
        
        db_instance = instances_response['DBInstances'][0]
        
        # RDS API: describe_pending_maintenance_actions
        # 保留中のメンテナンスアクションを取得
        pending_response = rds_client.describe_pending_maintenance_actions(
            ResourceIdentifier=db_instance.get('DBInstanceArn', '')
        )
        
        pending_actions = []
        for action_set in pending_response.get('PendingMaintenanceActions', []):
            for action in action_set.get('PendingMaintenanceActionDetails', []):
                pending_actions.append({
                    "action": action.get('Action', ''),
                    "auto_applied_after": action.get('AutoAppliedAfterDate', ''),
                    "forced_apply_date": action.get('ForcedApplyDate', ''),
                    "opt_in_status": action.get('OptInStatus', ''),
                    "current_apply_scheduled_time": action.get('CurrentApplyScheduledTime', '')
                })
        
        result = {
            "status": "success",
            "function": "FR-04",
            "db_instance_id": db_instance.get('DBInstanceIdentifier'),
            "db_instance_status": db_instance.get('DBInstanceStatus'),
            "engine": db_instance.get('Engine'),
            "engine_version": db_instance.get('EngineVersion'),
            "preferred_maintenance_window": db_instance.get('PreferredMaintenanceWindow'),
            "backup_retention_period": db_instance.get('BackupRetentionPeriod'),
            "preferred_backup_window": db_instance.get('PreferredBackupWindow'),
            "multi_az": db_instance.get('MultiAZ', False),
            "pending_maintenance_actions": pending_actions,
            "pending_actions_count": len(pending_actions),
            "has_pending_actions": len(pending_actions) > 0
        }
        
        logger.info(f"FR-04 completed: {len(pending_actions)} pending actions found")
        return result
        
    except rds_client.exceptions.DBInstanceNotFoundFault as e:
        logger.error(f"FR-04: DB instance not found: {str(e)}")
        return {
            "status": "error",
            "function": "FR-04",
            "error": f"DB instance not found: {str(e)}"
        }
    except Exception as e:
        logger.error(f"FR-04: Exception occurred: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "function": "FR-04",
            "error": str(e)
        }

def slow_query_detection_fr05(**kwargs) -> Dict[str, Any]:
    """
    FR-05: Slow Query Detection - Performance Insights + CloudWatch Logs 統合実装
    
    RDS インスタンスの遅いクエリを検出し、パフォーマンス分析を実施
    
    参照: https://docs.aws.amazon.com/boto3/latest/reference/services/pi/client/get_resource_metrics.html
    参照: https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PerfInsights_UsingDashboard.AnalyzeDBLoad.AdditionalMetrics.html
    """
    try:
        db_instance_id = kwargs.get('db_instance_id', '')
        dbi_resource_id = kwargs.get('dbi_resource_id', '')  # Performance Insights 必須
        duration_seconds = int(kwargs.get('duration_seconds', 3600))
        slow_query_threshold_ms = int(kwargs.get('slow_query_threshold_ms', 1000))
        
        if not dbi_resource_id:
            logger.warning(f"FR-05: dbi_resource_id not provided, attempting to retrieve from DB instance {db_instance_id}")
            if db_instance_id:
                # RDS API から DbiResourceId を取得
                instances = rds_client.describe_db_instances(DBInstanceIdentifier=db_instance_id)
                if instances.get('DBInstances'):
                    dbi_resource_id = instances['DBInstances'][0].get('DbiResourceId', '')
            
            if not dbi_resource_id:
                return {
                    "status": "error",
                    "function": "FR-05",
                    "error": "dbi_resource_id is required or cannot be retrieved from DB instance"
                }
        
        logger.info(f"FR-05: Detecting slow queries for RDS {db_instance_id} (dbi_resource_id: {dbi_resource_id})")
        
        # 時間範囲
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(seconds=duration_seconds)
        
        # Performance Insights API: get_resource_metrics
        # db.load.avg を query group で集計し、遅いクエリを検出
        try:
            pi_response = pi_client.get_resource_metrics(
                ServiceType='RDS',
                Identifier=dbi_resource_id,
                MetricQueries=[
                    {
                        'Metric': 'db.load.avg',
                        'GroupBy': {
                            'Group': 'db.sql',
                            'Limit': 10  # 上位 10 クエリ
                        }
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
                PeriodInSeconds=60  # 1 分ごとの集計
            )
        except Exception as pi_error:
            logger.warning(f"FR-05: Performance Insights API error, falling back to CloudWatch Logs: {str(pi_error)}")
            pi_response = {'MetricList': []}
        
        # Performance Insights の結果を解析
        slow_queries = []
        for metric_data in pi_response.get('MetricList', []):
            for point in metric_data.get('DataPoints', []):
                for dimension_group in point.get('DimensionGroup', []):
                    query_text = dimension_group.get('Dimensions', {}).get('db.sql', '')
                    load_value = point.get('Value', 0)
                    if load_value > 0:
                        slow_queries.append({
                            "query": query_text[:500],  # 最初の 500 文字
                            "db_load_avg": round(load_value, 4),
                            "timestamp": str(point.get('Timestamp', ''))
                        })
        
        # CloudWatch Logs からもスロークエリをスキャン（MySQL slow log）
        cloudwatch_slow_queries = []
        try:
            log_group_name = f"/aws/rds/instance/{db_instance_id}/slowquery"
            
            # CloudWatch Logs ストリームを取得
            streams = logs_client.describe_log_streams(logGroupName=log_group_name)
            for stream in streams.get('logStreams', [])[:5]:  # 最新 5 ストリーム
                events = logs_client.get_log_events(
                    logGroupName=log_group_name,
                    logStreamName=stream.get('logStreamName', ''),
                    startTime=int(start_time.timestamp() * 1000),
                    endTime=int(end_time.timestamp() * 1000),
                    limit=50
                )
                for event in events.get('events', []):
                    if 'Query_time' in event.get('message', ''):
                        cloudwatch_slow_queries.append({
                            "log_message": event.get('message', '')[:300],
                            "timestamp": str(event.get('timestamp', ''))
                        })
        except logs_client.exceptions.ResourceNotFoundException:
            logger.info(f"FR-05: Log group {log_group_name} not found")
        except Exception as log_error:
            logger.warning(f"FR-05: CloudWatch Logs error: {str(log_error)}")
        
        result = {
            "status": "success",
            "function": "FR-05",
            "db_instance_id": db_instance_id,
            "dbi_resource_id": dbi_resource_id,
            "duration_seconds": duration_seconds,
            "slow_query_threshold_ms": slow_query_threshold_ms,
            "slow_queries_from_pi": slow_queries[:10],  # 上位 10 件
            "pi_query_count": len(slow_queries),
            "cloudwatch_slow_queries": cloudwatch_slow_queries[:5],  # 上位 5 件
            "cloudwatch_query_count": len(cloudwatch_slow_queries),
            "total_slow_queries": len(slow_queries) + len(cloudwatch_slow_queries)
        }
        
        logger.info(f"FR-05 completed: {len(slow_queries)} PI queries, {len(cloudwatch_slow_queries)} CW logs found")
        return result
        
    except Exception as e:
        logger.error(f"FR-05: Exception occurred: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "function": "FR-05",
            "error": str(e)
        }

def high_load_query_detection_fr06(**kwargs) -> Dict[str, Any]:
    """
    FR-06: High Load Query Detection - Performance Insights + CloudWatch メトリクス統合実装
    
    RDS インスタンスの高負荷クエリを検出し、リソース消費パターンを分析
    
    参照: https://docs.aws.amazon.com/boto3/latest/reference/services/pi/client/get_resource_metrics.html
    参照: https://docs.aws.amazon.com/AmazonCloudWatch/latest/APIReference/API_GetMetricStatistics.html
    """
    try:
        db_instance_id = kwargs.get('db_instance_id', '')
        dbi_resource_id = kwargs.get('dbi_resource_id', '')  # Performance Insights 必須
        duration_seconds = int(kwargs.get('duration_seconds', 3600))
        high_load_threshold = float(kwargs.get('high_load_threshold', 2.0))
        
        if not dbi_resource_id:
            logger.warning(f"FR-06: dbi_resource_id not provided, attempting to retrieve from DB instance {db_instance_id}")
            if db_instance_id:
                # RDS API から DbiResourceId を取得
                instances = rds_client.describe_db_instances(DBInstanceIdentifier=db_instance_id)
                if instances.get('DBInstances'):
                    dbi_resource_id = instances['DBInstances'][0].get('DbiResourceId', '')
            
            if not dbi_resource_id:
                return {
                    "status": "error",
                    "function": "FR-06",
                    "error": "dbi_resource_id is required or cannot be retrieved from DB instance"
                }
        
        logger.info(f"FR-06: Analyzing high load queries for RDS {db_instance_id} (dbi_resource_id: {dbi_resource_id})")
        
        # 時間範囲
        end_time = datetime.utcnow()
        start_time = end_time - timedelta(seconds=duration_seconds)
        
        # Performance Insights API: get_resource_metrics
        # db.load.avg と db.wait_event を分析し、高負荷クエリを検出
        try:
            pi_response = pi_client.get_resource_metrics(
                ServiceType='RDS',
                Identifier=dbi_resource_id,
                MetricQueries=[
                    {
                        'Metric': 'db.load.avg',
                        'GroupBy': {
                            'Group': 'db.sql',
                            'Limit': 10
                        }
                    },
                    {
                        'Metric': 'db.load.avg',
                        'GroupBy': {
                            'Group': 'db.wait_event_type',
                            'Limit': 5
                        }
                    }
                ],
                StartTime=start_time,
                EndTime=end_time,
                PeriodInSeconds=60
            )
        except Exception as pi_error:
            logger.warning(f"FR-06: Performance Insights API error, falling back to CloudWatch: {str(pi_error)}")
            pi_response = {'MetricList': []}
        
        # Performance Insights の結果を解析：高負荷クエリ
        high_load_queries = []
        wait_events = []
        
        for metric_data in pi_response.get('MetricList', []):
            metric_name = metric_data.get('Key', {}).get('Metric', '')
            
            for point in metric_data.get('DataPoints', []):
                value = point.get('Value', 0)
                
                if value > high_load_threshold:
                    for dimension_group in point.get('DimensionGroup', []):
                        dimensions = dimension_group.get('Dimensions', {})
                        
                        if 'db.sql' in dimensions:
                            # クエリ型メトリクス
                            high_load_queries.append({
                                "query": dimensions.get('db.sql', '')[:500],
                                "db_load_avg": round(value, 4),
                                "timestamp": str(point.get('Timestamp', ''))
                            })
                        elif 'db.wait_event_type' in dimensions:
                            # 待機イベント型メトリクス
                            wait_events.append({
                                "wait_event_type": dimensions.get('db.wait_event_type', ''),
                                "db_load_avg": round(value, 4),
                                "timestamp": str(point.get('Timestamp', ''))
                            })
        
        # CloudWatch メトリクスからリソース使用率を取得
        resource_usage = {}
        
        try:
            # CPU 使用率
            cpu_response = cloudwatch_client.get_metric_statistics(
                Namespace='AWS/RDS',
                MetricName='CPUUtilization',
                Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=300,
                Statistics=['Average', 'Maximum']
            )
            
            if cpu_response.get('Datapoints'):
                max_cpu = max([p.get('Maximum', 0) for p in cpu_response.get('Datapoints', [])])
                avg_cpu = sum([p.get('Average', 0) for p in cpu_response.get('Datapoints', [])]) / len(cpu_response.get('Datapoints', [])) if cpu_response.get('Datapoints') else 0
                resource_usage['cpu_usage'] = {
                    'max_percent': round(max_cpu, 2),
                    'avg_percent': round(avg_cpu, 2)
                }
        except Exception as cpu_error:
            logger.warning(f"FR-06: CPU metric error: {str(cpu_error)}")
        
        try:
            # ディスク I/O スループット
            io_response = cloudwatch_client.get_metric_statistics(
                Namespace='AWS/RDS',
                MetricName='ReadThroughput',
                Dimensions=[{'Name': 'DBInstanceIdentifier', 'Value': db_instance_id}],
                StartTime=start_time,
                EndTime=end_time,
                Period=300,
                Statistics=['Average', 'Maximum']
            )
            
            if io_response.get('Datapoints'):
                max_io = max([p.get('Maximum', 0) for p in io_response.get('Datapoints', [])])
                resource_usage['read_throughput_bytes'] = round(max_io, 2)
        except Exception as io_error:
            logger.warning(f"FR-06: I/O metric error: {str(io_error)}")
        
        result = {
            "status": "success",
            "function": "FR-06",
            "db_instance_id": db_instance_id,
            "dbi_resource_id": dbi_resource_id,
            "duration_seconds": duration_seconds,
            "high_load_threshold": high_load_threshold,
            "high_load_queries": high_load_queries[:10],
            "high_load_query_count": len(high_load_queries),
            "wait_events": wait_events[:5],
            "wait_event_count": len(wait_events),
            "resource_usage": resource_usage,
            "total_high_load_metrics": len(high_load_queries) + len(wait_events)
        }
        
        logger.info(f"FR-06 completed: {len(high_load_queries)} high-load queries, {len(wait_events)} wait events found")
        return result
        
    except Exception as e:
        logger.error(f"FR-06: Exception occurred: {str(e)}", exc_info=True)
        return {
            "status": "error",
            "function": "FR-06",
            "error": str(e)
        }
