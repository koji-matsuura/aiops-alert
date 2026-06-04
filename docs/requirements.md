# AIOps‑RAG 要件（Bedrock Agent）

**文書バージョン**: 2026‑06‑13  
**作成者**: <your-name>  
**スコープ**: CloudFormation だけで **ap‑northeast‑1** にデプロイ、CI/CD は CodePipeline、CLI で `cloudformation` を直接実行しない。  

## 1. ビジネスコンテキスト

- 企業は生成AIでインシデント対応を自動化。
- Bedrock Agent が Runbook と監視データを推論し、実際に修復操作を呼び出す。
- システムは「自己治癒」「監査性」「CI/CD でのデプロイ」が必須。

## 2. 高水準機能要件

| No | 機能 | 内容 | 発火条件 | 出力 |
|----|------|------|----------|------|
| **FR‑01** | **ログ調査** | Agent が CloudWatch Logs を検索し、インシデントキーワードに合致するイベントを抜粋してサマリを生成。 | インシデントメッセージ受信または cron スケジュール。 | チャット／Slack／メールでサマリ。 |
| **FR‑02** | **ボトルネック調査** | 監視メトリクス（CPU, Memory, RDS の `free_storage_space_bytes` 等）を取得し、最も可能性の高いボトルネックを特定。 | インシデントまたはパフォーマンスアラーム。 | チャット／ダッシュボードで推奨。 |
| **FR‑03** | **DB スナップショット作成** | Agent が指定 RDS のスナップショットを作成し、インシデントIDでタグ付け。 | 手動トリガー（Agent プロンプト）または FR‑02 の自動応答。 | スナップショット ARN を返却・ログ化。 |
| **FR‑04** | **メンテナンス表示** | Agent が対象サービス（例：RDS）の現在のメンテナンスウィンドウを提示。 | インシデントまたは手動クエリ。 | 人間が読めるメンテウィンドウ日時と予定変更情報。 |

## 3. 非機能要件

| ID | 要件 | 合格基準 |
|----|------|----------|
| **NFR‑01** | レイテンシ | 4 秒以内に全ての応答（RAG + アクション呼び出し）を完了。 |
| **NFR‑02** | セキュリティ | IAM ロールは最小権限で構成。認証情報は漏れない。 |
| **NFR‑03** | 監査性 | 全アクション（クエリ、スナップショット、通知等）は CloudWatch と S3 にログ。365 日保存。 |
| **NFR‑04** | スケーラビリティ | 1 時間あたり 50 件のインシデントを処理。 |
| **NFR‑05** | 信頼性 | CodePipeline と CodeBuild のフェイルオーバーを確保。 |
| **NFR‑06** | 観測性 | エージェントのスループット・成功率・エラー率を CloudWatch ダッシュボードで表示。 |

## 4. アーキテクチャ前提

| コンポーネント | 役割 | 重要設定 |
|----------------|------|----------|
| **Bedrock Agent** | LLM + RAG | Prompt に Amazon Titan か Anthropic Claude を使用（設定可）。 |
| **Knowledge Base** | Runbook 文書 | S3 に保管し OpenSearch Serverless でインデックス。 |
| **Action Group** | Lambda 呼び出し | OpenAPI で `GetMetrics`、`CreateDBSnapshot`、`DescribeMaintenanceWindows` 等を公開。 |
| **CodePipeline** | CI/CD | CloudFormation テンプレートを自動デプロイし `cfn-dev-parameters.json` を渡す。 |
| **Lambda 関数** | Action 実装 | CloudWatch 取得、RDS スナップショット、SNS/メール通知等を実装。 |
| **EventBridge** | （任意） | スケジュールやアラームでトリガー。 |

## 5. データフロー

インシデント ──→ Bedrock Agent ──(RAG)──> Knowledge Base ──→ Agent Response
                                      │                    │
                                      │                    └─(OpenAPI)──> Action Group ──→ Lambda 実装


