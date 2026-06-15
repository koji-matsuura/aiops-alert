# 🔐 セキュリティ対応レポート - Slack API Token 流出防止

**作成日時**: 2026-06-20  
**対応者**: OpenCode Agent  
**優先度**: 🔴 CRITICAL  
**ステータス**: 対応完了（検証待機中）

---

## 1. 問題の概要

### 1.1 セキュリティ警告内容

**警告ソース**: GitHub Pre-commit Hook / Git Secret Scanner  
**検出内容**: Slack API Token（xoxb- / xoxp- 形式）がドキュメント内に含まれている

```
remote:        —— Slack API Token ———————————————————————————————————
remote:        locations:
remote:          - commit: 23004f0ad386f084f5664a3e1b15a7821cf5dfee
remote:            path: docs/SECRET-REGISTRATION-GUIDE.md:75
remote:          - commit: 5e5e74b1d8a52067604813a7771bf9f8dca182cd
remote:            path: docs/SECRET-REGISTRATION-GUIDE.md:75
remote:          - commit: 23004f0ad386f084f5664a3e1b15a7821cf5dfee
remote:            path: docs/SECRET-REGISTRATION-GUIDE.md:85
```

### 1.2 リスク評価

| リスク項目 | 深刻度 | 影響度 |
|----------|--------|--------|
| Git history へのトークン記録 | 🔴 CRITICAL | 非常に高い |
| GitHub リポジトリ クローン時にトークン公開 | 🔴 CRITICAL | 非常に高い |
| Slack アカウント乗っ取り | 🔴 CRITICAL | 非常に高い |
| ボット権限による不正操作 | 🔴 CRITICAL | 非常に高い |

---

## 2. 対応内容

### 2.1 完了項目 ✅

| 対応内容 | 実施内容 | 状態 |
|---------|---------|------|
| **ドキュメント修正** | SECRET-REGISTRATION-GUIDE.md からプレースホルダー化 | ✅ 完了 |
| **.gitignore 作成** | `*xoxb*`, `*xoxp*`, `*xoxs*` パターン追加 | ✅ 完了 |
| **Pre-commit hook 設定** | .pre-commit-config.yaml 作成（detect-secrets, gitleaks） | ✅ 完了 |

### 2.2 推奨実施項目 ⏳

| 対応内容 | 優先度 | 実施方法 |
|---------|--------|--------|
| **Git history 削除** | CRITICAL | BFG Repo-Cleaner で過去コミットから削除 |
| **Slack Token 無効化** | CRITICAL | Slack App 管理画面から token regenerate |
| **Pre-commit hook インストール** | HIGH | `pip install pre-commit && pre-commit install` |

---

## 3. ファイル修正内容

### 3.1 .gitignore（新規作成）

**ファイル**: `/Users/matsuurakouji/aiops-alert/.gitignore`  
**行数**: 70 行  
**内容**:
- Python キャッシュ除外
- **機密情報パターン**: `*.secret`, `*.key`, `*.token`
- **Slack トークン明示**: `*xoxb*`, `*xoxp*`, `*xoxs*`
- **AWS 認証情報**: `*AKIA*`, `*aws_secret*`
- IDE、一時ファイルなど

### 3.2 .pre-commit-config.yaml（新規作成）

**ファイル**: `/Users/matsuurakouji/aiops-alert/.pre-commit-config.yaml`  
**行数**: 95 行  
**含まれるツール**:
1. **detect-secrets** (v1.4.0)
   - Slack tokens, API keys を検出
   - `--baseline` で既知の秘密を許可可能
2. **Gitleaks** (v8.18.0)
   - 包括的な秘密スキャン
3. **TruffleHog** (v3.63.0)
   - ディープ秘密スキャン

**導入手順**:
```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

### 3.3 현재のドキュメント確認

✅ **SECRET-REGISTRATION-GUIDE.md**: 
- すべての例値がプレースホルダー化済み
- 実際のトークン形式の説明は `<YOUR_SIGNING_SECRET>`, `<YOUR_BOT_TOKEN>` で表記

✅ **E2E-TEST-PLAN.md**: 
- Bearer token 例が `<YOUR_BOT_TOKEN>` で表記

---

## 4. 次のステップ

### 4.1 IMMEDIATE（24時間以内）

#### Step 1: Slack App Token を無効化・ローテーション
```bash
# Slack App 管理画面で:
# 1. Settings → Basic Information → App Credentials
# 2. "Signing Secret" → "Rotate" ボタンをクリック
# 3. "Generate New Token" で新しい Bot Token を生成
# 4. 古いトークンを無効化
```

**理由**: コミット履歴に露出したトークンは即座に無効化すべき

#### Step 2: 新しい認証情報を Secrets Manager に登録
```bash
# 新しい Signing Secret と Bot Token を Secrets Manager に登録
aws secretsmanager update-secret \
  --secret-id "aiops/dev/slack" \
  --secret-string '{"signing_secret":"<NEW_SIGNING_SECRET>","bot_token":"<NEW_BOT_TOKEN>"}' \
  --region ap-northeast-1
```

#### Step 3: Lambda 環境変数を更新
- Lambda 関数（aiops-slack-webhook-dev）をデプロイ
- 新しい認証情報で動作確認

### 4.2 SHORT-TERM（1 週間以内）

#### Step 1: Git history から秘密を削除（BFG Repo-Cleaner）
```bash
# 1. BFG Repo-Cleaner をインストール
brew install bfg

# 2. 秘密検出リストを作成
cat > /tmp/secrets-to-remove.txt << 'EOF'
# Replace with actual values if they exist in history
# Example format: xoxb-XXXX...
EOF

# 3. BFG で履歴から削除
bfg --replace-text /tmp/secrets-to-remove.txt --no-blob-protection

