# AIOps 基盤（Bedrock Agents）構築ガイド（CloudFormation + Python Lambda 版）

> **対象**：このリポジトリの開発者・運用担当者  
> **目的**：**CDK を使わず**に CloudFormation + CodePipeline を利用して Bedrock‑AIOps ソリューションを構築・検証する際に必要な手順をまとめたファイルです。  
> **備考**：AWS CLI で CloudFormation を直接操作することは禁止。すべて CodePipeline で管理します。  
> **言語**：Lambda ハンドラは Python 3.11/3.12 で実装。Node.js ではなく Python を使用。
> **根拠**: AWS ブログ "Automate IT operations with Amazon Bedrock Agents"（著者: Upendra V, Deepak Dixit）  
> **アーキテクチャ**: ブログの「解決策アーキテクチャ」図に基づく統一設計

---

## 🎯 システムアーキテクチャ - 統一パイプライン

ブログが示す「解決策アーキテクチャ」に基づいています：

**すべてのトリガーが同じ Lambda 関数と Bedrock Agent パイプラインを通ります**

```
【複数のトリガー】
ユーザー入力 / CloudWatch Alarms / スケジュール実行
    ↓ (統一入口: 同一の Lambda 関数)
Lambda: extract_event_info(event)
    ├─ AWS 公式フィールド抽出
    │  ├─ source: "aws.cloudwatch", "aws.events"
    │  ├─ detail-type: イベント種別
    │  ├─ detail: イベント詳細
    │  └─ time: タイムスタンプ
    ↓
Lambda: build_prompt(event_info)
    └─ 統一 prompt 構築（Bedrock Agent が判定）
    ↓
Bedrock Agent (Claude Haiku 4.5)
    ├─ Knowledge Base 検索 (RAG)
    │  ├─ CloudWatch Alarms: アラーム対応ランブック
    │  └─ Cron: 定期メンテナンスランブック
    ├─ 【判定】このアラームに対応すべきか
    ├─ 【判定】定期メンテナンスを実行すべきか
    ├─ Action Group で実行対象 Lambda を判定
    └─ パラメータ設定して Lambda 呼び出し
        ↓
Lambda 実行 (FR-01～FR-06)
    ├─ ログ調査
    ├─ ボトルネック調査
    ├─ スナップショット作成
    ├─ メンテナンスウィンドウ表示
    ├─ スロークエリ検出
    └─ 高負荷クエリ分析
        ↓
SNS 通知
```

**重要な変更：**
- ✅ **統一入口：** 同一の Lambda 関数がすべてのトリガーを受け取る
- ✅ **統一処理：** AWS 公式フィールド抽出 → prompt 構築
- ✅ **統一判定：** Bedrock Agent が「何をすべきか」を判定
- ❌ **カスタムフィールド削除：** `trigger` フィールドは使用しない
- ❌ **InputTransformer 削除：** Lambda が AWS 公式イベント構造をそのまま受け取る

---

## 📊 トリガー形式（3 パターン）

### **パターン 1: ユーザー入力（Bedrock Console）**

```
ユーザー: 「EC2 の CPU が高いです。調査してください」
    ↓ (直接 Bedrock Agent に送信)
Bedrock Agent
    ├─ Knowledge Base: EC2 関連ランブック検索
    └─ Action Group: 適切な FR-XX を判定して実行
```

**処理フロー**:
- Bedrock Agent がユーザー質問を受信
- Knowledge Base から関連ランブックを検索
- Action Group で実行対象を選択

---

### **パターン 2: CloudWatch Alarms（自動トリガー）**

```
CloudWatch Alarm: EC2-HighCPU-i-xxxxx → ALARM
    ↓
EventBridge Rule: EC2-HighCPU-* を検出
    ↓
Lambda 起動 (AWS 公式イベント構造をそのまま受け取る)
    {
      "source": "aws.cloudwatch",
      "detail-type": "CloudWatch Alarm State Change",
      "detail": {
        "alarmName": "EC2-HighCPU-i-xxxxx",
        "state": {"value": "ALARM"},
        "alarmDescription": "EC2 instance CPU > 80%"
      },
      "time": "2026-06-08T10:30:00Z"
    }
    ↓
Lambda: extract_event_info() + build_prompt()
    ↓
Bedrock Agent
    ├─ RAG: アラーム対応ランブック検索
    ├─ 【判定】対応が必要か
    └─ Action Group: 適切な FR-XX を判定して実行
```

