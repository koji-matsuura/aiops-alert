# AIOps統合アーキテクチャ - 統一実装ガイド

**作成日**: 2026年6月4日  
**対象**: aiops-alert プロジェクト（CloudFormation + Python Lambda 統一実装）  
**目的**: Bedrock Agent による統一された AIOps プラットフォーム

---

## 1. アーキテクチャ概要

### 1.1 統一パイプライン設計

すべてのトリガー（ユーザー入力、CloudWatch Alarms、スケジュール実行）が同一の Bedrock Agent パイプラインを通過します。

```
【複数のトリガー】
  │
  ├─ ユーザー入力（Bedrock Console）
  ├─ CloudWatch Alarms → EventBridge ルール
  └─ スケジュール実行（EventBridge Cron: 毎週日曜 00:00 UTC）
  │
  ↓ (統一 Lambda エントリポイント)
  │
Lambda: handler()
  ├─ extract_event_info() - AWS 公式フィールド抽出
  ├─ build_prompt() - 統一 prompt 構築
  └─ invoke_bedrock_agent() - Bedrock Agent 呼び出し
  │
  ↓
Bedrock Agent (Claude Haiku 4.5)
  ├─ Knowledge Base 検索 (RAG) - ランブック取得
  ├─ 状況分析
  ├─ Action Group で FR-01～06 を判定
  └─ messageVersion 1.0 フォーマットで Lambda 呼び出し
  │
  ↓
Lambda: handle_bedrock_agent_message()
  ├─ dispatch_function() - function 名で FR-XX を実行
  └─ return messageVersion 1.0 レスポンス
  │
  ↓
SNS 通知 + Slack Block Kit レイアウト
  └─ インタラクティブ承認フロー（オプション）
```

### 1.2 ファイル構成

```
cfn-templates/
├── main.yaml                      # ルートスタック（すべてのネストを統合）
├── s3.yaml                        # S3 バケット + Lifecycle Policy
├── opensearch.yaml                # OpenSearch Serverless
├── lambda-function.yaml           # Lambda + IAM + Permission
├── bedrock-agent.yaml             # Bedrock Agent (KnowledgeBase + ActionGroup 統合)
├── knowledge-base.yaml            # Knowledge Base + Data Source
├── eventbridge-alarms.yaml        # EventBridge ルール（7個：6 Alarms + 1 Schedule）
└── security-groups.yaml           # VPC Security Groups

lib/
├── lambda_handler.py              # メインハンドラー
│   ├─ handler()                   # 統一エントリポイント
│   ├─ handle_bedrock_agent_message()  # messageVersion 1.0 処理
│   ├─ dispatch_function()         # FR-XX 関数ディスパッチ
│   ├─ log_investigation_fr01()    # CloudWatch Logs 検索
│   ├─ bottleneck_investigation_fr02()  # メトリクス分析
│   ├─ create_db_snapshot_fr03()   # DB スナップショット作成
│   ├─ maintenance_window_display_fr04()  # メンテナンスウィンドウ表示
│   ├─ slow_query_detection_fr05() # 遅いクエリ検出
│   ├─ high_load_query_detection_fr06()  # 高負荷クエリ分析
│   ├─ extract_event_info()        # AWS 公式フィールド抽出
│   ├─ build_prompt()              # 統一 prompt 構築
│   ├─ invoke_bedrock_agent()      # Bedrock Agent 呼び出し
│   ├─ convert_to_slack_block_kit()  # Block Kit フォーマット変換
│   └─ [他の補助関数 30+]
└── slack_webhook_handler.py       # Slack Webhook ハンドラー（承認フロー用）

runbooks/
├── FR-01-log-investigation.md     # ランブック 1（Git 版管理）
├── FR-01-log-investigation.md.metadata.json  # ランブック 1 メタデータ（Git 版管理）
├── FR-02-bottleneck-investigation.md  # ランブック 2（Git 版管理）
├── FR-02-bottleneck-investigation.md.metadata.json  # ランブック 2 メタデータ（Git 版管理）
├── FR-03-create-db-snapshot.md    # ランブック 3（Git 版管理）
├── FR-03-create-db-snapshot.md.metadata.json  # ランブック 3 メタデータ（Git 版管理）
├── FR-04-maintenance-display.md   # ランブック 4（Git 版管理）
├── FR-04-maintenance-display.md.metadata.json  # ランブック 4 メタデータ（Git 版管理）
├── FR-05-slow-query-detection.md  # ランブック 5（Git 版管理）
├── FR-05-slow-query-detection.md.metadata.json  # ランブック 5 メタデータ（Git 版管理）
├── FR-06-high-load-query-detection.md  # ランブック 6（Git 版管理）
└── FR-06-high-load-query-detection.md.metadata.json  # ランブック 6 メタデータ（Git 版管理）

docs/
├── AGENTS.md                      # 詳細実装ガイド
├── requirements.md                # 要件定義書
├── E2E-TEST-PLAN.md              # E2E テスト計画
├── SECRET-REGISTRATION-GUIDE.md   # シークレット登録ガイド
└── [その他ドキュメント]
```

---

## 2. 実装済み機能

### 2.1 コア機能

