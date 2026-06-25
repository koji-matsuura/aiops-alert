# AIOps システムアーキテクチャ

## 設計方針

Lambda の pre-filter による AI 判断の代替をやめ、AgentCore Runtime が Knowledge Base を直接検索し、AWS API を自律的に呼び出す構成に変更する。

**変更理由（確認済み事実）：**
- 現在の EventBridge 6 ルールがアラーム種別を事前フィルタしている（`cfn-templates/eventbridge-alarms.yaml` 行26-95）
- Lambda の `build_prompt()` はイベント情報をテンプレートに埋め込むだけで AI 判断がない（`lib/lambda_handler.py` 行142-175）
- Bedrock Agent の Action Group が FR 関数を固定的に割り当てており、AI の推論能力が活用されていない

---

## アーキテクチャ概要

```
【トリガー】
EventBridge（8ルール: EC2-HighCPU, RDS-HighCPU, RDS-HighConnections,
             RDS-ReplicationLag, Lambda-ErrorRate, Lambda-Throttle,
             ScheduledMaintenance, AlarmStateRecovery）
    ↓ （変更なし）
Lambda（thin proxy）
    ↓  bedrock-agentcore:InvokeAgentRuntime
AgentCore Runtime（HTTP, port 8080）
    ├─ Knowledge Base retrieve()
    │   └─ OpenSearch Serverless（aiops-kb-index）
    │       └─ Runbooks: FR-01〜FR-06.md + .metadata.json
    ├─ Bedrock InvokeModel（Claude Haiku 4.5）
    │   └─ AI が状況分析・実行対象を自律判定
    └─ AWS API 直接呼び出し
        ├─ CloudWatch Logs（FR-01）
        ├─ CloudWatch Metrics（FR-02）
        ├─ RDS create_db_snapshot（FR-03）
        ├─ RDS describe_db_instances（FR-04）
        ├─ Performance Insights（FR-05）
        └─ Performance Insights + CloudWatch（FR-06）
            ↓
          SNS 通知
```

---

## ディレクトリ構造

```
aiops-alert/
├── lambda/                        # Lambda thin proxy 専用
│   └── handler.py                 # handler() + invoke_agent_runtime() のみ
│
├── agentcore/                     # AgentCore Runtime 専用
│   ├── app.py                     # BedrockAgentCoreApp エントリポイント
│   └── tools/
│       └── fr_tools.py            # FR-01〜FR-06 AWS API 関数
│
├── Dockerfile                     # agentcore/ をコンテナ化（port 8080）
├── requirements-agentcore.txt     # bedrock-agentcore, aioboto3
│
├── cfn-templates/
│   ├── agentcore-runtime.yaml     # AWS::BedrockAgentCore::Runtime + IAM Role
│   ├── eventbridge-alarms.yaml    # 変更なし
│   ├── knowledge-base.yaml        # 変更なし
│   ├── lambda-function.yaml       # IAM 権限変更（InvokeAgentRuntime）
│   ├── main.yaml                  # BedrockAgentStack 削除・AgentCoreRuntimeStack 追加
│   └── ...
│
├── cfn-pipeline.yml               # ECR リポジトリ追加・Docker ビルドステップ追加
├── runbooks/                      # 変更なし（Knowledge Base データソース）
└── docs/                          # 設計ドキュメント
    ├── ARCHITECTURE.md            # このファイル
    └── IMPLEMENTATION.md          # 実装詳細
```

---

## コンポーネント詳細

### Lambda（thin proxy）

**役割：** EventBridge イベントを受け取り、AgentCore Runtime に転送する。

**処理：**
1. AWS 公式イベント構造（source, detail-type, detail, time）から情報抽出
2. AgentCore Runtime 用プロンプトを構築
3. `bedrock-agentcore:InvokeAgentRuntime` を呼び出す

**削除した機能：**
- `bedrock:InvokeAgent`（Bedrock Agent 呼び出し）
- `handle_bedrock_agent_message()`（Action Group ハンドラ）
- FR-01〜FR-06 関数（agentcore/ に移行）

