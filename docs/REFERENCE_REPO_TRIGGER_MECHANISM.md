# 参照リポジトリのランブック トリガーメカニズム分析

**分析対象**: https://github.com/aws-samples/improving-it-operations-efficiency-with-aiops (CDK版)  
**焦点**: ランブックをどのようなトリガーで読み込み、どのように対応するか  
**作成日**: 2026年6月4日

---

## 1. 参照リポジトリのトリガーメカニズム概要

### 1.1 トリガー方式

参照リポジトリは **完全にユーザー駆動型** です。

```
ユーザー (Bedrock Console)
    ↓ (質問入力)
「find any operational issue in account and fix issue as per knowledgebase」
    ↓
Bedrock Agent (Claude 3 Haiku)
    ├─ Knowledge Base 検索（ランブック S3 から）
    ├─ Action Group 呼び出し判定
    └─ Lambda 呼び出し
        ├─ GetAlertsActionGroup (get-all-alerts.py)
        └─ RemediationActionGroup (issue-remediation.py)
    ↓
結果をユーザーに返却
```

**重要**: 
- **自動トリガーなし**（CloudWatch Alarms 監視なし）
- **EventBridge 統合なし**（スケジュール実行なし）
- **ユーザーが質問を入力することが前提**

---

## 2. 参照リポジトリのアーキテクチャ

### 2.1 全体フロー

```
ステップ1: CDK デプロイ
  ├─ Bedrock Agent 作成
  ├─ Action Group 2個作成
  │  ├─ GetAlertsActionGroup
  │  │   └─ Lambda: get-all-alerts.py
  │  └─ RemediationActionGroup
  │      └─ Lambda: issue-remediation.py
  ├─ Knowledge Base 作成 (手動 UI)
  ├─ ランブック（DOCX）を S3 にアップロード
  └─ CloudWatch Alarm 1個作成
     └─ Web_Server_CPU_Utilization (90% threshold)

ステップ2: Bedrock Console で Agent テスト
  ├─ ユーザーが質問入力
  ├─ Agent が Knowledge Base 検索
  ├─ Action Group 実行判定
  └─ Lambda 呼び出し

ステップ3: Lambda 実行
  ├─ get-all-alerts.py: CloudWatch Alarms 確認
  └─ issue-remediation.py: EC2 インスタンス再起動 or スナップショット作成
```

---

### 2.2 トリガー入口

#### Bedrock Console (唯一のトリガー)

```
AWS Bedrock Console → Agent Chat Interface
    ↓
ユーザー質問入力例:
  - "find any operational issue in account"
  - "find any operational issue in account and fix issue as per knowledgebase"
    ↓
Agent が Knowledge Base 検索 → ランブック活用
```

**UI 画面** (README の Step 6 より):

```
準備ステップ: Agent を "Prepare" ボタンで準備
    ↓
テストインターフェース: ユーザー質問を入力
    ↓
[Screenshot: test1.png]
```

---

## 3. Action Group と Lambda の連携

### 3.1 Action Group 定義

参照リポジトリは 2 つの Action Group を作成:

| Action Group | Lambda | 用途 |
|---|---|---|
| **GetAlertsActionGroup** | get-all-alerts.py | CloudWatch Alarms 確認 / メール通知 |
| **RemediationActionGroup** | issue-remediation.py | EC2 操作（再起動/スナップショット） |

### 3.2 Lambda ハンドラーの設計

#### get-all-alerts.py (79行)

```python
def lambda_handler(event, context):
    # event['apiPath'] から処理を分岐
    
    if event['apiPath'] == '/get_all_alerts':
        # CloudWatch から ALARM 状態のアラーム取得
        cw_client = boto3.client('cloudwatch')
        response = cw_client.describe_alarms(
            AlarmNames=['Web_Server_CPU_Utilization'],
            StateValue='ALARM'
        )
        
        # ALARM 状態なら情報返却
        # OK 状態なら「問題なし」を返却
        
    else:
        # メール通知 (SES 使用)
        client.send_email(...)
```

