# AIOps 基盤（Bedrock Agents）構築ガイド（CloudFormation + Python Lambda 版）

> **対象**：このリポジトリの開発者・運用担当者  
> **目的**：**CDK を使わず**に CloudFormation + CodePipeline を利用して Bedrock‑AIOps ソリューションを構築・検証する際に必要な手順をまとめたファイルです。  
> **備考**：AWS CLI で CloudFormation を直接操作することは禁止。すべて CodePipeline で管理します。  
> **言語**：Lambda ハンドラは Python 3.11/3.12 で実装。Node.js ではなく Python を使用。

---

## 🎯 システムユースケース - 3 つの入力モード

このシステムは **ユーザー入力がオプション**です。以下の 3 つのモードで動作します：

### **モード 1: Bedrock Agent（対話型・ユーザー入力）✅ 必須**

ユーザーが AWS Console または Bedrock Agent API を通じて直接質問を入力

```
ユーザー: 「EC2 の CPU が高いです。調査してください」
    ↓
Bedrock Agent:
  1. Knowledge Base（ランブック）検索：EC2 CPU 関連ドキュメント
  2. Agent プロンプトに基づき優先度順に実行：
     - FR-02: ボトルネック調査（CloudWatch メトリクス分析）
     - FR-01: ログ調査（CloudWatch Logs 検索）
  3. Lambda を呼び出し、調査実行
  4. 結果を JSON で返却
  5. SNS で関連チームに通知
```

**特徴**：
- 対話的でユーザー驅動
- Agent プロンプト最適化が効果的
- 動的な問題解決

---

### **モード 2: EventBridge + CloudWatch Alarms（自動トリガー）✅ ユーザー入力不要**

CloudWatch Alarms が ALARM 状態に遷移すると自動的に Lambda を呼び出す

```
CloudWatch Alarm: EC2-HighCPU-i-1234567890abcdef0 → ALARM
    ↓
EventBridge Rule (EC2-HighCPU-*)
    ↓
Lambda Invoke with InputTransformer:
  {
    "action": "bottleneck_investigation",
    "alarmName": "EC2-HighCPU-i-1234567890abcdef0",
    "trigger": "cloudwatch_alarm"
  }
    ↓
FR-02: ボトルネック調査 自動実行
    ↓
SNS 通知
```

**トリガー対応表**：

| CloudWatch アラーム名 | 対応 FR | 説明 |
|-------------------|--------|------|
| `EC2-HighCPU-*` | FR-02 | EC2 CPU が高い |
| `RDS-HighCPU-*` | FR-02 | RDS CPU が高い |
| `RDS-HighConnections-*` | FR-05 | RDS 接続数超過 |
| `RDS-ReplicationLag-*` | 特定アクション | RDS レプリケーション遅延 |
| `Lambda-ErrorRate-*` | FR-01 | Lambda エラー率高 |
| `Lambda-Throttle-*` | 特定アクション | Lambda スロットル発生 |

**特徴**：
- リアルタイム自動対応
- ユーザー入力なし
- CloudWatch アラーム定義が前提（ユーザーが作成）

**アラーム作成例**：
```bash
# EC2 高 CPU アラーム（80%を超える状態が 2 期間以上続く）
aws cloudwatch put-metric-alarm \
  --alarm-name EC2-HighCPU-i-1234567890abcdef0 \
  --alarm-description "EC2 instance CPU > 80%" \
  --metric-name CPUUtilization \
  --namespace AWS/EC2 \
  --statistic Average \
  --period 300 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2 \
  --dimensions Name=InstanceId,Value=i-1234567890abcdef0
```

---

### **モード 3: Lambda Cron（定期バッチ実行）⏳ 実装予定・ユーザー入力不要**

毎週日曜日 00:00 UTC に自動実行

```
EventBridge ScheduleRule: cron(0 0 ? * SUN *)
    ↓
Lambda Invoke:
  {
    "action": "slow_query_detection",  # FR-05
    "trigger": "batch_schedule"
  }
  AND
  {
    "action": "high_load_query_detection",  # FR-06
    "trigger": "batch_schedule"
  }
    ↓
RDS Performance Insights API:
  - 過去 1 週間のスローク分析
  - 高負荷クエリを検出
    ↓
SNS 通知:
  - SlowQueryReport
  - HighLoadQueryReport
```

**特徴**：
- 完全自動実行
- ユーザー入力なし
- 予測的メンテナンス
- 毎週同じ時刻に実行