**対応アラーム**:

| アラーム名パターン | 説明 |
|------------|------|
| `EC2-HighCPU-*` | EC2 CPU が高い |
| `RDS-HighCPU-*` | RDS CPU が高い |
| `RDS-HighConnections-*` | RDS 接続数超過 |
| `RDS-ReplicationLag-*` | RDS レプリケーション遅延 |
| `Lambda-ErrorRate-*` | Lambda エラー率高 |
| `Lambda-Throttle-*` | Lambda スロットル |

---

### **パターン 3: スケジュール実行（毎週日曜 00:00 UTC）**

```
EventBridge ScheduleRule: cron(0 0 ? * SUN *)
    ↓
Lambda 起動 (AWS 公式イベント構造をそのまま受け取る)
    {
      "source": "aws.events",
      "detail-type": "Scheduled Event",
      "detail": {},
      "time": "2026-06-08T00:00:00Z"
    }
    ↓
Lambda: extract_event_info() + build_prompt()
    ↓
Bedrock Agent
    ├─ RAG: 定期メンテナンスランブック検索
    ├─ 【判定】メンテナンスを実行すべきか
    └─ Action Group: FR-05, FR-06 などを判定して実行
        ├─ スロークエリ検出
        └─ 高負荷クエリ分析
```

**目的**: 予測的メンテナンス

---

## 📊 3 パターンの比較

| 項目 | パターン 1（ユーザー） | パターン 2（Alarms） | パターン 3（Schedule） |
|------|---------------------|------------------|---------------------|
| **トリガー** | Bedrock Console | CloudWatch ALARM → EventBridge | EventBridge Cron |
| **入力方式** | ユーザー質問 | AWS 公式イベント | AWS 公式イベント |
| **ユーザー入力** | ✅ **必須** | ❌ 不要 | ❌ 不要 |
| **Lambda の処理** | extract + build_prompt | extract + build_prompt | extract + build_prompt |
| **RAG** | ✅ 実行 | ✅ 実行 | ✅ 実行 |
| **Bedrock Agent 判定** | ✅ 実行 | ✅ 実行 | ✅ 実行 |
| **Action Group** | ✅ 実行 | ✅ 実行 | ✅ 実行 |
| **自動化度** | 中（ユーザー判断） | 高（自動判定） | 高（定期実行） |
| **実行例** | ユーザーが問い合わせ | リアルタイム自動対応 | 毎週日曜メンテナンス |

---

## 🔄 処理フロー（詳細）

### ステップ 1: イベント受信

Lambda が AWS 公式イベント構造をそのまま受け取る：

```python
# CloudWatch Alarms イベント
event = {
    "source": "aws.cloudwatch",
    "detail-type": "CloudWatch Alarm State Change",
    "detail": {"alarmName": "EC2-HighCPU-i-xxxxx", ...},
    "time": "2026-06-08T10:30:00Z"
}

# または EventBridge Scheduled Event
event = {
    "source": "aws.events",
    "detail-type": "Scheduled Event",
    "detail": {},
    "time": "2026-06-08T00:00:00Z"
}
```

### ステップ 2: 統一情報抽出

AWS 公式フィールドから情報を抽出：

```python
event_info = extract_event_info(event)
# 返り値:
# {
#   "source": "aws.cloudwatch",
#   "detail_type": "CloudWatch Alarm State Change",
#   "detail": {...},
#   "time": "2026-06-08T10:30:00Z"
# }
```

### ステップ 3: 統一 Prompt 構築

Bedrock Agent が判定できるよう、イベント情報をそのまま prompt に含める：

```python
prompt = build_prompt(event_info)
# 例:
# 【イベント受信】
# イベントソース: aws.cloudwatch
# イベント種別: CloudWatch Alarm State Change
# イベント詳細:
# {
#   "alarmName": "EC2-HighCPU-i-xxxxx",
#   ...
# }
# 
# このイベントについて:
# 1. Knowledge Base から関連ランブックを検索してください
# 2. 状況を分析してください
# 3. 必要なアクションを判定してください
# ...
```

### ステップ 4: Bedrock Agent 呼び出し

