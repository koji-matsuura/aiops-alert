# E2E Test Plan: AIOps Slack Notification + Interactive Workflow

## Overview
E2E（End-to-End）テストは、全 6 つの FR（FR-01～FR-06）について、以下のシナリオをカバーします：
1. **基本フロー**：トリガー → Lambda → Bedrock Agent → SNS → Slack 通知
2. **Block Kit レイアウト**：リッチメッセージ表示（絵文字、セクション、ボタン）
3. **複数アラーム集約**：10分枠で同一トリガーのアラームを集約（Thread ID）
4. **インタラクティブ確認**：Slack ボタンクリック → Webhook → S3 承認記録（FR-02, FR-04, FR-05）
5. **タイムアウト/エラー**：Lambda タイムアウト、S3 エラー、Slack 署名検証失敗

---

## テスト環境セットアップ

### 前提条件
- AWS Account ID: `123456789012`
- Region: `ap-northeast-1`
- Slack Workspace ID: `T1234567890`
- Slack Channel ID: `C1234567890`
- **Slack Signing Secret**: Slack App 管理ページから取得（デプロイ後に Secrets Manager に登録）
- **Slack Bot Token**: Slack App 管理ページから取得（デプロイ後に Secrets Manager に登録）
- 詳細: [SECRET-REGISTRATION-GUIDE.md](./SECRET-REGISTRATION-GUIDE.md)

### デプロイ手順
```bash
# 1. S3 アーティファクトバケット作成
aws s3 mb s3://dev-image-aiagent-artifact --region ap-northeast-1

# 2. CloudFormation テンプレート + Lambda ZIP をアップロード
aws s3 cp cfn-templates/ s3://dev-image-aiagent-artifact/cfn-templates/ --recursive
aws s3 cp dist/lambda.zip s3://dev-image-aiagent-artifact/lambda.zip
aws s3 cp dist/lambda-webhook.zip s3://dev-image-aiagent-artifact/lambda-webhook.zip

# 3. CloudFormation スタックを作成
# ⚠️ 注意: SlackSigningSecret と SlackBotToken は CloudFormation パラメータではなく、
#         Secrets Manager で管理します。デプロイ後に CLI で登録してください。
#         詳細: docs/SECRET-REGISTRATION-GUIDE.md を参照
aws cloudformation create-stack \
  --stack-name aiops-dev-stack \
  --template-url https://s3.ap-northeast-1.amazonaws.com/dev-image-aiagent-artifact/cfn-templates/main.yaml \
  --parameters \
    ParameterKey=TemplateBucketName,ParameterValue=dev-image-aiagent-artifact \
    ParameterKey=EnvName,ParameterValue=dev \
    ParameterKey=SlackWorkspaceId,ParameterValue=T1234567890 \
    ParameterKey=SlackChannelId,ParameterValue=C1234567890 \
  --capabilities CAPABILITY_NAMED_IAM \
  --region ap-northeast-1

# 4. スタック作成完了を待機
aws cloudformation wait stack-create-complete --stack-name aiops-dev-stack --region ap-northeast-1

# 5. Slack 秘密情報を Secrets Manager に登録（デプロイ後）
# 以下を実行（<YOUR_*> を実際の値に置き換える）：
#   aws secretsmanager put-secret-value \
#     --secret-id "aiops/dev/slack" \
#     --secret-string '{
#       "signing_secret": "<YOUR_SIGNING_SECRET>",
#       "bot_token": "<YOUR_BOT_TOKEN>"
#     }' \
#     --region ap-northeast-1
#
# ⚠️ 注意: 実際の秘密値はドキュメントに記載しないこと
# 詳細は docs/SECRET-REGISTRATION-GUIDE.md を参照
```

### Slack App 設定
1. Slack App 管理画面から以下を設定：
   - **Interactivity & Shortcuts** → **Interactivity** を ON
   - **Request URL**: CloudFormation 出力の `SlackWebhookUrl`
   - **Block Kit** サポート確認
   - **Event Subscriptions** → アラートイベント購読

---

## テストシナリオ

### テスト 1: FR-01 ログ調査（基本フロー）

**目的**: ユーザー入力 → Bedrock Agent → Lambda → SNS → Slack 通知

