# source-verification スキル増強計画

**作成日**: 2026年6月4日  
**対象**: プロジェクト `aiops-alert`  
**背景**: 架空の CloudFormation Condition 作成に気づかず、ドキュメントに根拠なし記載

---

## 1. 不具合分析

### 発生事象

| 時系列 | 実施内容 | 誤り |
|------|--------|------|
| 開発初期 | s3.yaml に Condition `CreateBucket` を作成 | ✗ 根拠なし |
| その後 | AGENTS.md に「環境ごとにバケット作成を切り替える」と記載 | ✗ 実装なし |
| 検証段階 | 実装を確認せずに多数のドキュメント記載 | ✗ すべて架空 |
| 発見 | 「複数環境対応」と述べておきながら、Dev のみ実装 | **矛盾！** |

### 根本原因

1. **実装ファイルを読まずにドキュメント記載**
   - cfn-templates/s3.yaml を開いて Condition を確認していない
   - 「～があるはず」という想定で書いた

2. **ドキュメント相互検証なし**
   - AGENTS.md で述べた仕様が CloudFormation テンプレートに実装されているか確認していない
   - 逆方向（テンプレートの内容がドキュメントに記載されているか）の検証もなし

3. **パラメータファイルの実装を確認していない**
   - cfn-dev-parameters.json は存在するが
   - cfn-stg/prod-parameters.json は存在しない
   - にもかかわらず「環境別パラメータで指定」と記載

---

## 2. 増強内容（3段階）

### 段階 1: 事前検査（作成前）

**タイミング**: ドキュメント作成時に即座に実施

#### 1.1 「根拠確認チェックリスト」の追加

ドキュメント作成前に、以下を **必ず実行** してください：

```markdown
【ドキュメント作成チェックリスト】

□ 対象ファイルを `read` ツールで確認した（目視確認ではなくツール利用）
□ 行番号を記載する場合は、実際に read で確認した行番号である
□ 複数ファイルを参照する場合は、すべてのファイルを確認した
□ ドキュメント内に複数の記載がある場合は、相互参照を確認した
  例）AGENTS.md に「s3.yaml の Condition が～」と書く場合
      → s3.yaml 実際に Condition が存在することを確認

□ パラメータファイル（cfn-*-parameters.json）を参照する場合は、該当ファイルが存在することを確認
□ 実装ファイルに記載がない場合、ドキュメントに「根拠なし」と明記している
```

#### 1.2 Condition / パラメータ検証ツール

新規ツール案：`verify-yaml-implementation`

```bash
# 使用例：
./tools/verify-yaml-implementation.sh \
  --doc "AGENTS.md" \
  --template "cfn-templates/s3.yaml" \
  --claim "Condition CreateBucket が存在"

# 出力:
# ✅ 検証成功: Condition CreateBucket は s3.yaml 行 8 に存在
# または
# ❌ 検証失敗: Condition CreateBucket は s3.yaml に存在しません
```

---

### 段階 2: 記載検証（作成中）

**タイミング**: ドキュメント記載時

#### 2.1 「3つのレベルの情報ソース」分類の明確化

現在の SKILL.md セクション 2.1～2.3 を拡張：

| レベル | 信頼度 | 例 | 検証方法 |
|--------|--------|-----|--------|
| **L1: コード実装** | ★★★★★ 最高 | `cfn-templates/s3.yaml 行 8` | `read` ツール |
| **L2: テスト結果** | ★★★★☆ 高 | `CloudWatch Logs に実行ログ` | Bash コマンド実行 |
| **L3: ドキュメント参照** | ★★☆☆☆ 中 | `docs/requirements.md セクション 3` | `read` ツール |
| **L0: 推測・想定** | ☆☆☆☆☆ 不可 | 「～のはずだ」「～と思われる」 | **絶対に使用禁止** |

#### 2.2 「相互参照チェック」の義務化

ドキュメント内に複数の情報ソース参照がある場合、相互に矛盾がないことを確認：

```
例：
- AGENTS.md 行 884 で「環境ごとに S3 バケット名が異なる」と記載
  ↓ 検証
- main.yaml パラメータで `DataBucketName` が定義されている確認
  ↓ 検証
- cfn-dev-parameters.json に `DataBucketName` が設定されている確認
  ↓ 検証
- cfn-stg-parameters.json、cfn-prod-parameters.json が存在する確認
  ↓
  結果：cfn-stg/prod-parameters.json が存在しないため、記載は不完全
```

