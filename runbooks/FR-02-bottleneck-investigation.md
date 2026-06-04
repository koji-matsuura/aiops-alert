# FR-02：ボトルネック調査ランブック

**カテゴリ**: Bottleneck Investigation  
**優先度**: 1  
**作成日**: 2026-06-04  
**更新日**: 2026-06-04  
**適用対象**: EC2, RDS, Lambda  

## 概要

システムパフォーマンスのボトルネックを CloudWatch メトリクスから検出し、改善案を提案するランブック。

## 前提条件

- CloudWatch メトリクスが有効であること
- IAM ロールが `cloudwatch:GetMetricData` 権限を持つこと
- メトリクス期間が 1 日以上蓄積されていること

## 手順

### 1. メトリクス収集

以下のメトリクスを 5 分間隔で取得：

**EC2:**
- CPU 使用率（> 80% で警告）
- ネットワーク IN/OUT（帯域幅飽和確認）
- ディスク I/O（IOPS 上限確認）

**RDS:**
- CPU 使用率（> 75% で警告）
- Database Connections（接続上限接近）
- Read Latency（> 10ms で調査）
- Write Latency（> 10ms で調査）

**Lambda:**
- Duration（実行時間）
- Errors（エラー率）
- Throttles（スロットル数）
- Concurrent Executions

### 2. ボトルネック特定

各メトリクスから以下を判定：

```
高 CPU → アプリケーション/クエリ最適化
高メモリ → インスタンスタイプ変更
高ディスク I/O → ストレージ最適化
高ネットワーク遅延 → リージョン/AZ 最適化
接続数超過 → コネクションプーリング
```

### 3. 改善案提案

**スケーリング:**
- 水平スケーリング（台数増加）
- 垂直スケーリング（インスタンスタイプ変更）

**最適化:**
- キャッシング導入（ElastiCache）
- インデックス追加（RDS）
- Lambda 関数最適化（メモリ/タイムアウト調整）

### 4. 実装と検証

改善前後でメトリクスを比較：
- CPU 使用率：改善前後で 20% 以上低下
- レイテンシ：改善前後で 30% 以上低下
- スループット：改善前後で 20% 以上向上

## トラブルシューティング

**Q: メトリクスが見つからない**  
A: CloudWatch Agent がインストール/有効であることを確認

**Q: メトリクスが不正確**  
A: 統計値（Average、Max など）を確認

## 参考リンク

- [CloudWatch メトリクス](https://docs.aws.amazon.com/AmazonCloudWatch/latest/monitoring/working_with_metrics.html)
- [EC2 パフォーマンスチューニング](https://docs.aws.amazon.com/AWSEC2/latest/UserGuide/monitoring-system-performance.html)