**テスト手順**:
```python
# 1. Lambda ハンドラーをトリガー（ユーザー入力）
event = {
    "action": "log_investigation",
    "trigger": "user_query",
    "query": "Lambda 関数のエラーログを調査",
    "time_range_minutes": 15
}
response = lambda_client.invoke(
    FunctionName='aiops-lambda-dev',
    InvocationType='RequestResponse',
    Payload=json.dumps(event)
)
```

**期待結果**:
- ✅ Lambda 実行成功（StatusCode 200）
- ✅ Bedrock Agent 呼び出し成功（Agent Alias = TSTALIASID）
- ✅ SNS publish 成功
- ✅ Slack 通知受信（Channel: C1234567890）
- ✅ メッセージに以下を含む：
  - 絵文字（📋 ログ調査）
  - セクション分け
  - report_id, timestamp
  - ログ検索結果（5件以上推奨）

**Block Kit メッセージ検証**:
```json
{
  "blocks": [
    {
      "type": "header",
      "text": {"type": "plain_text", "text": "📋 AIOps Alert: Log Investigation", "emoji": true}
    },
    {
      "type": "section",
      "text": {"type": "mrkdwn", "text": "⏰ Timestamp: 2026-06-04T12:34:56Z\n📊 Report ID: aiops-log-investigation-20260604-1717500896"}
    }
  ]
}
```

**CloudWatch Logs 確認**:
```bash
aws logs tail /aws/lambda/aiops-lambda-dev --follow --region ap-northeast-1
# 出力: "Found X log groups", "Searched Y log streams"
```

---

### テスト 2: FR-02 ボトルネック調査（Approval 判定なし）

**目的**: CloudWatch Alarms → EventBridge → Lambda → Thread ID で集約 → Slack

**テスト手順**:
```bash
# 1. CloudWatch アラーム作成（テスト用）
aws cloudwatch put-metric-alarm \
  --alarm-name EC2-HighCPU-i-test-001 \
  --alarm-description "Test alarm for E2E" \
  --metric-name CPUUtilization \
  --namespace AWS/EC2 \
  --statistic Average \
  --period 60 \
  --threshold 75 \
  --comparison-operator GreaterThanThreshold \
  --evaluation-periods 1

# 2. アラーム ALARM 状態に変更
aws cloudwatch set-alarm-state \
  --alarm-name EC2-HighCPU-i-test-001 \
  --state-value ALARM \
  --state-reason "Manual trigger for E2E test"
```

**期待結果**:
- ✅ EventBridge ルール トリガー
- ✅ Lambda 実行（ActionGroup via Bedrock Agent）
- ✅ Slack スレッドに投稿（Thread ID = hash(EC2-HighCPU-i-test-001 + 10min bucket)）
- ✅ S3 に thread-mapping/{thread_id}.json 保存

**Thread ID 検証**:
```bash
# S3 から Thread ID 情報を確認
aws s3 cp s3://dev-image-aiagent-artifact/thread-mapping/ thread-mapping/ --recursive --region ap-northeast-1
cat thread-mapping/*.json
# 出力: {"thread_id": "thread_abc123_202606041230", "thread_ts": "..."}
```

---

### テスト 3: 複数アラーム集約（同一トリガー、10分枠内）

**目的**: 同じアラーム種別のアラームを 1 Slack スレッドに集約

**テスト手順**:
```bash
# 1. 同一アラーム名で 3 回連続トリガー（例: 10:30, 10:32, 10:38）
for i in 1 2 3; do
  aws cloudwatch set-alarm-state \
    --alarm-name EC2-HighCPU-i-test-001 \
    --state-value ALARM \
    --state-reason "Trigger $i at $(date)"
  sleep 120  # 2分待機
done
```

**期待結果**:
- ✅ Slack スレッド内に 3 つのメッセージが投稿
- ✅ すべてメッセージが同一 thread_ts を参照
- ✅ S3 に thread-mapping/{thread_id}.json が 1 回のみ保存（上書きなし）

**Slack スレッド検証**:
```bash
# Slack API でスレッドを確認（SlackBot）
# <YOUR_BOT_TOKEN> を実際の Bot Token に置き換える
curl -X GET https://slack.com/api/conversations.replies \
  -d "channel=C1234567890&ts=<thread_ts>" \
  -H "Authorization: Bearer <YOUR_BOT_TOKEN>"
# 出力: {"ok": true, "messages": [{...}, {...}, {...}]}  # 3件
```

