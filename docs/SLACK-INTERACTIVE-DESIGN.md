# Slack インタラクティブ機能 設計書

## 概要

Lambda が生成したアラートを Slack に投稿し、**ユーザーがボタンをクリック → Slack から AWS Lambda に Webhook で確認を送信 → 実行前に AWS オペレータが OK/Cancel を判定**するフロー。

---

## 🔄 実行フロー

```
【ステップ 1】Lambda 生成（FR-01～06）
├─ Block Kit メッセージを生成
├─ 2 つのボタンを含める
│  ├─ ✅ "Confirm & Execute"
│  └─ ❌ "Review Details"
└─ SNS に publish

    ↓ AWS Chatbot

【ステップ 2】Slack Channel に投稿
├─ Block Kit メッセージ表示
├─ 2 つのボタンが Slack に描画される
└─ report_id = "aiops-{type}-{date}-{timestamp}"

    ↓ ユーザーがボタンクリック

【ステップ 3】Slack がイベントを送信
├─ Webhook URL: API Gateway → Lambda
├─ Payload:
│  {
│    "type": "block_actions",
│    "actions": [
│      {
│        "type": "button",
│        "action_id": "btn_confirm_aiops-bottleneck-20260604-1717486200",
│        "value": "confirm_action",
│        "text": {"type": "plain_text", "text": "✅ Confirm & Execute"},
│        "selected_date": null,
│        "action_ts": "1717486205.123456"
│      }
│    ],
│    "trigger_id": "T123456.B654321.abc123def456",
│    "team": {"id": "T123456", "domain": "myworkspace"},
│    "user": {"id": "U123456", "username": "john.doe"},
│    "channel": {"id": "C123456", "name": "aiops-alerts"},
│    "message_ts": "1717486200.999999"
│  }
└─ X-Slack-Signature ヘッダー（署名検証用）

    ↓ Lambda Webhook

【ステップ 4】Webhook Lambda 処理
├─ Slack 署名検証
├─ action_id から report_id を抽出
├─ S3 から report 情報を取得（pending-confirmations/ ）
├─ Slack に確認メッセージを送信
│  {
│    "text": "Action pending confirmation",
│    "blocks": [...]
│  }
└─ Lambda に確認メッセージをスレッド返信

    ↓ AWS オペレータが Slack で確認

【ステップ 5】実行実行フェーズ
├─ オペレータが Slack で "実行" または "キャンセル" を決定
├─ 実行 → Lambda が FR-XX のアクションを実行
│  └─ EC2 再起動、DB スナップショット作成など
└─ キャンセル → アラート無視、ログに記録
```

---

## 🔐 **Slack 署名検証**

Slack から送信されるリクエストは、以下ヘッダーで検証されます：

```
X-Slack-Request-Timestamp: 1717486205  # Unix timestamp
X-Slack-Signature: v0=abc123...         # HMAC-SHA256 署名
```

**署名検証ロジック**:
```python
import hmac
import hashlib

SLACK_SIGNING_SECRET = os.environ.get('SLACK_SIGNING_SECRET')  # Slack App Config から取得

def verify_slack_signature(request_body: str, timestamp: str, signature: str) -> bool:
    """Slack リクエストの真正性を検証"""
    if abs(int(time.time()) - int(timestamp)) > 300:
        # リクエストが 5 分以上前 → リプレイ攻撃の可能性
        return False
    
    basestring = f"v0:{timestamp}:{request_body}".encode('utf-8')
    computed_signature = "v0=" + hmac.new(
        SLACK_SIGNING_SECRET.encode('utf-8'),
        basestring,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(computed_signature, signature)
```

---

## 📦 **実装構造**

### **Lambda 1: Webhook 受信 Lambda** (`lambda-webhook-handler`)