**重要な特徴**:
- CloudWatch から「手動作成されたアラーム」を確認するのみ
- アラーム名が **ハードコード** (`Web_Server_CPU_Utilization`)
- アラーム自動トリガーではなく「ユーザー質問時の確認」

#### issue-remediation.py (54行)

```python
def lambda_handler(event, context):
    # event['apiPath'] から処理を分岐
    
    if event['apiPath'] == '/create_snapshot_of_EC2_volume':
        # EC2 ボリュームのスナップショット作成
        volume_id = ec2.describe_instances(...)
        response = ec2.create_snapshot(VolumeId=volume_id)
        
    else:
        # EC2 インスタンス再起動
        response = ec2.reboot_instances(InstanceIds=[instanceid])
```

**重要な特徴**:
- 2 つの操作を `apiPath` で分岐
- ユーザーが Action Group を呼び出すまで実行されない

---

### 3.3 API Schema

参照リポジトリは 2 つの API Schema を定義:

```
lib/assets/api-schema/
├── api-schema-alert.json    (GetAlertsActionGroup 用)
└── api-schema-remediation.json (RemediationActionGroup 用)
```

**Schema 構造例** (推測):
```json
{
  "openapi": "3.0.1",
  "info": {
    "title": "Alert API",
    "version": "1.0.0"
  },
  "paths": {
    "/get_all_alerts": {
      "get": {
        "description": "Get all alerts in ALARM state"
      }
    }
  }
}
```

---

## 4. Agent Instruction (プロンプト)

### 4.1 Instruction 設定方法

参照リポジトリでは以下のフローで Instruction を設定:

```
CDK Construct (custom-bedrock-agent-construct.ts:116)
    ↓
environment: {
  BEDROCK_AGENT_INSTRUCTION: props.instruction
}
    ↓
Custom Resource Lambda (cdk-resource-bedrock-agent.py:20)
    ↓
agent_client.create_agent(
  instruction=instruction,  # ← ここで設定
  ...
)
```

### 4.2 Instruction 例 (README Step 4 より)

```
Knowledge base contains runbooks to fix operational issues in resources in aws account
```

**特徴**:
- 極めてシンプル（1 文）
- ランブック活用を明示
- アクション実行の指示なし
- Action Group の優先度なし

---

## 5. CloudWatch Alarm の役割

### 5.1 参照リポジトリのアラーム

```python
# cdk-resource-bedrock-agent.py:115-138

cloudwatch.put_metric_alarm(
    AlarmName='Web_Server_CPU_Utilization',
    ComparisonOperator='GreaterThanThreshold',
    Threshold=90.0,
    ActionsEnabled=False,  # ← 重要: アクションなし
    ...
)
```

**重要な特徴**:
- `ActionsEnabled=False` → **EventBridge やSNS トリガーなし**
- アラーム作成は「デモ用」にすぎない
- 実際のトリガーではない

### 5.2 アラーム確認の流れ

```
ユーザー質問
    ↓
Bedrock Agent
    ↓
Action Group (GetAlertsActionGroup) 呼び出し判定
    ↓
get-all-alerts.py 実行
    ↓
CloudWatch describe_alarms() で ALARM 状態確認
    ↓
結果をユーザーに返却
```

**つまり**: 
- アラームは「CloudWatch メトリクス」を記録するのみ
- ユーザーが Bedrock Console で質問した時点で「手動で確認」される
- 自動トリガーではない

---

## 6. 参照リポジトリ vs 当プロジェクト のトリガー比較

### 6.1 トリガー方式の根本的な違い

| 項目 | 参照リポジトリ | 当プロジェクト |
|-----|---|---|
| **トリガー入口** | Bedrock Console (ユーザー質問) | 3種類（Agent / EventBridge / Cron） |
| **ユーザー入力** | ✅ 必須 | ❌ 不要（モード2/3） |
| **自動実行** | ❌ なし | ✅ あり（モード2/3） |
| **CloudWatch Alarms** | 確認のみ (手動) | トリガー（自動） |
| **EventBridge** | なし | あり |
| **Lambda Cron** | なし | あり (日曜 00:00) |

