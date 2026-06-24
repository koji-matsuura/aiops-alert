# AgentCore 移行 - リスク評価マトリックス【要約版】

**作成日**: 2026年6月24日  
**対象**: aiops-alert プロジェクト v2.8.0 → AgentCore 移行
**目的**: 11個以上のリスクの統合的な評価と復帰戦略

---

## 🎯 リスク評価マトリックス（確度 × 影響度）

```
            ┌────────────────┬─────────────────┬──────────────┐
            │  高影響         │  中影響          │  低影響      │
         (Critical)      (High)           (Low)
┌──────┬───┼────────────────┼─────────────────┼──────────────┤
│高確度│70%│ CR-01 (互換性) │ HR-03 (スキーマ) │              │
│(60%) ├───┤ CR-02 (ベクトル)│ HR-05 (キャッシュ)│              │
│      │   │ CR-04 (Lambda) │ HR-07 (エラー)   │              │
│      │   │ CR-06 (セッション)│ HR-09 (性能)    │              │
│      │   │ CR-10 (IAM)    │ HR-11 (OpenSearch)│             │
├──────┼───┼────────────────┼─────────────────┼──────────────┤
│中確度│45%│ MR-01 (Model出力)│ MR-02 (Tool use)│ MR-04 (キャッシング)|
│(40%) ├───┤ MR-06 (Ingestion)│ MR-03 (State)   │ MR-05 (TTL)  │
│      │   │                │                 │              │
├──────┼───┼────────────────┼─────────────────┼──────────────┤
│低確度│35%│ LR-03 (ラグ) │ LR-04 (リソース制限)│ LR-05, LR-06 │
│(25%) ├───┤ LR-07 (Timeout) │ LR-08 (スケーリング)│             │
│      │   │                │                 │              │
└──────┴───┴────────────────┴─────────────────┴──────────────┘
```

---

## 📊 リスク一覧表

| ID | リスク | 確度 | 影響度 | 優先度 | 復帰時間 | 検出方法 |
|------|--------|------|--------|--------|----------|----------|
| **CR-01** | Bedrock ⇔ AgentCore 互換性不足 | 70% | 極大 | 🔴 P0 | 45～60分 | Lambda Error Rate > 50% |
| **CR-02** | Knowledge Base ベクトル化失敗 | 60% | 極大 | 🔴 P0 | 30～45分 | Ingestion Job FAILED |
| **CR-04** | Lambda ハンドラ移行バグ | 75% | 極大 | 🔴 P0 | 20～30分 | KeyError in logs |
| **CR-06** | セッション管理の不具合 | 65% | 極大 | 🔴 P0 | 40～50分 | Session state validation errors |
| **CR-10** | IAM 権限エラー | 50% | 極大 | 🔴 P0 | 60～90分 | AccessDeniedException |
| **HR-03** | OpenSearch スキーマ互換性 | 40% | 高 | 🟠 P1 | 15～25分 | Field type mismatch |
| **HR-05** | キャッシング層の問題 | 45% | 高 | 🟠 P1 | 10～20分 | Lambda Duration > 3s |
| **HR-07** | エラーハンドリング不足 | 55% | 高 | 🟠 P1 | 20～30分 | Unhandled exceptions |
| **HR-09** | パフォーマンス劣化 | 50% | 高 | 🟠 P1 | 15～25分 | P99 Latency > 2s |
| **HR-11** | OpenSearch スケーリング不足 | 35% | 高 | 🟠 P1 | 20～40分 | Search latency > 2s |
| **MR-01** | Bedrock Model 出力フォーマット変更 | 40% | 中 | 🟡 P2 | 10～15分 | JSON parse errors |

---

## 🚨 Critical Risks（即座対応が必要）

### CR-01: Bedrock ⇔ AgentCore 互換性不足
- **原因**: messageVersion 1.0 API が変更
- **症状**: Lambda Error Rate が50%超、Tool invocation 全失敗
- **復帰**: 互換性レイヤー実装＋即座のホットデプロイ（45～60分）
- **予防**: テスト環境で messageVersion 1.0 完全検証

### CR-02: Knowledge Base ベクトル化失敗
- **原因**: Vector dimension mismatch（1024D → 1536D など）
- **症状**: RAG 検索結果 0件、Knowledge Base FAILED 状態
- **復帰**: Ingestion Job 再実行＋スキーマ修正（30～45分）
- **予防**: インデックス事前検証、段階的インジェスト

### CR-04: Lambda ハンドラ移行バグ
- **原因**: Parameter 抽出ロジック KeyError
- **症状**: Agent が Tool 呼び出し後フリーズ（60秒タイムアウト）
- **復帰**: Parameter 抽出ロジック robust化＋サーキットブレーカー（20～30分）
- **予防**: ユニットテスト 100% カバレッジ

### CR-06: セッション管理の不具合
- **原因**: Session State がメモリのみに保持
- **症状**: 前の会話内容を Agent が忘れる、Multi-turn 失敗
- **復帰**: DynamoDB 永続化＋TTL管理（40～50分）
- **予防**: Multi-turn conversation 統合テスト

### CR-10: IAM 権限エラー
- **原因**: bedrock:InvokeAgent 権限がない/有効期限切れ
- **症状**: AccessDeniedException で 100% リクエスト失敗
- **復帰**: IAM Role 権限追加＋CloudFormation 更新（60～90分）
- **予防**: IAM権限 自動検証スクリプト

---

## 🟠 High Risks（監視が必要）