#### 2.3 「未実装・将来予定」の明確な分離

記載時に、以下を区別：

```markdown
✅ 実装済み（L1 コード実装で確認）
「bedrock-agent.yaml 行 16-62 で Agent Instruction を定義」

⏳ 実装予定（将来のマイルストーン）
「Phase 2 で CloudFormation テンプレット再構成を予定。詳細は INTEGRATION_STRATEGY.md セクション 2.2 を参照」

❌ 実装なし、検証不可（削除または仕様作成が必要）
「この機能は現在実装されていません。仕様定義が必要です」
```

---

### 段階 3: 事後検証（完成後）

**タイミング**: ドキュメント完成後、git push 前

#### 3.1 「自動相互検証スクリプト」の実装

新規スクリプト案：`tools/verify-documentation-consistency.sh`

```bash
#!/bin/bash

# 使用例:
./tools/verify-documentation-consistency.sh

# 検査内容:
# 1. AGENTS.md で言及されたすべてのファイルが存在確認
# 2. 記載された行番号が実際の行と一致確認
# 3. ドキュメント内の相互参照が矛盾していないか確認
# 4. 根拠なしの主張（L0）が存在しないか確認

# 出力例:
# ✅ AGENTS.md 行 100: "bedrock-agent.yaml 行 115" → 実際に存在確認
# ❌ AGENTS.md 行 200: "bedrock-agent.yaml 行 999" → 存在しません
# ⚠️  AGENTS.md 行 300: 根拠が記載されていません
```

#### 3.2 「ドキュメント根拠マトリックス」の生成

各ドキュメント完成時に、根拠の完全性を可視化：

```
docs/INTEGRATION_STRATEGY.md 完全性レポート:

| 主張 | ファイル | 行 | 確認状態 |
|------|---------|-----|---------|
| Phase 1 は単一テナント | cfn-dev-parameters.json | ✓ | 確認済み |
| S3 バケットは事前作成 | main.yaml 行 12 | ✓ | 確認済み |
| cfn-stg-parameters.json が必要 | (存在しない) | ✗ | 未実装 |

合計: 2/3 完全性 67%
（❌ 合格基準は 100%）
```

---

## 3. ツール開発仕様

### ツール A: `verify-yaml-implementation.sh`

```bash
# 使用例
./tools/verify-yaml-implementation.sh \
  --doc "AGENTS.md" \
  --claim-line 884 \
  --expected-file "s3.yaml" \
  --expected-content "Condition"

# 処理:
# 1. AGENTS.md 行 884 を読み込み
# 2. 記載内容から「確認対象」を抽出
# 3. s3.yaml を読み込み
# 4. Condition が存在するか検索
# 5. 結果を出力
```

### ツール B: `verify-documentation-consistency.sh`

```bash
# 使用例
./tools/verify-documentation-consistency.sh \
  --target "AGENTS.md" \
  --mode "strict"

# strict モード:
# - すべての主張に根拠が必須（L0 禁止）
# - 相互参照の矛盾チェック
# - ファイル存在確認
# - 行番号の正確性確認
```

---

## 4. スキル適用フロー（改訂版）

```
ドキュメント作成開始
    ↓
【段階 1】事前検査
  ☐ 対象ファイル読み込み
  ☐ 行番号確認
  ☐ パラメータファイル確認
    ↓
【段階 2】記載検証
  ☐ 情報ソースレベル分類（L1～L3）
  ☐ 相互参照チェック
  ☐ 未実装・将来予定の明確化
    ↓
ドキュメント作成完了
    ↓
【段階 3】事後検証
  ☐ 自動相互検証スクリプト実行
  ☐ 根拠マトリックス生成
  ☐ 合格基準（100%）達成確認
    ↓
✅ git push 許可
```

---

## 5. チェックリスト（プロジェクト適用版）

### 当プロジェクトで適用する「必須確認項目」

