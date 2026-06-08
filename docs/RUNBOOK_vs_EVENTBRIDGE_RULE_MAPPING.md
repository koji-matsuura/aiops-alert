# ランブック数 vs EventBridgeルール数 - 正確な対応関係

**作成日**: 2026年6月4日  
**目的**: 統合戦略で指摘された「6ランブック」と「6ルール」の乖離を説明・修正

---

## 1. 正確な現状

### ランブック: 6個（機能別）

| 番号 | 機能 | ファイル | 用途 |
|------|------|---------|------|
| **FR-01** | ログ調査 | `FR-01-log-investigation.md` | CloudWatch Logs の検索・分析 |
| **FR-02** | ボトルネック調査 | `FR-02-bottleneck-investigation.md` | メトリクス分析・ボトルネック特定 |
| **FR-03** | DB スナップショット作成 | `FR-03-create-db-snapshot.md` | RDS スナップショット作成・管理 |
| **FR-04** | メンテナンスウィンドウ表示 | `FR-04-maintenance-display.md` | メンテナンス情報の提示 |
| **FR-05** | 遅いクエリ検出 | `FR-05-slow-query-detection.md` | RDS Performance Insights API 利用 |
| **FR-06** | 高負荷クエリ調査 | `FR-06-high-load-query-detection.md` | Performance Insights API 利用 |

---

### EventBridge ルール: 7個（トリガー別）

| ルール名 | アラーム対象 | トリガー条件 | 対応する FR |
|----------|-----------|-----------|-----------|
| **EC2HighCPUAlarmRule** | EC2 インスタンス | アラーム名 `EC2-HighCPU-*` | FR-02 |
| **RDSHighCPUAlarmRule** | RDS インスタンス | アラーム名 `RDS-HighCPU-*` | FR-02 |
| **RDSHighConnectionsAlarmRule** | RDS 接続数 | アラーム名 `RDS-HighConnections-*` | FR-05 |
| **RDSReplicationLagAlarmRule** | RDS レプリケーション | アラーム名 `RDS-ReplicationLag-*` | 特定アクション |
| **LambdaErrorAlarmRule** | Lambda エラー率 | アラーム名 `Lambda-ErrorRate-*` | FR-01 |
| **LambdaThrottleAlarmRule** | Lambda スロットル | アラーム名 `Lambda-Throttle-*` | 特定アクション |
| **AlarmRecoveryRule** | 汎用（全アラーム） | CloudWatch Alarms ALARM状態 | すべてのアラーム記録 |

---

## 2. 不一致の理由（深掘り分析）

### 理由1: 多対1マッピング

```
EC2-HighCPU-* ─┐
               ├─→ FR-02（ボトルネック調査）
RDS-HighCPU-* ─┘
```

**結論**: 2つのアラームルールが1つの FR をトリガー

---

### 理由2: スケジュールベースのトリガー

```
EventBridge ScheduleRule: cron(0 0 ? * SUN *)  
       ↓
   Lambda invoke
       ↓
   複数のFR実行（FR-05 + FR-06）
```

**FR-05/FR-06 は**:
- ランブック: 存在（Knowledge Base に登録）
- EventBridge ルール: **スケジュールルール** として実装（専用ルール 1個）
- Lambda ハンドラー: `handle_slow_query_detection()`, `handle_high_load_query_detection()`

---

### 理由3: 汎用ルール（AlarmRecoveryRule）

```
AlarmRecoveryRule（CloudWatch Alarms ALARM状態 全般）
       ↓
CloudWatch Logs に記録
       ↓
ダッシュボード表示・監視
```

**用途**: アラーム全般の可視化・監査ログ

---

## 3. 修正内容

### 統合戦略ドキュメント（docs/INTEGRATION_STRATEGY.md）の修正

**修正前**:
```
- EventBridge 6ルール すべてが CloudWatch Alarms をトリガー
```

**修正後**:
```
- EventBridge 7ルール（アラーム6 + スケジュール1）が正常に動作
  - EC2-HighCPU アラームルール → Lambda トリガー → FR-02 実行
  - RDS-HighCPU アラームルール → Lambda トリガー → FR-02 実行
  - RDS-HighConnections アラームルール → Lambda トリガー → FR-05 実行
  - RDS-ReplicationLag アラームルール → Lambda トリガー → 対応アクション実行
  - Lambda-ErrorRate アラームルール → Lambda トリガー → FR-01 実行
  - Lambda-Throttle アラームルール → Lambda トリガー → 対応アクション実行
  - AlarmRecoveryRule（汎用） → すべてのアラーム監視 → CloudWatch Logs 記録
```

---

## 4. 対応関係の明確な表示

### Mode 2: EventBridge Alarms トリガー（自動実行）

```
CloudWatch Alarms ALARM状態
         ↓
EventBridge ルール（7個）
    ├─ EC2-HighCPU → Lambda ─(FR-02)→ ボトルネック調査
    ├─ RDS-HighCPU → Lambda ─(FR-02)→ ボトルネック調査
    ├─ RDS-HighConnections → Lambda ─(FR-05)→ 遅いクエリ検出
    ├─ RDS-ReplicationLag → Lambda ─(特定)→ 対応アクション
    ├─ Lambda-ErrorRate → Lambda ─(FR-01)→ ログ調査
    ├─ Lambda-Throttle → Lambda ─(特定)→ 対応アクション
    └─ AlarmRecoveryRule → CloudWatch Logs（監視・監査）
         ↓
    SNS 通知（各FR対応）
         ↓
    運用チーム・Slack/メール
```

### Mode 3: Lambda Cron トリガー（定期実行）

