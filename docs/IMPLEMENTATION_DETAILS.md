# AWS AIOps リポジトリ - コード実装詳細比較

## I. Lambda ハンドラー実装パターン比較

### A. 参照リポジトリ：マイクロサービス型

#### 1. Alert Lambda (get-all-alerts.py) - 79 行

```python
def lambda_handler(event, context):
    # Bedrock Agent からの呼び出し形式
    # event = {
    #   'apiPath': '/get_all_alerts',
    #   'requestBody': { ... },
    #   'promptSessionAttributes': { ... }
    # }
    
    if (event['apiPath']=='/get_all_alerts'):
        # CloudWatch アラーム取得
        cw_client = boto3.client('cloudwatch')
        response = cw_client.describe_alarms(
            AlarmNames=['Web_Server_CPU_Utilization'],
            StateValue='ALARM'
        )
        # JSON 形式で返却
    else:
        # SES でメール送信
        client = boto3.client('ses')
        client.send_email(...)
    
    # Bedrock Agent が理解する形式で返却
    return {
        'messageVersion': '1.0',
        'response': {
            'actionGroup': event['actionGroup'],
            'apiPath': event['apiPath'],
            'httpStatusCode': 200,
            'responseBody': response_body
        }
    }
```

**特徴**:
- `apiPath` でルーティング
- Bedrock Agent のアクションハンドラー標準形式
- GET/POST を `apiPath` で区別
- SES メール通知 (メール送信は Lambda 直接実行)

#### 2. Remediation Lambda (issue-remediation.py) - 54 行

```python
def lambda_handler(event, context):
    if (event['apiPath']=='/create_snapshot_of_EC2_volume'):
        # EC2 スナップショット作成
        instanceid = extract_instance_id(event)
        volume_id = get_volume_id(instanceid)
        response = ec2.create_snapshot(VolumeId=volume_id)
    else:
        # インスタンスリブート
        instanceid = extract_instance_id(event)
        response = ec2.reboot_instances(InstanceIds=[instanceid])
    
    # Bedrock 標準形式で返却
    return { 'messageVersion': '1.0', ... }
```

**特徴**:
- API PATH ごとに EC2 操作
- 単純な条件分岐
- 即座に操作実行

#### 3. Custom Resource Lambda (cdk-resource-bedrock-agent.py) - 152 行

```python
def on_event(event, context):
    request_type = event['RequestType']  # Create/Update/Delete
    
    if request_type == 'Create':
        agent_id = create_agent(...)      # Agent 作成
        time.sleep(15)                    # 待機
        create_agent_action_group(...)    # Action Group 登録
        create_cloudwatch_alarm(...)      # アラーム作成
    elif request_type == 'Update':
        pass  # 更新不要
    elif request_type == 'Delete':
        delete_agent(...)                 # Agent 削除
```

**特徴**:
- CloudFormation Custom Resource ハンドラー
- CDK デプロイ時に自動実行
- Bedrock Agent のライフサイクル管理
- 非同期処理の待機 (`time.sleep()`)

### B. 当プロジェクト：統合型（Lambda 603 行）

```python
def lambda_handler(event, context):
    action = event.get('action', 'log_investigation')
    
    # action で機能を切り分け
    if action == 'log_investigation':
        return handle_log_investigation(event)
    elif action == 'bottleneck_investigation':
        return handle_bottleneck_investigation(event)
    # ... 他の 4 つの FR
```

#### handle_log_investigation() - 詳細実装

```python
def handle_log_investigation(event):
    """
    CloudWatch Logs を検索し、エラーやセキュリティ異常を検出
    複数のロググループを同時処理
    """
    log_group_prefix = event.get('log_group_prefix', '/aws/lambda/')
    time_range_seconds = event.get('time_range_seconds', 900)
    filter_pattern = event.get('filter_pattern', '?ERROR *')
    
    # ロググループ一覧取得
    log_groups = get_log_groups_by_prefix(log_group_prefix)
    
    # 各ロググループを検索
    alerts = []
    for log_group in log_groups:
        group_alerts = search_logs(
            log_group_name=log_group,
            time_range_seconds=time_range_seconds,
            filter_pattern=filter_pattern
        )
        alerts.extend(group_alerts)
    
    # レポート生成
    report = {
        'type': 'logInvestigation',
        'runAt': datetime.utcnow().isoformat() + 'Z',
        'alertCount': len(alerts),
        'alerts': alerts[:50]
    }
    
    # 複数の通知・保存
    publish_sns_message(SNS_LOG_INVESTIGATION_ARN, report)    # SNS 通知
    backup_report_to_s3(f'logs/log-investigation/...', report)  # S3 保存
    put_metric_data('LogErrors', len(alerts))                  # Metric 送信
    
    return { 'statusCode': 200, 'body': json.dumps({...}) }
```

