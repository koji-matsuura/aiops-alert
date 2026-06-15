# Slack Credentials Registration Guide

**Date**: 2026-06-04  
**Purpose**: Register Slack credentials into AWS Secrets Manager after CloudFormation deployment

---

## ⚠️ **重要：秘密情報管理のセキュリティ**

### **なぜ CloudFormation テンプレートに秘密を含めないのか？**

CloudFormation に秘密情報（`SecretString` パラメータ）を埋め込むと：

1. ❌ **git に秘密が記録される**（GitHub に永遠に残る）
2. ❌ **CloudFormation スタック定義に秘密が保存される**（`aws cloudformation describe-stacks` で見える）
3. ❌ **CloudFormation イベント履歴に秘密が記録される**（監査ログに漏洩）
4. ❌ **CodePipeline ログに秘密が記録される**（チームメンバーが見える）

### **正しい方法**

- ✅ CloudFormation では **Secret リソース定義のみ** 作成（中身は空）
- ✅ デプロイ後に **AWS CLI で秘密を登録**（テンプレート外で管理）
- ✅ Secrets Manager に **AWS 管理キー（aws/secretsmanager）で暗号化**（コスト効率的、AWS 推奨）

**根拠**: 
- AWS Secrets Manager Best Practices: https://docs.aws.amazon.com/secretsmanager/latest/userguide/cloudformation.html
- AWS Encryption Best Practices: https://docs.aws.amazon.com/prescriptive-guidance/latest/encryption-best-practices/secrets-manager.html

---

## 📋 **デプロイ手順**

### **ステップ 1: CloudFormation スタックをデプロイ**

```bash
# CodePipeline で自動デプロイ、または手動デプロイ:
aws cloudformation deploy \
  --template-file cfn-templates/main.yaml \
  --stack-name aiops-stack-dev \
  --parameter-overrides \
    EnvironmentName=dev \
  --capabilities CAPABILITY_NAMED_IAM \
  --region ap-northeast-1
```

**デプロイ完了後の確認:**

```bash
aws cloudformation describe-stacks \
  --stack-name aiops-stack-dev \
  --region ap-northeast-1 \
  --query 'Stacks[0].StackStatus'

# 出力: CREATE_COMPLETE または UPDATE_COMPLETE ✅
```

---

### **ステップ 2: Slack App から認証情報を取得**

Slack アプリ設定ページから以下 2 つを確認：

1. **Signing Secret**
   - Slack App ページ → Settings > Basic Information
   - セクション: "App Credentials"
   - 値: `signing_secret_` で始まる英数字の文字列

2. **Bot User OAuth Token**
   - Slack App ページ → Features > OAuth & Permissions
   - セクション: "Bot User OAuth Token"
   - 値: `xoxb-` で始まる英数字の文字列

**⚠️ SECURITY WARNING: 実際の秘密値は Git や ドキュメント、コマンドラインに記載しないこと**

---

### **ステップ 3: AWS CLI で秘密を登録**

```bash
# ⚠️ IMPORTANT: シェル履歴に残さないよう注意してください
# set +o history でシェル履歴を無効にしてから実行してください

# Secrets Manager に登録
# <YOUR_SIGNING_SECRET> と <YOUR_BOT_TOKEN> を Slack から取得した実際の値に置き換える
# 例: export SLACK_SIGNING_SECRET="signing_secret_..."
#     export SLACK_BOT_TOKEN="xoxb-..."
aws secretsmanager put-secret-value \
  --secret-id "aiops/dev/slack" \
  --secret-string "{
    \"signing_secret\": \"${SLACK_SIGNING_SECRET}\",
    \"bot_token\": \"${SLACK_BOT_TOKEN}\"
  }" \
  --region ap-northeast-1
```

**確認メッセージ:**
```json
{
    "ARN": "arn:aws:secretsmanager:ap-northeast-1:123456789012:secret:aiops/dev/slack-abcde",
    "Name": "aiops/dev/slack",
    "VersionId": "12345678-1234-1234-1234-123456789012"
}
```

---

### **ステップ 4: 秘密情報が正しく登録されたか確認**

```bash
aws secretsmanager get-secret-value \
  --secret-id "aiops/dev/slack" \
  --region ap-northeast-1 \
  --query 'SecretString'

# 出力:
# {
#   "signing_secret": "xoxb-...",
#   "bot_token": "xoxp-..."
# }
```

---

### **ステップ 5: Lambda が秘密にアクセスできるか確認**

Lambda ハンドラーが `lib/slack_webhook_handler.py` の `get_slack_credentials()` 関数を実行して取得確認：

