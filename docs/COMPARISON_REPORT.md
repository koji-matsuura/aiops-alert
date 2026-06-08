# AWS AIOps リポジトリ構造・実装比較レポート

## 1. プロジェクト概要

### 参照リポジトリ (aws-samples/improving-it-operations-efficiency-with-aiops)
- **言語**: TypeScript + Python
- **IAC**: AWS CDK 2.x
- **ビルドツール**: npm / TypeScript
- **言語ランタイム**: Node.js (CDK ホスト) + Python 3.13 (Lambda)
- **デプロイ方式**: CDK CLI (`cdk deploy`)
- **リポジトリタイプ**: GitHub Sample (aws-samples)

### 当プロジェクト (/Users/matsuurakouji/aiops-alert)
- **言語**: Python + YAML
- **IAC**: CloudFormation (CFN) 単体
- **ビルドツール**: CodePipeline (BuildSpec 統合)
- **言語ランタイム**: Python 3.11/3.12 (Lambda のみ)
- **デプロイ方式**: CodePipeline（AWS CLI は禁止）
- **リポジトリタイプ**: 社内プロジェクト

---

## 2. ディレクトリ構成比較

### 参照リポジトリ構造
```
aiops-reference/
├── bin/
│   └── bedrock-agent-cdk.ts          # エントリポイント (CDK App)
├── lib/
│   ├── bedrock-agent-cdk-stack.ts    # メインスタック定義
│   ├── ec2-cdk-stack.ts              # EC2 スタック
│   ├── constructs/                   # CDK Constructs (再利用可能コンポーネント)
│   │   ├── bedrock-agent-iam-construct.ts
│   │   ├── custom-bedrock-agent-construct.ts
│   │   ├── ec2-construct.ts
│   │   ├── lambda-construct.ts
│   │   ├── lambda-iam-construct.ts
│   │   ├── s3-bucket-construct.ts
│   │   ├── s3-kb-bucket-construct.ts
│   │   └── ses-construct.ts
│   └── assets/
│       ├── lambdas/
│       │   ├── cdk-resource-bedrock-agent.py    # Custom Resource
│       │   └── agent/
│       │       ├── alerts/get-all-alerts.py
│       │       └── remediation/issue-remediation.py
│       ├── api-schema/
│       │   ├── operations-api.json
│       │   └── remediation-api.json
│       └── kb/                       # Knowledge Base データ
├── static/                           # ドキュメント用スクリーンショット
├── cdk.json                          # CDK 設定
├── tsconfig.json                     # TypeScript 設定
├── package.json                      # npm 依存
├── jest.config.js                    # テスト設定
└── README.md
```

### 当プロジェクト構造
```
aiops-alert/
├── cfn-templates/                    # CloudFormation テンプレート (YAML)
│   ├── main.yaml                     # ルートスタック
│   ├── bedrock-agent.yaml
│   ├── knowledge-base.yaml
│   ├── action-group.yaml
│   ├── lambda-function.yaml
│   ├── eventbridge-alarms.yaml
│   ├── opensearch.yaml
│   ├── s3.yaml
│   ├── kms.yaml
│   └── security-groups.yaml
├── lib/
│   └── lambda_handler.py             # 統合 Lambda ハンドラー (FR-01～FR-06)
├── runbooks/                         # ナレッジベース用ランブック
│   ├── FR-01-log-investigation.md
│   ├── FR-02-bottleneck-investigation.md
│   ├── FR-03-create-db-snapshot.md
│   ├── FR-04-maintenance-display.md
│   ├── FR-05-slow-query-detection.md
│   ├── FR-06-high-load-query-detection.md
│   ├── metadata.json
│   └── bedrock-ingest-template.json
├── docs/                             # ドキュメント
├── .agents/                          # Agent スキル定義
├── cfn-pipeline.yml                  # CodePipeline ビルドスペック
├── cfn-dev-parameters.json           # パラメータファイル
├── AGENTS.md                         # デプロイメントガイド
└── tests/
```

**主な違い:**
1. **参照**: bin/ に TypeScript エントリポイント、lib/ に Construct 階層構造
2. **当プロジェクト**: cfn-templates/ に直接 CloudFormation YAML、lib/ に Python Lambda のみ
3. **参照**: assets/ 内に Lambda と API Schema を管理
4. **当プロジェクト**: lambda_handler.py は統合ファイル (603行)

---

## 3. デプロイメント・ビルドフロー比較

