---
metadata:
  category: "Log Investigation"
  priority: 1
  created_date: "2026-06-04"
  updated_date: "2026-06-04"
  applicable_to:
    - EC2
    - Lambda
    - RDS
  tags:
    - logs
    - troubleshooting
    - cloudwatch
    - error-analysis
  estimated_resolution_time_minutes: 30
  difficulty: "Medium"
---

# FR-01：CloudWatch ログ調査ランブック

**カテゴリ**: Log Investigation  
**優先度**: 1  
**作成日**: 2026-06-04  
**更新日**: 2026-06-04  
**適用対象**: EC2, Lambda, RDS  

## 概要

CloudWatch Logs から特定のエラーパターンを検索し、問題の根本原因を特定するランブック。

## 前提条件

- CloudWatch Logs グループが存在すること
- Lambda 関数が CloudWatch Logs へのアクセス権限を持つこと
- ログ保持期間が 7 日以上であること

## 手順

### 1. ログクエリ実行

```bash
# CloudWatch Insights クエリ例
fields @timestamp, @message, @logStream
| filter @message like /ERROR/
| stats count() by @logStream
```

### 2. エラー パターン分析

エラーメッセージから以下の情報を抽出：
- エラー発生時刻
- エラー発生源（サービス、インスタンス）
- エラーコード
- スタックトレース（該当時）

### 3. 根本原因特定

以下の観点から分析：
- **アプリケーション層**: コード/設定エラー
- **インフラ層**: リソース不足（CPU、メモリ、ディスク）
- **ネットワーク層**: 接続タイムアウト、DNS 障害
- **データベース層**: クエリタイムアウト、制約違反

### 4. 対応

根本原因に応じた対応：
- コード修正 → デプロイ
- リソース増強 → スケーリング
- 設定変更 → 再起動
- DB 最適化 → インデックス追加

## トラブルシューティング

**Q: ログが見つからない**  
A: ログ保持期間を確認し、CloudWatch ロググループ名が正しいことを確認

**Q: クエリがタイムアウト**  
A: 時間範囲を狭める（直近 1 時間に限定など）

## 参考リンク

- [CloudWatch Logs Insights クエリ構文](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/CWL_QuerySyntax.html)
- [CloudWatch Logs ベストプラクティス](https://docs.aws.amazon.com/AmazonCloudWatch/latest/logs/Best-Practice-Recommended-Alarms-AWS-Services.html)
