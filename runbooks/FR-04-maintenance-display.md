---
metadata:
  category: "Maintenance Management"
  priority: 2
  created_date: "2026-06-04"
  updated_date: "2026-06-04"
  applicable_to:
    - RDS
    - Systems Manager
  tags:
    - maintenance
    - patching
    - scheduling
    - planning
  estimated_resolution_time_minutes: 20
  difficulty: "Low"
---

# FR-04：メンテナンスウィンドウ表示ランブック

**カテゴリ**: Maintenance Management  
**優先度**: 2  
**作成日**: 2026-06-04  
**更新日**: 2026-06-04  
**適用対象**: RDS, Systems Manager  

## 概要

RDS およびシステムリソースのメンテナンスウィンドウを確認し、計画的なメンテナンスを実施するランブック。

## 前提条件

- RDS インスタンスが存在すること
- Systems Manager が有効であること
- IAM ロールが以下の権限を持つこと：
  - `rds:DescribeDBInstances`
  - `rds:DescribeDBClusters`
  - `ssm:GetMaintenanceWindow`

## 手順

### 1. RDS メンテナンスウィンドウ確認

```bash
# RDS DB インスタンスのメンテナンスウィンドウ確認
aws rds describe-db-instances \
  --query 'DBInstances[*].[DBInstanceIdentifier, PreferredMaintenanceWindow, PendingMaintenanceActions]'

# 出力例:
# db-prod-01 | sun:13:00-sun:14:00 | [Pending: DB Engine Upgrade]
# db-prod-02 | sat:15:30-sat:16:30 | []
```

### 2. メンテナンスウィンドウ内容確認

**実施予定メンテナンス:**
- マイナーバージョンアップグレード：通常 30 分以内、短い再起動
- メジャーバージョンアップグレード：1-3 時間、ダウンタイム有
- セキュリティパッチ：自動適用、短い再起動
- OS パッチ：月次実施

### 3. メンテナンスウィンドウの変更（必要に応じて）

```bash
# メンテナンスウィンドウを変更
aws rds modify-db-instance \
  --db-instance-identifier <DB_INSTANCE_ID> \
  --preferred-maintenance-window "sun:02:00-sun:03:00" \
  --apply-immediately  # false: 次の定期メンテナンス時に適用
```

**推奨スケジュール:**
- 本番環境：オフピーク時間（日本標準時 02:00-03:00）
- ステージング：業務開始前（06:00-07:00）
- 開発：任意

### 4. 計画的なメンテナンス実施前チェック

メンテナンス 24 時間前に以下を確認：

```
□ バックアップが正常（直近 24 時間内）
□ レプリケーション遅延が 0 に近い（マルチ AZ 構成）
□ 接続数が通常以下（メンテナンス中の中断を最小化）
□ アプリケーション設定でリトライポリシーが有効
```

### 5. メンテナンス実施

**手動でメンテナンスを強制する場合:**
```bash
aws rds reboot-db-instance \
  --db-instance-identifier <DB_INSTANCE_ID> \
  --force-failover  # Multi-AZ の場合、フェイルオーバーで再起動時間短縮
```

### 6. メンテナンス後検証

```bash
# インスタンス状態確認
aws rds describe-db-instances \
  --db-instance-identifier <DB_INSTANCE_ID> \
  --query 'DBInstances[0].[DBInstanceStatus, Engine, EngineVersion]'

# アプリケーション疎通確認
# - DB 接続テスト
# - クエリ実行テスト
# - アプリケーションログ監視（エラー量が通常範囲内）
```

## トラブルシューティング

**Q: メンテナンスウィンドウ中に接続が切れた**  
A: アプリケーション側でコネクションプーリングとリトライを実装

**Q: メンテナンス後、パフォーマンスが低下**  
A: パラメータグループがメンテナンス後にリセットされていないか確認

## 参考リンク

- [RDS メンテナンスウィンドウ](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_UpgradeDBInstance.Maintenance.html)
- [RDS DB エンジンアップグレード](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_UpgradeDBInstance.Upgrading.html)