```python
def lambda_handler(event, context):
    # ① Slack リクエスト本文を取得
    body = event.get('body', '{}')
    headers = event['headers']
    
    # ② Slack 署名検証
    timestamp = headers.get('X-Slack-Request-Timestamp')
    signature = headers.get('X-Slack-Signature')
    
    if not verify_slack_signature(body, timestamp, signature):
        return {'statusCode': 401, 'body': 'Unauthorized'}
    
    # ③ Slack イベント解析
    payload = json.loads(body)
    action = payload['actions'][0]
    action_id = action['action_id']  # "btn_confirm_aiops-bottleneck-..."
    
    # ④ report_id を抽出
    report_id = action_id.replace('btn_confirm_', '').replace('btn_review_', '')
    
    # ⑤ S3 から report 情報を取得（pending-confirmations/ ）
    s3_key = f"pending-confirmations/{report_id}-{int(time.time())}.json"
    response = s3_client.get_object(Bucket=bucket_name, Key=s3_key)
    report = json.loads(response['Body'].read())
    
    # ⑥ Slack にユーザーが確認中であることを通知
    slack_client.chat_postMessage(
        channel=payload['channel']['id'],
        thread_ts=payload['message_ts'],  # スレッドで返信
        text="⏳ Waiting for operator confirmation...",
        blocks=[...]
    )
    
    # ⑦ DB に "pending_confirmation" 状態で保存
    update_report_status(report_id, 'pending_confirmation', action['value'])
    
    return {'statusCode': 200, 'body': 'OK'}
```

---

### **Lambda 2: 手動確認 Lambda** (`lambda-manual-confirmation`)

AWS オペレータが Slack で「実行」または「キャンセル」を決定した時点で呼び出される。

```python
def manual_confirmation_handler(event, context):
    # ① DB から pending_confirmation レポート一覧を取得
    pending_reports = query_pending_reports()
    
    for report_id, action_value in pending_reports:
        # ② ユーザー入力: "確認"
        user_confirmation = get_user_input(report_id)  # Slack メッセージから
        
        if user_confirmation == 'confirm':
            # ③ 元の FR-XX Lambda を呼び出し
            lambda_client.invoke(
                FunctionName='AiopsLambda',
                Payload=json.dumps({
                    'action': report['action'],
                    'confirmed': True,
                    'report_id': report_id
                })
            )
            
            # ④ Slack に実行結果を通知
            notify_slack(report_id, 'Action executed')
            
        elif user_confirmation == 'cancel':
            # ⑤ キャンセルの場合はログに記録
            log_cancelled_action(report_id)
            notify_slack(report_id, 'Action cancelled')
        
        # ⑥ DB から "pending_confirmation" を削除
        delete_pending_report(report_id)
```

---

## 🔌 **API Gateway 設定**

API Gateway が Slack Webhook を受信するための設定：

```yaml
# lambda-webhook-api.yaml（新規テンプレート）

Resources:
  WebhookApi:
    Type: AWS::ApiGateway::RestApi
    Properties:
      Name: AIOpsSlackWebhookAPI
      Description: Slack interactive events receiver

  WebhookResource:
    Type: AWS::ApiGateway::Resource
    Properties:
      RestApiId: !Ref WebhookApi
      ParentId: !GetAtt WebhookApi.RootResourceId
      PathPart: webhook

  WebhookPost:
    Type: AWS::ApiGateway::Method
    Properties:
      RestApiId: !Ref WebhookApi
      ResourceId: !Ref WebhookResource
      HttpMethod: POST
      AuthorizationType: NONE
      Integration:
        Type: AWS_PROXY
        IntegrationHttpMethod: POST
        Uri: !Sub 'arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${WebhookLambdaArn}/invocations'

  WebhookApiDeployment:
    Type: AWS::ApiGateway::Deployment
    DependsOn: WebhookPost
    Properties:
      RestApiId: !Ref WebhookApi
      StageName: prod

  WebhookApiUrl:
    Type: AWS::ApiGateway::Stage
    Properties:
      RestApiId: !Ref WebhookApi
      StageName: prod
      DeploymentId: !Ref WebhookApiDeployment

Outputs:
  WebhookUrl:
    Value: !Sub 'https://${WebhookApi}.execute-api.${AWS::Region}.amazonaws.com/prod/webhook'
    Export:
      Name: SlackWebhookURL
```