| リスク | 検出 | 復帰時間 | 対策 |
|--------|------|----------|------|
| HR-03: OpenSearch スキーマ | Field type mismatch | 15～25分 | マッピング検証 |
| HR-05: キャッシング問題 | Duration > 3s | 10～20分 | キャッシュクリア |
| HR-07: エラーハンドリング | Unhandled exceptions | 20～30分 | Try-except強化 |
| HR-09: 性能劣化 | P99 Latency > 2s | 15～25分 | Lambda スケール |
| HR-11: OpenSearch スケーリング | Search latency > 2s | 20～40分 | OCU スケール |

---

## 📈 全体的なリスク軽減戦略

### 1. 技術的軽減策（65% リスク削減）
```
✅ 互換性レイヤー実装
✅ DynamoDB Session State 永続化
✅ サーキットブレーカー パターン
✅ IAM 権限 自動検証
✅ 段階的 Ingestion とスキーマ検証
```

### 2. プロセス的軽減策（20% リスク削減）
```
✅ Pre-deployment checklist 自動化
✅ 月1回のロールバック演習
✅ ドキュメント日次更新
✅ テスト カバレッジ 100%
```

### 3. 本番フェーズ軽減策（15% リスク削減）
```
✅ Canary 5% トラフィック 30分確認
✅ Shadow 10% トラフィック 2時間確認
✅ 本格投入後 72時間継続監視
✅ 自動ロールバック（エラー率 > 5%）
```

---

## ⏱️ 総復帰時間の分布

```
リスク別の復帰時間（分）:

CR-01 互換性不足      ████████████ 45-60分
CR-02 ベクトル化失敗   ████████ 30-45分
CR-04 Lambda バグ     ██████ 20-30分
CR-06 セッション管理   ████████████ 40-50分
CR-10 IAM 権限        ██████████████ 60-90分

HR-03 スキーマ        ██████ 15-25分
HR-05 キャッシング    ████ 10-20分
HR-07 エラーハンドリング ██████ 20-30分
HR-09 性能劣化        ██████ 15-25分
HR-11 スケーリング    ████████ 20-40分

平均復帰時間: 29.5分（Median 20分）
最悪ケース: 90分（CR-10 + 複数同時障害）
```

---

## 🎬 段階的フェーズ実行スケジュール

```
Day 1-2: テスト検証フェーズ
  ├─ ユニット/統合テスト 100% パス
  ├─ 互換性テスト完了
  ├─ ドキュメント完成
  └─ 予定: 16時間

Day 3: Canary 5% フェーズ
  ├─ 監視開始（リアルタイム）
  ├─ 30分間 安定性確認
  ├─ エラー率 < 1%
  └─ 予定: 2時間

Day 3-4: Shadow 10% フェーズ
  ├─ 2時間の追跡観測
  ├─ ログ分析＆改善
  └─ 予定: 2時間

Day 4: 本格投入 100% フェーズ
  ├─ 全トラフィック AgentCore へ
  ├─ 72時間継続監視
  └─ 予定: 以降 72時間

Day 5+: 安定化フェーズ
  ├─ パフォーマンスチューニング
  ├─ Cost 最適化
  └─ 継続的なドキュメント更新

総期間: 9日間（7日間の監視含む）
```

---

## 🔧 実装チェックリスト

### Phase 0: テスト環境（Day 1-2）
- [ ] 互換性レイヤー実装（lib/agentcore_compatibility_layer.py）
- [ ] DynamoDB Session Manager 実装（lib/session_manager.py）
- [ ] CircuitBreaker パターン実装（lib/circuit_breaker.py）
- [ ] ユニットテスト 実装＆実行（tests/test_lambda_handler_agentcore.py）
- [ ] 統合テスト 実装＆実行（tests/integration/test_agentcore_integration.py）
- [ ] 負荷テスト スクリプト準備（tests/load/run_load_test.sh）
- [ ] ロールバック手順書 作成＆検証（scripts/emergency_rollback.sh）
- [ ] 監視ダッシュボード 作成（CloudWatch Alarms, X-Ray）
- [ ] ドキュメント 完成（本レポート含む）

### Phase 1: Canary 5%（Day 3）
- [ ] Lambda Alias を canary に設定（weights: 95%, 5%）
- [ ] CloudWatch Alarms 有効化
- [ ] 30分間リアルタイム監視
- [ ] エラー率 < 1% 確認
- [ ] 拡大判断（Go/NoGo）

### Phase 2: Shadow 10%（Day 3-4）
- [ ] Lambda Alias を shadow に設定（weights: 90%, 10%）
- [ ] 2時間の追跡観測
- [ ] ログ分析＆改善
- [ ] 本格投入判断

### Phase 3: 本格投入 100%（Day 4）
- [ ] Lambda Alias を prod に設定（weights: 0%, 100%）
- [ ] 72時間継続監視開始
- [ ] 自動ロールバック トリガーチェック

---

## 📞 Escalation 流れ

```
【エラー検出】
    ↓ (自動)
【CloudWatch Alarm 発火】
    ↓ (1分)
【PagerDuty 通知】
    ↓ (2分)
【On-call エンジニア 対応開始】
    ├─ Canary フェーズ: 5分以内にロールバック
    ├─ Shadow フェーズ: 10分以内に Shadow 中止
    └─ 本格投入後: 15分以内にロールバック
```

---

## 📊 成功指標

```
復帰完了の判断基準:

✅ Lambda Error Rate < 5%
✅ Lambda Duration P99 < 2秒（通常 <1秒）
✅ BedrockAgent invocation 成功率 > 95%
✅ RAG 検索結果件数 > 0（全テストクエリ）
✅ CloudTrail に AccessDenied 0件
✅ CloudWatch Logs に "Session not found" 0件
✅ Tool invocation 成功率 > 95%
```

---

