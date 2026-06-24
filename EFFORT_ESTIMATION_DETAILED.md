# CloudFormation + Lambda + Knowledge Base 移行工数分析レポート

**分析対象**: AIOps Bedrock Agent システムから AWS::Bedrock::Agent CloudFormation リソース削除への移行
**分析日**: 2026-06-24
**対象リージョン**: ap-northeast-1

---

## 1. CloudFormation テンプレート修正工数

### 1.1 削除対象：bedrock-agent.yaml（295行全削除）

**ファイルパス**: `/Users/matsuurakouji/aiops-alert/cfn-templates/bedrock-agent.yaml`  
**行数**: 295行  
**構成**:

| セクション | 行数 | 詳細 |
|----------|------|------|
| AWSTemplateFormatVersion/Description | 2行 | ヘッダー |
| Parameters | 28行 | EnvName, ServiceName, AgentName, Description, FoundationModel, KnowledgeBaseId, ActionGroupLambdaArn |
| Resources.BedrockAgentRole | 58行 | IAM Role 定義（AssumeRole + 4つのポリシー） |
| Resources.BedrockAgent | 177行 | Agent リソース本体（Instruction: 50行 + ActionGroup FunctionSchema: 127行） |
| Resources.BedrockAgentAlias | 6行 | Agent Alias |
| Outputs | 20行 | AgentArn, AgentId, AgentAliasId, RoleArn |

**削除工数見積もり**:
- ファイル削除: 1行
- git 履歴確認: 5分
- 従属リソース確認: 10分
- **小計**: 15分 ≈ **0.25時間**

---

### 1.2 修正対象：lambda-function.yaml（環境変数削除）

**ファイルパス**: `/Users/matsuurakouji/aiops-alert/cfn-templates/lambda-function.yaml`  
**現状**: 127行

**修正内容**:

| 修正行 | 項目 | 削除内容 |
|--------|------|---------|
| 19-26 | Parameters | BedrockAgentId, BedrockAgentAlias (8行) |
| 47-57 | Environment Variables | BEDROCK_AGENT_ID, BEDROCK_AGENT_ALIAS (11行) |
| 115-123 | Lambda Permission | BedrockAgentInvokeLambdaPermission (9行) |

**削除対象合計**: 28行

**修正工数見積もり**:
- Parameters セクション削除: 2分（検証含む）
- Environment Variables 削除: 2分
- Lambda Permission 削除: 2分
- 他の環境変数との依存関係確認: 5分
- テンプレート検証（cfn-lint）: 3分
- **小計**: **14分 ≈ 0.23時間**

**修正後のファイルサイズ**: 127 - 28 = **99行**

---

### 1.3 修正対象：main.yaml から BedrockAgentStack ネスト削除

**ファイルパス**: `/Users/matsuurakouji/aiops-alert/cfn-templates/main.yaml`  
**現状**: 134行

**修正内容**:

| 修正行 | 項目 | 削除内容 |
|--------|------|---------|
| 111-123 | BedrockAgentStack | ネストスタック定義 + コメント (13行) |
| 78-79 | LambdaStack.Parameters | BedrockAgentId, BedrockAgentAlias への参照 (2行) |

**削除対象合計**: 15行

**修正工数見積もり**:
- ネストスタック定義削除: 2分
- パラメータ参照削除: 2分
- DependsOn 関係確認: 3分（EventBridgeAlarmsStack に影響なし）
- 円形依存関係破壊確認: 5分（重要）
- テンプレート検証: 3分
- **小計**: **15分 ≈ 0.25時間**

**修正後のファイルサイズ**: 134 - 15 = **119行**

---

### 1.4 追加対象：AgentCore 設定の環境変数

**追加対象**: lambda-function.yaml の Environment Variables

| 新規環境変数 | 用途 | 行数 |
|-----------|------|------|
| AGENTCORE_ENDPOINT_URL | AgentCore エンドポイント | 1行 |
| AGENTCORE_API_KEY | AgentCore API キー | 1行 |
| AGENTCORE_MODEL | LLM モデル指定 | 1行 |
| AGENTCORE_MAX_ITERATIONS | エージェントループ上限 | 1行 |
| AGENTCORE_TIMEOUT_SECONDS | タイムアウト設定 | 1行 |

**追加対象合計**: 5行

**追加工数見積もり**:
- 環境変数定義: 3分
- Secrets Manager との連携確認: 5分（api-key は Secrets から取得）
- テンプレート検証: 3分
- **小計**: **11分 ≈ 0.18時間**

---

### 1.5 CloudFormation テンプレート修正の合計工数

