---
metadata:
  category: "Database Performance"
  priority: 1
  created_date: "2026-06-04"
  updated_date: "2026-06-04"
  applicable_to:
    - RDS
  tags:
    - query-optimization
    - performance-insights
    - index
    - sql
  estimated_resolution_time_minutes: 120
  difficulty: "High"
---

# FR-05：遅いクエリ検出ランブック

**カテゴリ**: Database Performance  
**優先度**: 1  
**作成日**: 2026-06-04  
**更新日**: 2026-06-04  
**適用対象**: RDS (MySQL, PostgreSQL, Aurora)  

## 概要

RDS Performance Insights から遅いクエリを検出し、クエリ最適化とインデックス改善を提案するランブック。

## 前提条件

- RDS DB インスタンスが Performance Insights 対応（db.t3.small 以上）
- Performance Insights が有効であること
- IAM ロールが `pi:DescribeDBInstances` 権限を持つこと
- Slow Query Log が有効（MySQL）または log_min_duration_statement が設定（PostgreSQL）

## 手順

### 1. 遅いクエリ検出

```bash
# Performance Insights から遅いクエリを取得
aws pi get-resource-metrics \
  --service-type RDS \
  --identifier <RESOURCE_ID> \
  --start-time 2026-06-04T10:00:00Z \
  --end-time 2026-06-04T11:00:00Z \
  --period-in-seconds 60 \
  --metric-queries '[{"Metric":"db.load.by_host"},{"Metric":"db.sql_tokenized"}]'
```

### 2. クエリ分析

**検出対象:**
- 実行時間: > 1 秒
- 実行頻度: > 10 回/分
- 平均メモリ使用: > 100MB

**分析項目:**
```
SELECT COUNT(*) 
FROM performance_schema.events_statements_summary_by_digest
WHERE SUM_TIMER_WAIT > 1000000000000  -- 1秒以上
ORDER BY SUM_ROWS_EXAMINED DESC
LIMIT 10;
```

### 3. クエリプラン確認

```sql
-- MySQL
EXPLAIN FORMAT=JSON SELECT ...;

-- PostgreSQL
EXPLAIN (FORMAT JSON) SELECT ...;

-- 確認項目:
-- - Table Scans vs Index Scans
-- - Rows Examined vs Rows Returned
-- - Estimated Cost vs Actual Cost
```

### 4. 改善提案

**インデックス追加:**
```sql
-- WHERE句や JOIN条件に使用されるカラムにインデックス作成
CREATE INDEX idx_user_status ON users(status, created_at);

-- インデックス効果検証（実行前後でEXPLAINを比較）
```

**クエリ最適化:**
```sql
-- 改善前（Full Table Scan）
SELECT * FROM orders 
WHERE user_id = 123 AND status = 'pending';

-- 改善後（インデックス利用）
SELECT id, amount, created_at FROM orders 
WHERE user_id = 123 AND status = 'pending'
ORDER BY created_at DESC
LIMIT 100;
```

**その他の最適化:**
- JOIN 順序の変更
- サブクエリをJOINに変更
- 集計関数の最適化
- 不要なカラム削除

### 5. テスト環境での検証

開発環境で改善案をテスト：

```bash
# ステージング環境でクエリ実行時間測定
SET SESSION query_cache_type = OFF;
SELECT SQL_CALC_FOUND_ROWS ... -- 改善後のクエリ

# 実行時間比較:
# 改善前: 2.5 秒
# 改善後: 0.3 秒 (88% 削減)
```

### 6. 本番適用

本番適用前チェック：
```
□ インデックス作成時間を計測（ロック時間確認）
□ インデックスサイズを確認（ストレージ余裕確認）
□ 統計情報を再計算（ANALYZE TABLE）
□ 実行計画が正しく更新されたか確認
```

本番適用:
```bash
# オンラインでインデックス作成（MySQL 5.7+）
ALTER TABLE orders ADD INDEX idx_user_status(user_id, status), ALGORITHM=INPLACE, LOCK=NONE;
```

### 7. 効果測定

適用後 24-48 時間で以下を確認：
- クエリ実行時間が 30% 以上削減
- CPU 使用率が低下
- アプリケーションレスポンスタイム改善

## トラブルシューティング

**Q: インデックス作成後も遅い**  
A: インデックス統計情報が古い；ANALYZE TABLE で再計算

**Q: Performance Insights データが見つからない**  
A: 有効期限確認（デフォルト 7 日）；CloudWatch Logs で Slow Query Log も確認

## 参考リンク

- [RDS Performance Insights](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_PerfInsights.html)
- [MySQL クエリ最適化](https://dev.mysql.com/doc/refman/8.0/en/optimization.html)
- [PostgreSQL クエリプラン](https://www.postgresql.org/docs/current/sql-explain.html)