**特徴**:
1. **複数ロググループ処理** - ロジック複雑
2. **複数の出力形式** - SNS, S3, Metrics
3. **CloudWatch Metrics 送信** - モニタリング統合
4. **レポート永続化** - S3 バックアップ

#### handle_bottleneck_investigation() - 詳細実装

```python
def handle_bottleneck_investigation(event):
    """
    CloudWatch Metrics と RDS Performance Insights を利用
    ボトルネック検出・分析
    """
    time_range_seconds = event.get('time_range_seconds', 900)
    thresholds = event.get('thresholds', {
        'CPUUtilization': 90,
        'FreeStorageSpace': 100000
    })
    resource_arns = event.get('resource_arns', [])
    
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
    
    # レポート生成・通知
    report = {
        'type': 'bottleneckInvestigation',
        'bottlenecks': bottlenecks
    }
    publish_sns_message(SNS_BOTTLENECK_ARN, report)
    backup_report_to_s3(f'metrics/bottleneck/...', report)
    put_metric_data('BottleneckCount', len(bottlenecks))
```

**特徴**:
1. **複数のメトリクスソース** - CloudWatch + RDS PI
2. **複合分析** - しきい値による判定
3. **ARN による動的リソース指定**

#### handle_slow_query_detection() - RDS Performance Insights 統合

```python
def handle_slow_query_detection(event):
    """
    RDS Performance Insights API を利用した遅いクエリ検出
    """
    db_instance_id = event.get('db_instance_id')
    period_in_seconds = event.get('period_in_seconds', 3600)
    
    # PI API へアクセス
    response = pi_client.describe_dimension_keys(
        ServiceType='RDS',
        Identifier=get_db_resource_id(db_instance_id),
        StartTime=datetime.utcnow() - timedelta(seconds=period_in_seconds),
        EndTime=datetime.utcnow(),
        PeriodInSeconds=60,
        GroupBy={'Group': 'db.sql'},  # SQL でグループ化
        Metric='db_time',
        PartitionBy={'Group': 'host'}
    )
    
    # スローク検出
    slow_queries = extract_slow_queries(response)
    
    # 詳細情報取得
    for query in slow_queries:
        get_digest_details(query)
    
    # レポート・通知
    report = {
        'type': 'slowQueryDetection',
        'queries': slow_queries
    }
    publish_sns_message(SNS_SLOW_QUERY_ARN, report)
```

**特徴**:
1. **RDS Performance Insights 専用** - PI API 使用
2. **SQL ごとのグループ化** - 詳細分析
3. **db_time メトリクス** - DB 負荷の正確な測定

---

## II. IAM ロール設計パターン

### A. 参照リポジトリ (TypeScript Construct)

```typescript
// lambda-iam-construct.ts
const lambdaRole = new cdk.aws_iam.Role(this, "LambdaRole", {
  roleName: props.roleName,
  assumedBy: new cdk.aws_iam.ServicePrincipal('lambda.amazonaws.com')
});

// 複数の PolicyStatement で権限を追加
lambdaRole.addToPolicy(
  new iam.PolicyStatement({
    sid: 'ec2volume',
    effect: iam.Effect.ALLOW,
    resources: [`arn:aws:ec2:...:volume/vol-*`],
    actions: ['ec2:CreateSnapshot', 'ec2:CreateTags'],
    conditions: {
      StringLike: {
        'aws:ResourceTag/Name': '*/Loadtest-EC2Instance'
      }
    }
  })
);

// SES メール送信権限
lambdaRole.addToPolicy(
  new iam.PolicyStatement({
    sid: 'ses',
    effect: iam.Effect.ALLOW,
    resources: [
      `arn:aws:ses:...:identity/${props.email}`,
      `arn:aws:ses:...:configuration-set/MyDemoConfigurationSet`
    ],
    actions: ['ses:SendEmail']
  })
);
```