---

## ⚠️ **ユーザー確認フロー**

### **シナリオ: EC2 高 CPU ボトルネック検出**

```
【Slack】
─────────────────────────────────────────

🔴 AIOps Alert: bottleneck_investigation
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Status: COMPLETED
Instance: i-1234567890abcdef0
CPU: 85%, Memory: 72%

Root Cause: High background process

💡 Recommendation: Review process list

⚠️ Action Required?
Review findings and confirm before taking action.

[✅ Confirm & Execute] [❌ Review Details]

───────────────────────────────────────

【ユーザーがボタンをクリック】

✅ Confirm & Execute → Report ID: aiops-bottleneck-...

API Gateway Webhook Lambda へ:
- 署名検証
- action_id から report_id 抽出
- S3 に "pending-confirmations/" に保存（1時間後自動削除）
- Slack スレッドに「確認中...」と返信

───────────────────────────────────────

Slack スレッド返信:
「⏳ Waiting for operator confirmation...

以下のアクションを実行しようとしています:
Action: Bottleneck Investigation
Instance: i-1234567890abcdef0
CPU Threshold: 85%

AWS オペレータは以下を実行するまで待機します:
- EC2 インスタンスの再起動
- または関連プロセスの終了」

───────────────────────────────────────

【AWS オペレータが Slack で確認】

上記スレッドに返信:
「実行する」 → manual_confirmation_handler へ

これにより:
1️⃣ EC2 インスタンスが再起動される
2️⃣ 実行結果が Slack に投稿される
3️⃣ S3 の "pending-confirmations/" ファイルは 7 日後に自動削除（ライフサイクルポリシー）

───────────────────────────────────────

Slack 最終通知:
「✅ Action Executed!

Action: Bottleneck Investigation
Instance: i-1234567890abcdef0
Status: COMPLETED

実行内容:
- Instance stopped: 1717486200
- Instance restarted: 1717486205
- CPU usage after restart: 45%」
```

---

## 🛑 **タイムアウト処理**

確認ダイアログが 1 時間以上表示されている場合、Lambda は JSON の `ttl` フィールドで有効期限を判定：

```python
def check_pending_confirmation_expired(confirmation_record: Dict) -> bool:
    """S3 から取得した JSON の ttl フィールドをチェック"""
    current_time = int(time.time())
    ttl = confirmation_record.get('ttl', 0)
    
    if current_time > ttl:
        logger.info(f"Confirmation has expired (TTL: {ttl}, Current: {current_time})")
        return True
    return False
```

**S3 自動削除:**
- `pending-confirmations/` ファイルは CloudFormation LifecycleConfiguration で 7 日後に自動削除
- （詳細: cfn-templates/s3.yaml 行 48-52）

**Lambda 手動チェック:**
- Slack スレッドで確認ボタンクリック時、JSON `ttl` をチェック
- 期限切れの場合は Slack に「Confirmation expired」と通知

---

## 📋 **チェックリスト**

実装時の確認項目：

- [ ] Slack App の「Interactivity」で Webhook URL を登録
- [ ] Slack Signing Secret をAWS Secrets Manager に保存
- [ ] API Gateway の CORS を有効化（Slack からのリクエスト許可）
- [ ] Lambda の IAM ロールに `s3:PutObject`, `s3:GetObject`, `chat:postMessage` 権限を付与
- [ ] S3 ライフサイクル設定確認（cfn-templates/s3.yaml 行 48-52: pending-confirmations 7日後自動削除）
- [ ] Slack Bot Token スコープ：
  - `chat:write` - Slack メッセージ送信
  - `reactions:write` - リアクション追加（オプション）
  - `users:read` - ユーザー情報取得
- [ ] Lambda のタイムアウトを 30 秒以上に設定
- [ ] CloudWatch Logs で Webhook Lambda の実行を監視