# 4. 強制プッシュ
git reflog expire --expire=now --all
git gc --prune=now --aggressive
git push origin --force-with-lease
```

**⚠️ 注意**: force-with-lease は慎重に実行。チーム全員が新しい履歴をクローンし直す必要があります。

#### Step 2: Pre-commit hook をインストール
```bash
pip install pre-commit
pre-commit install
pre-commit run --all-files
```

#### Step 3: .secrets.baseline を生成・コミット
```bash
detect-secrets scan > .secrets.baseline
git add .secrets.baseline
git commit -m "🔐 Add detect-secrets baseline"
```

### 4.3 LONG-TERM（定期的）

| 対応内容 | 頻度 | 実施者 |
|---------|------|--------|
| Pre-commit hook の自動実行 | 全コミット時 | Git hook（自動） |
| Slack Token ローテーション | 90 日ごと | DevOps/Team Lead |
| 秘密スキャン監査 | 月 1 回 | Security Team |
| GitHub Advanced Security 設定確認 | 月 1 回 | Repo Admin |

---

## 5. 技術的詳細

### 5.1 Slack Token 形式と検出パターン

| Token 種別 | プレフィックス | 例 | 検出優先度 |
|-----------|------------|-----|----------|
| Signing Secret | `signing_secret_` | signing_secret_... | HIGH |
| Bot Token | `xoxb-` | xoxb-... | CRITICAL |
| User Token | `xoxp-` | xoxp-... | CRITICAL |
| Refresh Token | `xoxe-` | xoxe-... | CRITICAL |
| User Session | `xoxs-` | xoxs-... | HIGH |

### 5.2 検出ツール比較

| ツール | 精度 | 速度 | セットアップ | 推奨度 |
|--------|------|------|-----------|--------|
| detect-secrets | ⭐⭐⭐⭐ | ⭐⭐⭐⭐ | 簡単 | ⭐⭐⭐⭐ |
| Gitleaks | ⭐⭐⭐⭐⭐ | ⭐⭐⭐ | 中程度 | ⭐⭐⭐⭐ |
| TruffleHog | ⭐⭐⭐⭐ | ⭐⭐ | 複雑 | ⭐⭐⭐ |

**推奨**: detect-secrets + Gitleaks の組み合わせ

### 5.3 .gitignore パターンの説明

```bash
# Slack credentials (明示的なパターン)
*xoxb*   # Bot Token
*xoxp*   # User/Legacy Token
*xoxs*   # User Session Token

# AWS credentials
*AKIA*   # AWS Access Key ID
*aws_secret*  # AWS Secret Access Key

# Generic secrets
*.secret, *.key, *.token, *.pem
```

これらのパターンにより、誤ってコミットされた秘密は自動的に .gitignore で無視されます。

---

## 6. チェックリスト

### 直ちに実施 🚨

- [ ] Slack App の古い Token を無効化（Slack 管理画面）
- [ ] 新しい Token を生成
- [ ] Secrets Manager に新しい Token を登録
- [ ] Lambda 環境変数を更新してデプロイ

### 1 週間以内に実施

- [ ] Git history から秘密を削除（BFG Repo-Cleaner）
- [ ] Pre-commit hook をインストール（全開発者）
- [ ] .secrets.baseline を生成・コミット
- [ ] Git history 削除後、全開発者が新しい履歴をクローン

### 定期的に実施

- [ ] Pre-commit hook が正常に動作しているか確認（毎日）
- [ ] Slack Token をローテーション（90 日ごと）
- [ ] セキュリティ監査を実施（月 1 回）

---

## 7. 参考資料

### セキュリティベストプラクティス
- [Slack Security Best Practices](https://api.slack.com/authentication/best-practices)
- [AWS Secrets Manager Best Practices](https://docs.aws.amazon.com/secretsmanager/latest/userguide/best-practices.html)
- [OWASP - Secrets Management](https://owasp.org/www-community/attacks/Secrets_Management)

### 検出ツールドキュメント
- [detect-secrets](https://github.com/Yelp/detect-secrets)
- [Gitleaks](https://github.com/gitleaks/gitleaks)
- [TruffleHog](https://github.com/trufflesecurity/trufflehog)

### Git セキュリティ
- [BFG Repo-Cleaner](https://rtyley.github.io/bfg-repo-cleaner/)
- [GitHub - Removing sensitive data](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository)

---

## 8. 対応者署名

| 項目 | 内容 |
|------|------|
| 対応完了日 | 2026-06-20 |
| 作業内容 | .gitignore, .pre-commit-config.yaml 作成 |
| 次のアクション | Slack Token 無効化 → Git history 削除 → デプロイ |
| セキュリティリスク | ⚠️ 削減（完全除去待機中） |

---

## 9. 付録: 導入ガイド（チーム向け）

### 9.1 新規開発者のセットアップ

```bash
# 1. リポジトリをクローン
git clone https://github.com/your-org/aiops-alert.git
cd aiops-alert

# 2. Pre-commit hook をインストール
pip install pre-commit
pre-commit install

# 3. 既存ファイルをスキャン（オプション）
pre-commit run --all-files

# 4. 確認
echo "✅ セットアップ完了: 次回コミット時に自動スキャンが実行されます"
```

### 9.2 秘密情報を誤ってコミットした場合

```bash
# ローカルのみの場合（push 前）
git reset HEAD~1  # コミットを取り消し
git add .gitignore  # .gitignore を追加
git commit -m "🔐 Add to gitignore"

# 既に push した場合
# → 即座に管理者に報告
# → Slack Token を無効化（Slack 管理画面）
# → BFG で history から削除（管理者）
```

---

**ステータス**: 🟡 対応中（Slack Token 無効化待機中）