**特徴**:
- Condition で ResourceTag 指定
- SES メール送信 (Configuration Set 含む)
- Sid で権限の目的を明記

### B. 当プロジェクト (CloudFormation YAML)

```yaml
# lambda-function.yaml - IAM Role
LambdaExecutionRole:
  Type: AWS::IAM::Role
  Properties:
    AssumeRolePolicyDocument:
      Statement:
        - Effect: Allow
          Principal:
            Service: lambda.amazonaws.com
          Action: sts:AssumeRole
    Policies:
      - PolicyName: LambdaPolicy
        PolicyDocument:
          Statement:
            # CloudWatch Logs
            - Sid: cloudwatch-logs
              Effect: Allow
              Action:
                - logs:CreateLogGroup
                - logs:CreateLogStream
                - logs:PutLogEvents
              Resource: !Sub 'arn:aws:logs:${AWS::Region}:${AWS::AccountId}:*'
            
            # RDS Performance Insights
            - Sid: rds-performance-insights
              Effect: Allow
              Action:
                - pi:DescribeDimensionKeys
                - pi:GetResourceMetrics
                - pi:ListAvailableResourceDimensions
                - pi:ListAvailableResourceMetrics
              Resource: '*'
            
            # SNS Publish
            - Sid: sns-publish
              Effect: Allow
              Action:
                - sns:Publish
              Resource: !Sub 'arn:aws:sns:${AWS::Region}:${AWS::AccountId}:*'
            
            # S3 Backup
            - Sid: s3-backup
              Effect: Allow
              Action:
                - s3:PutObject
                - s3:GetObject
              Resource: !Sub 'arn:aws:s3:::${BackupBucket}/*'
            
            # CloudWatch Metrics
            - Sid: cloudwatch-metrics
              Effect: Allow
              Action:
                - cloudwatch:PutMetricData
              Resource: '*'
```

**特徴**:
- YAML で読みやすく定義
- 各権限に Sid でラベル付け
- 環境変数で ARN をパラメータ化

---

## III. CloudFormation vs CDK テンプレート生成

### A. 参照リポジトリ (CDK から生成)

CDK Stack をビルドすると CloudFormation テンプレートが生成される

```typescript
const bedrockAgentRole = new cdk.aws_iam.Role(this, "BedrockAgentRole", {
  roleName: props.roleName,
  assumedBy: new cdk.aws_iam.ServicePrincipal('bedrock.amazonaws.com'),
});

bedrockAgentRole.attachInlinePolicy(
  new cdk.aws_iam.Policy(this, "BedrockAgentLambdaPolicy", {
    policyName: "BedrockAgentLambdaPolicy",
    statements: [
      new cdk.aws_iam.PolicyStatement({
        effect: cdk.aws_iam.Effect.ALLOW,
        resources: [props.lambdaRoleArn],
        actions: ['lambda:InvokeFunction']
      })
    ]
  })
);
```

**生成される CloudFormation:**
```yaml
BedrockAgentRole123ABC:
  Type: AWS::IAM::Role
  Properties:
    AssumeRolePolicyDocument:
      Statement:
        - Action: sts:AssumeRole
          Effect: Allow
          Principal:
            Service: bedrock.amazonaws.com
    Policies:
      - PolicyName: BedrockAgentLambdaPolicy
        PolicyDocument:
          Statement:
            - Action: lambda:InvokeFunction
              Effect: Allow
              Resource: <lambda_role_arn>
```

**メリット**:
- Construct で抽象化
- エラーチェック (コンパイル時)
- 再利用可能

**デメリット**:
- TypeScript 学習コスト
- デバッグが難しい
- 生成されたテンプレートが複雑

### B. 当プロジェクト (手書き YAML)

```yaml
Resources:
  LambdaExecutionRole:
    Type: AWS::IAM::Role
    Properties:
      AssumeRolePolicyDocument:
        Version: "2012-10-17"
        Statement:
          - Effect: Allow
            Principal:
              Service: lambda.amazonaws.com
            Action: sts:AssumeRole
      Policies:
        - PolicyName: LambdaExecutionPolicy
          PolicyDocument:
            Version: "2012-10-17"
            Statement:
              - Sid: rds-pi
                Effect: Allow
                Action:
                  - pi:*
                Resource: '*'
```