**実装**：
```yaml
# EventBridge ScheduleRule（未実装、今後追加）
EventBridgeScheduleRule:
  Type: AWS::Events::Rule
  Properties:
    ScheduleExpression: cron(0 0 ? * SUN *)  # 毎週日曜 00:00 UTC
    Targets:
      - Arn: !Ref LambdaFunctionArn
        RoleArn: !GetAtt EventBridgeInvokeRole.Arn
        Input: |
          {
            "action": "slow_query_detection",
            "trigger": "batch_schedule"
          }
```

---

### **📊 まとめ：3 モードの比較**

| 項目 | モード 1（Agent） | モード 2（EventBridge） | モード 3（Cron） |
|------|-----------------|----------------------|-----------------|
| **入力方式** | ユーザー質問 | CloudWatch アラーム | スケジュール |
| **ユーザー入力** | ✅ **必須** | ❌ 不要 | ❌ 不要 |
| **トリガー条件** | ユーザーが質問 | アラーム状態 = ALARM | 毎週日曜 00:00 UTC |
| **実装状態** | ✅ 完了 | ✅ 完了 | ⏳ 実装予定 |
| **特徴** | 対話的・動的 | リアルタイム・自動 | 定期・予測的 |
| **Agent プロンプト適用** | ✅ 適用 | ❌ 使用されない | ❌ 使用されない |
| **事前準備** | 不要 | CloudWatch アラーム定義 | EventBridge Schedule |

---

## 1. 事前準備

| ステップ | コマンド/確認事項 | 備考 |
|------|-----------|------|
| 1 | `git clone <repo-url>` | プロジェクトをローカルにクローン |
| 2 | `cd aiops-alert` | ルートディレクトリへ移動 |
| 3 | （CloudFormation テンプレート確認） | `cfn-templates/main.yaml` が存在することを確認 |
| 4 | **S3 バケット作成** | `aws s3 mb s3://dev-image-aiagent-artifact --region ap-northeast-1` |
| 5 | **テンプレートをS3へアップロード** | `aws s3 cp cfn-templates/ s3://dev-image-aiagent-artifact/cfn-templates/ --recursive` |
| 6 | **GitHub 接続確認** | GitHub Personal Access Token が AWS Secrets Manager に保存されていることを確認 |
| 7 | **CodePipeline パイプライン起動** | GitHub にコミット＆プッシュ → CodePipeline が自動トリガー → CloudFormation デプロイ |

> ⚠️ **IAM 権限**  
>  - CodePipeline の実行ロールに `cloudformation:*`, `s3:*`, `lambda:*`, `bedrock:*`, `opensearch:*` を付与。  
>  - `aws configure` で `default` プロファイル（または `dev`）を設定しておいてください。

---

## 2. CloudFormation テンプレート構造

```
cfn-templates/
├── main.yaml                  # ルートスタック（すべてのネストを統合）
├── kms.yaml                   # KMS キー（オプション）
├── s3.yaml                    # S3 バケット（既存/作成分岐）
├── opensearch.yaml            # OpenSearch Serverless データベース
├── lambda-function.yaml       # Lambda 関数定義
├── bedrock-agent.yaml         # Bedrock Agent + IAM Role
├── knowledge-base.yaml        # Bedrock Knowledge Base + IAM Role
├── action-group.yaml          # Lambda ベースのアクションハンドラ
├── security-groups.yaml       # 必要なら VPC SG
└── eventbridge-alarms.yaml    # EventBridge CloudWatch Alarms トリガー
```

> **ポイント**  
> - `main.yaml` は全ネストスタックを統合し、パラメータを下位テンプレートに渡す。
> - 各テンプレートは `Outputs` でリソース ARN をエクスポート。
> - IAM Role は各テンプレートに含まれ、最小権限で構成。
> - Bedrock Agent はKnowledgeBase と ActionGroup を統合。

---

## 3. Lambda パッケージ化（CodePipeline 自動化）

### Lambda パッケージング処理は CodePipeline に統合されています

CodePipeline の BuildSpec に Lambda パッケージング処理が組み込まれました：

```yaml
# cfn-pipeline.yml の Build フェーズで自動実行
build:
  commands:
    - echo "Packaging Lambda function..."
    - mkdir -p dist
    - |
      if [ -f "lib/lambda_handler.py" ]; then
        mkdir -p lambda_package
        cp lib/lambda_handler.py lambda_package/lambda_function.py
        cd lambda_package
        pip install --target . boto3 -q
        zip -r ../dist/lambda.zip . -q
        cd ..
      fi
    - echo "Uploading Lambda ZIP to S3..."
    - |
      if [ -f "dist/lambda.zip" ]; then
        aws s3 cp dist/lambda.zip s3://$TEMPLATE_BUCKET/lambda.zip
      fi
```

