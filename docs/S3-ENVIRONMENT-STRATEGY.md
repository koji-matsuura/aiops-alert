# 📋 S3 実装戦略 - 現在の設定と拡張可能性

## 現在の実装

### S3 バケット構成

- **バケット名**: `dev-image-aiagent-artifact`
- **用途**:
  - CloudFormation テンプレート保存
  - Lambda ZIP ファイル保存
  - ランブック・ドキュメント保存
  - Slack 承認記録保存（TTL 付き）
  - Thread ID マッピング保存

### パラメータファイル

現在は開発環境向けのみ実装：
- ✅ `cfn-dev-parameters.json` - 開発環境用

将来の拡張に向けた設計：
- ⏳ `cfn-stg-parameters.json` - ステージング環境用（未実装）
- ⏳ `cfn-prod-parameters.json` - 本番環境用（未実装）

### 現在の制限事項

1. **単一バケット制限**: すべての環境が `dev-image-aiagent-artifact` を使用
2. **環境分離なし**: 開発・ステージング・本番のデータが混在する可能性
3. **バージョニング未実装**: CloudFormation テンプレート更新時のロールバック対応不足

---

## 拡張可能性

### 環境別バケット分離戦略（将来実装予定）

```
Dev 環境:
  - バケット: dev-image-aiagent-artifact
  - リージョン: ap-northeast-1
  - ライフサイクル: 7日で削除

Stg 環境:
  - バケット: stg-image-aiagent-artifact
  - リージョン: ap-northeast-1
  - ライフサイクル: 30日で削除

Prod 環境:
  - バケット: prod-image-aiagent-artifact
  - リージョン: ap-northeast-1
  - ライフサイクル: 永続保存
```

### 実装手順

1. **パラメータファイル作成**
   ```bash
   cp cfn-dev-parameters.json cfn-stg-parameters.json
   cp cfn-dev-parameters.json cfn-prod-parameters.json
   ```

2. **バケット名更新**
   ```json
   {
     "Parameters": {
       "TemplateBucketName": "stg-image-aiagent-artifact"  // 環境別に変更
     }
   }
   ```

3. **S3 バケット作成**
   ```bash
   aws s3 mb s3://stg-image-aiagent-artifact --region ap-northeast-1
   aws s3 mb s3://prod-image-aiagent-artifact --region ap-northeast-1
   ```

4. **CloudFormation デプロイ**
   ```bash
   # Stg 環境
   git push origin main  # CodePipeline が cfn-stg-parameters.json を参照
   
   # Prod 環境
   git push origin main  # CodePipeline が cfn-prod-parameters.json を参照
   ```

---

## セキュリティ考慮事項

- ✅ **暗号化**: S3 バケットは AES-256 で暗号化（デフォルト）
- ✅ **アクセス制御**: CloudFormation 実行ロールのみアクセス可能
- ✅ **ライフサイクル**: 承認記録は TTL 付きで自動削除
- ✅ **ログ**: CloudTrail で全アクセスを記録

---

## ベストプラクティス

1. **バケット単位での環境分離**: 環境が異なれば別バケット
2. **ライフサイクルポリシー**: 環境別に異なる保有期間
3. **バージョニング**: CloudFormation テンプレートの世代管理
4. **タグ付け**: 環境・プロジェクト・所有者でタグ管理

---

## 参考資料