```bash
# Lambda テスト実行
aws lambda invoke \
  --function-name aiops-slack-webhook-dev \
  --payload '{"test": true}' \
  --region ap-northeast-1 \
  /tmp/lambda-test-output.json

# CloudWatch Logs で実行ログを確認
aws logs tail "/aws/lambda/aiops-slack-webhook-dev" --follow --region ap-northeast-1
```

ログに以下が表示されれば成功 ✅：
```
Slack credentials retrieved successfully from Secrets Manager
```

---

## 🔄 **秘密情報の更新（ローテーション）**

Slack App の認証情報を変更した場合、以下で更新：

```bash
aws secretsmanager update-secret \
  --secret-id "aiops/dev/slack" \
  --secret-string "{
    \"signing_secret\": \"<new-signing-secret>\",
    \"bot_token\": \"<new-bot-token>\"
  }" \
  --region ap-northeast-1
```

**更新確認:**

```bash
aws secretsmanager describe-secret \
  --secret-id "aiops/dev/slack" \
  --region ap-northeast-1 \
  --query 'LastChangedDate'
```

---

## 📊 **トラブルシューティング**

### **エラー: `ResourceNotFoundException: Secret not found`**

**原因**: Secret リソースが Secrets Manager に存在しない

**解決策**:
```bash
# Secret が存在するか確認
aws secretsmanager list-secrets --region ap-northeast-1

# 存在しない場合は CloudFormation スタックの作成状態を確認
aws cloudformation describe-stacks --stack-name aiops-stack-dev --region ap-northeast-1
```

---

### **エラー: `AccessDenied` (Lambda から秘密にアクセスできない)**

**原因**: Lambda IAM ロールに `secretsmanager:GetSecretValue` 権限がない

**解決策**:
```bash
# Lambda IAM ロールを確認
aws iam get-role-policy \
  --role-name aiops-webhook-lambda-role-dev \
  --policy-name aiops-webhook-lambda-policy-dev \
  --region ap-northeast-1

# ポリシーに以下が含まれているか確認:
# "Action": ["secretsmanager:GetSecretValue"]
```

修正が必要な場合は、`cfn-templates/lambda-function.yaml` の IAM ロール定義を確認・修正。

---

### **エラー: `DecryptionFailure`**

**原因**: Secret が KMS で暗号化されているが、Lambda が復号化権限を持たない

**現在の実装**: AWS 管理キー（aws/secretsmanager）を使用しているため、このエラーは発生しません ✅

---

## 📝 **環境別の秘密登録**

### **開発環境 (dev)**

```bash
aws secretsmanager put-secret-value \
  --secret-id aiops/dev/slack \
  --secret-string '{
    "signing_secret": "<YOUR_SIGNING_SECRET>",
    "bot_token": "<YOUR_BOT_TOKEN>"
  }' \
  --region ap-northeast-1
```

### **ステージング環境 (stg)**

```bash
aws secretsmanager put-secret-value \
  --secret-id aiops/stg/slack \
  --secret-string '{
    "signing_secret": "<YOUR_SIGNING_SECRET>",
    "bot_token": "<YOUR_BOT_TOKEN>"
  }' \
  --region ap-northeast-1
```

### **本番環境 (prod)**

```bash
aws secretsmanager put-secret-value \
  --secret-id aiops/prod/slack \
  --secret-string '{
    "signing_secret": "<YOUR_SIGNING_SECRET>",
    "bot_token": "<YOUR_BOT_TOKEN>"
  }' \
  --region ap-northeast-1
```

⚠️ **注意**: `<YOUR_SIGNING_SECRET>` と `<YOUR_BOT_TOKEN>` を実際の値に置き換えてください。実際の秘密値はドキュメントに記載しないこと。

---

## ✅ **デプロイ完了チェックリスト**

- [ ] CloudFormation スタック: `CREATE_COMPLETE` または `UPDATE_COMPLETE`
- [ ] Slack App から認証情報を取得
- [ ] AWS CLI で秘密を登録（3 環境すべて）
- [ ] `aws secretsmanager get-secret-value` で秘密が取得可能か確認
- [ ] Lambda テスト実行: CloudWatch Logs に "credentials retrieved successfully" が表示される
- [ ] **秘密情報の登録に使用したシェルの履歴を削除**（シェル履歴に環境変数が記録されないよう）

```bash
# bash/zsh の履歴から削除（オプション）
history -c  # 現在のセッション履歴をクリア
unset SLACK_SIGNING_SECRET SLACK_BOT_TOKEN ENVIRONMENT  # 環境変数をクリア
```

---

## 📚 **関連ドキュメント**

- [E2E-TEST-PLAN.md](./E2E-TEST-PLAN.md) - テスト実行手順
- [AGENTS.md](../AGENTS.md) - システムアーキテクチャ概要
- [IMPLEMENTATION-COMPLETE.md](./IMPLEMENTATION-COMPLETE.md) - 実装完了報告