**処理の流れ:**
1. `lib/lambda_handler.py` を `lambda_function.py` にリネーム
2. `boto3` 等の依存パッケージをダウンロード
3. `dist/lambda.zip` を作成
4. S3 にアップロード（`$TEMPLATE_BUCKET` = `dev-image-aiagent-artifact`）
5. CloudFormation が S3 から取得して Lambda デプロイ

> **重要**：Lambda ZIP ファイルは手動で作成・アップロードせず、CodePipeline が自動的に処理します。

---

## 4. ビルドパイプラインの実行フロー

```
【1】GitHub Push
     ↓
【2】CodePipeline トリガー
     ├─ Source: GitHub からコード取得
     ├─ Build: CodeBuild 実行
     │  ├─ Lambda パッケージ化 (lib/lambda_handler.py → dist/lambda.zip)
     │  ├─ dist/lambda.zip を S3 にアップロード
     │  ├─ CloudFormation テンプレートを S3 にコピー
     │  └─ パラメータファイルを更新
     └─ Deploy: CloudFormation
        ├─ main.yaml を S3 から取得
        ├─ ネストスタックを実行
        ├─ S3 から lambda.zip を取得して Lambda デプロイ
        ├─ Bedrock Agent を作成
        └─ OpenSearch, Knowledge Base を構築
```

---

## 5. Bedrock Knowledge Base の構築

### 5.1 CloudFormation による Knowledge Base 自動作成

`knowledge-base.yaml` で Knowledge Base を自動作成します。必須プロパティ：

```yaml
Resources:
  BedrockKnowledgeBase:
    Type: AWS::Bedrock::KnowledgeBase
    Properties:
      Name: aiops-knowledge-base
      Description: Knowledge base for AIOps investigation and remediation
      RoleArn: !GetAtt KnowledgeBaseRole.Arn
      KnowledgeBaseConfiguration:
        Type: VECTOR
        VectorKnowledgeBaseConfiguration:
          EmbeddingModelArn: !Ref EmbeddingModelArn  # Titan Embed v2
      StorageConfiguration:
        Type: OPENSEARCH_SERVERLESS
        OpensearchServerlessConfiguration:
          CollectionArn: !GetAtt OpensearchCollection.CollectionArn
          VectorIndexName: aiops-kb-index
          FieldMapping:
            VectorField: vector
            TextField: text
            MetadataField: metadata
```

**出力：**
- `KnowledgeBaseId`：Knowledge Base ID（データソース作成時に使用）
- `KnowledgeBaseArn`：Knowledge Base ARN

---

### 5.2 CloudFormation による Data Source 作成

Knowledge Base と同じテンプレートで Data Source を作成：

```yaml
  BedrockDataSource:
    Type: AWS::Bedrock::DataSource
    DependsOn: BedrockKnowledgeBase
    Properties:
      Name: aiops-data-source
      KnowledgeBaseId: !Ref BedrockKnowledgeBase
      Description: S3 data source for AIOps runbooks and documentation
      DataSourceConfiguration:
        Type: S3
        S3Configuration:
          BucketArn: !Sub 'arn:aws:s3:::${DataSourceBucket}'
          InclusionPrefixes:
            - runbooks/
            - documentation/
```

**出力：**
- `DataSourceId`：Data Source ID（文書インジェスト時に使用）

---

### 5.3 S3 に Runbook・Documentation をアップロード

```bash
# ローカルから S3 へアップロード
aws s3 cp runbooks/ s3://dev-image-aiagent-artifact/runbooks/ --recursive
aws s3 cp docs/ s3://dev-image-aiagent-artifact/documentation/ --recursive
```

**対応ファイル形式：**
- PDF（`.pdf`）
- Markdown（`.md`）
- Text（`.txt`）
- Word（`.docx`）
- CSV（`.csv`）

---

### 5.4 文書インジェスト（API で直接登録）

CloudFormation デプロイ後、以下のコマンドで文書をインジェストします：

#### **方法 1：S3 から直接参照**

```bash
aws bedrock-agent ingest-knowledge-base-documents \
  --knowledge-base-id KB123456789012 \
  --data-source-id DS123456789012 \
  --documents '[
    {
      "content": {
        "dataSourceType": "S3",
        "s3": {
          "uri": "s3://dev-image-aiagent-artifact/runbooks/ec2-investigation.md"
        }
      },
      "metadata": {
        "inlineAttributes": [
          {
            "key": "category",
            "value": {"stringValue": "EC2", "type": "STRING"}
          },
          {
            "key": "priority",
            "value": {"numberValue": 1, "type": "NUMBER"}
          }
        ],
        "type": "IN_LINE_ATTRIBUTE"
      }
    }
  ]'
```

#### **方法 2：テキストをインライン定義**