```markdown
【ドキュメント作成時：必須チェック】

□ 【L1 検証】実装ファイルを read ツールで確認した
□ 【L2 検証】テスト結果がある場合、実行ログで確認した
□ 【L3 検証】参照ドキュメント全て読んだ
□ 【相互参照】複数ファイル参照時、矛盾がないか確認
□ 【パラメータ】cfn-*-parameters.json が実際に存在するか確認
□ 【未実装区別】実装なしの内容は「未実装」と明記
□ 【ツール実行】verify-documentation-consistency.sh で 100% 合格確認

【git push 前】
□ 自動検証スクリプト実行で エラー 0 件
```

---

## 6. 今後のプロセス改善

### 6.1 CI/CD パイプランへの統合

```yaml
# cfn-pipeline.yml に追加
DocVerificationStage:
  Type: AWS::CodePipeline::Stage
  Properties:
    Actions:
      - Name: VerifyDocumentation
        ActionTypeId:
          Category: Build
          Owner: AWS
          Provider: CodeBuild
          Version: '1'
        Configuration:
          ProjectName: doc-verification
        RunOrder: 1
```

### 6.2 Pre-commit Hook の設定

```bash
# .git/hooks/pre-commit
#!/bin/bash
./tools/verify-documentation-consistency.sh --target "AGENTS.md" || {
  echo "❌ ドキュメント検証失敗。git push をキャンセルしました"
  exit 1
}
```

### 6.3 Code Review チェックリスト

PR レビュー時に必ず確認：

```markdown
## ドキュメント修正 PR チェック

- [ ] 新規記載または修正内容の根拠ファイルが存在するか
- [ ] 記載された行番号は実装と一致しているか
- [ ] cfn-*-parameters.json など、存在が前提のファイルは本当に存在するか
- [ ] 未実装・将来予定の内容が明記されているか
- [ ] 相互参照に矛盾がないか
```

---

## 7. 再発防止：本不具合の具体的対策

### 本不具合が発生した理由（詳細分析）

```
実装: s3.yaml に Condition CreateBucket を作成
    ↓ （実装の根拠を確認していない）
ドキュメント: AGENTS.md に「環境ごとにバケット作成」と記載
    ↓ （ドキュメントと実装の相互検証がない）
矛盾: s3.yaml に Condition はあるが、
      実際には何も使用していない
      cfn-dev/stg/prod-parameters.json が不完全
    ↓ （不完全性に気づかなかった）
気づき: 「Condition は不要」と判断
```

### 対策（段階 3 で防止可能）

```
事後検証スクリプト実行:

$ ./tools/verify-documentation-consistency.sh --target "AGENTS.md"

❌ 検証失敗:
   行 884: "cfn-*-parameters.json の TemplateBucketName パラメータで指定"
   → cfn-stg-parameters.json が存在しません
   
   根拠マトリックス:
   | cfn-dev-parameters.json | ✓ | 存在 |
   | cfn-stg-parameters.json | ✗ | 存在しない |
   | cfn-prod-parameters.json| ✗ | 存在しない |

→ git push ブロック

→ 修正: 
   1. ファイル作成 OR
   2. ドキュメント修正
```

---

## 8. 実装スケジュール

| フェーズ | 内容 | 予定日 | ステータス |
|---------|------|--------|----------|
| フェーズ 1 | SKILL.md 拡張（段階 1～3） | 2026/06/04 | **今すぐ** |
| フェーズ 2 | verify-yaml-implementation.sh 実装 | 2026/06/05 | 予定 |
| フェーズ 3 | verify-documentation-consistency.sh 実装 | 2026/06/06 | 予定 |
| フェーズ 4 | Pre-commit Hook 設定 | 2026/06/07 | 予定 |
| フェーズ 5 | CI/CD パイプライン統合 | 2026/06/10 | 予定 |

---

## 9. 参考：本不具合との対比

| 項目 | 不具合時 | 改善後 |
|------|---------|--------|
| ドキュメント根拠 | 確認なし | 段階 1 で必須確認 |
| 相互参照検証 | なし | 段階 2 で必須チェック |
| 事後検証 | なし | 段階 3 で自動化 |
| 根拠不完全性の検知 | 手動 | 自動スクリプトで検知 |
| 修正前の再確認 | なし | 段階 3 で 100% 合格が条件 |

---

**結論**：source-verification スキルを 3 段階で増強することで、「架空の実装をドキュメント化する」という根本的誤りを防止できます。