---

### AgentCore Runtime

**定義：** `AWS::BedrockAgentCore::Runtime`（CloudFormation）  
**プロトコル：** HTTP（port 8080, /invocations）  
**ソース：** `cfn-infra-base/cfn_agentcore_runtime.yml` 行126-161 を参照

**処理：**
1. Lambda から受け取ったプロンプトとイベント情報を解析
2. Knowledge Base `retrieve()` でランブックを検索
3. Claude Haiku 4.5 で状況分析・実行対象を判定
4. FR-01〜FR-06 の AWS API 関数を直接呼び出し
5. SNS に結果を通知

**IAM Trust Principal：** `bedrock-agentcore.amazonaws.com`  
（`cfn-infra-base/cfn_agentcore_runtime.yml` 行212 で確認済み）

---

### Knowledge Base

**ID：** `OQZNQIPJTS`（AGENTS.md 記載）  
**Data Source ID：** `9TZ9MCQRGH`  
**インデックス：** `aiops-kb-index`（OpenSearch Serverless）  
**変更なし：** Runbooks（`runbooks/FR-0X.md`）・メタデータ（`.metadata.json`）はそのまま再利用

**メタデータフィルタ（`runbooks/FR-0X.md.metadata.json`）：**
- `category`：Log Investigation, Bottleneck Investigation, Database Operations, etc.
- `applicable_to`：EC2, RDS, Lambda（STRING_LIST）
- `priority`：1 または 2

---

### EventBridge（変更なし）

**8 ルール定義：** `cfn-templates/eventbridge-alarms.yaml`

| ルール | 行 | 目的 |
|-------|---|------|
| EC2HighCPUAlarmRule | 行26 | EC2 高 CPU |
| RDSHighCPUAlarmRule | 行50 | RDS 高 CPU |
| RDSHighConnectionsAlarmRule | 行74 | RDS 接続数超過 |
| RDSReplicationLagAlarmRule | 行98 | RDS レプリケーション遅延 |
| LambdaErrorAlarmRule | 行122 | Lambda エラー率 |
| LambdaThrottleAlarmRule | 行146 | Lambda スロットル |
| ScheduledMaintenance | 行169 | 定期メンテナンス（Cron） |
| AlarmStateRecovery | 行182 | INSUFFICIENT_DATA → OK 回復検知 |

**Target：** Lambda ARN（変更なし）  
**変更なし理由：** EventBridge は AgentCore Runtime を直接ターゲットにできない（`cfn-infra-base/cfn_agentcore_runtime.yml` に EventBridge 記述ゼロで確認済み）。Lambda が proxy として継続する。

---

## CFN スタック構成

```
main.yaml（ルートスタック）
├── S3Stack（変更なし）
├── KnowledgeBaseStack（変更なし）
├── SQSDLQStack（変更なし）
├── LambdaStack（IAM 権限変更）
├── SecretsManagerStack（変更なし）
├── SlackWebhookStack（変更なし）
├── ChatbotSlackNotificationStack（変更なし）
├── EventBridgeAlarmsStack（変更なし）
└── AgentCoreRuntimeStack（新規：BedrockAgentStack を置き換え）
```

**削除：** `BedrockAgentStack`（`cfn-templates/bedrock-agent.yaml`）

---

## CodePipeline ビルドフロー

```
GitHub Push
    ↓
CodeBuild
    ├─ Lambda ZIP ビルド（lambda/handler.py → dist/lambda.zip → S3）
    ├─ ECR ログイン
    ├─ Docker ビルド（agentcore/ → ECR イメージ）
    └─ CFN テンプレートを S3 にコピー
    ↓
CloudFormation デプロイ（main.yaml）
```

**ECR リポジトリ：** `cfn-pipeline.yml` に `AWS::ECR::Repository` として定義  
（cfn-infra-base/cfn-pipeline.yml 行91-94 のパターンを参照）