```bash
aws bedrock-agent ingest-knowledge-base-documents \
  --knowledge-base-id KB123456789012 \
  --data-source-id DS123456789012 \
  --documents '[
    {
      "content": {
        "dataSourceType": "CUSTOM",
        "custom": {
          "customDocumentIdentifier": {"id": "doc-001"},
          "inlineContent": {
            "type": "TEXT",
            "textContent": {"data": "# EC2 Investigation Guide\n\n## Steps:\n1. Check instance status\n2. Review CloudWatch metrics\n3. Execute remediation"}
          },
          "sourceType": "IN_LINE"
        }
      }
    }
  ]'
```

---

### 5.5 ベクトル化と検索準備

ドキュメントがアップロードされると、Bedrock が自動的に以下を実行します：

1. **ベクトル化**：Embedding Model（Titan v2）が各ドキュメントをベクトル化
2. **OpenSearch Serverless へ保存**：ベクトルを OpenSearch インデックスに保存
3. **メタデータ関連付け**：ドキュメントのメタデータを保存

**状態確認：**

```bash
aws bedrock-agent describe-knowledge-base \
  --knowledge-base-id KB123456789012 \
  --query 'knowledgeBase.status'

# 出力: ACTIVE（検索可能）
```

---

### 5.6 Knowledge Base 統合（Agent）

Bedrock Agent が Knowledge Base を使用する設定：

```yaml
# bedrock-agent.yaml
Resources:
  BedrockAgent:
    Type: AWS::Bedrock::Agent
    Properties:
      AgentName: AiopsAgent
      KnowledgeBases:
        - KnowledgeBaseId: !Ref KnowledgeBaseId
          Description: AIOps investigation guide
      # ... 他の設定
```

---

### 5.7 API で Knowledge Base を照会（RAG）

Agent が以下を自動実行：

```python
# Lambda ハンドラ内
response = bedrock_agent_runtime.retrieve_and_generate(
    input={"text": "EC2 インスタンスの高 CPU 使用率を調査する手順"},
    knowledgeBaseId="KB123456789012",
    modelArn="arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
    retrievalConfiguration={
        "vectorSearchConfiguration": {
            "numberOfResults": 5,
            "overrideSearchType": "SEMANTIC"
        }
    }
)
```

---

### 5.8 トラブルシューティング

| 問題 | 原因 | 解決策 |
|------|------|--------|
| `KnowledgeBaseNotFound` | Knowledge Base ID が誤っている | `aws bedrock-agent describe-knowledge-base` で確認 |
| `DataSourceNotFound` | Data Source ID が誤っている | Knowledge Base の Data Sources を確認 |
| ベクトル化が遅い | 大量ドキュメント | 数分待機、CloudWatch Logs で進行状況確認 |
| 検索精度が低い | メタデータ不足 | `metadata` を追加して再インジェスト |
| `AccessDenied` | IAM 権限不足 | KnowledgeBaseRole に `bedrock:*` 権限を付与 |

> **注意**：ドキュメント更新時、同じ `id` で再度インジェストするとドキュメントが置き換わります。

### 5.5 シンプル版：メタデータなしでの文書インジェスト（推奨）

当初段階ではメタデータを付与せず、シンプルに S3 URI でドキュメントを取り込むことを推奨します。セマンティック検索で十分な精度が得られます：

```bash
# シンプル版：メタデータなし
aws bedrock-agent ingest-knowledge-base-documents \
  --knowledge-base-id KB123456789012 \
  --data-source-id DS123456789012 \
  --documents '[
    {
      "content": {
        "dataSourceType": "S3",
        "s3": {
          "uri": "s3://dev-image-aiagent-artifact/runbooks/FR-01-log-investigation.md"
        }
      }
    }
  ]'
```

**メタデータ付与のタイミング（後追加推奨）：**
- 複数ドメイン（EC2、RDS、Lambda など）が増加時
- クエリ精度が低下した場合
- カテゴリ別フィルタリングが必要になった場合

---

### 5.6 サンプルランブック（FR-01～FR-06）

プロジェクトには 6 つのサンプルランブック（Markdown）が提供されています：

| ファイル | カテゴリ | 優先度 | 対象サービス |
|---------|--------|-------|-----------|
| `runbooks/FR-01-log-investigation.md` | Log Investigation | 1 | EC2, Lambda, RDS |
| `runbooks/FR-02-bottleneck-investigation.md` | Bottleneck Investigation | 1 | EC2, RDS, Lambda |
| `runbooks/FR-03-create-db-snapshot.md` | Database Operations | 2 | RDS |
| `runbooks/FR-04-maintenance-display.md` | Maintenance Management | 2 | RDS, Systems Manager |
| `runbooks/FR-05-slow-query-detection.md` | Database Performance | 1 | RDS |
| `runbooks/FR-06-high-load-query-detection.md` | Database Performance | 1 | RDS |

