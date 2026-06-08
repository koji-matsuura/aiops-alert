# 参照リポジトリ（AWS Sample CDK版）のランブック処理方式

**分析対象**: https://github.com/aws-samples/improving-it-operations-efficiency-with-aiops  
**比較対象**: 当プロジェクト aiops-alert  
**作成日**: 2026年6月4日

---

## 1. 参照リポジトリのランブック処理概要

### 1.1 ランブック数と形式

| 項目 | 参照リポジトリ | 当プロジェクト |
|-----|---|---|
| **ランブック数** | 3個 | 6個 |
| **形式** | DOCX (Word形式) | Markdown (.md) |
| **保存場所** | `lib/assets/kb/` | `runbooks/` |
| **処理方式** | 手動作成（UI） | 自動取り込み（API） |

### 1.2 参照リポジトリのランブック一覧

```
lib/assets/kb/
├── runbook_ec2.docx        (24.5 KB)
├── runbook_lambda.docx      (24.5 KB)
└── runbook_dynamodb.docx    (24.4 KB)
```

**特徴**: 
- 3つのサービス別ランブック（EC2, Lambda, DynamoDB）
- バイナリ形式（DOCX）
- リポジトリに静的に格納

---

## 2. 参照リポジトリの処理フロー

### 2.1 CDK デプロイ時の処理

```
TypeScript CDK コード
    ├─ S3KBConstruct (s3-kb-bucket-construct.ts)
    │   ├─ S3 バケット作成
    │   └─ BucketDeployment で lib/assets/kb/ をアップロード
    │
    ├─ S3 に 3つのDOCXを配置
    │
    └─ 出力: S3 バケット名
```

### 2.2 CDK コード実装（S3KBConstruct）

**ファイル**: `lib/constructs/s3-kb-bucket-construct.ts` (58行)

```typescript
// BucketDeployment で lib/assets/kb ディレクトリを S3 にアップロード
new cdk.aws_s3_deployment.BucketDeployment(this, "KBBucket", {
  sources: [
    cdk.aws_s3_deployment.Source.asset(
        "lib/assets/kb"  // ← ここで lib/assets/kb ディレクトリ指定
    ),
  ],
  destinationBucket: s3Bucket
});
```

**処理内容**:
1. `lib/assets/kb/` ディレクトリをアセットとして指定
2. CDK が CloudFormation テンプレート生成時にアップロード対象に含める
3. デプロイ時に S3 バケットに自動アップロード

---

### 2.3 Knowledge Base への登録（手動手順）

参照リポジトリの README より:

```
ステップ1: Knowledge Base 詳細設定
  - 名前: knowledge-base-quick-start-xxxx
  - IAM ロール: 新規作成

ステップ2: Data Source 設定
  - S3 バケット: agent-kb-xxxx-bucket
  ↑ CDK で作成されたバケット

ステップ3: Embeddings モデル選択
  - Titan Embeddings G1 - Text v1.2
  - Vector dimensions: 1536

ステップ4: Knowledge Base を Agent に追加
  - UI から手動で "Add" ボタンをクリック
  - Instruction: "Knowledge base contains runbooks..."

ステップ5: Agent の Lambda 権限設定
  - Lambda リソースベースポリシーを手動編集
```

**重要**: 
- **完全に手動プロセス**（UI を使用）
- CloudFormation には Knowledge Base リソース定義がない
- CDK は S3 バケット作成のみ

---

## 3. 当プロジェクトとの比較

### 3.1 処理フロー比較

#### 参照リポジトリ (CDK版)

```
ローカル: lib/assets/kb/*.docx
    ↓ (CDK デプロイ時に自動アップロード)
S3 バケット
    ↓ (手動: AWS Console UI)
Knowledge Base (手動作成、UI で)
    ↓ (手動: AWS Console UI)
Bedrock Agent（手動で追加）
```

**自動化度**: デプロイまで 70%
**手動作業**: Knowledge Base 作成～Agent 連携（4ステップ、15分程度）

---

#### 当プロジェクト (CloudFormation版)

```
ローカル: runbooks/*.md + bedrock-ingest-template.json
    ↓ (Git Push)
CodePipeline
    ├─ Build: Lambda ZIP 化
    └─ Deploy: CloudFormation（全自動）
        ├─ Knowledge Base 自動作成 (YAML)
        ├─ Data Source 自動作成 (YAML)
        ├─ Bedrock Agent 自動作成 (YAML)
        ├─ EventBridge ルール 自動作成 (YAML)
        └─ Lambda ハンドラー 自動デプロイ
             ↓ (API経由で自動取り込み)
Knowledge Base にランブック自動インジェスト
    ↓
RAG 検索可能
```