| 項目 | 工数（時間） |
|------|----------|
| bedrock-agent.yaml 削除 | 0.25 |
| lambda-function.yaml 修正 | 0.23 |
| main.yaml 修正 | 0.25 |
| AgentCore 環境変数追加 | 0.18 |
| **合計** | **0.91時間 ≈ 0.9時間** |

**見積もり時間**: 約 **50分**

---

## 2. Python 実装工数

### 2.1 新規ファイル：agentcore_agent_config.py

**目的**: AgentCore 設定管理  
**予想行数**: 150-200行

**実装内容**:

```python
# 必須セクション（行数概算）
import statements: 10行
AgentCoreConfig class: 60行
  - __init__: 20行
  - validate(): 15行
  - from_env(): 15行
  - to_dict(): 10行
ConnectionPoolManager: 40行
  - __init__: 15行
  - get_connection(): 10行
  - close_all(): 5行
  - retry_logic: 10行
PromptBuilder class: 40行
  - build_system_prompt(): 20行
  - build_action_group_schema(): 20行
ErrorHandler utilities: 30行
  - handle_api_errors(): 20行
  - retry_on_failure(): 10行
```

**実装工数見積もり**:
- 基本クラス設計: 15分
- Config クラス実装: 20分
- ConnectionPool 実装: 15分
- PromptBuilder 実装: 20分
- エラーハンドリング: 10分
- ドキュメント + コメント: 10分
- **小計**: **90分 ≈ 1.5時間**

**予想行数**: **170行**

---

### 2.2 新規ファイル：agentcore_runtime.py

**目的**: AgentCore ランタイムエンジン  
**予想行数**: 250-350行

**実装内容**:

```python
# 必須セクション（行数概算）
import statements: 15行
AgentCoreRuntime class: 150行
  - __init__: 20行
  - process_message(): 50行  # 主要ロジック
  - route_to_action(): 30行
  - handle_tool_call(): 30行
  - format_response(): 20行
MessageRouter class: 80行
  - route_bedrock_message(): 40行
  - route_user_input(): 20行
  - route_scheduled_event(): 20行
ToolExecutor class: 60行
  - execute_action(): 30行
  - validate_parameters(): 20行
  - retry_failed_actions(): 10行
ActionGroupAdapter: 40行
  - adapt_to_openapi(): 25行
  - extract_function_schema(): 15行
```

**実装工数見積もり**:
- 基本ランタイム設計: 20分
- AgentCoreRuntime クラス実装: 40分
- MessageRouter 実装: 30分
- ToolExecutor 実装: 20分
- ActionGroupAdapter 実装: 15分
- エラーハンドリング + retry: 15分
- ドキュメント + コメント: 20分
- **小計**: **160分 ≈ 2.7時間**

**予想行数**: **300行**

---

### 2.3 修正対象：lib/lambda_handler.py

**現状**: 2198行

**修正内容**:

| セクション | 削除行 | 追加行 | 修正行 | 説明 |
|----------|--------|--------|--------|------|
| handler() | 0 | 0 | 10 | invoke_bedrock_agent() 削除、agentcore_runtime 呼び出し追加 |
| invoke_bedrock_agent() | 53 | 0 | 0 | 全体削除（1行 → 本体は build_prompt() に統合） |
| build_prompt() | 0 | 5 | 10 | AgentCore 対応プロンプト形式に変更 |
| handle_bedrock_agent_message() | 113 | 20 | 30 | messageVersion 1.0 → AgentCore メッセージ形式に変更 |
| dispatch_function() | 0 | 10 | 20 | 関数マッピング追加検証 |
| extract_event_info() | 0 | 5 | 5 | AgentCore イベント形式対応 |

**修正詳細**:

1. **handler() 関数（行 48-103）**
   - 削除: bedrock_agent_runtime.invoke_agent() 呼び出し（10行）
   - 追加: agentcore_runtime.invoke_agent() 呼び出し（5行）
   - 修正: エラーハンドリング、ロギング（3行）

2. **invoke_bedrock_agent() 関数（行 178-227）**
   - 全削除: 53行
   - 代替: agentcore_runtime で実装

3. **build_prompt() 関数（行 142-175）**
   - 修正: AgentCore ネイティブ形式に対応（+10行）
   - 追加: メタデータフィルタ情報（+5行）

4. **handle_bedrock_agent_message() 関数（行 1345-1457）**
   - 修正: messageVersion 1.0 → AgentCore メッセージ形式に変換（+30行）
   - 検証ロジック強化（+10行）

5. **dispatch_function() 関数（行 1460-1513）**
   - 追加: AgentCore アクション名マッピング（+10行）
   - 修正: パラメータ検証強化（+10行）