Lambda が Bedrock Agent を呼び出し（ブログ要件）：

```python
response = invoke_bedrock_agent(
    prompt=prompt,
    session_id=context.aws_request_id
)
```

### ステップ 5: Agent 処理

Bedrock Agent が以下を実行（ブログの「Solution workflow」ステップ 3-6）:

1. **RAG**: Knowledge Base から関連ランブック検索
2. **分析**: ランブック内容を分析
3. **Action Group**: 実行対象 Lambda を判定
4. **パラメータ設定**: 状況に応じたパラメータを設定
5. **Lambda 実行**: 適切な FR-XX を呼び出し

### ステップ 6: 結果通知

Agent が結果を SNS に通知

**例：Alarm パターン**
```
【CloudWatch アラーム検出】

アラーム名: EC2-HighCPU-i-xxxxx
メッセージ: EC2 instance CPU > 80%

このアラームについて:
1. Knowledge Base から関連ランブックを検索してください
2. 問題の原因を分析してください
3. 必要な対応アクション（スナップショット作成、インスタンス再起動など）を実行してください
4. 実行結果をまとめて報告してください
```

### ステップ 3: Bedrock Agent 呼び出し

Lambda が Bedrock Agent を呼び出し（ブログ要件）:

```python
response = invoke_bedrock_agent(
    prompt=prompt,
    session_id=context.aws_request_id,
    trigger_type=trigger_type
)
```

**重要**: Lambda が Agent を呼び出すことで、「すべてのトリガーが同じロジックを通る」という要件を満たします。

### ステップ 4: Agent 処理

Bedrock Agent が以下を実行（ブログの「Solution workflow」ステップ 3-6）:

1. **RAG**: Knowledge Base から関連ランブック検索
2. **分析**: ランブック内容を分析
3. **Action Group**: 実行対象 Lambda を判定
4. **パラメータ設定**: 状況に応じたパラメータを設定
5. **Lambda 実行**: 適切な FR-XX を呼び出し

### ステップ 5: 結果通知

Agent が結果を SNS に通知:

```
SNS Topic: AIOpsReport
Subject: "AIOps Report - Trigger: alarm"
Message: {JSON形式の詳細結果}
```

---

## 🔗 根拠（Information Source）

このアーキテクチャはブログの「解決策アーキテクチャ」図に基づいています：

**参照**: AWS ブログ "Automate IT operations with Amazon Bedrock Agents"
- **著者**: Upendra V, Deepak Dixit (AWS Sr. Solutions Architects)
- **セクション**: "Solution Overview" + "Solution workflow" (6 steps)
- **重要な記述**:
  > "When a user prompt is received or an alert is detected, Amazon Bedrock Agents uses RAG, action groups, and the OpenAPI specification to determine the appropriate API calls."

**翻訳**: ユーザー質問またはアラーム検出時、Bedrock Agent が RAG + Action Group で適切な API（Lambda）を呼び出す

**この実装での対応**:
- ユーザー質問 ✅ 実装
- CloudWatch Alarms 自動トリガー ✅ 実装
- スケジュール実行 ✅ 実装
- すべてが Bedrock Agent を通過 ✅ 実装

---