**ランブックには以下が含まれています：**
- 概要、前提条件
- ステップバイステップの手順
- AWS CLI/SQL コマンド例
- トラブルシューティング
- 参考リンク

**Knowledge Base へのインジェスト方法（ランブック 1 つの例）：**

```bash
aws bedrock-agent ingest-knowledge-base-documents \
  --knowledge-base-id KB123456789012 \
  --data-source-id DS123456789012 \
  --documents '[
    {
      "content": {
        "dataSourceType": "S3",
        "s3": {
          "uri": "s3://dev-image-aiagent-artifact/runbooks/FR-01-log-investigation.md"
        }
      }
    }
  ]'
```

すべてのランブックをインジェストする場合は、`runbooks/bedrock-ingest-template.json` を参照してください。

---

### 5.7 ドキュメント Metadata（オプション）

**Metadata スキーマ**（`runbooks/metadata.json` で定義）：

```json
{
  "category": "STRING",           // Log Investigation, Bottleneck Investigation など
  "priority": "NUMBER",            // 1: High, 2: Medium, 3: Low
  "service": "STRING_LIST",        // EC2, RDS, Lambda など
  "difficulty": "STRING",          // Low, Medium, High
  "resolution_time_minutes": "NUMBER"  // 推定解決時間
}
```

**将来的にメタデータを使用する場合の例（RAG クエリ時）：**

```python
# メタデータフィルタリング付き RAG 検索
response = bedrock_agent_runtime.retrieve_and_generate(
    input={"text": "RDS の高 CPU 問題を解決したい"},
    knowledgeBaseId="KB123456789012",
    modelArn="arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
    retrievalConfiguration={
        "vectorSearchConfiguration": {
            "numberOfResults": 5,
            "overrideSearchType": "SEMANTIC",
            "filter": {
                "equals": {
                    "key": "service",
                    "value": "RDS"
                }
            }
        }
    }
)
```

---

## 6. EventBridge CloudWatch Alarms トリガー

### 6.1 概要

リアルタイムでシステム異常を検出し、Lambda を自動トリガーする EventBridge ルールを提供します。

**対応するアラーム：**
- EC2 高 CPU 使用率
- RDS 高 CPU 使用率
- RDS 接続数超過
- RDS レプリケーションラグ
- Lambda エラー率
- Lambda スロットル

### 6.2 CloudFormation テンプレート

`cfn-templates/eventbridge-alarms.yaml` に以下が含まれます：

```yaml
Resources:
  EC2HighCPUAlarmRule:
    Type: AWS::Events::Rule
    # CloudWatch アラーム名が "EC2-HighCPU" で始まるアラームをトリガー
    
  RDSHighCPUAlarmRule:
    Type: AWS::Events::Rule
    # CloudWatch アラーム名が "RDS-HighCPU" で始まるアラームをトリガー
    
  # ... その他 5 つのアラームルール
```

**main.yaml への統合：**
```yaml
EventBridgeAlarmsStack:
  Type: AWS::CloudFormation::Stack
  Properties:
    TemplateURL: !Sub 'https://s3.${AWS::Region}.amazonaws.com/${TemplateBucketName}/cfn-templates/eventbridge-alarms.yaml'
    Parameters:
      LambdaFunctionArn: !GetAtt LambdaStack.Outputs.LambdaARN
      Environment: !Ref EnvName
```

### 6.3 アラーム命名規則

EventBridge が検出するアラーム名のプレフィックス：

| アラームタイプ | プレフィックス | 例 |
|-------------|-----------|-----|
| EC2 高 CPU | `EC2-HighCPU` | `EC2-HighCPU-i-1234567890abcdef0` |
| RDS 高 CPU | `RDS-HighCPU` | `RDS-HighCPU-prod-order-db` |
| RDS 接続数 | `RDS-HighConnections` | `RDS-HighConnections-prod-order-db` |
| RDS レプリケーション遅延 | `RDS-ReplicationLag` | `RDS-ReplicationLag-prod-order-db` |
| Lambda エラー | `Lambda-ErrorRate` | `Lambda-ErrorRate-aiops-lambda` |
| Lambda スロットル | `Lambda-Throttle` | `Lambda-Throttle-aiops-lambda` |

**CloudWatch アラーム作成例：**