### 参照リポジトリ (CDK 方式)
```
npm install
    ↓
cdk bootstrap
    ↓
cdk deploy BedrockAgentCDKStack
    ↓
1. TypeScript をコンパイル (lib/*.ts → lib/*.js)
2. CDK が CloudFormation テンプレートを生成
3. CloudFormation Stack を AWS に デプロイ
4. Lambda 関数をパッケージング＆アップロード
5. S3 に Lambda ZIP をアップロード
6. Bedrock Agent を作成
```

**特徴:**
- LocalStack や SAM との互換性がない (CDK 専用)
- `cdk.json` でコンテキスト設定
- `cdk destroy` でクリーンアップ

### 当プロジェクト (CloudFormation + CodePipeline 方式)
```
git commit & git push
    ↓
CodePipeline トリガー
    ├─ Source: GitHub から取得
    └─ Build: CodeBuild 実行
       ├─ Lambda パッケージング (lib/lambda_handler.py → dist/lambda.zip)
       ├─ Lambda ZIP を S3 にアップロード
       ├─ CFN テンプレートを S3 にコピー
       └─ パラメータファイルを更新
    └─ Deploy: CloudFormation
       ├─ main.yaml を S3 から取得
       ├─ ネストスタックを実行
       └─ Lambda を S3 から取得してデプロイ
```

**特徴:**
- CloudFormation テンプレートは AWS CLI で直接操作禁止
- CodePipeline が全て自動化
- Lambda パッケージングをビルド段階で実行
- `cfn-dev-parameters.json` で環境別パラメータ管理

---

## 4. Lambda ハンドラー実装比較

### 参照リポジトリ

#### 1) cdk-resource-bedrock-agent.py (Custom Resource)
- **目的**: CDK デプロイ時に Bedrock Agent を作成
- **行数**: 152行
- **関数**:
  - `on_event()` - Create/Update/Delete ハンドリング
  - `create_agent()` - Agent 作成
  - `create_agent_action_group()` - Action Group 登録
  - `create_cloudwatch_alarm()` - CloudWatch アラーム作成
  - `delete_agent()` - Agent 削除

#### 2) get-all-alerts.py (Action Group Lambda)
- **目的**: CloudWatch アラーム一覧を取得
- **行数**: 79行
- **機能**:
  - `/get_all_alerts` - アラーム一覧 (GET)
  - `/send-Notification` - メール送信 (POST、SES 使用)
- **特徴**: Bedrock Agent が invocation する

#### 3) issue-remediation.py (Action Group Lambda)
- **目的**: EC2 スナップショット・リブート実行
- **行数**: 54行
- **機能**:
  - `/create_snapshot_of_EC2_volume` - スナップショット作成 (POST)
  - `/restart_ec2_instance` - インスタンスリブート (POST)

**合計行数**: 285行

**特徴**:
- 3 つの独立した Lambda 関数
- AWS Lambda のアクションハンドラー標準形式に従う
- Bedrock Agent の `actionGroup` に対応

### 当プロジェクト (lambda_handler.py)

- **行数**: 603行
- **構造**: 統合ハンドラー (6 つの機能を 1 ファイルで管理)
- **関数** (FR):
  - `handle_log_investigation()` - FR-01
  - `handle_bottleneck_investigation()` - FR-02
  - `handle_create_snapshot()` - FR-03
  - `handle_maintenance_display()` - FR-04
  - `handle_slow_query_detection()` - FR-05
  - `handle_high_load_query_detection()` - FR-06

**特徴**:
- `event['action']` で機能を切り分け
- CloudWatch Logs, Metrics, RDS Performance Insights API を使用
- SNS で各機能別に通知
- S3 へレポートをバックアップ
- CloudWatch Metrics を更新
- EventBridge Alarms から直接トリガー対応
- 統合型設計 (より複雑な処理)

**比較表**:

| 項目 | 参照リポジトリ | 当プロジェクト |
|------|---|---|
| Lambda 関数数 | 3個 | 1個（統合） |
| 総行数 | 285行 | 603行 |
| 設計パターン | マイクロサービス | 統合型 |
| トリガー方式 | Bedrock Agent の actionGroup | event['action'] + EventBridge |
| 外部通知 | SES (メール) | SNS (複数チャネル) |
| データ永続化 | なし | S3 バックアップ |
| 分析機能 | 基本的なアラーム検出 | CloudWatch Metrics + RDS PI API |

---

## 5. API スキーマ定義比較

### 参照リポジトリ