## 🎓 設計の原則
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
| 4 | **S3 バケット作成** | `aws s3 mb s3://dev-aiops-aiops-artifact --region ap-northeast-1` |
| 5 | **テンプレートをS3へアップロード** | `aws s3 cp cfn-templates/ s3://dev-aiops-aiops-artifact/cfn-templates/ --recursive` |
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
├── s3.yaml                    # S3 バケット（既存/作成分岐）
├── opensearch.yaml            # OpenSearch Serverless データベース
├── lambda-function.yaml       # Lambda 関数定義 + IAM Role
├── bedrock-agent.yaml         # Bedrock Agent + IAM Role + Action Groups
├── knowledge-base.yaml        # Bedrock Knowledge Base + Data Source
├── eventbridge-alarms.yaml    # EventBridge CloudWatch Alarms トリガー（7ルール）
├── secrets-manager.yaml       # Secrets Manager + AWS 管理キー
├── slack-webhook.yaml         # Slack Webhook Lambda + API Gateway
└── chatbot-slack-notification.yaml  # Slack 通知フォーマッティング
```

> **ポイント**  
> - `main.yaml` は全ネストスタックを統合し、パラメータを下位テンプレートに渡す。
> - 各テンプレートは `Outputs` でリソース ARN をエクスポート。
> - IAM Role は各テンプレートに含まれ、最小権限で構成。
> - **Bedrock Agent は Knowledge Base と Action Groups を統合**（messageVersion 1.0 対応）。
> - **KMS**: AWS 管理キー（aws/secretsmanager）を使用（コスト効率的、AWS 推奨）。
> - **VPC Security Groups**: OpenSearch Serverless は VPC なしで動作するため不要。

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
4. S3 にアップロード（`$TEMPLATE_BUCKET` = `dev-aiops-aiops-artifact`）
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
aws s3 cp runbooks/ s3://aiops-kb-${ACCOUNT_ID}-ap-northeast-1-dev/runbooks/ --recursive
aws s3 cp docs/ s3://aiops-kb-${ACCOUNT_ID}-ap-northeast-1-dev/documentation/ --recursive
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
          "uri": "s3://aiops-kb-${ACCOUNT_ID}-ap-northeast-1-dev/runbooks/ec2-investigation.md"
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
          "uri": "s3://aiops-kb-${ACCOUNT_ID}-ap-northeast-1-dev/runbooks/FR-01-log-investigation.md"
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
          "uri": "s3://aiops-kb-${ACCOUNT_ID}-ap-northeast-1-dev/runbooks/FR-01-log-investigation.md"
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

## 7. アクショングループの統合

Bedrock Agent の Action Groups は `bedrock-agent.yaml` に定義され、Lambda 関数と統合されています。

### 7.1 6 関数分割アーキテクチャ（v2.5.0 以降）

CloudFormation の 5 パラメータ制限に対応するため、単一の `ExecuteAIOpsAction` 関数から **6 つの独立した関数** に分割されました。

**各関数スペック：**

| # | 関数名 | FR | パラメータ数 | 入力パラメータ | 説明 |
|---|--------|-----|----------|-------------|------|
| 1 | **LogInvestigation** | FR-01 | 3 | `log_group_name` (必須), `log_stream_name` (必須), `time_range_seconds` (省略可) | CloudWatch Logs を調査してエラーを特定 |
| 2 | **BottleneckAnalysis** | FR-02 | 3 | `resource_id` (必須), `resource_type` (必須), `time_range_seconds` (省略可) | CloudWatch メトリクスからボトルネック（CPU/メモリ/接続）を調査 |
| 3 | **CreateSnapshot** | FR-03 | 3 | `db_instance_id` (必須), `snapshot_identifier` (必須), `region` (省略可) | RDS データベースのスナップショットを作成（緊急時のデータ保全） |
| 4 | **MaintenanceDisplay** | FR-04 | 3 | `db_instance_id` (必須), `display_format` (省略可), `region` (省略可) | RDS メンテナンスウィンドウを表示（予防的なシステムチェック） |
| 5 | **SlowQueryDetection** | FR-05 | 3 | `db_instance_id` (必須), `analysis_period_days` (省略可), `region` (省略可) | RDS Performance Insights でスロークエリを検出（DB クエリ性能確認） |
| 6 | **HighLoadQueryAnalysis** | FR-06 | 3 | `db_instance_id` (必須), `analysis_period_days` (省略可), `region` (省略可) | 複数クエリの影響度を測定して高負荷クエリを分析 |

✅ **すべての関数が 3 パラメータで CloudFormation 制限（最大 5 パラメータ）をクリア**

### 7.2 ActionGroup の構成

`bedrock-agent.yaml` 内の ActionGroup FunctionSchema：

```yaml
ActionGroups:
  - ActionGroupName: AIOpsActionGroup
    FunctionSchema:
      Functions:
        - Name: LogInvestigation          # 関数 1
          Parameters: [log_group_name, log_stream_name, time_range_seconds]
        - Name: BottleneckAnalysis        # 関数 2
          Parameters: [resource_id, resource_type, time_range_seconds]
        # ... etc (計 6 関数)
