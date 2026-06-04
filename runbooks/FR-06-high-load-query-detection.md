# FR-06：高負荷クエリ分析ランブック

**カテゴリ**: Database Performance  
**優先度**: 1  
**作成日**: 2026-06-04  
**更新日**: 2026-06-04  
**適用対象**: RDS (MySQL, PostgreSQL, Aurora)  

## 概要

RDS Performance Insights から高負荷クエリを特定し、リソース消費の最適化と容量計画を実施するランブック。

## 前提条件

- RDS DB インスタンスが Performance Insights 対応（db.t3.small 以上）
- Performance Insights が有効であること
- IAM ロールが以下の権限を持つこと：
  - `pi:DescribeDBInstances`
  - `pi:GetResourceMetrics`
  - `sns:Publish`（SNS 通知用）

## 手順

### 1. 高負荷クエリ検出

```bash
# Performance Insights から高負荷クエリを抽出
aws pi get-resource-metrics \
  --service-type RDS \
  --identifier <RESOURCE_ID> \
  --start-time $(date -u -d '1 hour ago' +%Y-%m-%dT%H:%M:%SZ) \
  --end-time $(date -u +%Y-%m-%dT%H:%M:%SZ) \
  --period-in-seconds 60 \
  --metric-queries '[
    {"Metric":"db.load.by_wait_type"},
    {"Metric":"db.load.by_host"},
    {"Metric":"db.load.by_application"},
    {"Metric":"db.load.top_sql"}
  ]'
```

### 2. クエリの負荷分類

**高負荷クエリ判定基準:**

| 指標 | 閾値 | 判定 |
|------|------|------|
| CPU 使用率 | > 80% | 緊急 🔴 |
| ロック待機時間 | > 500ms | 警告 🟡 |
| I/O 操作 | > 10,000 ops/sec | 警告 🟡 |
| メモリ使用 | > 85% | 注意 🟢 |
| 並行実行数 | > 100 | 注意 🟢 |

**分類例:**
```
1. CPU集約クエリ: 複雑な集計、シーケンシャルスキャン
2. I/O集約クエリ: 大量データ取得、フルテーブルスキャン
3. ロック競合: トランザクション衝突、デッドロック
4. メモリ集約: 大規模ソート、GROUP BY
```

### 3. 負荷クエリの詳細分析

```sql
-- MySQL: Slow Query Log から負荷クエリを取得
SELECT
  query_time,
  lock_time,
  rows_sent,
  rows_examined,
  sql_text
FROM mysql.slow_log
WHERE query_time > 1
ORDER BY query_time DESC
LIMIT 10;

-- PostgreSQL: pg_stat_statements から負荷クエリを取得
SELECT
  mean_exec_time,
  calls,
  total_exec_time,
  rows,
  query
FROM pg_stat_statements
WHERE mean_exec_time > 1000  -- 1秒以上
ORDER BY total_exec_time DESC
LIMIT 10;
```

### 4. リソース消費の分析

```
CPU 消費分析:
- クエリごとの CPU 使用率を算出
- トップ 10 CPU 消費クエリを特定
- 実行頻度との組み合わせで総 CPU 消費を計算

I/O 消費分析:
- ディスク読み書き IOPS を測定
- インデックス vs テーブルスキャンの比率
- キャッシュヒット率を確認（90% 以上が理想）

メモリ消費分析:
- バッファプール効率
- テンポラリテーブル使用状況
- ソート領域消費
```

### 5. 改善の優先順付け

高負荷クエリを以下の観点で優先付け：

```
スコア = (CPU消費 + I/O消費 + 実行頻度) × 改善可能度
```

**改善優先順:**
1. 実行頻度高×改善可能度高 → インデックス追加、クエリ最適化
2. 実行頻度高×改善可能度低 → リソース増強、キャッシング
3. 実行頻度低×改善可能度高 → 必要性検討、廃止検討

### 6. 改善施策の実装

**即時対応（バッチ処理の見直し）:**
```sql
-- 改善前: リアルタイムで大量データ集計
SELECT user_id, SUM(amount) 
FROM transactions
WHERE DATE(created_at) = CURDATE()
GROUP BY user_id;

-- 改善後: バッチ処理に変更
-- 夜間 02:00 に集計結果をMaterialize
SELECT * FROM daily_user_summary
WHERE summary_date = CURDATE();
```

**中期対応（インデックス最適化）:**
```sql
CREATE INDEX idx_transactions_date_user 
ON transactions(created_at, user_id);
```

**長期対応（キャッシング導入）:**
```python
# ElastiCache (Redis) を導入
cached_result = redis_client.get(f"daily_summary:{date}")
if not cached_result:
    result = db.query("SELECT ... FROM daily_user_summary")
    redis_client.setex(f"daily_summary:{date}", 86400, result)
```

### 7. 容量計画

高負荷クエリの傾向から容量計画：

```
現在の負荷: 60% CPU 使用
高負荷クエリ改善後: 35% CPU 使用
3ヶ月後の予想増加: +20%
→ 3ヶ月後: 35% + 20% = 55% CPU 使用
→ 余裕度: 45% あり（インスタンスタイプ変更不要）

6ヶ月後の予想: 35% + 40% = 75% CPU 使用
→ インスタンスタイプをアップグレード検討時期
```

### 8. SNS 通知

高負荷クエリ検出時、SNS で通知：

```json
{
  "AlertType": "HighLoadQueryDetected",
  "Severity": "WARNING",
  "DBInstance": "prod-order-db",
  "TopQueryCPU": "SELECT * FROM orders WHERE status IN (...)",
  "CPUUsage": "82%",
  "RecommendedAction": "Consider index optimization or query refactoring",
  "Timestamp": "2026-06-04T10:30:00Z"
}
```

## トラブルシューティング

**Q: Performance Insights データが不足**  
A: Performance Insights が 7 日間保持；CloudWatch Logs の Slow Query Log も併用

**Q: インデックス追加後も改善しない**  
A: インデックス選択度が低い可能性；クエリプランを再確認

**Q: クエリ最適化により他クエリが遅化**  
A: 回帰テストを実施；本番環境で段階的に反映

## 参考リンク

- [RDS Performance Insights](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PerfInsights.html)
- [AWS DMS での実行計画最適化](https://docs.aws.amazon.com/dms/latest/userguide/CHAP_BestPractices.html)
- [データベース性能チューニング](https://aws.amazon.com/blogs/database/)