#### operations-api.json
```json
{
  "paths": {
    "/get_all_alerts": {
      "get": { /* CloudWatch アラーム取得 */ }
    },
    "/send-Notification": {
      "post": { /* メール送信 */ }
    }
  }
}
```

#### remediation-api.json
```json
{
  "paths": {
    "/create_snapshot_of_EC2_volume": {
      "post": { /* EBS スナップショット作成 */ }
    },
    "/restart_ec2_instance": {
      "post": { /* EC2 リブート */ }
    }
  }
}
```

**特徴**:
- OpenAPI 3.0.0 標準
- Bedrock Agent が Lambda 関数を呼び出すための定義
- 2 つの API スキーマに分割

### 当プロジェクト

**当プロジェクトには API スキーマがない**
- Lambda ハンドラーが `event['action']` で処理を切り分け
- API Gateway 経由ではなく直接 Lambda 呼び出し
- EventBridge から定型的なペイロードで呼び出し
- Bedrock Agent と統合しない設計

---

## 6. IAM ロール & ポリシー比較

### 参照リポジトリ (Construct ベース)

**8 つの独立した Construct:**
1. `bedrock-agent-iam-construct.ts` - Bedrock Agent Role
2. `lambda-iam-construct.ts` - Lambda Execution Role
3. `custom-bedrock-agent-construct.ts` - Custom Resource Role

**各ロールの権限**:
- **Bedrock Agent Role**:
  - `bedrock:InvokeModel` - Claude モデル呼び出し
  - `lambda:InvokeFunction` - Lambda 関数呼び出し
  - `s3:GetObject` - API Schema 取得
  - `bedrock:Retrieve` - Knowledge Base 検索 (オプション)

- **Lambda Role**:
  - `cloudwatch:DescribeAlarms` - アラーム監視
  - `ec2:CreateSnapshot`, `ec2:CreateTags` - EBS 操作
  - `logs:*` - CloudWatch Logs 操作
  - `ses:SendEmail` - SES でメール送信
  - `ec2:StartInstances`, `ec2:StopInstances` - インスタンス操作

### 当プロジェクト (CloudFormation YAML)

**lambda-function.yaml にすべてのポリシーが定義**:
- CloudWatch Logs フィルタリング
- CloudWatch Metrics 取得・更新
- RDS Performance Insights API 呼び出し
- SNS メッセージ発行
- S3 へのバックアップ
- EC2 メタデータ取得
- EventBridge トリガー検知

**EventBridge Role** (`eventbridge-alarms.yaml`):
- Lambda 関数を呼び出す権限
- CloudWatch Alarms をフィルタリング

---

## 7. Bedrock Agent と Knowledge Base の統合

### 参照リポジトリ

**Agent 作成**:
- Custom Resource Lambda (`cdk-resource-bedrock-agent.py`) が実行時に作成
- Action Group 2 つを登録 (Alerts, Remediation)
- API Schema を S3 から参照

**Knowledge Base**:
- CloudFormation では作成されない
- デプロイ後、AWS Console で手動で作成・登録
- README に Step-by-Step ガイド記載

### 当プロジェクト

**Agent 作成**:
- `bedrock-agent.yaml` で定義
- Agent に Instruction を指定
- Knowledge Base を統合

**Knowledge Base**:
- `knowledge-base.yaml` で自動作成
- OpenSearch Serverless をバックエンド
- Data Source を定義 (S3 参照)
- ランブック (FR-01～06) を自動インジェスト

**違い**:
- 参照リポジトリ: Knowledge Base は手動構成
- 当プロジェクト: Knowledge Base 完全自動化

---

## 8. CloudFormation テンプレート設計

### 参照リポジトリ

**CDK で自動生成**:
- CDK Construct が CloudFormation テンプレートを生成
- ネストスタックなし
- すべて 1 つの CloudFormation Stack に統合

### 当プロジェクト

**手書き YAML (ネストスタック設計)**:
```yaml
main.yaml (ルート)
├── bedrock-agent.yaml
├── knowledge-base.yaml
├── lambda-function.yaml
├── action-group.yaml
├── s3.yaml
├── kms.yaml
├── opensearch.yaml
├── security-groups.yaml
└── eventbridge-alarms.yaml
```

**メリット**:
- モジュール性が高い
- 環境別にスタックを分離可能
- テンプレート更新が容易

---

## 9. EventBridge 統合

### 参照リポジトリ

**EventBridge は使用されない**
- CloudWatch Alarms は作成されるが、アクション設定なし
- 手動でアラームをテストする前提

### 当プロジェクト