---

### テスト 4: インタラクティブ確認フロー（FR-02 with Approval Request）

**目的**: Slack ボタンクリック → Webhook → S3 記録 → Lambda が S3 で承認確認

**テスト手順**:

#### Step 4.1: 承認待ちメッセージを送信
```python
# Lambda が「確認待ち」メッセージを Slack に送信
event = {
    "action": "bottleneck_investigation",
    "trigger": "alarm",
    "report_id": "aiops-bottleneck-investigation-20260604-1717500896",
    "requires_approval": True  # 承認要求フラグ
}
```

**期待結果**:
- ✅ Block Kit メッセージに以下を含む：
  - ✅ Approve ボタン（value = report_id）
  - ✅ Review Details ボタン
  - ⏰ "Awaiting operator approval..." テキスト

#### Step 4.2: Slack で Approve ボタンをクリック

**期待結果**:
- ✅ Webhook Lambda 呼び出し（API Gateway → Lambda）
- ✅ Slack 署名検証成功
- ✅ S3 に pending-confirmations/{report_id}-{timestamp}.json 保存

**S3 ファイル内容検証**:
```bash
aws s3 cp s3://dev-image-aiagent-artifact/pending-confirmations/ pending-confirmations/ --recursive --region ap-northeast-1
cat pending-confirmations/*.json
# 出力:
# {
#   "report_id": "aiops-bottleneck-investigation-20260604-1717500896",
#   "action": "approve",
#   "user_id": "U1234567890",
#   "timestamp": "2026-06-04T12:35:00Z",
#   "status": "confirmed",
#   "ttl": 1717500900  # 1時間後の Unix timestamp
# }
```

#### Step 4.3: Lambda が S3 から承認確認

```python
# 破壊的アクション前に approval status をチェック
status, operator_id = check_approval_status(report_id)
assert status == "approved"
assert operator_id == "U1234567890"
# → Lambda がアクション実行を続行
```

**期待結果**:
- ✅ check_approval_status() が "approved" を返す
- ✅ Lambda がボトルネック調査を続行
- ✅ 最終レポートが Slack に投稿

---

### テスト 5: 承認期限切れシナリオ

**目的**: 1 時間以上経過した承認要求を拒否

**テスト手順**:

#### Step 5.1: 古い pending-confirmation を S3 に作成
```python
old_confirmation = {
    "report_id": "aiops-bottleneck-old-old-old",
    "action": "approve",
    "user_id": "U1234567890",
    "timestamp": "2026-06-04T10:00:00Z",
    "ttl": 1717489200  # 1時間以上前
}
s3_client.put_object(
    Bucket='dev-image-aiagent-artifact',
    Key='pending-confirmations/aiops-bottleneck-old-old-old-1717489200.json',
    Body=json.dumps(old_confirmation)
)
```

#### Step 5.2: check_approval_status() 実行
```python
status, operator_id = check_approval_status("aiops-bottleneck-old-old-old")
assert status == "expired"
```

**期待結果**:
- ✅ check_approval_status() が "expired" を返す
- ✅ Lambda がアクション実行をスキップ
- ✅ Slack に "Approval expired" メッセージ投稿

---

### テスト 6: Slack 署名検証失敗

**目的**: リプレイ攻撃、なりすまし対策を検証

**テスト手順**:

#### Step 6.1: 無効な署名でリクエスト送信
```bash
# 間違った署名を使用
curl -X POST https://<webhook_url>/slack/interactive \
  -H "X-Slack-Signature: v0=invalid_signature_here" \
  -H "X-Slack-Request-Timestamp: $(date +%s)" \
  -H "Content-Type: application/json" \
  -d '{
    "type": "block_actions",
    "actions": [{"action_id": "approve_action", "value": "report_id"}]
  }'
```

**期待結果**:
- ✅ HTTP 401 Unauthorized
- ✅ CloudWatch Logs: "Slack signature verification failed"
- ✅ S3 に pending-confirmation **未作成**

