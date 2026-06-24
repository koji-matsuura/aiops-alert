# AgentCore 移行実装テンプレート

**作成日**: 2026年6月24日  
**対象**: aiops-alert プロジェクト  
**目的**: リスク軽減の実装スクリプト・テンプレート集

---

## 📁 ファイル構造

```
lib/
├── agentcore_compatibility_layer.py    # 互換性層
├── session_manager.py                   # Session 管理
├── circuit_breaker.py                   # サーキットブレーカー
├── conversation_manager.py              # Multi-turn 会話管理
└── session_timeout_policy.py            # Timeout ポリシー

tests/
├── test_lambda_handler_agentcore.py    # ユニットテスト
├── integration/
│   └── test_agentcore_integration.py    # 統合テスト
└── load/
    ├── run_load_test.sh                # 負荷テスト
    ├── agentcore_load_test.jmx         # JMeter テスト
    └── analyze_results.py              # 結果分析

scripts/
├── emergency_rollback.sh                # 緊急ロールバック
├── verify_iam_permissions.py           # IAM 権限検証
├── verify_rollback.py                  # ロールバック検証
└── health_check.sh                     # ヘルスチェック

cfn-templates/
├── session-table.yaml                   # DynamoDB Table
└── monitoring-alarms.yaml               # CloudWatch Alarms

docs/
├── AGENTCORE_FAILURE_RECOVERY_PLAN.md  # 復帰手順書（本体）
└── AGENTCORE_RISK_ASSESSMENT_SUMMARY.md # リスク評価（要約）
```

---

## 🔧 実装優先度

### Phase 0: テスト環境準備（優先度：P0）
1. **互換性レイヤー** → CR-01対策
2. **Session Manager** → CR-06対策
3. **CircuitBreaker** → CR-04対策
4. **ユニットテスト** → 全テスト
5. **統合テスト** → 全テスト

### Phase 1: 本番準備（優先度：P1）
6. **IAM 権限検証スクリプト** → CR-10対策
7. **ロールバック手順書** → 全リスク対策
8. **CloudWatch Alarms** → HR-05, HR-09対策
9. **負荷テスト** → HR-09対策

### Phase 2: 本番実行（優先度：P2）
10. **Canary フェーズ監視** → 全リスク検出
11. **Shadow フェーズ監視** → 全リスク検出
12. **本格投入監視** → 全リスク対応

---

## 📋 実装チェックリスト

### ✅ 互換性レイヤー（lib/agentcore_compatibility_layer.py）
```python
class AgentCoreCompatibility:
    @staticmethod
    def convert_request_to_agentcore(legacy_request)
    @staticmethod
    def convert_response_to_bedrock(agentcore_response)
```
- [ ] messageVersion 1.0 → AgentCore 変換
- [ ] AgentCore → messageVersion 1.0 変換
- [ ] エラーハンドリング
- [ ] ユニットテスト完成

### ✅ Session Manager（lib/session_manager.py）
```python
class SessionManager:
    @staticmethod
    def save_session(session_id, state)
    @staticmethod
    def load_session(session_id)
    @staticmethod
    def delete_session(session_id)
    @staticmethod
    def list_active_sessions()
```
- [ ] DynamoDB への永続化
- [ ] TTL 管理
- [ ] エラーハンドリング
- [ ] 統合テスト完成

### ✅ CircuitBreaker（lib/circuit_breaker.py）
```python
class CircuitBreaker:
    def call(self, func, *args, **kwargs)
    def _on_success(self)
    def _on_failure(self)
```
- [ ] 状態遷移（CLOSED → OPEN → HALF_OPEN）
- [ ] Failure threshold 管理
- [ ] Timeout 管理
- [ ] ユニットテスト完成

### ✅ ユニットテスト（tests/test_lambda_handler_agentcore.py）
- [ ] messageVersion 1.0 フォーマット処理
- [ ] Parameter 抽出（複数形式対応）
- [ ] 互換性レイヤー変換
- [ ] エラーハンドリング
- [ ] CircuitBreaker 動作

### ✅ 統合テスト（tests/integration/test_agentcore_integration.py）
- [ ] E2E: LogInvestigation
- [ ] E2E: BottleneckAnalysis
- [ ] Multi-turn 会話
- [ ] Session state 保持
- [ ] 30秒以内の処理完了