**メリット**:
- 直接可視化
- 修正が容易
- AWS 標準形式

**デメリット**:
- テンプレート管理の手間
- 入力ミスのリスク

---

## IV. Bedrock Agent 統合パターン

### A. 参照リポジトリ (Custom Resource による動的作成)

```python
def on_create(event, ...):
    # Bedrock Agent を作成
    agent_id = create_agent(
        agentName=agent_name,
        agentResourceRoleArn=bedrock_agent_role_arn,
        foundationModel="anthropic.claude-3-haiku-20240307-v1:0",
        instruction="find if there is any operational issue and fix..."
    )
    
    # 15 秒待機
    time.sleep(15)
    
    # Action Group 1: Alerts
    create_agent_action_group(
        agent_id=agent_id,
        lambda_arn=bedrock_agent_alert_lambda_arn,
        actionGroupName="GetAlertsActionGroup"
    )
    
    # Action Group 2: Remediation
    create_agent_action_group(
        agent_id=agent_id,
        lambda_arn=bedrock_agent_remediation_lambda_arn,
        actionGroupName="RemediationActionGroup"
    )
```

**特徴**:
- 実行時に Agent を作成
- 2 つの独立した Action Group
- API Schema を S3 から参照

**フロー:**
```
CDK Deploy
  ↓
Custom Resource Lambda 実行
  ↓
Bedrock Agent 作成
  ↓
Action Group 登録 (2 個)
  ↓
CloudWatch Alarm 作成
```

### B. 当プロジェクト (CloudFormation で宣言的定義)

```yaml
# bedrock-agent.yaml
BedrockAgent:
  Type: AWS::Bedrock::Agent
  Properties:
    AgentName: !Sub 'aiops-agent-${EnvName}'
    Description: AIOps automation agent
    Instruction: !Sub |
      You are an AIOps agent. Your role:
      1. Find operational issues in AWS account using runbooks
      2. Execute remediation steps strictly following runbooks
      3. Send notifications with investigation results
    KnowledgeBases:
      - KnowledgeBaseId: !Ref KnowledgeBase
        Description: AIOps investigation runbooks
```

```yaml
# action-group.yaml
ActionGroup:
  Type: AWS::Bedrock::AgentActionGroup
  Properties:
    AgentId: !Ref BedrockAgent
    AgentVersion: DRAFT
    ActionGroupName: AIOpsActions
    ActionGroupExecutor:
      Lambda: !GetAtt LambdaFunction.Arn
    ApiSchema:
      S3:
        S3BucketName: !Ref S3Bucket
        S3ObjectKey: api-schema/operations.json
```

**特徴**:
- 宣言的 (実行時ロジック不要)
- Knowledge Base を統合
- 単一の Action Group (複数 API エンドポイント)

**フロー:**
```
CloudFormation Deploy
  ↓
Agent リソース作成
  ↓
Action Group 登録
  ↓
Knowledge Base 自動検索可能
```

---

## V. Knowledge Base 統合

### A. 参照リポジトリ (手動作成)

README に Step-by-Step ガイド:
1. AWS Console → Bedrock → Knowledge Base 作成
2. S3 データソース指定
3. Embedding Model 選択
4. Agent に Add
5. Agent を Prepare

```bash
# 手動作業
AWS Console でクリック操作多数
```

### B. 当プロジェクト (完全自動化)

```yaml
# knowledge-base.yaml
KnowledgeBase:
  Type: AWS::Bedrock::KnowledgeBase
  Properties:
    Name: aiops-kb
    RoleArn: !GetAtt KBRole.Arn
    KnowledgeBaseConfiguration:
      Type: VECTOR
      VectorKnowledgeBaseConfiguration:
        EmbeddingModelArn: !Sub 'arn:aws:bedrock:${AWS::Region}::foundation-model/amazon.titan-embed-text-v2:0'
    StorageConfiguration:
      Type: OPENSEARCH_SERVERLESS
      OpensearchServerlessConfiguration:
        CollectionArn: !GetAtt OpenSearchCollection.Arn
        VectorIndexName: aiops-kb-index
        FieldMapping:
          VectorField: vector
          TextField: text
          MetadataField: metadata

DataSource:
  Type: AWS::Bedrock::DataSource
  Properties:
    KnowledgeBaseId: !Ref KnowledgeBase
    Name: aiops-runbooks
    DataSourceConfiguration:
      Type: S3
      S3Configuration:
        BucketArn: !GetAtt RubookBucket.Arn
        InclusionPrefixes:
          - runbooks/
```