#### Step 6.2: 古いタイムスタンプでリクエスト（リプレイ攻撃）
```bash
# 5分以上前のタイムスタンプを使用
OLD_TIMESTAMP=$(( $(date +%s) - 400 ))

# 有効な署名を計算
SIGNING_SECRET="YOUR_SECRET"
SIG_BASE_STRING="v0:${OLD_TIMESTAMP}:{...json...}"
SIGNATURE="v0=$(echo -n "$SIG_BASE_STRING" | openssl dgst -sha256 -hmac "$SIGNING_SECRET" -hex | cut -d' ' -f2)"

curl -X POST https://<webhook_url>/slack/interactive \
  -H "X-Slack-Signature: $SIGNATURE" \
  -H "X-Slack-Request-Timestamp: $OLD_TIMESTAMP" \
  ...
```

**期待結果**:
- ✅ HTTP 401 Unauthorized
- ✅ CloudWatch Logs: "Request timestamp too old"
- ✅ リプレイ攻撃が防止される

---

### テスト 7: S3 Lifecycle 自動削除検証

**目的**: Lifecycle Policy に基づく自動クリーンアップ

**テスト手順**:

#### Step 7.1: pending-confirmation テストデータ作成
```bash
# 14日前のデータを作成（手動で）
aws s3 cp /dev/null s3://dev-image-aiagent-artifact/pending-confirmations/old-test-old.json \
  --metadata "created=$(date -d '14 days ago' +%s)"
```

#### Step 7.2: S3 Lifecycle Policy を手動トリガー（または 24 時間待機）
```bash
# Lifecycle Expiration を確認（本来は 1日後に自動削除）
aws s3api head-object \
  --bucket dev-image-aiagent-artifact \
  --key pending-confirmations/old-test-old.json \
  --region ap-northeast-1
# → 予想: 404 Not Found（削除済み）
```

**期待結果**:
- ✅ 1日経過した thread-mapping/ ファイルが削除
- ✅ 7日経過した pending-confirmations/ ファイルが削除
- ✅ 30日経過した reports/ ファイルが削除

---

### テスト 8: 全 FR シナリオ（自動テストスイート）

**目的**: 全 6 つの FR を連続実行・検証

```python
# tests/test_e2e_aiops.py
import boto3
import json
import time

def test_all_fr_scenarios():
    """全 FR シナリオを実行"""
    lambda_client = boto3.client('lambda', region_name='ap-northeast-1')
    
    fr_scenarios = [
        {
            "name": "FR-01 Log Investigation",
            "event": {"action": "log_investigation", "trigger": "user_query"}
        },
        {
            "name": "FR-02 Bottleneck Investigation",
            "event": {"action": "bottleneck_investigation", "trigger": "alarm"}
        },
        {
            "name": "FR-03 Create Snapshot",
            "event": {"action": "create_snapshot", "db_instance_identifier": "test-db"}
        },
        {
            "name": "FR-04 Maintenance Display",
            "event": {"action": "maintenance_display", "service_name": "RDS"}
        },
        {
            "name": "FR-05 Slow Query Detection",
            "event": {"action": "slow_query_detection", "trigger": "schedule"}
        },
        {
            "name": "FR-06 High Load Query Detection",
            "event": {"action": "high_load_query_detection", "trigger": "schedule"}
        }
    ]
    
    results = []
    
    for scenario in fr_scenarios:
        try:
            response = lambda_client.invoke(
                FunctionName='aiops-lambda-dev',
                InvocationType='RequestResponse',
                Payload=json.dumps(scenario["event"])
            )
            
            # 結果検証
            status_code = response.get('StatusCode')
            payload = json.loads(response.get('Payload').read())
            
            success = status_code == 200 and 'error' not in payload
            results.append({
                "scenario": scenario["name"],
                "success": success,
                "status_code": status_code,
                "report_id": payload.get('report_id')
            })
            
            print(f"✅ {scenario['name']}: {'PASS' if success else 'FAIL'}")
        
        except Exception as e:
            results.append({
                "scenario": scenario["name"],
                "success": False,
                "error": str(e)
            })
            print(f"❌ {scenario['name']}: {str(e)}")
        
        time.sleep(2)  # レート制限回避
    
    # 結果集計
    passed = sum(1 for r in results if r['success'])
    print(f"\n=== E2E Test Results ===")
    print(f"Passed: {passed}/{len(results)}")
    
    return results

if __name__ == "__main__":
    test_all_fr_scenarios()
```