### ✅ 負荷テスト（tests/load/run_load_test.sh）
- [ ] 100 並行リクエスト
- [ ] 5分間の連続実行
- [ ] 結果の集計＆分析
- [ ] CloudWatch へのメトリクス送信

### ✅ IAM 権限検証（scripts/verify_iam_permissions.py）
- [ ] bedrock:InvokeAgent 権限確認
- [ ] bedrock:InvokeModel 権限確認
- [ ] SNS Publish 権限確認
- [ ] CloudWatch Logs 権限確認

### ✅ ロールバック手順（scripts/emergency_rollback.sh）
- [ ] Git revert 実行
- [ ] CodePipeline トリガー
- [ ] デプロイ完了待機
- [ ] Lambda ヘルスチェック
- [ ] SNS 通知

### ✅ CloudWatch Alarms（cfn-templates/monitoring-alarms.yaml）
- [ ] Error Rate > 5% → Rollback
- [ ] P99 Latency > 2s → Alert
- [ ] BedrockAgent Success < 95% → Alert
- [ ] RAG Retrieval Quality < 70% → Alert

---

## 🚀 実装順序（推奨）

### Day 1 午前: 基礎実装
1. `lib/agentcore_compatibility_layer.py` を実装
2. `tests/test_lambda_handler_agentcore.py` でテスト
3. `lib/lambda_handler.py` に互換性レイヤーを統合

### Day 1 午後: Session 管理
4. `lib/session_manager.py` を実装
5. `cfn-templates/session-table.yaml` で DynamoDB テーブル定義
6. `lib/conversation_manager.py` で Multi-turn 会話管理を実装
7. 統合テストで検証

### Day 2 午前: 信頼性向上
8. `lib/circuit_breaker.py` を実装
9. `lib/lambda_handler.py` に CircuitBreaker を統合
10. ユニットテストで検証

### Day 2 午後: テスト完全化
11. `tests/integration/test_agentcore_integration.py` を実装
12. `tests/test_lambda_handler_agentcore.py` を 100% カバレッジに
13. 統合テスト全て パスを確認

### Day 3 午前: 本番準備
14. `scripts/verify_iam_permissions.py` を実装
15. `scripts/emergency_rollback.sh` を実装＆テスト
16. `scripts/verify_rollback.py` で rollback 手順検証

### Day 3 午後: 監視準備
17. `cfn-templates/monitoring-alarms.yaml` で Alarms 定義
18. `tests/load/run_load_test.sh` で負荷テスト実行
19. CloudWatch ダッシュボード作成

---

## 📊 テスト実行コマンド集

```bash
# ユニットテスト
pytest tests/test_lambda_handler_agentcore.py -v --cov

# 統合テスト
pytest tests/integration/test_agentcore_integration.py -v -m integration

# ロールバック検証
python scripts/verify_rollback.py

# IAM 権限検証
python scripts/verify_iam_permissions.py

# ヘルスチェック
./scripts/health_check.sh

# 負荷テスト
./tests/load/run_load_test.sh

# ドキュメント検証
cfn-lint cfn-templates/*.yaml
```

---

## 📝 コードレビューチェックリスト

各実装ファイルのコードレビュー際に確認する項目：

### 互換性レイヤー
- [ ] 複数形式の Parameter に対応
- [ ] エラーが gracefully handle される
- [ ] ユニットテストで複数パターン検証
- [ ] パフォーマンス（変換処理 <10ms）

### Session Manager
- [ ] DynamoDB write consistency 適切
- [ ] TTL expiration ロジック正確
- [ ] 同時並行アクセス対応（乗楽観的ロック）
- [ ] 統合テストで実 DynamoDB で検証

### CircuitBreaker
- [ ] 状態遷移が正確（CLOSED→OPEN→HALF_OPEN→CLOSED）
- [ ] Failure threshold threshold が適切（デフォルト 5）
- [ ] Timeout が適切（デフォルト 60秒）
- [ ] Exception タイプに応じた処理分岐

### テスト
- [ ] テストカバレッジ > 90%
- [ ] Edge case 全て網羅
- [ ] Mock/Stub の使い分け正確
- [ ] テスト実行時間 <5分

### 監視・ロールバック
- [ ] Alarm 設定が正確
- [ ] ロールバック手順が 10分以内
- [ ] 複数同時障害に対応
- [ ] エスカレーション流れが明確

---