**EventBridge ルール** (`eventbridge-alarms.yaml`):
- CloudWatch Alarm ALARM 状態を自動検知
- Lambda を非同期呼び出し
- InputTransformer で event を成形

**トリガー対応表** (AGENTS.md より):
| Alarm | 対応 FR | Action |
|-------|--------|--------|
| EC2-HighCPU-* | FR-02 | bottleneck_investigation |
| RDS-HighCPU-* | FR-02 | bottleneck_investigation |
| RDS-HighConnections-* | FR-05 | slow_query_detection |
| Lambda-ErrorRate-* | FR-01 | log_investigation |

---

## 10. デプロイメント手順比較

### 参照リポジトリ

```bash
# 1. 依存をインストール
npm install [--force]

# 2. AWS CDK を初期化
cdk bootstrap

# 3. デプロイ
cdk deploy BedrockAgentCDKStack --require-approval never \
  --parameters EmailAddressParam=ops@example.com

# 4. Knowledge Base を AWS Console で手動作成
# 5. Agent に Knowledge Base を追加 (手動)
# 6. Lambda リソースベースポリシーを設定 (手動)
# 7. Agent を Prepare (手動)

# 削除
cdk destroy --force --all
```

### 当プロジェクト

```bash
# 1. S3 バケット作成
aws s3 mb s3://dev-image-aiagent-artifact --region ap-northeast-1

# 2. テンプレートを S3 にアップロード
aws s3 cp cfn-templates/ s3://dev-image-aiagent-artifact/cfn-templates/ --recursive

# 3. GitHub にコミット & プッシュ
git add . && git commit -m "Deploy" && git push

# 4. CodePipeline が自動実行
#    (ユーザーは何もしない)

# 削除
# AWS Console から CloudFormation Stack を削除
# または CodePipeline 削除ステージを実行
```

**主な違い**:
- 参照: CLI 操作 + 手動設定が多い
- 当プロジェクト: Git Push で完全自動化、手動作業なし

---

## 11. テスト & 検証方法

### 参照リポジトリ

**jest.config.js で定義**:
- Unit テスト対応
- CDK Stack のテストフレームワーク
- サンプルテストは README に記載なし

### 当プロジェクト

**tests/test_lambda_handler.py**:
- 各 FR ごとにユニットテスト
- Lambda ハンドラーのテスト
- EventBridge ペイロードのテスト

---

## 12. 設定管理・パラメータ化

### 参照リポジトリ

**cdk.json**:
```json
{
  "app": "npx ts-node --prefer-ts-exts bin/bedrock-agent-cdk.ts",
  "context": {
    "@aws-cdk/aws-lambda:recognizeLayerVersion": true,
    // ... AWS CDK Feature Flags
  }
}
```

**コマンドラインパラメータ**:
```bash
cdk deploy ... --parameters EmailAddressParam=ops@example.com
cdk deploy ... -c agentName="my-agent"
```

### 当プロジェクト

**cfn-dev-parameters.json**:
```json
{
  "ParameterKey": "EmailAddress",
  "ParameterValue": "ops@example.com"
}
```

**環境別管理**:
- `cfn-dev-parameters.json` - 開発環境
- `cfn-prod-parameters.json` - 本番環境 (将来対応)

---

## 13. パッケージング・アーティファクト管理

### 参照リポジトリ

**CDK が自動処理**:
1. Lambda コードは `lib/assets/lambdas/` に配置
2. CDK deploy 時に自動で ZIP パッケージング
3. CloudFormation Template に埋め込み
4. デプロイ時に Lambda へアップロード

### 当プロジェクト

**CodePipeline Build フェーズで処理**:
```yaml
build:
  commands:
    - mkdir -p dist
    - cp lib/lambda_handler.py lambda_package/lambda_function.py
    - pip install --target . boto3
    - cd lambda_package && zip -r ../dist/lambda.zip .
    - aws s3 cp dist/lambda.zip s3://dev-image-aiagent-artifact/lambda.zip
```

**特徴**:
- Build フェーズで Lambda ZIP を生成
- S3 にアップロード
- CloudFormation Deploy フェーズで S3 から参照

---

## 14. ロギング & モニタリング

### 参照リポジトリ

**Lambda ログ**:
- CloudWatch Logs に自動出力
- IAM ロールに `logs:*` 権限を付与

**CloudWatch Alarms**:
- Custom Resource が作成 (`create_cloudwatch_alarm()`)
- CPU Utilization > 90% でアラーム

### 当プロジェクト

**Lambda ログ**:
- CloudWatch Logs に詳細ログ出力
- logger.info() で構造化ログ