**実行方法**:
```bash
pip install pytest boto3
pytest tests/test_e2e_aiops.py -v
```

---

## テスト検証チェックリスト

| # | 項目 | 検証方法 | 期待結果 |
|----|------|---------|---------|
| 1 | Lambda 実行成功 | CloudWatch Logs | "Invoke successful" |
| 2 | Bedrock Agent 呼び出し | CloudWatch Logs | "Agent session created" |
| 3 | SNS Publish 成功 | CloudWatch Metrics | SNS PublishSize > 0 |
| 4 | Slack 通知受信 | Slack Channel 確認 | Block Kit メッセージ表示 |
| 5 | Thread ID 集約 | Slack スレッド確認 | 複数メッセージが同一スレッド |
| 6 | S3 保存 | S3 ls | pending-confirmations/ に JSON 存在 |
| 7 | Webhook 署名検証 | CloudWatch Logs | "Slack signature verified" |
| 8 | Lifecycle 自動削除 | S3 Versioning | 期限切れファイル削除 |

---

## トラブルシューティング

| エラー | 原因 | 解決策 |
|--------|------|--------|
| `InvalidParameterValue: Lambda timeout` | Lambda実行時間超過 | timeout 増加（300秒まで） |
| `AccessDenied: S3 PutObject` | IAM権限不足 | Lambda Role に s3:PutObject 付与 |
| `Slack signature verification failed` | 署名不一致 | SLACK_SIGNING_SECRET 確認 |
| `KnowledgeBase not found` | Knowledge Base ID 誤り | bedrock-agent.yaml で KnowledgeBaseId 確認 |
| `Thread aggregation not working` | S3 thread-mapping 書き込み失敗 | S3 Versioning 確認 |

---

## デプロイ後の検証

### 全体的な正常性確認
```bash
# 1. CloudFormation スタック確認
aws cloudformation describe-stacks --stack-name aiops-dev-stack --region ap-northeast-1 \
  | grep -E "StackStatus|Outputs" | head -20

# 2. Lambda 関数確認
aws lambda list-functions --region ap-northeast-1 | grep aiops

# 3. Bedrock Agent 確認
aws bedrock-agent list-agents --region ap-northeast-1

# 4. EventBridge ルール確認
aws events list-rules --name-prefix EC2-HighCPU --region ap-northeast-1

# 5. SNS Topic 確認
aws sns list-topics --region ap-northeast-1 | grep aiops

# 6. Slack Chatbot 確認
aws chatbot describe-slack-channel-configurations --region ap-northeast-1
```

### ログストリーム確認
```bash
# Lambda ログ
aws logs tail /aws/lambda/aiops-lambda-dev --follow --region ap-northeast-1 &

# Webhook ログ
aws logs tail /aws/lambda/aiops-slack-webhook-dev --follow --region ap-northeast-1 &

# API Gateway ログ
aws logs tail /aws/apigateway/aiops-webhook-dev --follow --region ap-northeast-1 &
```

---

## 実行コマンド

### E2E テスト全体実行
```bash
cd /Users/matsuurakouji/aiops-alert

# 1. テスト環境セットアップ
bash tests/setup_test_env.sh

# 2. テストスイート実行
pytest tests/test_e2e_aiops.py -v --tb=short

# 3. 結果レポート生成
python tests/generate_test_report.py
```

---

## 根拠と参照

- **Slack API Documentation**: https://api.slack.com/authentication/verifying-requests-from-slack
- **AWS Lambda Timeout**: Max 15 minutes (900 seconds) - AGENTS.md §11
- **S3 Lifecycle Policy**: ブログ要件に基づくデータ保持戦略 - AGENTS.md §5.8
- **CloudFormation Validation**: cfn-lint で構文検証
- **EventBridge + Lambda**: ブログ「Automate IT operations with Amazon Bedrock Agents」

---

**ドキュメント作成日**: 2026-06-04  
**最終更新**: v1.0 - 初版作成  
**ステータス**: 準備完了 → デプロイ前テスト実施予定