---

### 6.2 トリガーフロー比較

#### 参照リポジトリ (純粋にユーザー駆動)

```
ユーザー (Bedrock Console)
  ↓ (質問入力)
Bedrock Agent Chat
  ├─ Instruction: "Knowledge base contains runbooks..."
  ├─ Knowledge Base 検索
  └─ Action Group 実行判定
    └─ Lambda 呼び出し (get-all-alerts.py / issue-remediation.py)
```

**すべてのステップがユーザー質問に依存**

---

#### 当プロジェクト (3モード並行)

**モード 1: ユーザー駆動 (参照リポジトリと類似)**
```
ユーザー (Bedrock Console)
  ↓ (質問入力)
Bedrock Agent
  ├─ Instruction: 日本語・詳細プロンプト
  ├─ Knowledge Base 検索
  └─ Lambda 呼び出し (FR-01～FR-06)
```

**モード 2: 自動実行 (参照リポジトリに存在しない)**
```
CloudWatch Alarm ALARM
  ↓ (自動トリガー)
EventBridge Rule
  ├─ InputTransformer で JSON 変換
  └─ Lambda 直接呼び出し (FR-01～FR-06)
    ↓ (Agent バイパス)
```

**モード 3: スケジュール実行 (参照リポジトリに存在しない)**
```
EventBridge ScheduleRule (日曜 00:00)
  ↓ (定期実行)
Lambda 直接呼び出し
  ├─ Performance Insights API
  └─ スローク/高負荷クエリ検出
```

---

## 7. ランブック活用方法の比較

### 7.1 参照リポジトリ

```
ランブック取得のトリガー:
  └─ ユーザーが Bedrock Console で質問
    └─ Agent が Knowledge Base 検索
      └─ S3 (DOCX) から ランブック読み込み
        └─ セマンティック検索 (Embeddings)
          └─ マッチしたランブックをコンテキストに含める
            └─ Agent プロンプトで活用
```

**特徴**:
- ランブックの取得は「ユーザー質問」のみ
- 自動取得なし
- アラームと連携なし

---

### 7.2 当プロジェクト

```
ランブック取得のトリガー:

【モード 1: ユーザー質問】
  └─ 参照リポジトリと同じ

【モード 2: CloudWatch Alarm】
  └─ EventBridge で Lambda 呼び出し
    └─ Lambda が Knowledge Base 検索 (retrieve_and_generate)
      └─ Markdown ランブック から 関連情報抽出
        └─ Lambda が SNS で通知

【モード 3: スケジュール実行】
  └─ Performance Insights API で クエリ分析
    └─ ランブック (FR-05, FR-06) に基づき対応
      └─ SNS で報告
```

**特徴**:
- 3つのトリガー入口
- ユーザー入力は不要（モード2/3）
- ランブック活用が自動化

---

## 8. 重要な発見

### 参照リポジトリが採用していない設計

1. **🚫 自動トリガー**
   - CloudWatch Alarms は作成されるが、EventBridge で自動実行しない
   - ActionEnabled=False で、SNS/SQS などの自動アクションなし

2. **🚫 スケジュール実行**
   - Lambda Cron なし
   - 定期的なバッチ処理なし

3. **🚫 ランブックの自動取得**
   - ユーザー質問が入力されるまで、ランブックは読み込まれない
   - 予測的メンテナンスなし

4. **🚫 EventBridge 統合**
   - EventBridge ルールなし
   - アラーム → Lambda 直接呼び出しなし

5. **🚫 アラーム駆動型の応答**
   - Alarm が ALARM 状態になっても、自動で Agent/Lambda は実行されない
   - 人間がアラームに気付いて、Bedrock Console で質問するのを待つ

---

### なぜ参照リポジトリはこの設計か？

**理由**:
1. **AWS Sample としての教育的価値**
   - Bedrock Agent の基本動作を示すことが目的
   - ユーザーが Console UI を学ぶことを重視