**自動化度**: 100% (手動作業なし)
**手動作業**: Git Push のみ

---

### 3.2 ランブック形式の比較

| 項目 | 参照リポジトリ | 当プロジェクト |
|-----|---|---|
| **形式** | DOCX (Word) | Markdown (.md) |
| **テキストエディタ** | Microsoft Word/LibreOffice | Vim/VS Code/任意 |
| **バージョン管理** | バイナリなのでテキスト差分困難 | テキストなので Git 差分表示可能 |
| **メタデータ** | なし | JSON スキーマ定義（category, priority など） |
| **検索対応** | セマンティック検索のみ | セマンティック + メタデータフィルター |
| **拡張性** | 低（DOCX 編集は手作業） | 高（Markdown は簡単編集） |
| **数量** | 3個（固定） | 6個（拡張可能） |

---

## 4. 参照リポジトリの設計上の特徴

### 4.1 なぜ DOCX を選んだのか？

**推測される理由**:

1. **AWS Sample としての汎用性**
   - 多くの企業が Word ドキュメントを既に保有
   - 既存の Runbook ライブラリからの移行が容易

2. **Bedrock Knowledge Base の仕様**
   - DOCX は PDF, Text, Markdown と同じく対応フォーマット
   - 学習用のサンプルとして DOCX を選択

3. **UI での手動作成を想定**
   - Knowledge Base の作成～Agent 連携が手動プロセス
   - ユーザーが AWS Console UI を学ぶことが目的

### 4.2 なぜ自動化していないのか？

参照リポジトリは:
- **教育的なサンプル**（AWS ベストプラクティス示唆）
- **手動ステップを含める**ことで Bedrock Agent の理解を深める
- **全自動化は想定していない**（各企業で独自にカスタマイズすることを想定）

---

## 5. 当プロジェクトが異なる理由

### 5.1 設計哲学の違い

| 観点 | 参照リポジトリ | 当プロジェクト |
|-----|---|---|
| **用途** | AWS 教育・デモンストレーション | 社内オペレーション自動化 |
| **目標** | ベストプラクティス展示 | 完全自動化・運用効率化 |
| **ターゲット** | AWS エンジニア・学習者 | 運用チーム・SRE |
| **手動作業** | あり（学習効果） | なし（自動化重視） |

### 5.2 当プロジェクトが Markdown + API を選んだ理由

1. **Markdown の利点**
   - テキストベース → Git で差分管理
   - 簡単に編集・拡張可能
   - バージョン管理が容易

2. **自動インジェスト API の利用**
   ```bash
   aws bedrock-agent ingest-knowledge-base-documents \
     --knowledge-base-id <KB_ID> \
     --data-source-id <DS_ID> \
     --documents file://runbooks/bedrock-ingest-template.json
   ```
   - CloudFormation デプロイ後に自動実行
   - ランブック追加時も同じ API で対応

3. **メタデータ活用**
   - category, priority, service, difficulty など
   - RAG 検索の精度向上
   - 将来的なフィルター機能対応

---

## 6. アーキテクチャ図比較

### 参照リポジトリ (CDK版)

```
Git リポジトリ
    ├─ lib/
    │   └─ assets/kb/
    │       ├─ runbook_ec2.docx
    │       ├─ runbook_lambda.docx
    │       └─ runbook_dynamodb.docx
    │
    ├─ cdk deploy
    │   ↓
    │   (TypeScript コンパイル → CloudFormation 生成)
    │   ↓
    │   S3 バケット自動作成
    │   ↓
    │   DOCX 3個を S3 にアップロード
    │
    └─ 【手動手順】
        AWS Console UI:
        ├─ Knowledge Base 作成（UI）
        ├─ Data Source 設定（UI）
        ├─ Embeddings モデル選択（UI）
        ├─ Bedrock Agent に追加（UI）
        └─ Lambda 権限設定（手動編集）
            ↓
            Knowledge Base 完成
```

**自動化**: ~70%  
**手動作業**: 4ステップ（15分）

---

### 当プロジェクト (CloudFormation版)