**修正工数見積もり**:
- handler() 関数の修正確認: 15分
- invoke_bedrock_agent() 削除確認: 10分
- build_prompt() 修正: 15分
- handle_bedrock_agent_message() 修正（複雑）: 30分
- dispatch_function() 修正: 15分
- 他の FR 関数への影響確認: 10分
- ユニットテスト修正: 20分
- **小計**: **115分 ≈ 1.92時間**

**修正後のファイルサイズ**: 2198 - 53 + 75 = **2220行**

---

### 2.4 新規テストファイル

**対象**: tests/ ディレクトリ

**新規テストファイル**:

| ファイル | 行数 | 対象 |
|---------|------|------|
| test_agentcore_config.py | 200行 | AgentCoreConfig クラス |
| test_agentcore_runtime.py | 300行 | AgentCoreRuntime + MessageRouter |
| test_action_group_adapter.py | 150行 | ActionGroupAdapter |
| test_lambda_handler_agentcore.py | 250行 | handler() 関数との統合 |

**新規テスト行数合計**: 900行

**テスト実装工数見積もり**:
- test_agentcore_config.py: 45分
- test_agentcore_runtime.py: 60分
- test_action_group_adapter.py: 30分
- test_lambda_handler_agentcore.py: 50分
- 既存テスト修正: 40分
- **小計**: **225分 ≈ 3.75時間**

---

### 2.5 Python 実装の合計工数

| 項目 | 工数（時間） |
|------|----------|
| agentcore_agent_config.py (新規) | 1.5 |
| agentcore_runtime.py (新規) | 2.7 |
| lib/lambda_handler.py (修正) | 1.92 |
| テストファイル (新規 + 修正) | 3.75 |
| **合計** | **9.87時間 ≈ 10時間** |

---

## 3. Knowledge Base 移行工数

### 3.1 メタデータ互換性確認

**対象**: 6つのランブック (FR-01～FR-06)  
**メタデータファイル**: `runbooks/*.md.metadata.json`

**確認項目**:

| 項目 | 詳細 | 工数 |
|------|------|------|
| 既存メタデータ構造確認 | 現状 6 ファイルの metadata 検証 | 10分 |
| AgentCore 対応スキーマ定義 | 新しい metadata スキーマ設計 | 15分 |
| 互換性マッピング | 既存 metadata → AgentCore 形式への変換ロジック | 20分 |
| メタデータ検証スクリプト作成 | 6 ファイルのバリデーション | 15分 |
| 動作確認テスト | Knowledge Base インジェスト前の検証 | 10分 |

**小計**: **70分 ≈ 1.17時間**

---

### 3.2 OpenSearch スキーマ変更の必要性判定

**対象**: OpenSearch Serverless インデックス (`aiops-kb-index`)

**判定項目**:

| チェック項目 | 現状 | 変更要否 |
|----------|------|--------|
| ベクトル化エンジン | Amazon Titan Embed v2 | ✅ 継続利用（互換性あり） |
| インデックス名 | `aiops-kb-index` | ✅ 継続利用 |
| FieldMapping (vector_field, text_field, metadata_field) | 既存 3 フィールド | ⚠️ metadata_field スキーマ拡張のみ |
| メタデータ属性 | 既存 5 属性 (category, priority, applicable_to, difficulty, estimated_resolution_time_minutes) | ✅ 互換性維持 |
| 全文検索 analyzer | 日本語対応（JapaneseAnalyzer） | ✅ 継続利用 |

**スキーマ修正内容**:
- 新規メタデータ属性: 2-3 個追加（AgentCore ネイティブ）
- 既存 metadata_field マッピング：拡張のみ（非互換変更なし）

**スキーマ変更工数見積もり**:

| 作業 | 工数 |
|------|------|
| スキーマ設計書作成 | 20分 |
| OpenSearch インデックス拡張 | 15分 |
| マイグレーションスクリプト作成 | 30分 |
| データ再インデックス実行 | 10分 |
| 検証テスト | 15分 |
| **小計** | **90分 ≈ 1.5時間** |

**重要**: 既存データの再インジェストは **不要**（後方互換性維持）

---

### 3.3 データ移行スクリプト作成

**スクリプト**: `scripts/migrate_to_agentcore.py`（新規）

**スクリプト内容**:

```python
# 必須セクション（行数概算）
import statements: 15行
MigrationConfig class: 40行
MetadataTransformer: 60行
  - transform_metadata(): 30行
  - validate_schema(): 20行
  - map_attributes(): 10行
OpensearchMigrator: 80行
  - backup_existing_index(): 20行
  - create_new_index(): 20行
  - migrate_documents(): 20行
  - verify_migration(): 20行
ProgressTracker: 30行
ErrorRecovery: 40行
main(): 35行
```