```bash
# EC2 高 CPU アラーム作成
aws cloudwatch put-metric-alarm \
  --alarm-name EC2-HighCPU-i-1234567890abcdef0 \
  --alarm-description "EC2 instance CPU usage > 80%" \
  --metric-name CPUUtilization \
  --namespace AWS/EC2 \
  --statistic Average \
  --period 300 \
  --threshold 80 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 2 \
  --dimensions Name=InstanceId,Value=i-1234567890abcdef0 \
  --alarm-actions arn:aws:sns:ap-northeast-1:123456789012:topic-name
```

### 6.4 Lambda への入力フォーマット

EventBridge から Lambda へ渡されるペイロード例：

```json
{
  "action": "bottleneck_investigation",
  "trigger": "cloudwatch_alarm",
  "alarmName": "EC2-HighCPU-i-1234567890abcdef0",
  "alarmState": "ALARM",
  "alarmDescription": "EC2 instance CPU usage > 80%",
  "timestamp": "2026-06-04T10:30:00Z"
}
```

Lambda ハンドラがこの入力を受け取り、対応する関数（FR-01～FR-06）を実行します。

---

## 7. アクショングループの作成

`action-group.yaml` に Lambda ベースのアクション定義を記述：

```yaml
Resources:
  ActionGroupLambdaFunction:
    Type: AWS::Lambda::Function
    Properties:
      Handler: lambda_function.lambda_handler
      Code:
        S3Bucket: !Ref TemplateBucketName
        S3Key: lambda.zip
      # アクション:
      # - log_investigation: CloudWatch Logs 検索
      # - bottleneck_investigation: メトリクス分析
      # - create_snapshot: RDS スナップショット作成
      # - maintenance_display: メンテナンスウィンドウ表示
      # - slow_query_detection: 遅いクエリ検出
      # - high_load_query_detection: 高負荷クエリ分析
```

> **重要**：`bedrock-agent.yaml` は `ActionGroups` プロパティで Lambda を参照。S3 バケットは `TemplateBucketName` パラメータから動的に参照。

---

## 8. Lambda 関数の実装（FR‑01～FR‑06）

`lib/lambda_handler.py` に実装：

| FR | 機能 | 入力 | 出力 |
|-------|-----------|------|------|
| **FR‑01** | ログ調査 | `action: 'log_investigation'` | `LogInvestigationReport` SNS |
| **FR‑02** | ボトルネック調査 | `action: 'bottleneck_investigation'` | `BottleneckReport` SNS |
| **FR‑03** | DB スナップショット作成 | `action: 'create_snapshot'` | `SnapshotReport` SNS |
| **FR‑04** | メンテナンスウィンドウ表示 | `action: 'maintenance_display'` | `MaintenanceReport` SNS |
| **FR‑05** | 遅いクエリ検出 | `action: 'slow_query_detection'` | `SlowQueryReport` SNS |
| **FR‑06** | 高負荷クエリ分析 | `action: 'high_load_query_detection'` | `HighLoadQueryReport` SNS |

---

## 9. エラー対策（実行時）

| エラー | 原因 | 改善策 |
|--------|------|--------|
| `AccessDeniedException` | Bedrock IAM Role の権限不足 | `bedrock:InvokeModel` と `s3:GetObject` を付与 |
| `ValidationError: Parameter validation failed` | CloudFormation テンプレートの式ミス | `cfn-lint cfn-templates/*.yaml` で検証 |
| `OpenSearchServerless:ServiceLimitExceededException` | リソース制限 | `opensearch:UpdateLimits` で上限調整 |
| `Lambda: package size too large` | ZIP ファイルが大きすぎる | 不要なファイルをZIPから除外 |

> `cfn-lint` でテンプレート検証は必須です。  
> ```bash
> pip install cfn-lint
> cfn-lint cfn-templates/*.yaml
> ```

---

## 10. CodePipeline でのスタックデプロイ・更新・削除

| 目的 | 実行手順 | 備考 |
|------|----------|------|
| **デプロイ** | git commit → git push → CodePipeline 自動トリガー → CloudFormation デプロイ | 初回デプロイ時はパイプラインを起動 |
| **更新** | テンプレートまたはLambda関数を修正 → git commit → git push → 自動デプロイ | CLI での `deploy` は使用不可 |
| **削除** | AWS Console から CloudFormation Stack を削除、または CodePipeline の削除ステージを実行 | すべてのネストスタックと関連リソースが削除されます |

> **重要**：CLI で `aws cloudformation deploy/delete-stack` を実行してはなりません。すべての CloudFormation 操作は CodePipeline が実行します。

---

## 11. CloudFormation テンプレート検証（CLI）

| コマンド | 使い道 |
|----------|--------|
| `cfn-lint cfn-templates/*.yaml` | CloudFormation テンプレートを検証 |
| `pip install cfn-lint` | cfn-lint をインストール |