**CloudWatch Metrics**:
- `put_metric_data()` で Custom Metrics を送信
- LogErrors, BottleneckMetrics 等

**SNS 通知**:
- 各 FR ごとに異なるトピック
- レポートを JSON 形式で送信

---

## 15. セキュリティ & コンプライアンス

### 参照リポジトリ

**cdk-nag**:
```typescript
Aspects.of(app).add(new AwsSolutionsChecks({ verbose: true }))
```

**NagSuppressions**:
```typescript
NagSuppressions.addStackSuppressions(this, [
  { id: 'AwsSolutions-IAM5', reason: '...' }
])
```

**セキュリティ対応**:
- AWS Solutions チェック (セキュリティベストプラクティス)
- サプレッション理由を明示

### 当プロジェクト

**CloudFormation テンプレート**:
- S3 Bucket Encryption (S3 managed)
- S3 BlockPublicAccess (BLOCK_ALL)
- S3 SSL 強制
- 最小権限の IAM ポリシー

**AGENTS.md でセキュリティガイドライン**:
- CloudFormation 操作は CLI で禁止
- CodePipeline で管理

---

## 16. 拡張性・カスタマイズ

### 参照リポジトリ

**新機能追加**:
1. 新しい `construct.ts` を作成
2. `bedrock-agent-cdk-stack.ts` で インスタンス化
3. API Schema JSON を追加
4. Lambda 関数を実装
5. `cdk deploy`

**自動テスト**:
- jest で Construct テストを記述可能

### 当プロジェクト

**新機能追加 (新しい FR)**:
1. `lib/lambda_handler.py` に新しい `handle_XXX()` 関数を追加
2. `lambda_handler()` に条件を追加
3. `cfn-templates/lambda-function.yaml` で IAM 権限を追加
4. ランブック Markdown を `runbooks/` に追加
5. `git push` → CodePipeline が自動デプロイ

**カスタマイズ**:
- Bedrock Agent Instruction を `bedrock-agent.yaml` で修正
- Knowledge Base の OpenSearch クエリを調整
- EventBridge ルールをカスタマイズ

---

## 17. 総合比較表

| 項目 | 参照リポジトリ | 当プロジェクト |
|------|---|---|
| **IAC 言語** | TypeScript (CDK) | YAML (CloudFormation) |
| **Lambda 言語** | Python 3.13 | Python 3.11/3.12 |
| **デプロイ方式** | CDK CLI | CodePipeline |
| **Lambda 関数数** | 3個 | 1個 (統合) |
| **Lambda 総行数** | 285行 | 603行 |
| **パッケージング** | CDK 自動 | CodePipeline Build 自動 |
| **Knowledge Base** | 手動作成 | 自動化 |
| **API Schema** | OpenAPI JSON | なし (event['action']) |
| **EventBridge** | 未使用 | 完全統合 |
| **SNS 通知** | SES メール | SNS 複数チャネル |
| **データ永続化** | なし | S3 バックアップ |
| **Metrics 送信** | なし | CloudWatch Custom Metrics |
| **テスト** | jest | pytest |
| **セキュリティチェック** | cdk-nag | 手動確認 |
| **手動作業** | 多い (3～4 ステップ) | 最小限 (Git Push のみ) |
| **カスタマイズ難易度** | 中 (Construct 学習必要) | 低 (Python + YAML) |
| **スケーラビリティ** | 高 (Construct 再利用) | 中 (ハンドラー統合) |

---

## 18. まとめ：設計パターンの違い

### 参照リポジトリの特徴
- **アーキテクチャ**: マイクロサービス型 (3 つの Lambda)
- **デプロイ**: CDK ネイティブ、強力なオブジェクト指向設計
- **統合**: Bedrock Agent が API Schema で各 Lambda を呼び出し
- **用途**: AWS のサンプルコード、ベストプラクティス示唆
- **拡張性**: Construct ライブラリとして高い再利用性

### 当プロジェクトの特徴
- **アーキテクチャ**: 統合型 (1 つの Lambda で 6 機能)
- **デプロイ**: CloudFormation ネイティブ、完全自動化
- **統合**: EventBridge が CloudWatch Alarms をトリガー
- **用途**: 社内オペレーション自動化プラットフォーム
- **拡張性**: ランブックベースの Knowledge Base 中心

### 設計選択の理由
- **参照リポジトリ**: 教育的、再利用可能な Construct パターン
- **当プロジェクト**: 実運用重視、完全自動化パイプライン