**予想行数**: 300行

**データ移行工数見積もり**:

| 作業 | 工数 |
|------|------|
| スクリプト実装 | 60分 |
| ローカルテスト | 20分 |
| Dev 環境でのドライラン | 30分 |
| トラブルシューティング + 修正 | 20分 |
| ロールバック計画書作成 | 15分 |
| **小計** | **145分 ≈ 2.42時間** |

---

### 3.4 Knowledge Base 移行の合計工数

| 項目 | 工数（時間） |
|------|----------|
| メタデータ互換性確認 | 1.17 |
| OpenSearch スキーマ変更 | 1.5 |
| データ移行スクリプト作成 | 2.42 |
| **合計** | **5.09時間 ≈ 5時間** |

---

## 4. ドキュメント更新工数

### 4.1 ドキュメント修正対象

**対象ファイル**:

| ファイル | 現状行数 | 修正内容 | 新行数 |
|---------|---------|--------|--------|
| AGENTS.md | 1173 | AgentCore 移行ガイド追加 | 1500 |
| docs/IMPLEMENTATION_DETAILS.md | 400 | AgentCore ランタイム詳細説明 | 600 |
| docs/PROJECT-ARCHITECTURE.md | 350 | アーキテクチャ図更新 + 説明 | 500 |
| docs/E2E-TEST-PLAN.md | 280 | AgentCore テストシナリオ追加 | 400 |
| lib/agentcore_agent_config.py | 170 | ドキュメント文字列 + サンプル | 250 |
| lib/agentcore_runtime.py | 300 | ドキュメント文字列 | 420 |

**ドキュメント修正工数見積もり**:

| ファイル | 修正時間 |
|---------|--------|
| AGENTS.md | 60分 |
| IMPLEMENTATION_DETAILS.md | 45分 |
| PROJECT-ARCHITECTURE.md | 40分 |
| E2E-TEST-PLAN.md | 35分 |
| Python docstrings | 30分 |
| README/Getting Started | 20分 |
| **小計** | **230分 ≈ 3.83時間** |

---

## 5. 総工数計算

### 5.1 工数サマリー

| カテゴリ | 工数（時間） |
|---------|----------|
| **1. CloudFormation 修正** | 0.91 |
| **2. Python 実装** | 9.87 |
| **3. Knowledge Base 移行** | 5.09 |
| **4. ドキュメント更新** | 3.83 |
| **中間小計** | **19.7時間** |

---

### 5.2 追加工数（テスト・検証・ロールバック）

| 項目 | 工数（時間） | 説明 |
|------|----------|------|
| ユニットテスト実行 + 修正 | 4.0 | 既存 3,141 行テスト + 新規 900 行 |
| 統合テスト (E2E) | 3.5 | 各 FR-01～06 の AgentCore 動作確認 |
| CloudFormation デプロイ検証 | 2.0 | main.yaml, lambda-function.yaml 検証 |
| Knowledge Base インジェスト検証 | 1.5 | メタデータ + OpenSearch 検証 |
| パフォーマンステスト | 1.5 | エージェント応答時間、メモリ使用量 |
| ロールバック計画 + 検証 | 2.0 | Bedrock Agent → AgentCore 切り替え計画 |
| セキュリティレビュー | 1.5 | IAM 権限、API キー管理 |
| **テスト・検証小計** | **16.0時間** |

---

### 5.3 最終工数見積もり

| フェーズ | 工数（時間） | 日数（フル稼働, 8h/day） |
|---------|----------|----------------------|
| 実装（Coding） | 19.7 | 2.46日 ≈ **2.5日** |
| テスト（Unit + Integration） | 7.5 | 0.94日 ≈ **1日** |
| 検証（Manual + Automated） | 8.5 | 1.06日 ≈ **1日** |
| ドキュメント更新 | 3.83 | 0.48日 ≈ **0.5日** |
| **合計** | **39.53時間** | **5.44日 ≈ 5.5日** |

---

### 5.4 クリティカルパス分析

**依存関係が強い順序**:

```
1. CloudFormation テンプレート修正 (0.9h)
   ↓
2. agentcore_agent_config.py + agentcore_runtime.py 実装 (4.2h)
   ↓
3. lambda_handler.py 修正 (1.92h)
   ↓（並行可能）
4. テストコード実装 (3.75h) + Knowledge Base 移行 (5.09h)
   ↓
5. 統合テスト + E2E テスト (7.5h)
   ↓
6. ドキュメント最終更新 (3.83h)
```