2. **汎用性**
   - どのアラームが発火するか、事前に決まっていない
   - 各企業が CloudWatch Alarms を独自に定義することを想定

3. **複雑性を避ける**
   - EventBridge/Cron 実装は複雑
   - MVP（Minimum Viable Product）としてシンプルな設計

---

## 9. 当プロジェクトが異なる理由

### 当プロジェクトの設計意図

1. **社内オペレーション自動化**
   - ユーザー入力がなくても自動応答
   - 運用負荷を最小化

2. **複数のトリガー入口**
   - モード 1（対話型）: ユーザーが質問
   - モード 2（リアルタイム）: アラームで自動実行
   - モード 3（定期）: スケジュールで定期実行

3. **ランブック活用の最大化**
   - 予測的メンテナンス（Performance Insights）
   - 事前対応（クエリ分析）

4. **完全な自動化**
   - ユーザーが何もしなくても、システムが自動判断・対応

---

## 10. 当プロジェクトのトリガー構成

### 現在の実装

```
トリガー 1️⃣: Bedrock Agent (ユーザー質問)
  └─ AGENTS.md Section 0, Mode 1 参照

トリガー 2️⃣: EventBridge CloudWatch Alarms
  ├─ cfn-templates/eventbridge-alarms.yaml
  ├─ 7つのルール
  │  ├─ EC2-HighCPU-* → FR-02
  │  ├─ RDS-HighCPU-* → FR-02
  │  ├─ RDS-HighConnections-* → FR-05
  │  ├─ RDS-ReplicationLag-* → 対応アクション
  │  ├─ Lambda-ErrorRate-* → FR-01
  │  ├─ Lambda-Throttle-* → 対応アクション
  │  └─ AllAlarmsRule → CloudWatch Logs
  └─ AGENTS.md Section 0, Mode 2 参照

トリガー 3️⃣: EventBridge ScheduleRule (日曜 00:00 UTC)
  ├─ cron(0 0 ? * SUN *)
  ├─ Performance Insights API
  ├─ FR-05, FR-06 実行
  ├─ SNS 通知
  └─ AGENTS.md Section 0, Mode 3 参照
```

---

## 11. まとめ表

| 観点 | 参照リポジトリ | 当プロジェクト |
|-----|---|---|
| **トリガー方式** | Bedrock Console (ユーザー質問のみ) | 3モード（Agent / EventBridge / Cron） |
| **ユーザー入力** | ✅ 必須 | ❌ 不要（モード2/3） |
| **自動実行** | ❌ なし | ✅ あり（モード2/3） |
| **CloudWatch Alarms** | 確認のみ | トリガー |
| **EventBridge** | なし | あり（2ルール型） |
| **Lambda Cron** | なし | あり |
| **ランブック取得** | ユーザー質問時のみ | 常時自動取得（モード2/3） |
| **自動化度** | ~30% | ~100% |
| **運用負荷** | 高（人間が監視） | 低（完全自動化） |

---

## 12. 統合戦略への影響

### 今後の拡張検討項目

参照リポジトリから学べること:
- ✅ Bedrock Agent + Action Group の基本設計
- ✅ Knowledge Base + ランブック の活用パターン
- ✅ Lambda API Schema によるアクション定義

当プロジェクトが先進していること:
- ✅ EventBridge による自動トリガー
- ✅ Cron による定期実行
- ✅ 複数モードの統合
- ✅ 完全な自動化

### 推奨される統合方針

- 参照リポジトリ: **ユーザー質問駆動型の AIOps デモ**（教育用）
- 当プロジェクト: **完全自動化された AIOps 本番運用**（実運用用）
- 将来: **両者の融合**
  - 参照リポジトリの UI/UX 学習機能 + 当プロジェクトの自動化

---

**作成日**: 2026年6月4日  
**関連ドキュメント**:
- `docs/REFERENCE_REPO_RUNBOOK_PROCESSING.md` (ランブック形式・保存)
- `AGENTS.md` (トリガーメカニズム - Section 0)
- `docs/INTEGRATION_STRATEGY.md` (統合戦略)