> **Tip**：`aws configure` で `default` プロファイル（または `dev`）を設定しておくと `aws` コマンドは自動でプロファイルを拾います。

---

## 12. Bedrock Agent プロンプト最適化

### 12.1 目的

Bedrock Agent の Instruction パラメータを最適化することで：
- 複数機能（FR-01～06）の優先度を明確化
- Knowledge Base（ランブック）活用のガイダンス
- ユーザー質問への対応パターンを統一
- JSON 形式の返答・機密情報保護の制約を明確化

### 12.2 現在のプロンプト戦略（日本語版）

Bedrock Agent には以下の指示が設定されています：

```
あなたは AWS インフラストラクチャの自動運用（AIOps）を支援するアシスタントです。

## 主な責務
1. インフラの問題を迅速に診断する
2. ボトルネックを特定し、根本原因を分析する
3. ランブックに基づいた自動復旧アクションを実行する
4. リアルタイムアラート（CloudWatch）に対応する

## 対象システム
- EC2 インスタンス（CPU/メモリ/ディスク）
- Amazon RDS（MySQL/PostgreSQL）
  - CPU 使用率・コネクション数・レプリケーションラグ
  - 遅いクエリ・高負荷クエリ
- AWS Lambda（エラー率・スロットル）

## アクション実行の優先度（高→低）
1. **FR-01: ログ調査** - CloudWatch Logs から最新エラーを検索。まずはこれで問題を特定。
2. **FR-02: ボトルネック調査** - CloudWatch メトリクスから CPU/メモリ/接続を分析。
3. **FR-05: 遅いクエリ検出** - RDS Performance Insights で DB クエリ性能を確認。
4. **FR-06: 高負荷クエリ分析** - 複数クエリの影響度を測定。
5. **FR-03: DB スナップショット作成** - 問題発生時のデータ保全。緊急時のみ。
6. **FR-04: メンテナンスウィンドウ表示** - 予防的なシステムチェック。非緊急時。

## Knowledge Base（ランブック）の活用
- ユーザーの質問に対して、まず Knowledge Base から関連ランブックを検索する。
- セマンティック検索を活用し、問い合わせの意図に最も近いランブックを優先する。
- ランブックに記載されたステップを用いて調査・復旧手順を説明する。

## ユーザー質問への対応パターン
- **「EC2 の CPU が高い」** → FR-02 (ボトルネック) → FR-01 (ログ確認) → 復旧案提示
- **「RDS が遅い」** → FR-05 (遅いクエリ検出) → FR-02 (リソース分析) → クエリ最適化案
- **「アラートが発火した」** → 対応するランブックを検索 → 即座にアクション実行

## 返答形式
- 常に JSON 形式で返答する。
- 調査結果・アクション内容・推奨事項を明確に分離する。
- 可能な限り具体的な数値・メトリクス・根本原因を含める。

## 制約・注意点
- 機密情報（DB パスワード・API キー）は返答に含めない。
- 実行権限外のアクションは提案しない。
- 調査完了後、常に SNS で関連チームに通知する。
- タイムアウトは 60 秒。時間がかかる調査は非同期で実行し、Job ID を返す。
```

### 12.3 プロンプト更新の方法

#### **方法 1：CloudFormation テンプレートで直接編集**

`bedrock-agent.yaml` の `Instruction` パラメータを編集：

```yaml
Parameters:
  Instruction:
    Type: String
    Default: |
      あなたは AWS インフラストラクチャの自動運用（AIOps）を支援するアシスタントです。
      ...（プロンプト本文）
    Description: Agentへの指示プロンプト（日本語版）
```

#### **方法 2：パラメータファイルで管理**

`cfn-dev-parameters.json` に `Instruction` パラメータを定義（推奨）：

```json
{
  "Parameters": {
    "Instruction": "あなたは AWS インフラストラクチャの自動運用（AIOps）を支援するアシスタントです。..."
  }
}
```

> **メリット**：環境ごとにプロンプトを切り替え可能。例：`cfn-dev-parameters.json`, `cfn-prod-parameters.json` で異なるプロンプトを指定。

### 12.4 プロンプト変更後の反映

1. **ファイル編集**
   ```bash
   # bedrock-agent.yaml または cfn-dev-parameters.json を編集
   ```

2. **Git コミット**
   ```bash
   git add cfn-templates/bedrock-agent.yaml cfn-dev-parameters.json
   git commit -m "Optimize Bedrock Agent prompt with Japanese instructions"
   git push origin main
   ```

3. **CodePipeline 自動トリガー**
   - GitHub push → CodePipeline Start → CloudFormation Update
   - 既存 Agent が新しいプロンプトで置き換わる