```

### 7.3 Lambda ハンドラーとのマッピング

Lambda 関数（`lib/lambda_handler.py`）が messageVersion 1.0 形式のリクエストを受け取り、以下を実行：

- **関数名の解析**：`event['function']` から Bedrock Agent が指定した関数名を取得（例：`LogInvestigation`）
- **パラメータ抽出**：`event['parameters']` から関数に必要なパラメータを抽出
- **ディスパッチ**：`dispatch_function()` が function_map から対応する FR ハンドラを呼び出し
- **結果返却**：messageVersion 1.0 形式で Bedrock Agent に結果を返す

**dispatch_function の mapping（lib/lambda_handler.py 行 1475-1490）:**

```python
function_map = {
    # CloudFormation 定義の 6 関数（bedrock-agent.yaml）
    'LogInvestigation': log_investigation_fr01,
    'BottleneckAnalysis': bottleneck_investigation_fr02,
    'CreateSnapshot': create_db_snapshot_fr03,
    'MaintenanceDisplay': maintenance_window_display_fr04,
    'SlowQueryDetection': slow_query_detection_fr05,
    'HighLoadQueryAnalysis': high_load_query_detection_fr06,
    
    # 後方互換性のため、旧命名規則（snake_case）も対応
    'log_investigation': log_investigation_fr01,
    'bottleneck_investigation': bottleneck_investigation_fr02,
    # ... etc
}
```

### 7.4 Bedrock Agent の判定フロー

```
【ユーザー質問またはアラーム受信】
    ↓
Lambda: handler() → handle_bedrock_agent_message()
    ↓
Bedrock Agent:
  1. Knowledge Base から関連ランブック検索（RAG）
  2. 6 関数の中から最適なアクションを判定
  3. パラメータ値を決定（log_group_name など）
  4. Action Group 経由で Lambda を呼び出し
    ↓
Lambda: dispatch_function()
  1. function_name（例：LogInvestigation）で対応 FR ハンドラを特定
  2. FR-01～06 いずれかを実行
  3. 結果を SNS に通知
    ↓
【調査完了】
```

> **重要**：Lambda 関数は単一の `handler()` エントリポイントで全アクションを処理。Bedrock Agent が 6 関数の中から最適なものを判定・呼び出すため、**動的なパラメータ値の注入が可能**です。

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

## 12. よくある質問

| 質問 | 回答 |
|------|------|
| **Q**：CloudFormation テンプレートは JSON で書くべき？ | **A**：YAML の方が可読性が高く Git の差分と比較しやすいので推奨。 |
| **Q**：Bedrock Agent のプロンプトはどうやってカスタマイズ？ | **A**：`bedrock-agent.yaml` の `Instruction` パラメータで直接編集。Git コミット後に CodePipeline で反映。または `cfn-dev-parameters.json` で環境別に管理。 |
| **Q**：OpenSearch Serverless でデータの削除は？ | **A**：`aws opensearch delete-collection` または CloudFormation で `OpensearchCollection` リソースを削除。 |
| **Q**：Lambda 関数のコードを修正したい | **A**：`lib/lambda_handler.py` を修正 → git push → CodePipeline が自動で `dist/lambda.zip` を作成・デプロイ |
| **Q**：Lambda がタイムアウトする | **A**：`lambda-function.yaml` の `Timeout` を増やす（デフォルト 300秒） |
| **Q**：S3 バケット戦略は？ | **A**：現在は Dev 環境のみ実装。S3 バケット（`DataBucketName`）は事前作成が必須。Stg/Prod への拡張は Phase 2 として計画。詳細は `docs/S3-ENVIRONMENT-STRATEGY.md` を参照。 |

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
| v2.5.0 | 2026‑06‑04 | **仕様根拠不明な内容を削除** + **bedrock-agent.yaml から「ユーザー質問への対応パターン」セクション削除** + **AGENTS.md セクション 12 削除** + **docs/test-specifications-sources.md 削除** |
| v2.6.0 | 2026‑06‑22 | **Knowledge Base S3 バケット配置修正** + **セクション 5.3-5.7: runbook/documentation URIs 更新** + **from: s3://dev-aiops-aiops-artifact/runbooks/ → to: s3://aiops-kb-${ACCOUNT_ID}-ap-northeast-1-dev/runbooks/** + **理由: LifeCycle 保護 (KB bucket 30+ days, artifact bucket 14日自動削除)** |

> 変更があった際は必ず `push` 先に `AGENTS.md` を更新し、全員が最新の手順を参照できるようにしてください。