```
EventBridge ScheduleRule: cron(0 0 ? * SUN *)
         ↓
   毎週日曜 00:00 UTC
         ↓
   Lambda invoke
    ├─ FR-05: 遅いクエリ検出 → RDS Performance Insights API
    └─ FR-06: 高負荷クエリ調査 → RDS Performance Insights API
         ↓
   SNS トピック
    ├─ SlowQueryReport
    └─ HighLoadQueryReport
         ↓
   E-mail / Slack
```

---

## 5. 新規FR追加時のスケーリング方針

### シナリオ1: アラーム駆動型 FR を追加

例: FR-07 = RDS-DiskSpaceAlert 検知

```
1. ランブック作成
   → runbooks/FR-07-disk-space-investigation.md

2. EventBridge ルール追加
   → cfn-templates/eventbridge-alarms.yaml に
      RDSDiskSpaceAlarmRule 追加

3. Lambda ハンドラー追加
   → lib/lambda_handler.py に
      handle_disk_space_investigation() 関数追加

4. SNS トピック追加（必要に応じて）
   → DiskSpaceReport topic

5. Knowledge Base に取り込み
   → bedrock-ingest-template.json に FR-07 エントリ追加
   → aws bedrock-agent ingest-knowledge-base-documents
```

**結果**: 
- ランブック: +1 (6 → 7)
- EventBridge ルール: +1 (7 → 8)
- Lambda 関数: +1 (既存ファイル内)

---

### シナリオ2: スケジュール駆動型 FR を追加

例: FR-08 = 日次バックアップ確認

```
1. ランブック作成
   → runbooks/FR-08-daily-backup-verification.md

2. EventBridge ScheduleRule 追加（OR 既存ルール拡張）
   → 新規ルール: cron(0 2 * * ? *)（毎日 02:00 UTC）
      または既存の日曜ルール拡張

3. Lambda ハンドラー追加
   → lib/lambda_handler.py に
      handle_daily_backup_verification() 関数追加

4. SNS トピック追加
   → BackupVerificationReport topic

5. Knowledge Base に取り込み
```

**結果**:
- ランブック: +1 (6 → 7)
- EventBridge ルール: 0～+1 (ルール数は設計に依存)
- Lambda 関数: +1

---

## 6. 対応表の更新（AGENTS.md Section 6.3 対応）

### CloudWatch アラーム ← → Lambda トリガー対応表（確定版）

| CloudWatch アラーム名 | イベント条件 | 対応 FR / アクション | Lambda Handler |
|-------------------|-----------|---|---|
| `EC2-HighCPU-*` | CPU > 80%, 2期間 | FR-02 | `handle_bottleneck_investigation()` |
| `RDS-HighCPU-*` | CPU > 80%, 2期間 | FR-02 | `handle_bottleneck_investigation()` |
| `RDS-HighConnections-*` | 接続数 > 閾値 | FR-05 | `handle_slow_query_detection()` |
| `RDS-ReplicationLag-*` | レプリケーション遅延 > 閾値 | 対応アクション | `handle_replication_lag()` |
| `Lambda-ErrorRate-*` | エラー率 > 1% | FR-01 | `handle_log_investigation()` |
| `Lambda-Throttle-*` | スロットル発生 | 対応アクション | `handle_lambda_throttle()` |
| （スケジュール） | 毎週日曜 00:00 UTC | FR-05 + FR-06 | `handle_slow_query_detection()` + `handle_high_load_query_detection()` |

---

## 7. 正確な統計

### リソース数の正確な計算

| リソース種別 | 数量 |
|-----------|-----|
| ランブック（ナレッジベース） | 6個 |
| EventBridge アラームルール | 6個 |
| EventBridge スケジュールルール | 1個 |
| **EventBridge ルール合計** | **7個** |
| Lambda ハンドラー関数 | 6個（+ 2個の内部ヘルパー） |
| SNS トピック | 6個（各FR対応） |
| CloudWatch Alarms（ユーザー作成） | 0～複数（ユーザー側で作成） |

---

## 8. 今後のドキュメント更新予定

- [ ] INTEGRATION_STRATEGY.md を修正完了
  - [ ] チェックリスト詳細化
  
- [ ] AGENTS.md Section 6.3 を修正
  - [ ] アラーム対応表を7ルール対応に更新
  - [ ] スケジュールルール説明の追加
  
- [ ] COMPARISON_REPORT.md を修正
  - [ ] EventBridge ルール数の正確化
  
- [ ] README.md に スケーリング方針を追加
  - [ ] 新規FR追加ガイド
  - [ ] アラーム追加手順

---

## 9. 質問への回答

**Q: なぜランブック数が固定なのか？**

**A**: ランブック数が固定ではなく、**設計上の機能単位（FR-01～FR-06）に基づいている**ためです。

- **ランブック**: 機能の説明・手順を記載した Markdown ファイル
- **ランブック数**: ビジネス要件で定義された6つの機能（FR）に対応
- **拡張性**: 新しい FR を追加すればランブック数は増加

---

**Q: EventBridge ルール数は変わるのか？**

**A**: はい、**アラーム種類に応じて変わります**。

- **アラーム駆動型 FR**: 新規ルール追加（1ルール = 1アラーム対応）
- **スケジュール駆動型 FR**: 既存ルール拡張 OR 新規ルール作成（設計次第）
- **結果**: ルール数 ≠ ランブック数（多対1対応が存在）

---

**版の更新**:
- INTEGRATION_STRATEGY.md v1.0 → v1.1 (7ルール対応)

**完成日**: 2026年6月4日