**特徴**:
- 完全 IaC 化
- OpenSearch Serverless 自動作成
- S3 ランブック自動取得
- ベクトル化自動実行

---

## VI. EventBridge トリガー設計

### A. 参照リポジトリ

CloudWatch Alarm は作成されるが、EventBridge Rule は不在

```python
# cdk-resource-bedrock-agent.py で Alarm のみ作成
cloudwatch.put_metric_alarm(
    AlarmName='Web_Server_CPU_Utilization',
    Threshold=90.0,
    ActionsEnabled=False  # ← アクション設定なし
)
```

手動でテストするか、CloudWatch Console からアラーム状態変更

### B. 当プロジェクト (完全統合)

```yaml
# eventbridge-alarms.yaml
EC2HighCPURule:
  Type: AWS::Events::Rule
  Properties:
    EventPattern:
      source:
        - aws.cloudwatch
      detail-type:
        - CloudWatch Alarm State Change
      detail:
        alarmName:
          - prefix: EC2-HighCPU-
        state:
          value:
            - ALARM
    State: ENABLED
    Targets:
      - Arn: !GetAtt LambdaFunction.Arn
        RoleArn: !GetAtt EventBridgeRole.Arn
        InputTransformer:
          InputPathsMap:
            alarm: $.detail.alarmName
            state: $.detail.state.value
          InputTemplate: |
            {
              "action": "bottleneck_investigation",
              "trigger": "cloudwatch_alarm",
              "alarmName": "<alarm>",
              "alarmState": "<state>"
            }
```

**特徴**:
- Event Pattern で Alarm 名フィルタリング
- InputTransformer で event を成形
- Lambda に直接渡す

**イベントフロー:**
```
CloudWatch Alarm → ALARM 状態
  ↓
EventBridge Rule (Pattern マッチ)
  ↓
InputTransformer で event 成形
  ↓
Lambda 非同期呼び出し
  ↓
FR-02 (bottleneck_investigation) 実行
```

---

## VII. パッケージング・ビルドプロセス

### A. 参照リポジトリ (CDK 自動)

```bash
cdk deploy
```

CDK が内部で自動実行:
1. TypeScript コンパイル (`lib/*.ts` → `cdk.out/`)
2. CloudFormation テンプレート生成
3. Lambda コード圧縮 (`lib/assets/lambdas/` → ZIP)
4. CloudFormation Stack デプロイ
5. Lambda 関数アップロード

**構成:**
```
cdk.out/
├── asset.1234567890abcdef.zip  # Lambda 自動 ZIP
└── BedrockAgentCDKStack.template.json
```

### B. 当プロジェクト (CodePipeline Build フェーズ)

```yaml
# cfn-pipeline.yml
build:
  commands:
    - echo "Packaging Lambda function..."
    - mkdir -p lambda_package
    - cp lib/lambda_handler.py lambda_package/lambda_function.py
    - cd lambda_package
    - pip install --target . boto3 -q
    - zip -r ../dist/lambda.zip . -q
    - cd ..
    - echo "Uploading Lambda ZIP to S3..."
    - aws s3 cp dist/lambda.zip s3://$TEMPLATE_BUCKET/lambda.zip
```

**フロー:**
```
1. Source (GitHub)
  ↓
2. Build (CodeBuild)
   ├─ Lambda ハンドラー コピー
   ├─ 依存パッケージ インストール (pip)
   ├─ ZIP パッケージング
   └─ S3 アップロード
  ↓
3. Deploy (CloudFormation)
   ├─ テンプレート読み込み (S3)
   ├─ Lambda ZIP 取得 (S3)
   └─ スタック作成
```

**特徴:**
- 明示的なビルドステップ
- 依存パッケージを明確に管理
- デバッグが容易

---

## VIII. エラーハンドリング・ロギング

### A. 参照リポジトリ