- [AWS S3 ベストプラクティス](https://docs.aws.amazon.com/AmazonS3/latest/userguide/BestPractices.html)
- [S3 ライフサイクルポリシー](https://docs.aws.amazon.com/AmazonS3/latest/userguide/object-lifecycle-mgmt.html)
| AGENTS.md | AGENTS.md:884 | ❌ 「環境ごとに異なる」と記載だが、根拠なし |
| 要件定義 | docs/requirements.md | ❌ NFR-03 はログ保存のみ、環境分離戦略なし |
| 統合戦略 | docs/INTEGRATION_STRATEGY.md | ❌ 「単一テナント（開発環境のみ）」と明記 |

**AGENTS.md の矛盾:**

**行 884（Q&A 形式）:**
```
Q：S3 バケット名が環境ごとに異なるのは？
A：cfn-*-parameters.json の TemplateBucketName パラメータで指定。
   Pipeline が自動で参照。
```

**矛盾の根拠:**
- ✅ 「環境ごとに異なる」と述べている
- ❌ しかし `cfn-stg-parameters.json` が存在しない
- ❌ `cfn-prod-parameters.json` が存在しない
- ❌ つまり「異なる」ことが実装されていない

**情報ソース:**
- AGENTS.md 行 884
- ファイルシステム検索結果

---

**docs/INTEGRATION_STRATEGY.md の記載:**

```
【目標】複数チーム・複数環境への対応
【現在】単一テナント（開発環境のみ）
```

**意味:**
- Stg/Prod は「今後の課題」
- 現在は Dev 環境専用として設計されている

**情報ソース:**
- docs/INTEGRATION_STRATEGY.md

---

### 🔍 なぜこのギャップが発生したのか

#### **根拠 1: 開発段階のため、単一環境（Dev）のみ実装**

**根拠:**
- cfn-dev-parameters.json のみ存在（Stg/Prod なし）
- docs/INTEGRATION_STRATEGY.md で「単一テナント（開発環境のみ）」と明記
- テンプレートは複数環境対応だが、パラメータが Dev 用のみ

**結論:**
- 「意図的に同じ S3 を使っている」わけではなく
- 「複数環境パラメータを実装していない」

---

#### **根拠 2: テンプレートはパラメータ化されているが使用されていない**

**実装:**
- `cfn-templates/main.yaml` は `TemplateBucketName` をパラメータ化 ✅
- `cfn-templates/s3.yaml` は `BucketName` で条件分岐 ✅
- しかし `cfn-stg-parameters.json` などを使用する仕組みがない ❌

**意味:**
- 「将来の拡張を想定した設計」
- 「しかし Stg/Prod への拡張はまだ実装していない」

**情報ソース:**
- `cfn-templates/main.yaml` 行 5-7, 34
- `cfn-templates/s3.yaml` 行 8-14

---

### 🎯 「同じ S3 を使う」理由の真実

| 判定 | 説明 | 根拠 |
|------|------|------|
| **設計判断** | ❌ NO | ドキュメントに「なぜ同じバケットなのか」という説明がない |
| **意図的選択** | ❌ NO | AGENTS.md は「環境ごとに異なる」と述べているが、実装がない |
| **実装未完了** | ✅ YES | cfn-stg/prod-parameters.json が存在しない |
| **開発段階** | ✅ YES | docs/INTEGRATION_STRATEGY.md で「単一テナント（開発環境のみ）」と明記 |

---

## 📝 本来あるべき S3 環境戦略

### Phase 1（現在：開発段階）
```
Dev 環境のみ実装
├─ TemplateBucket: dev-image-aiagent-artifact
├─ DataBucket: aiops-kb-{AccountId}-{Region} または既存参照
└─ 理由: 開発効率化（1 つのバケットで管理）
```

### Phase 2（本番環境対応：未実装）
```
環境別バケット分離
├─ Dev:
│   ├─ TemplateBucket: dev-image-aiagent-artifact
│   └─ DataBucket: dev-aiops-kb-bucket
├─ Stg:
│   ├─ TemplateBucket: stg-image-aiagent-artifact
│   └─ DataBucket: stg-aiops-kb-bucket
└─ Prod:
    ├─ TemplateBucket: prod-image-aiagent-artifact
    └─ DataBucket: prod-aiops-kb-bucket

理由: データ隔離 + セキュリティ + コンプライアンス
```

---

## ✅ 推奨される対応

### A. 即座の対応：ドキュメント修正（根拠ソースの追加）

1. **AGENTS.md 行 884 の修正**

**現在:**
```
Q：S3 バケット名が環境ごとに異なるのは？
A：cfn-*-parameters.json の TemplateBucketName パラメータで指定。
   Pipeline が自動で参照。
```

**修正後:**
```
Q：S3 バケット名が環境ごとに異なるのは？
A：【現在は未実装】テンプレートはパラメータ化されていますが、
   cfn-stg-parameters.json と cfn-prod-parameters.json がまだ作成されていません。
   
【開発段階（Phase 1）】
- Dev 環境のみ実装: cfn-dev-parameters.json で TemplateBucketName 指定
- 情報ソース: cfn-dev-parameters.json:3

【将来の計画（Phase 2）】
- Stg 環境: cfn-stg-parameters.json で別バケット指定
- Prod 環境: cfn-prod-parameters.json で別バケット指定
- 理由: docs/INTEGRATION_STRATEGY.md で「複数環境への対応」と明記
```

2. **docs/S3-ENVIRONMENT-STRATEGY.md を作成**

```markdown
# S3 環境分離戦略

## 現在の状態（Phase 1：開発段階）

### 実装状況
- ✅ Dev 環境用パラメータ: cfn-dev-parameters.json
- ❌ Stg 環境用パラメータ: 未作成
- ❌ Prod 環境用パラメータ: 未作成

### S3 バケット
| 環境 | TemplateBucket | DataBucket | 状態 |
|-----|----------------|-----------|------|
| Dev | dev-image-aiagent-artifact | 自動生成 | ✅ 実装済み |
| Stg | - | - | ❌ 未実装 |
| Prod | - | - | ❌ 未実装 |

### 理由
- 開発効率化のため、単一環境（Dev）で検証
- テンプレートはパラメータ化済み（複数環境対応可能）
- 情報ソース: docs/INTEGRATION_STRATEGY.md「単一テナント（開発環境のみ）」

## 今後の計画（Phase 2+：本番環境対応）

### 目標
- Stg/Prod で環境別バケット分離
- データ隔離 + セキュリティ強化
- 情報ソース: docs/INTEGRATION_STRATEGY.md「複数チーム・複数環境への対応」

### 実装方法
1. cfn-stg-parameters.json 作成
2. cfn-prod-parameters.json 作成
3. CodePipeline で環境別パラメータを自動選択
```

---

### B. Phase 2 実装（本番環境対応）

1. **cfn-stg-parameters.json 作成**

```json
{
  "Parameters": {
    "TemplateBucketName": "stg-image-aiagent-artifact",
    "EnvName": "stg",
    ...
  }
}
```

2. **cfn-prod-parameters.json 作成**

```json
{
  "Parameters": {
    "TemplateBucketName": "prod-image-aiagent-artifact",
    "EnvName": "prod",
    ...
  }
}
```

3. **S3 テンプレートに警告を追加**

**cfn-templates/s3.yaml:**
```yaml
Parameters:
  BucketName:
    Type: String
    Description: |
      Existing S3 bucket name for Knowledge Base runbooks.
      【注意】Default を空にする（新規作成）は Dev 環境のみ推奨。
      Stg/Prod では必ず既存バケット名を指定してください。
    Default: ""
```

---

## 🎓 結論

**質問：「なぜ Dev/Stg/Prd で同じ S3 を使うのか。その理由が説明されていない」**

### 答え

| 層 | 説明 |
|----|------|
| **実装現実** | cfn-stg/prod-parameters.json が存在しないため、Dev パラメータが使用される |
| **設計意図** | テンプレートはパラメータ化（複数環境対応可能）、しかし拡張していない |
| **ドキュメント** | AGENTS.md では「環境ごとに異なる」と述べるが、根拠がない |
| **真の理由** | 開発段階のため、単一環境（Dev）のみ実装。Stg/Prod は未実装 |
| **根拠ソース** | docs/INTEGRATION_STRATEGY.md「単一テナント（開発環境のみ）」 |

### 最終判定
```
「同じ S3 を使う」理由
  = 「設計判断がある」ではなく
  = 「複数環境パラメータが未実装である」
```

**推奨対応:**
- 即座：ドキュメント修正（根拠明記）
- Phase 2：Stg/Prod パラメータファイル作成

---

## 📚 参考資料

| ファイル | 行番号 | 内容 |
|---------|--------|------|
| cfn-dev-parameters.json | 3 | TemplateBucketName: dev-image-aiagent-artifact |
| cfn-templates/main.yaml | 12-15 | ExistingBucketName パラメータ定義 |
| cfn-templates/s3.yaml | 8-14 | Condition: CreateBucket 定義 |
| docs/INTEGRATION_STRATEGY.md | - | 「単一テナント（開発環境のみ）」 |
| AGENTS.md | 884 | S3 バケット名が環境ごとに異なるという説明 |