```
Git リポジトリ
    ├─ runbooks/
    │   ├─ FR-01-log-investigation.md
    │   ├─ FR-02-bottleneck-investigation.md
    │   ├─ FR-03-create-db-snapshot.md
    │   ├─ FR-04-maintenance-display.md
    │   ├─ FR-05-slow-query-detection.md
    │   ├─ FR-06-high-load-query-detection.md
    │   ├─ metadata.json
    │   └─ bedrock-ingest-template.json
    │
    ├─ git push
    │   ↓ (自動トリガー)
    │   CodePipeline
    │   ├─ Source: GitHub から取得
    │   ├─ Build: Lambda パッケージング
    │   │   └─ dist/lambda.zip 作成 → S3 アップロード
    │   │
    │   └─ Deploy: CloudFormation
    │       ├─ Knowledge Base 自動作成（YAML）
    │       ├─ Data Source 自動作成（YAML）
    │       ├─ Bedrock Agent 自動作成（YAML）
    │       ├─ EventBridge ルール 自動作成（YAML）
    │       ├─ Lambda ハンドラー デプロイ
    │       │
    │       └─ 【自動化】
    │           CodeBuild スクリプト内で:
    │           aws bedrock-agent ingest-knowledge-base-documents \
    │               --knowledge-base-id ${KB_ID} \
    │               --documents file://runbooks/bedrock-ingest-template.json
    │           ↓
    │           Knowledge Base に 6個のランブック自動登録
    │           ↓
    │           セマンティック検索インデックス自動生成
    │
    └─ 完全自動化完成
```

**自動化**: 100%  
**手動作業**: なし（Git Push のみ）

---

## 7. 統合戦略への影響

### 7.1 今後の改善検討項目

参照リポジトリから学べるパターン:
- **Knowledge Base の構造設計**（3つのサービス別ランブック）
- **Bedrock Agent の Instruction 設定**

当プロジェクトが改良したパターン:
- **6つの機能別ランブック** (参照: 3つサービス別)
- **メタデータによるフィルター機能**（参照: 未実装）
- **完全自動化パイプライン**（参照: 手動）

### 7.2 新規FR追加時の手順比較

#### 参照リポジトリ (手動)

```
1. Word で runbook_service.docx を作成
2. lib/assets/kb/ に保存
3. cdk deploy で S3 にアップロード
4. AWS Console UI で Knowledge Base 再作成
5. Data Source を再スキャン
6. Agent に再度追加
```

**所要時間**: 30分～1時間（手動作業が多い）

---

#### 当プロジェクト (自動)

```
1. Markdown で runbooks/FR-07-new-feature.md を作成
2. bedrock-ingest-template.json に エントリ追加
3. git push
   ↓ (自動)
   CodePipeline が新規ランブックを自動取り込み
```

**所要時間**: 5分（Git push のみ）

---

## 8. ランブック数の違いを示唆するもの

### 参照リポジトリが 3個である理由

1. **サービス単位の分類** (EC2, Lambda, DynamoDB)
2. **AWS Sample としてのシンプル性** (学習用)
3. **手動プロセスの負担考慮**

### 当プロジェクトが 6個である理由

1. **機能単位の分類** (FR-01～FR-06)
2. **社内オペレーション自動化**（複雑な要件対応）
3. **Performance Insights API 活用** (FR-05/FR-06)
4. **完全自動化で拡張性重視**

---

## 9. 今後の統合提案

### 参照リポジトリの設計から学べる要素

✅ **取り入れるべき**:
- サービス別の Runbook 構成（EC2, RDS, Lambda など）
- Knowledge Base の Instruction 最適化

❌ **変更すべき**:
- DOCX → Markdown に変更（テキスト管理）
- 手動 UI プロセス → 完全自動化
- 3個 → 6個+ へのスケーリング対応

### 統合後の理想的なランブック構成

```
runbooks/
├── services/
│   ├── ec2/
│   │   └── FR-02-bottleneck-investigation.md
│   ├── rds/
│   │   ├── FR-03-create-db-snapshot.md
│   │   ├── FR-05-slow-query-detection.md
│   │   └── FR-06-high-load-query-detection.md
│   └── lambda/
│       └── FR-01-log-investigation.md
├── metadata.json
└── bedrock-ingest-template.json
```

**効果**:
- 参照リポジトリのサービス別構成を採用
- 当プロジェクトの自動化・拡張性を維持
- メタデータでサービスフィルター対応

---

## 10. 結論

| 観点 | 参照リポジトリ | 当プロジェクト |
|-----|---|---|
| **ランブック形式** | DOCX (手作業) | Markdown (自動化) |
| **数量** | 3個（固定） | 6個（拡張可能） |
| **処理方式** | 手動 UI | 自動 API + CloudFormation |
| **メタデータ** | なし | あり（5属性） |
| **自動化度** | ~70% | 100% |
| **拡張性** | 低 | 高 |

**統合方向**:
- 参照リポジトリ: **ランブック構成設計**（サービス別）を学ぶ
- 当プロジェクト: **自動化・メタデータ活用**を深掘り
- **最適な融合**: サービス別構成 + Markdown + 自動化 + メタデータ

---

**作成日**: 2026年6月4日  
**次の検討**: Knowledge Base 構成の最適化設計
