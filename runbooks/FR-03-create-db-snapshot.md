# FR-03：DB スナップショット作成ランブック

**カテゴリ**: Database Operations  
**優先度**: 2  
**作成日**: 2026-06-04  
**更新日**: 2026-06-04  
**適用対象**: RDS  

## 概要

RDS インスタンスのスナップショットを作成し、バックアップ戦略を実装するランブック。

## 前提条件

- RDS インスタンスが存在すること
- IAM ロールが `rds:CreateDBSnapshot` 権限を持つこと
- DB パラメータグループが設定されていること
- ストレージ容量に 50% 以上の空き容量があること

## 手順

### 1. スナップショット取得前チェック

```bash
# DB インスタンスの状態確認
aws rds describe-db-instances \
  --db-instance-identifier <DB_INSTANCE_ID> \
  --query 'DBInstances[0].[DBInstanceStatus, DBInstanceIdentifier, Engine]'

# 確認項目：
# - Status: available（利用可能状態）
# - Backup Retention: 1 以上（自動バックアップ有効）
# - Multi-AZ: 有効推奨
```

### 2. スナップショット作成

```bash
aws rds create-db-snapshot \
  --db-instance-identifier <DB_INSTANCE_ID> \
  --db-snapshot-identifier <SNAPSHOT_ID>-$(date +%Y%m%d-%H%M%S)
```

**命名規則:**
```
{env}-{db-name}-{operation}-{timestamp}
例: prod-order-db-manual-20260604-120000
```

### 3. スナップショット進捗監視

```bash
# スナップショット作成進捗確認
aws rds describe-db-snapshots \
  --db-snapshot-identifier <SNAPSHOT_ID> \
  --query 'DBSnapshots[0].[Status, PercentProgress, AllocatedStorage]'

# 待機: Status が "available" になるまで
```

### 4. スナップショット検証

- **サイズ確認**: 元の DB サイズと一致することを確認
- **保持期間設定**: スナップショット自動削除ポリシー設定
- **リージョン複製**: 災害対策として他リージョンへのコピーを検討

### 5. ドキュメント記録

スナップショット作成完了後、以下を記録：
- スナップショット ID
- 作成日時
- DB インスタンス ID
- 理由（手動バックアップ/定期バックアップ/事前テスト など）

## トラブルシューティング

**Q: スナップショット作成に失敗**  
A: DB ステータスが "available" であることを確認；ストレージ容量不足の場合は拡張

**Q: スナップショット作成が遅い**  
A: DB サイズが大きい場合、数時間要する場合あり；Multi-AZ 構成で高速化可能

## 参考リンク

- [RDS 手動スナップショット](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/USER_CreateSnapshot.html)
- [RDS バックアップと復元](https://docs.aws.amazon.com/AmazonRDS/latest/UserGuide/BackupRestoreGuide.html)