```python
# get-all-alerts.py - 基本的なエラーハンドリング
import json
import boto3 

def lambda_handler(event, context):
    try:
        # 処理
        response = cw_client.describe_alarms(...)
    except Exception as e:
        # エラーログ出力なし
        response_body = {'error': str(e)}
    
    return { 'messageVersion': '1.0', ... }
```

**特徴**:
- 例外をキャッチするが、詳細なログなし
- Bedrock Agent へエラーを返すのみ

### B. 当プロジェクト (構造化ログ)

```python
# lambda_handler.py
import logging

logger = logging.getLogger()
logger.setLevel(logging.INFO)

def lambda_handler(event, context):
    try:
        action = event.get('action', 'log_investigation')
        logger.info(f"Executing action: {action}")
        
        if action == 'log_investigation':
            return handle_log_investigation(event)
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

def handle_log_investigation(event):
    try:
        log_groups = get_log_groups_by_prefix(log_group_prefix)
        logger.info(f"Found {len(log_groups)} log groups")
    except Exception as e:
        logger.error(f"Error getting log groups: {str(e)}")
        return []
```

**特徴:**
- 全関数でロギング
- `exc_info=True` でスタックトレース記録
- 各処理段階でログ出力

---

## IX. テスト戦略

### A. 参照リポジトリ

```javascript
// jest.config.js
module.exports = {
  preset: 'ts-jest',
  testEnvironment: 'node'
}
```

テストコード提供なし。CDK Stack のスナップショットテストが可能。

### B. 当プロジェクト

```python
# tests/test_lambda_handler.py
import unittest
from unittest.mock import patch, MagicMock
import sys
sys.path.insert(0, '../lib')
from lambda_handler import (
    handle_log_investigation,
    handle_bottleneck_investigation,
    # ... 他の FR テスト
)

class TestLogInvestigation(unittest.TestCase):
    @patch('lambda_handler.logs_client')
    def test_log_investigation_found_errors(self, mock_logs):
        # Mock CloudWatch Logs 応答
        mock_logs.describe_log_groups.return_value = {
            'logGroups': [
                {'logGroupName': '/aws/lambda/test-function'}
            ]
        }
        mock_logs.filter_log_events.return_value = {
            'events': [
                {
                    'message': 'ERROR: Database connection failed',
                    'timestamp': 1234567890000
                }
            ]
        }
        
        # テスト実行
        result = handle_log_investigation({
            'log_group_prefix': '/aws/lambda/',
            'time_range_seconds': 900
        })
        
        # アサーション
        self.assertEqual(result['statusCode'], 200)
        self.assertIn('alertCount', result['body'])
```

**特徴:**
- pytest/unittest による unit テスト
- Mock で AWS API を置き換え
- 各 FR ごとにテストケース

---

## X. メトリクス・モニタリング

### A. 参照リポジトリ

CloudWatch Alarm のみ。Custom Metrics は送信しない。

### B. 当プロジェクト

```python
def put_metric_data(metric_name: str, value: float):
    """CloudWatch Custom Metric を送信"""
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
    except Exception as e:
        logger.error(f"Error putting metric data: {str(e)}")

# 各 FR で Metrics を送信
put_metric_data('LogErrors', len(alerts))          # FR-01
put_metric_data('BottleneckCount', len(bottlenecks))  # FR-02
put_metric_data('SnapshotCreated', 1)              # FR-03
put_metric_data('SlowQueriesDetected', len(queries))  # FR-05
```

**CloudWatch ダッシュボードで可視化可能:**
```
AIOps/LogErrors
AIOps/BottleneckCount
AIOps/SnapshotCreated
AIOps/SlowQueriesDetected
```

---

## まとめ：実装パターンの選択基準

| 項目 | 参照リポジトリ | 当プロジェクト |
|------|---|---|
| **言語** | TypeScript | Python |
| **Lambda 関数設計** | マイクロサービス | 統合型 |
| **API Schema** | OpenAPI (必須) | event['action'] |
| **Bedrock 統合** | Custom Resource | 宣言的 (YAML) |
| **Knowledge Base** | 手動作成 | 自動化 |
| **EventBridge** | 未実装 | 完全統合 |
| **ログレベル** | 基本的 | 構造化ログ |
| **テスト** | なし | pytest |
| **メトリクス** | なし | Custom Metrics |