**最短スケジュール** (並行実行最大化):
- Day 1: CFN 修正 + agentcore モジュール実装
- Day 2: lambda_handler.py 修正 + テスト実装（並行）
- Day 3: 統合テスト + Knowledge Base 移行（並行）
- Day 4-5: E2E テスト + ドキュメント + ロールバック計画

**リソース効率**: 1 人で実施可能（5.5 日）、2 人で並行（3 日）

---

## 6. 工数削減オプション

### 6.1 スコープ削減案

| 削減項目 | 削減時間 | リスク | 推奨度 |
|---------|---------|--------|--------|
| AgentCore メタデータ最小化（3 属性のみ） | -1.0h | 低 | 🟢 推奨 |
| テストカバレッジを 70% に削減 | -2.0h | 中 | 🟡 要検討 |
| ドキュメント最小版（README のみ） | -2.0h | 高 | 🔴 非推奨 |
| ロールバック計画省略 | -1.0h | 高 | 🔴 非推奨 |
| Knowledge Base マイグレーションスクリプト自動化スキップ | -1.5h | 中 | 🟡 要検討 |

**推奨最小スコープ**: 3.0 時間削減 → **36.5 時間 ≈ 4.5 日**

---

## 7. リスク評価と対策

### 7.1 主要リスク

| リスク | 影響度 | 対応策 | 工数 |
|--------|--------|--------|------|
| Bedrock Agent ⇔ AgentCore 動作互換性 | 🔴 高 | E2E テスト強化 + 並行デプロイ | +2.0h |
| Knowledge Base インデックス再構築エラー | 🟡 中 | マイグレーション手順書作成 + ドライラン | +1.5h |
| IAM 権限不足（AgentCore API） | 🟡 中 | 権限分析ドキュメント作成 | +0.5h |
| OpenSearch Serverless クォータ超過 | 🟡 中 | スケーリングテスト | +1.0h |
| Lambda タイムアウト（AgentCore 処理） | 🟢 低 | 非同期処理への移行計画 | +1.0h |

**リスク対応工数小計**: +6.0h

---

## 8. 最終工数見積もり（リスク込み）

| フェーズ | 工数（時間） |
|---------|----------|
| 実装 + テスト + 検証 | 39.53 |
| リスク対応 | 6.0 |
| **合計（推奨）** | **45.53時間 ≈ 5.7日** |

**バッファ込み（20%）**: 54.6 時間 ≈ **6.8 日**

---

## 9. マイルストーン別工数配分

| マイルストーン | 工数（時間） | 期間 | 成果物 |
|-------------|----------|------|--------|
| M1: 基盤実装 | 6.5 | 1.0日 | agentcore モジュール + lambda_handler 修正 |
| M2: テスト実装 | 7.5 | 1.0日 | ユニット・統合テスト |
| M3: Knowledge Base 移行 | 5.0 | 0.7日 | データ移行 + 検証 |
| M4: ドキュメント・ロールバック | 5.5 | 0.7日 | ドキュメント + 切り替え計画 |
| M5: E2E テスト・デプロイ | 8.0 | 1.0日 | 本番環境検証 |
| M6: バッファ・フォローアップ | 7.0 | 0.9日 | トラブルシューティング |

**推奨スケジュール**: 5 ～ 7 営業日（並行実行最大化時）

---

## 付記：ファイル引用一覧

### CloudFormation テンプレート
- `/Users/matsuurakouji/aiops-alert/cfn-templates/bedrock-agent.yaml` (295行)
- `/Users/matsuurakouji/aiops-alert/cfn-templates/lambda-function.yaml` (127行)
- `/Users/matsuurakouji/aiops-alert/cfn-templates/main.yaml` (134行)

### Lambda ハンドラ
- `/Users/matsuurakouji/aiops-alert/lib/lambda_handler.py` (2198行)
  - handler(): 行 48-103
  - extract_event_info(): 行 106-138
  - build_prompt(): 行 142-175
  - invoke_bedrock_agent(): 行 178-227
  - handle_bedrock_agent_message(): 行 1345-1457
  - dispatch_function(): 行 1460-1513

### テストファイル
- `/Users/matsuurakouji/aiops-alert/tests/test_lambda_handler.py` (674行)
- `/Users/matsuurakouji/aiops-alert/tests/test_fr_implementations.py` (545行)
- 他 4 ファイル（合計 3141行）

### ドキュメント
- `/Users/matsuurakouji/aiops-alert/AGENTS.md` (1173行)
- `/Users/matsuurakouji/aiops-alert/docs/` (10,798行 合計)