4. **Agent の確認**
   ```bash
   aws bedrock-agent get-agent \
     --agent-id <AGENT_ID> \
     --region ap-northeast-1 \
     --query 'agent.instruction' \
     --output text
   ```

### 12.5 ベストプラクティス

| ガイドライン | 説明 |
|-----------|------|
| **簡潔性** | 1000 字以内に保つ（過度に長いと理解度が低下） |
| **優先度明記** | 6 つの FR の実行順序を明示的に列挙 |
| **RAG 活用** | Knowledge Base（ランブック）検索を明記 |
| **制約記述** | 機密情報・権限範囲・タイムアウトを明記 |
| **返答形式** | JSON・言語・詳細度を指定 |
| **テスト** | 更新後、Bedrock Agent テスト画面で動作確認 |

### 12.6 カスタマイズ例

#### **例 1：本番環境用プロンプト（より厳格）**

```json
{
  "Instruction": "...本番環境では、FR-03/FR-04 は禁止。アラート対応のみ実行。..."
}
```

#### **例 2：開発環境用プロンプト（詳細ログ）**

```json
{
  "Instruction": "...開発環境では、すべてのアクション実行結果を詳細ログ出力..."
}
```

---

## 13. よくある質問

| 質問 | 回答 |
|------|------|
| **Q**：CloudFormation テンプレートは JSON で書くべき？ | **A**：YAML の方が可読性が高く Git の差分と比較しやすいので推奨。 |
| **Q**：Bedrock Agent のプロンプトはどうやってカスタマイズ？ | **A**：`bedrock-agent.yaml` の `Instruction` パラメータで直接編集。Git コミット後に CodePipeline で反映。または `cfn-dev-parameters.json` で環境別に管理。 |
| **Q**：OpenSearch Serverless でデータの削除は？ | **A**：`aws opensearch delete-collection` または CloudFormation で `OpensearchCollection` リソースを削除。 |
| **Q**：Lambda 関数のコードを修正したい | **A**：`lib/lambda_handler.py` を修正 → git push → CodePipeline が自動で `dist/lambda.zip` を作成・デプロイ |
| **Q**：S3 バケット名が環境ごとに異なるのは？ | **A**：`cfn-*-parameters.json` の `TemplateBucketName` パラメータで指定。Pipeline が自動で参照。 |
| **Q**：Lambda がタイムアウトする | **A**：`lambda-function.yaml` の `Timeout` を増やす（デフォルト 300秒） |
| **Q**：Agent プロンプトを環境別に切り替えたい | **A**：`cfn-dev-parameters.json` で dev 環境、`cfn-prod-parameters.json` で本番環境のプロンプトを指定。CloudFormation はパラメータファイルから自動読み込み。 |

---

## 14. 変更履歴

| バージョン | 日付 | 内容 |
|------------|------|------|
| v1.0.0 | 2026‑06‑02 | CDK 版から CloudFormation 版へ完全移行 |
| v1.1.0 | 2026‑06‑05 | アクショングループ OpenAPI 定義を追加 |
| v1.2.0 | 2026‑06‑10 | `ap-northeast-1` での動作を追加し、CLI で CFN 操作を禁止。CodePipeline を推奨。 |
| v2.0.0 | 2026‑06‑14 | **Python Lambda に統合** + **CodePipeline ビルドに Lambda パッケージング処理を追加** + **main.yaml への統合** |
| v2.1.0 | 2026‑06‑20 | **FoundationModel を Claude Sonnet から Haiku 4.5 に変更** + **main.yaml の TemplateURL を動的参照に修正** + **TemplateBucketName パラメータを追加** + **不要な package.json と package-lambda.sh を削除** |
| v2.2.0 | 2026‑06‑04 | **サンプルランブック作成（FR-01～FR-06）** + **Metadata 定義追加** + **EventBridge CloudWatch Alarms トリガー実装** + **AGENTS.md セクション 5-7 更新** |
| v2.3.0 | 2026‑06‑04 | **Bedrock Agent プロンプト最適化（日本語版）** + **優先度付きアクション実行ガイド追加** + **Knowledge Base ランブック検索の明記** + **ユーザー対応パターンの統一** + **AGENTS.md セクション 12 新規追加** |
| v2.4.0 | 2026‑06‑04 | **システムユースケース - 3 つの入力モード説明追加** + **モード 1（Bedrock Agent：ユーザー入力必須）** + **モード 2（EventBridge：自動トリガー）** + **モード 3（Lambda Cron：定期バッチ）** + **AGENTS.md セクション 0 新規追加（目次直後）** |

> 変更があった際は必ず `push` 先に `AGENTS.md` を更新し、全員が最新の手順を参照できるようにしてください。
