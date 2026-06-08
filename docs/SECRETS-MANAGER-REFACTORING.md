# Secrets Manager 修正報告（2026-06-04）

**Status**: ✅ 完了  
**修正内容**: CloudFormation テンプレートから秘密情報を除外 + AWS 管理キー採用  
**理由**: AWS 公式推奨に準拠 + セキュリティベストプラクティス  

---

## 📋 **修正内容サマリー**

| 項目 | 修正前 | 修正後 | 根拠 |
|------|--------|--------|------|
| **テンプレートの秘密情報** | ❌ `!Sub` で埋め込み | ✅ 除外 | AWS Secrets Manager Best Practices |
| **CloudFormation パラメータ** | ❌ `SlackSigningSecret`, `SlackBotToken` | ✅ 削除 | 秘密漏洩リスク削減 |
| **KMS 暗号化方式** | ❌ カスタマー管理キー | ✅ AWS 管理キー | AWS 公式推奨 |
| **シークレット登録方法** | ❌ テンプレートデプロイ時 | ✅ デプロイ後 CLI | セキュリティ強化 |

---

## 🔍 **修正ファイル一覧**

### **1. `cfn-templates/secrets-manager.yaml` (修正)**

**削除内容:**
- ❌ `SecretsEncryptionKey` リソース（行 28-50）
- ❌ `SecretsEncryptionKeyAlias` リソース（行 52-56）
- ❌ `SlackSigningSecret` パラメータ（行 14-18）
- ❌ `SlackBotToken` パラメータ（行 20-24）
- ❌ `SlackCredentialsSecret` の `KmsKeyId` プロパティ（行 64）
- ❌ `SlackCredentialsSecret` の `SecretString` プロパティ（行 65-69）
- ❌ `SecretsEncryptionKeyArn` Output（行 112-116）
- ❌ `SecretsEncryptionKeyId` Output（行 118-121）

**追加内容:**
- ✅ コメント: 秘密登録の手順（行 57-72）
- ✅ `EnvironmentName` パラメータのみ保持
- ✅ Secret リソース定義は保持（中身なし）
- ✅ Secret Policy リソースは保持
- ✅ `PostDeploymentInstruction` Output 追加

**ファイル行数:**
- 修正前: 122 行
- 修正後: 90 行
- **削減: 32 行**

**修正後の状態:**
```yaml
# CloudFormation テンプレート内に秘密情報は含まれない
SlackCredentialsSecret:
  Type: AWS::SecretsManager::Secret
  Properties:
    Name: !Sub 'aiops/${EnvironmentName}/slack'
    Description: 'Slack app credentials (signing secret and bot token) - register via CLI after deployment'
    # KmsKeyId omitted - uses AWS managed key (aws/secretsmanager)
    Tags:
      - Key: Environment
        Value: !Ref EnvironmentName
```

**cfn-lint 検証:** ✅ 0 errors, 0 warnings

---

### **2. `docs/SECRET-REGISTRATION-GUIDE.md` (新規作成)**

**内容:**
- AWS CLI での秘密登録手順
- 環境別の登録方法（dev/stg/prod）
- トラブルシューティング
- セキュリティ理由の説明
- AWS 公式ドキュメントへのリンク

**長さ:** 327 行

---

## ✅ **セキュリティ改善**

### **修正前の問題点**

| 流出経路 | 状況 |
|---------|------|
| **git リポジトリ** | ❌ パラメータ値がコミット履歴に記録される |
| **CloudFormation テンプレート** | ❌ `describe-stacks` で秘密が見える |
| **CloudFormation イベント** | ❌ デプロイイベントに秘密が含まれる |
| **CodePipeline ログ** | ❌ BuildSpec ログに秘密が記録される |

### **修正後の状態**

| 流出経路 | 状況 |
|---------|------|
| **git リポジトリ** | ✅ テンプレートに秘密なし |
| **CloudFormation テンプレート** | ✅ Secret リソースのみ（中身なし） |
| **CloudFormation イベント** | ✅ 秘密は記録されない |
| **CodePipeline ログ** | ✅ 秘密は記録されない |
| **Secrets Manager** | ✅ AWS 管理キーで暗号化 |

---

## 📚 **根拠・参考資料**

### **AWS 公式ドキュメント**

1. **Secrets Manager Best Practices**
   - URL: https://docs.aws.amazon.com/secretsmanager/latest/userguide/cloudformation.html
   - **推奨**: CloudFormation テンプレートに秘密を埋め込まない

2. **Encryption Best Practices for AWS Secrets Manager**
   - URL: https://docs.aws.amazon.com/prescriptive-guidance/latest/encryption-best-practices/secrets-manager.html
   - **推奨**: 「For most use cases, AWS recommends using the free aws/secretsmanager AWS managed key」

3. **Slack API Security**
   - URL: https://api.slack.com/authentication/verifying-requests-from-slack
   - **推奨**: 署名検証でリプレイ攻撃を防止（実装済み in `slack_webhook_handler.py`）

---

## 🔄 **関連ファイルの状態**

### **変更不要のファイル**

| ファイル | 理由 |
|---------|------|
| `lib/slack_webhook_handler.py` | Secrets Manager クライアントは KMS 方式に依存しない |
| `cfn-templates/main.yaml` | ネストスタック参照を保持（Secret リソースは存在） |
| `cfn-templates/lambda-function.yaml` | IAM ロール定義は変わらない |
| `cfn-templates/s3.yaml` | 変更なし |
| `cfn-dev-parameters.json` など | Secret パラメータは削除されるため更新不要 |

---

## 🚀 **次ステップ（デプロイ手順）**

1. **Git コミット**
   ```bash
   git add cfn-templates/secrets-manager.yaml docs/SECRET-REGISTRATION-GUIDE.md
   git commit -m "fix: Remove secrets from CloudFormation template, use AWS managed key for Secrets Manager"
   git push origin main
   ```

2. **CodePipeline で自動デプロイ**
   - GitHub push → CodePipeline トリガー
   - CloudFormation デプロイ

3. **デプロイ後：秘密登録**
   - `docs/SECRET-REGISTRATION-GUIDE.md` の手順に従って AWS CLI で秘密を登録

4. **検証**
   - `aws secretsmanager get-secret-value` で秘密が取得可能か確認
   - Lambda テスト実行で CloudWatch Logs を確認

---

## 📊 **修正による影響評価**

### **機能への影響**

- ✅ **なし**: Lambda ハンドラーは AWS 管理キー/カスタマー管理キーの区別をしない
- ✅ **なし**: Slack ボタン処理は変わらない
- ✅ **なし**: SNS 通知は変わらない

### **セキュリティへの影響**

- ✅ **向上**: 秘密がテンプレートから除外される
- ✅ **向上**: git に秘密が記録されない
- ✅ **向上**: AWS 公式推奨に準拠

### **コスト効果**

- ✅ **削減**: KMS 暗号化料金が 0 に（AWS 管理キーは無料）
- ✅ **削減**: テンプレートが 32 行短縮

---

## ✨ **修正完了**

修正内容は AWS 公式推奨に完全に準拠しており、セキュリティベストプラクティスを満たしています。

次のフェーズでは、E2E テスト実行 → 本番デプロイに進めます。