## 6. API / OpenAPI スペック（抜粋）

```yaml
openapi: 3.0.0
info:
  title: AIOps Action Group
  version: 1.0.0
paths:
  /GetCloudWatchMetrics:
    post:
      summary: リソースメトリクス取得
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                resourceArn: { type: string }
                metrics: { type: array, items: { type: string } }
      responses: { 200: { description: "メトリクス取得成功" } }
  /CreateDBSnapshot:
    post:
      summary: RDS スナップショット作成
      requestBody:
        content:
          application/json:
            schema:
              type: object
              properties:
                dbInstanceIdentifier: { type: string }
                snapshotName: { type: string }
      responses: { 200: { description: "スナップショット ARN" } }
  /DescribeMaintenanceWindow:
    get:
      summary: メンテナンスウィンドウ取得
      parameters:
        - name: resourceArn
          in: query
          schema: { type: string }
      responses: { 200: { description: "ウィンドウ情報" } }
7. 合格テストケース
機能	テストケース	期待結果
FR‑01	ERROR: Timeout を検索	3 件以上のログイベントとタイムスタンプを含むサマリ。
FR‑02	CPU > 90% をクエリ	CPU がボトルネックと判断し拡張の推奨を返す。
FR‑03	DB スナップショット作成	スナップショットが作成され、incident-id タグ付き。
FR‑04	RDS のメンテウィンドウ取得	開始・終了時刻が正しく返却。
8. デプロイチェックリスト
1. S3  
- my-aiops-bucket が ap‑northeast‑1 に存在。  
- cfn-templates/、runbooks/、cfn-dev-parameters.json を保持。
2. IAM  
- ロール: CodePipelineServiceRoleAiAgent, CodeBuildProjectAiAgent, ActionGroupRole, LambdaExecutionRole。  
- ポリシーは cfn-pipeline.yml を参照。
3. CodeBuild  
- BuildSpec で cfn-dev-parameters.json と TemplatePath を使用。
4. CodePipeline  
- ソース: GitHub (GithubOwner, GithubRepo, BranchName)。  
- ステージ: Source → Build → DeployInfrastructure。
5. Bedrock  
- Agent は cfn-base-stack.yml の Knowledge Base ARN を参照して生成。  
- Agent に Action Group を紐付け。
9. セキュリティ & コンプライアンス
- CloudWatch の各ロググループは /aws/codebuild/${EnvName}-${ServiceName}-aiagent。  
- すべてのアクションは CloudTrail に記録（eventSource: bedrock.amazonaws.com）。  
- IAM ロールは セッショントークン を利用し、最小権限（policy 設定を確認）。  
- シークレット（GitHub token、Bedrock 検証情報）は Secrets Manager に保存し {{resolve:secretsmanager:...}} で参照。
10. 今後の拡張方向（ロードマップ）
- スナップショット失敗時の自動ロールバック。  
- Slack / Teams 用の通知テンプレートを追加。  
- RDS 自動バックアップをメンテウィンドウに組み込み。  
- CLI での手動エージェント再呼び出しを実装し、アドホッククエリを可能に。

## 2-1. 高水準機能要件（追加：Performance Insights）

| No | 機能 | 内容 | 発火条件 | 出力 |
|----|------|------|----------|------|
| **FR‑05** | **Slow Query 検出** | RDS Performance Insights API で過去 24h の Slow Query を取得し、SQL テキスト・実行時間・インスタンスをレポート。 | 毎週日曜 00:00 UTC でバッチ起動。 | SNS 通知（JSON 形式）。 |
| **FR‑06** | **高負荷クエリ 調査** | Performance Insights で CPU／I/O／ネットワークの 90% 超のクエリを抽出し、平均実行時間・重複率を算出。 | 毎週日曜 00:00 UTC でバッチ起動。 | SNS 通知（JSON 形式）。 |

### FR‑05 の詳細（Slow Query 検出）

- **対象**：MySQL / MariaDB / PostgreSQL / Aurora DB  
- **パラメータ**  
  - `Duration`：過去 24h（秒数 = 86400）  
  - `Metric`：`DatabaseConnections` or `QueryRuntime`  
  - `Filter`: `SQLText`（長さ > 200 で長時間実行）  
- **出力例**  
```json
{
  "type": "slowQuery",
  "date": "2026-06-07",
  "queries": [
    {
      "queryText": "SELECT * FROM orders WHERE created_at < '2025-01-01'",
      "averageTimeMs": 15234,
      "count": 34,
      "topInstances": ["ap-northeast-1b", "ap-northeast-1c"]
    }
  ]
}
```

### FR‑06 の詳細（高負荷クエリ 調査）

- **対象**：CPU、Disk I/O、ネットワークの 90％以上の使用率を示すクエリ  
- **パラメータ**  
  - `Metric`：`CPUUtilization`, `DiskIOPS`, `NetworkTransmitThroughput`  
  - `Threshold`：90%  
- **出力例**  
```json
{
  "type": "highLoadQueries",
  "date": "2026-06-07",
  "queries": [
    {
      "queryText": "CALL update_inventory()",
      "avgCpuPercent": 92.3,
      "avgDiskIoPercent": 88.1,
      "timeRange": "22:00-23:00"
    }
  ]
}
```

### SNS 通知設定

| SNS Topic | 送信メッセージ | 備考 |
|-----------|-----------------|------|
| `arn:aws:sns:ap-northeast-1:123456789012:SlowQueryReport` | `FR‑05` の JSON をそのまま本文に。 | 既存サブスクライバーをメール/SQS/Slack に設定。 |
| `arn:aws:sns:ap-northeast-1:123456789012:HighLoadQueryReport` | `FR‑06` の JSON をそのまま本文に。 | 既存サブスクライバーをメール/SQS/Slack に設定。 |

### バッチジョブのスケジュール設定

- **EventBridge ルール**：`cron(0 0 ? * SUN *)`（毎週日曜 00:00 UTC）  
- **ターゲット**：Lambda 関数（Slow Query 検出・高負荷クエリ検出）  
- **タイムアウト**：30 秒以上を推奨（Performance Insights API の応答時間）  

## 9-1. セキュリティ & コンプライアンス（追加）

### Performance Insights API への IAM 権限

- **LambdaExecutionRole** に以下を付与：
  ```json
  {
    "Effect": "Allow",
    "Action": [
      "cloudwatch:GetMetricData",
      "pi:GetResourceMetrics",
      "rds:DescribeDBInstances",
      "rds:DescribeDBClusters"
    ],
    "Resource": "*"
  }
  ```

### SNS Publisher 権限

- **LambdaExecutionRole** に以下を付与：
  ```json
  {
    "Effect": "Allow",
    "Action": ["sns:Publish"],
    "Resource": [
      "arn:aws:sns:ap-northeast-1:123456789012:SlowQueryReport",
      "arn:aws:sns:ap-northeast-1:123456789012:HighLoadQueryReport"
    ]
  }
  ```

### ログ監査

- すべての Slow Query 検出・高負荷クエリ検出は CloudWatch Logs に記録。  
- ロググループ：`/aws/lambda/aiops-slow-query-detector`  
- 保持期間：365 日。  

## 10-1. 今後の拡張方向（追加）

- **データの長期保持**：RDS Performance Insights のデータを **Athena** で集約し、S3 に保存。  
- **BI ツール連携**：QuickSight / Grafana で Slow Query トレンドを可視化。  
- **自動修復**：検出された Slow Query に対して**自動インデックス作成**を提案する機能。  
- **AI による根本原因分析**：Bedrock Agent が Slow Query の原因を分析し、修正案を提示。  

---

**更新日**：2026‑06‑14  
**変更内容**：Performance Insights を活用した Slow Query / 高負荷クエリ検出と SNS 通知機能を追加。