✅ **統一 Lambda ハンドラー**
- すべてのトリガーを同一 `handler()` で処理
- AWS 公式イベント構造の直接処理
- Bedrock Agent への統一 prompt 構築

✅ **Bedrock Agent 統合**
- Knowledge Base によるランブック検索（RAG）
- Action Group による FR-01～06 の自動ディスパッチ
- messageVersion 1.0 フォーマット対応

✅ **EventBridge 統合**
- 6 つのアラームルール（EC2, RDS, Lambda）
- 1 つのスケジュールルール（毎週日曜 00:00 UTC）
- Lambda への直接トリガー

✅ **SNS 通知**
- Block Kit リッチレイアウト対応
- スレッド集約（10 分枠）
- インタラクティブ承認ボタン

✅ **Slack Webhook**
- ボタンクリック検証（HMAC-SHA256）
- 承認記録の S3 保存（TTL 付き）
- リプレイ攻撃防止

### 2.2 6 つの調査・復旧関数（FR-01～06）

| FR | 機能 | 対象 | 実装状態 |
|----|------|------|--------|
| FR-01 | ログ調査 | CloudWatch Logs | ✅ 完了 |
| FR-02 | ボトルネック調査 | EC2/RDS/Lambda メトリクス | ✅ 完了 |
| FR-03 | DB スナップショット作成 | RDS | ✅ 完了 |
| FR-04 | メンテナンスウィンドウ表示 | RDS | ✅ 完了 |
| FR-05 | 遅いクエリ検出 | RDS Performance Insights | ✅ 完了 |
| FR-06 | 高負荷クエリ分析 | RDS Performance Insights | ✅ 完了 |

---

## 3. デプロイメント

### 3.1 前提条件

- AWS CLI 設定済み（`default` または `dev` プロファイル）
- S3 バケット作成: `aws s3 mb s3://dev-image-aiagent-artifact --region ap-northeast-1`
- CloudFormation テンプレートアップロード: `aws s3 cp cfn-templates/ s3://dev-image-aiagent-artifact/cfn-templates/ --recursive`

### 3.2 デプロイ手順

1. **github パーソナルアクセストークンを Secrets Manager に登録**
   ```bash
   aws secretsmanager create-secret \
     --name github-token \
     --secret-string "<token>"
   ```

2. **CodePipeline トリガー**
   ```bash
   git add .
   git commit -m "Deploy AIOps platform"
   git push origin main
   ```

3. **パイプラインが自動実行**
   - Build: Lambda パッケージング、テンプレート検証
   - Deploy: CloudFormation スタック作成

### 3.3 検証

```bash
# CloudFormation スタック確認
aws cloudformation describe-stacks --stack-name aiops-main

# Lambda 関数確認
aws lambda list-functions --query 'Functions[?contains(FunctionName, `AiopsLambda`)].FunctionArn'

# Bedrock Agent 確認
aws bedrock-agent list-agents

# EventBridge ルール確認
aws events list-rules --query 'Rules[?contains(Name, `aiops`)].Name'
```

---

## 4. トラブルシューティング

### 4.1 よくある問題

| 症状 | 原因 | 解決策 |
|------|------|--------|
| Lambda が呼ばれない | EventBridge ルール無効 | `aws events describe-rule --name <rule-name>` で確認 |
| Bedrock Agent エラー | Knowledge Base ID が誤り | `aws bedrock-agent describe-knowledge-base --knowledge-base-id <KB_ID>` で確認 |
| SNS 通知が来ない | SNS Permission 不足 | Lambda IAM Role の SNS Policy を確認 |
| Slack 署名エラー | Signing Secret が誤り | cfn-dev-parameters.json の値を確認 |

### 4.2 ログ確認

```bash
# Lambda ログ
aws logs tail /aws/lambda/AiopsLambda --follow

# EventBridge イベント
aws events list-events

# CloudFormation イベント
aws cloudformation describe-stack-events --stack-name aiops-main
```

---

## 5. セキュリティ考慮事項

- ✅ **シークレット**: AWS Secrets Manager で管理（AWS 管理キー）
- ✅ **IAM 権限**: 最小権限の原則で設計
- ✅ **Slack 署名**: HMAC-SHA256 で検証
- ✅ **CloudTrail**: すべてのデプロイを記録

---

## 6. 参考資料

### AWS 公式ドキュメント
- [Bedrock Agent 開発ガイド](https://docs.aws.amazon.com/bedrock/latest/userguide/agents.html)
- [CloudFormation ユーザーガイド](https://docs.aws.amazon.com/AWSCloudFormation/latest/UserGuide/)
- [Lambda ハンドラー](https://docs.aws.amazon.com/lambda/latest/dg/python-handler.html)
- [EventBridge ルール](https://docs.aws.amazon.com/eventbridge/latest/userguide/eb-rules.html)

### Slack 公式ドキュメント
- [Slack API ドキュメント](https://api.slack.com/)
- [Block Kit ビルダー](https://app.slack.com/block-kit-builder)

### ブログ参考
- AWS ブログ: "Automate IT operations with Amazon Bedrock Agents" (著者: Upendra V, Deepak Dixit)

---

## 7. ライセンス・貢献

このプロジェクトは MIT ライセンスの下で公開されています。
バグ報告・機能要望は GitHub Issues にお願いします。
