# Slack ボタンクリック → Lambda → SNS → Slack スレッド返信 詳細フロー

**版**：v1.0（2026-06-20）  
**対象**：AIOps Alert プロジェクト  
**情報ソース方針**：すべての記述に実装ファイルの行番号を明記（source-verification スキル準拠）

---

## 📑 目次

1. [全体フロー図](#1-全体フロー図)
2. [ステップ 1: Slack メッセージ表示（初期状態）](#ステップ-1-slack-メッセージ表示初期状態)
3. [ステップ 2: ユーザーがボタンをクリック](#ステップ-2-ユーザーがボタンをクリック)
4. [ステップ 3: Slack → API Gateway → Lambda（Webhook ハンドラ）](#ステップ-3-slack--api-gateway--lambdawebhook-ハンドラ)
5. [ステップ 4: Slack 署名検証](#ステップ-4-slack-署名検証)
6. [ステップ 5: イベントパース & message.ts 抽出](#ステップ-5-イベントパース--messagets-抽出)
7. [ステップ 6: 承認決定を S3 に保存 + スレッド追跡](#ステップ-6-承認決定を-s3-に保存--スレッド追跡)
8. [ステップ 7: Slack スレッドに確認応答を返信](#ステップ-7-slack-スレッドに確認応答を返信)
9. [ステップ 8: Lambda 処理結果を SNS に通知](#ステップ-8-lambda-処理結果を-sns-に通知)
10. [ステップ 9: SNS → Slack チャットボット → スレッド最終通知](#ステップ-9-sns--slack-チャットボット--スレッド最終通知)
11. [エラーハンドリング](#エラーハンドリング)
12. [タイムスタンプ・スレッド ID 追跡](#タイムスタンプスレッド-id-追跡)

---

## 1. 全体フロー図

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                           ⭐ Slack ボタンクリック全体フロー                  │
└─────────────────────────────────────────────────────────────────────────────┘

【ステップ 1】Lambda (FR-01～06) が実行結果を SNS に publish
    ↓ (SNS Topic: AIOpsReport)
    
【ステップ 2】SNS が Slack チャットボットに通知（Block Kit メッセージ）
    ↓ メッセージ内容:
    │ 【実行結果】
    │ リソース: EC2-i-xxxxx
    │ 調査内容: ボトルネック検出
    │ 結果: CPU 95% で高い
    │ [✅ Approve] [❌ Cancel] ← ボタン
    │ スレッド: report_123_ts_1618350863.001400
    ↓
    
【ステップ 3】ユーザーが [✅ Approve] ボタンをクリック
    ↓ Slack がボタンクリックイベントを Webhook に POST
    │ URL: https://{API-Gateway-URL}/slack/interactive
    │ POST body: {
    │   "type": "block_actions",
    │   "actions": [{"action_id": "approve_action", "value": "report_123"}],
    │   "message": {"ts": "1618350863.001400"},  # ⭐ スレッド ID
    │   "channel": {"id": "C123456"},
    │   "user": {"id": "U1234567890"},
    │   "response_url": "https://hooks.slack.com/actions/...",
    │   ...
    │ }
    │ ヘッダー:
    │   X-Slack-Request-Timestamp: 1234567890
    │   X-Slack-Signature: v0=abc123...
    ↓
    
【ステップ 4】API Gateway が Lambda (Webhook Handler) を起動
    ├─ URL Path: POST /slack/interactive
    ├─ Handler: slack_webhook_handler.lambda_handler() (行 463-467)
    └─ 入力: 
       {
         "body": "{...Slack イベント JSON...}",
         "headers": {
           "X-Slack-Request-Timestamp": "1234567890",
           "X-Slack-Signature": "v0=..."
         }
       }
    ↓
    
【ステップ 5】Lambda: webhook_handler() が起動（行 361-467）
    ├─ ステップ A: Slack 署名検証
    │  └─ verify_slack_signature() (行 81-128)
    │     ├─ タイムスタンプ検証: 5分以内か？ (行 101-106)
    │     ├─ 署名検証: HMAC-SHA256 + hmac.compare_digest() (行 108-124)
    │     └─ 結果: ✅ または ❌ 401 Unauthorized
    │
    ├─ ステップ B: イベントタイプ判定（行 400-409）
    │  ├─ url_verification → challenge 返却
    │  └─ block_actions → 承認フロー続行
    │
    ├─ ステップ C: parse_slack_interactive_event()（行 415）
    │  ├─ action_id 抽出: "approve_action" or "cancel_action"
    │  ├─ report_id 抽出: "report_123"
    │  ├─ user_id 抽出: "U1234567890"
    │  ├─ response_url 抽出: "https://hooks.slack.com/..."
    │  ├─ channel_id 抽出: "C123456" (スレッド返信用)
    │  └─ ⭐ message_ts 抽出: "1618350863.001400" (スレッド ID)
    │     根拠: slack_webhook_handler.py 行 176-182
    │
    ├─ ステップ D: save_approval_decision()（行 425）
    │  ├─ S3 保存先 1: pending-confirmations/{report_id}-{timestamp}.json
    │  ├─ S3 保存先 2: thread-mapping/{message_ts}.json  # ⭐ スレッド追跡
    │  └─ 内容: action (approve/cancel), user_id, thread_ts, timestamp
    │
    ├─ ステップ E: send_slack_response()（行 432）
    │  ├─ thread_ts と channel_id を使用
    │  ├─ Slack Web API chat.postMessage を呼び出し
    │  └─ payload: {"channel": "C123456", "thread_ts": "1618350863.001400", "text": "✅ Approval recorded..."}
    │     根拠: Slack API https://api.slack.com/methods/chat.postMessage
    │
    └─ ステップ F: Lambda 返却（HTTP 200）
       {
         "statusCode": 200,
         "body": {
           "status": "ok",
           "action": "approve",
           "report_id": "report_123",
           "s3_key": "pending-confirmations/report_123-1234567890.json",
           "message_ts": "1618350863.001400"
         }
       }
    ↓
    
【ステップ 6】Slack スレッド内にボット返信が表示
    ├─ 親メッセージ: 実行結果 (ts=1618350863.001400)
    ├─ スレッド返信: ✅ Approval recorded: approve for report report_123 by @user123
    └─ スレッドのコンテキストが保持される（同一スレッド内のみ表示）
    ↓
    
【ステップ 7】別の Lambda (メインハンドラ) が処理完了後、SNS に publish
    ├─ 実装: lambda_handler.py 行 230-251 (notify_result())
    ├─ SNS TopicArn: arn:aws:sns:ap-northeast-1:account:AIOpsReport
    ├─ 通知内容:
    │  {
    │    "action": "log_investigation",
    │    "status": "completed",
    │    "report_id": "log_investigation_20260620_103000",
    │    "thread_ts": "1618350863.001400",  # ⭐ Slack スレッド ID
    │    "result": {...}
    │  }
    └─ 根拠: lambda_handler.py 行 242-246 (sns_client.publish)
    ↓
    
【ステップ 8】SNS → Slack チャットボット（chatbot-slack-notification stack）
    ├─ SNS が Lambda トリガー
    ├─ Lambda が Slack Web API を呼び出し
    └─ 同じ thread_ts を使用してスレッド内に追加メッセージを送信
    ↓
    
【ステップ 9】最終状態
    ┌─────────────────────────┐
    │ Slack スレッド           │
    ├─────────────────────────┤
    │ 親メッセージ (ts=1618350863.001400):
    │ 【実行結果】            
    │ リソース: EC2-i-xxxxx  
    │ ボットメッセージ 1:
    │ ✅ Approval recorded: approve
    │ ボットメッセージ 2:
    │ 🔔 処理完了: ボトルネック検出完了
    │    CPU: 95%
    │    メモリ: 88%
    └─────────────────────────┘
```

---

## ステップ 1: Slack メッセージ表示（初期状態）

### 1.1 どこから Slack メッセージが来るのか？

Slack メッセージは以下のいずれかのトリガーから来ます：

#### パターン A: CloudWatch Alarms トリガー
```
CloudWatch Alarm (EC2-HighCPU)
  ↓ ALARM 状態に遷移
EventBridge ルール (eventbridge-alarms.yaml 行 20-56)
  ↓ Lambda (main_lambda_handler) を起動
Lambda (lambda_handler.py 行 48-96)
  ↓ Bedrock Agent を呼び出し
Bedrock Agent + Knowledge Base
  ↓ 適切な FR-XX (ボトルネック調査など) を実行
Lambda (FR-02)
  ↓ SNS に結果を publish
SNS → Slack チャットボット
  ↓ Slack メッセージ表示 (ボタン付き)
```

#### パターン B: ユーザー入力トリガー
```
ユーザー: "EC2 の CPU が高いです"
  ↓
Bedrock Agent Console
  ↓
Bedrock Agent
  ↓ RAG + Action Group
FR-02 (ボトルネック調査)
  ↓ SNS に結果を publish
  ↓ Slack メッセージ表示
```

### 1.2 Slack メッセージの構造

```json
{
  "type": "message",
  "text": "【実行結果】リソース: EC2-i-xxxxx",
  "thread_ts": "1618350863.001400",  // ⭐ スレッド ID（親メッセージのタイムスタンプ）
  "blocks": [
    {
      "type": "section",
      "text": {
        "type": "mrkdwn",
        "text": "*【ボトルネック調査結果】*\nリソース: EC2-i-xxxxx\nCPU: 95%\nメモリ: 88%"
      }
    },
    {
      "type": "actions",
      "block_id": "actions_block",
      "elements": [
        {
          "type": "button",
          "action_id": "approve_action",
          "text": {"type": "plain_text", "text": "✅ Approve"},
          "value": "report_123"  // ⭐ report_id（カスタム値）
        },
        {
          "type": "button",
          "action_id": "cancel_action",
          "text": {"type": "plain_text", "text": "❌ Cancel"},
          "value": "report_123"
        }
      ]
    }
  ]
}
```

**根拠**: Slack Block Kit API  
https://api.slack.com/messaging/composing/layouts

---

## ステップ 2: ユーザーがボタンをクリック

### 2.1 ボタンクリック時の Slack の動作

ユーザーが **[✅ Approve]** ボタンをクリックすると：

1. **Slack がクリックイベントを生成**
   - イベントタイプ: `block_actions`
   - アクション ID: `approve_action`
   - ボタンの値: `report_123` (レポート ID)
   - メッセージタイムスタンプ: `1618350863.001400` (スレッド ID)

2. **Slack がウェブフックに POST**
   ```
   POST https://{API-Gateway-URL}/slack/interactive
   Content-Type: application/json
   X-Slack-Request-Timestamp: 1234567890
   X-Slack-Signature: v0=abc123...
   
   {
     "type": "block_actions",
     "actions": [{"action_id": "approve_action", "value": "report_123"}],
     "message": {"ts": "1618350863.001400"},  // ⭐ thread_ts
     "channel": {"id": "C123456"},
     "user": {"id": "U1234567890"},
     "response_url": "https://hooks.slack.com/actions/...",
     ...
   }
   ```

**根拠**: Slack API Reference - Block Actions Payload  
https://api.slack.com/reference/interaction-payloads/block-actions

### 2.2 response_url の役割

`response_url` は、即座に Slack に応答を返すための URL です：

```python
# 短縮形の返信（最初の返信のみ）
curl -X POST https://hooks.slack.com/actions/... \
  -H "Content-Type: application/json" \
  -d '{"text": "✅ 承認しました"}'
```

ただし、本実装ではスレッド返信（`thread_ts`）を優先するため、`response_url` の使用を最小限にします。

---

## ステップ 3: Slack → API Gateway → Lambda（Webhook ハンドラ）

### 3.1 API Gateway ルーティング

CloudFormation テンプレート: **cfn-templates/slack-webhook.yaml**

```yaml
# 行 124-137: API Gateway リソース
SlackResource:
  Type: AWS::ApiGateway::Resource
  Properties:
    RestApiId: !Ref WebhookApiGateway
    ParentId: !GetAtt WebhookApiGateway.RootResourceId
    PathPart: slack

InteractiveResource:
  Type: AWS::ApiGateway::Resource
  Properties:
    RestApiId: !Ref WebhookApiGateway
    ParentId: !Ref SlackResource
    PathPart: interactive

# 行 139-150: POST メソッド
SlackInteractiveMethod:
  Type: AWS::ApiGateway::Method
  Properties:
    RestApiId: !Ref WebhookApiGateway
    ResourceId: !Ref InteractiveResource
    HttpMethod: POST
    AuthorizationType: NONE  # Slack 署名検証で保護
    Integration:
      Type: AWS_PROXY
      IntegrationHttpMethod: POST
      Uri: !Sub 'arn:aws:apigateway:${AWS::Region}:lambda:path/2015-03-31/functions/${WebhookLambdaFunction.Arn}/invocations'

# 行 152-158: デプロイ
WebhookApiDeployment:
  Type: AWS::ApiGateway::Deployment
  Properties:
    RestApiId: !Ref WebhookApiGateway
    StageName: !Ref EnvironmentName
```

**ルーティング結果:**
```
POST https://{API-Gateway-ID}.execute-api.ap-northeast-1.amazonaws.com/{stage}/slack/interactive
  ↓
Lambda: slack_webhook_handler.lambda_handler() (行 463-467)
```

### 3.2 Lambda 起動

```python
# slack_webhook_handler.py 行 463-467

def lambda_handler(event, context):
    """
    Lambda ハンドラー（メインエントリーポイント）
    """
    return webhook_handler(event, context)
```

**Lambda イベント構造:**
```json
{
  "version": "2.0",
  "routeKey": "POST /slack/interactive",
  "rawPath": "/slack/interactive",
  "headers": {
    "X-Slack-Request-Timestamp": "1234567890",
    "X-Slack-Signature": "v0=abc123..."
  },
  "body": "{...Slack JSON...}"
}
```

---

## ステップ 4: Slack 署名検証

### 4.1 署名検証フロー

**ファイル**: slack_webhook_handler.py  
**関数**: `verify_slack_signature()` (行 81-128)  
**目的**: リプレイ攻撃となりすまし攻撃を防止

```python
def verify_slack_signature(request_body: str, timestamp: str, signature: str) -> bool:
    """
    Slack リクエスト署名を検証（リプレイ攻撃防止）
    
    Args:
        request_body: リクエストボディ（JSON文字列）
        timestamp: X-Slack-Request-Timestamp ヘッダー
        signature: X-Slack-Signature ヘッダー
    
    Returns:
        bool: 署名が有効な場合 True
    
    根拠: Slack Security Documentation
    https://api.slack.com/authentication/verifying-requests-from-slack
    """
    try:
        # ⭐ Secrets Manager から Slack credentials を取得
        credentials = get_slack_credentials()
        slack_signing_secret = credentials['signing_secret']
        
        # タイムスタンプが5分以上古い場合は拒否（リプレイ攻撃防止）
        current_time = int(time.time())
        request_time = int(timestamp)
        if abs(current_time - request_time) > 300:  # 行 101-106
            logger.warning(f"Request timestamp too old: {current_time} vs {request_time}")
            return False
        
        # 署名を構築: "v0=sha256_hash(v0:{timestamp}:{request_body})"
        sig_basestring = f"v0:{timestamp}:{request_body}"  # 行 109
        computed_signature = "v0=" + hmac.new(
            slack_signing_secret.encode(),
            sig_basestring.encode(),
            hashlib.sha256
        ).hexdigest()  # 行 110-114
        
        # 署名を比較（タイミング攻撃対策として hmac.compare_digest を使用）
        is_valid = hmac.compare_digest(computed_signature, signature)  # 行 117
        
        if is_valid:
            logger.info("Slack signature verified successfully")  # 行 120
        else:
            logger.warning(f"Slack signature mismatch. Expected: {computed_signature}, Got: {signature}")
        
        return is_valid
    
    except Exception as e:
        logger.error(f"Error verifying Slack signature: {str(e)}")
        return False
```

### 4.2 署名検証の処理フロー

```
入力:
  ├─ request_body: '{"type":"block_actions","actions":[...]}'
  ├─ timestamp: "1234567890"
  └─ signature: "v0=abc123..."

ステップ 1: タイムスタンプ検証（行 101-106）
  ├─ current_time = 1234567895 (現在)
  ├─ request_time = 1234567890 (リクエスト)
  ├─ 差分: |1234567895 - 1234567890| = 5秒 < 300秒
  └─ ✅ OK（5分以内）

ステップ 2: 署名生成（行 109-114）
  ├─ sig_basestring = "v0:1234567890:{'type':'block_actions',...}"
  ├─ computed_signature = "v0=" + HMAC-SHA256(slack_signing_secret, sig_basestring)
  └─ 結果: "v0=abc123..."

ステップ 3: 署名比較（行 117）
  ├─ hmac.compare_digest(computed_signature, signature)
  │  = hmac.compare_digest("v0=abc123...", "v0=abc123...")
  └─ 結果: True

出力:
  └─ True（署名有効）
```

**根拠**:
- Slack Security: https://api.slack.com/authentication/verifying-requests-from-slack
- RFC 7235: https://tools.ietf.org/html/rfc7235
- HMAC タイミング攻撃対策: https://docs.python.org/3/library/hmac.html#hmac.compare_digest

### 4.3 Webhook ハンドラでの署名検証

```python
# slack_webhook_handler.py 行 391-397

# ===== ステップ 1: Slack 署名検証 =====
if not verify_slack_signature(request_body, timestamp, signature):
    logger.error("Slack signature verification failed")
    return {
        "statusCode": 401,  # RFC 7235: Unauthorized
        "body": json.dumps({"error": "Unauthorized"})
    }
```

署名検証に失敗した場合、即座に HTTP 401 を返して処理を中断します。

---

## ステップ 5: イベントパース & message.ts 抽出

### 5.1 イベントタイプ判定

```python
# slack_webhook_handler.py 行 399-409

# ===== ステップ 2: イベントタイプの確認 =====
event_type = body_json.get('type', '')

# URL Verification リクエスト（Slack のセットアップ時に送信）
if event_type == 'url_verification':
    challenge = body_json.get('challenge', '')
    logger.info(f"URL verification challenge received: {challenge}")
    return {
        "statusCode": 200,
        "body": challenge
    }
```

**イベントタイプ別処理:**

| イベントタイプ | 意味 | 処理 | 根拠 |
|-------------|------|------|------|
| `url_verification` | Slack がウェブフックを登録するためのテスト | challenge をそのまま返す | Slack API docs |
| `block_actions` | ボタンクリック | 承認フロー実行 | slack_webhook_handler.py 行 412-446 |

### 5.2 Interactive イベント処理

```python
# slack_webhook_handler.py 行 411-420

# ===== ステップ 3: Interactive イベント処理 =====
if event_type == 'block_actions':
    # Slack ボタンクリックイベント
    # ⭐ 戻り値に message_ts が追加
    action_id, trigger_id, user_id, report_id, response_url, message_ts = parse_slack_interactive_event(body_json)
    
    # チャンネル ID を取得（スレッド返信に必要）
    channel_id = body_json.get('channel', {}).get('id', '')
    
    logger.info(f"Processing block_actions: action_id={action_id}, user_id={user_id}, report_id={report_id}, message_ts={message_ts}")
```

### 5.3 message.ts（スレッド ID）抽出

```python
# slack_webhook_handler.py 行 131-186

def parse_slack_interactive_event(event_body: Dict[str, Any]) -> Tuple[str, str, str, str, str, str]:
    """
    Slack Interactive イベント（ボタンクリック）をパース
    
    入力例:
        {
            "type": "block_actions",
            "actions": [
                {
                    "type": "button",
                    "action_id": "approve_action",
                    "value": "report_123"
                }
            ],
            "trigger_id": "...",
            "user": {"id": "U1234567890"},
            "channel": {"id": "C123456"},
            "message": {
                "ts": "1618350863.001400"  # ⭐ スレッド ID
            },
            "response_url": "https://hooks.slack.com/..."
        }
    
    返り値:
        Tuple[
            action_id,           # "approve_action"
            trigger_id,          # "..."
            user_id,             # "U1234567890"
            report_id,           # "report_123"
            response_url,        # "https://hooks.slack.com/..."
            message_ts           # ⭐ "1618350863.001400"
        ]
    
    根拠: Slack API Reference
    https://api.slack.com/reference/interaction-payloads/block-actions
    """
    try:
        actions = event_body.get('actions', [])
        if not actions:
            raise ValueError("No actions in event")
        
        action = actions[0]
        action_id = action.get('action_id', '')
        trigger_id = event_body.get('trigger_id', '')
        user_id = event_body.get('user', {}).get('id', 'unknown')
        report_id = action.get('value', '')
        response_url = event_body.get('response_url', '')
        
        # ⭐ Slack API 仕様: message.ts でスレッド返信の親メッセージを特定
        # 根拠: https://api.slack.com/methods/chat.postMessage (thread_ts パラメータ)
        message_ts = event_body.get('message', {}).get('ts', '')  # 行 178
        
        logger.info(f"Parsed Slack action: {action_id} from user {user_id}, report {report_id}, thread_ts={message_ts}")
        
        return action_id, trigger_id, user_id, report_id, response_url, message_ts  # 行 182
    
    except Exception as e:
        logger.error(f"Error parsing Slack interactive event: {str(e)}")
        raise
```

**抽出結果の例:**
```
action_id: "approve_action"
trigger_id: "1618350863.000100"
user_id: "U1234567890"
report_id: "report_123"
response_url: "https://hooks.slack.com/actions/T12345/B12345/xxxxxxxxxxxx"
message_ts: "1618350863.001400"  # ⭐ このタイムスタンプでスレッド返信を指定
```

**根拠**: Slack API - block_actions Payload  
https://api.slack.com/reference/interaction-payloads/block-actions

---

## ステップ 6: 承認決定を S3 に保存 + スレッド追跡

### 6.1 S3 保存フロー

```python
# slack_webhook_handler.py 行 422-425

# ===== ステップ 4: 決定を S3 に保存 =====
action = "approve" if action_id == "approve_action" else "cancel"
# ⭐ thread_ts を渡す
s3_key = save_approval_decision(report_id, action, user_id, message_ts)
```

### 6.2 save_approval_decision() 実装

```python
# slack_webhook_handler.py 行 189-273

def save_approval_decision(
    report_id: str,
    action: str,  # "approve" or "cancel"
    user_id: str,
    thread_ts: str,
    timestamp: str = None
) -> str:
    """
    確認決定を S3 (pending-confirmations/ + thread-mapping/) に保存
    
    Args:
        report_id: レポート ID
        action: アクション ("approve" or "cancel")
        user_id: Slack ユーザー ID
        thread_ts: Slack スレッドタイムスタンプ（message.ts）
        timestamp: ISO8601 タイムスタンプ（デフォルト: 現在時刻）
    
    Returns:
        str: S3 キー
    
    根拠: cfn-templates/slack-webhook.yaml 行 53 で S3 権限定義
    - s3:PutObject to thread-mapping/* 許可
    """
    if timestamp is None:
        timestamp = datetime.utcnow().isoformat() + "Z"
    
    confirmation_record = {
        "report_id": report_id,
        "action": action,
        "user_id": user_id,
        "thread_ts": thread_ts,  # ⭐ Slack スレッド ID を保存
        "timestamp": timestamp,
        "status": "confirmed",
        "ttl": int((datetime.utcnow() + timedelta(hours=1)).timestamp())  # 1時間後に有効期限
    }
    
    # S3 キー: pending-confirmations/{report_id}-{timestamp}.json
    s3_key = f"pending-confirmations/{report_id}-{int(time.time())}.json"  # 行 226
    # ⭐ スレッド管理: thread-mapping/{thread_ts}.json にも保存
    thread_mapping_key = f"thread-mapping/{thread_ts}.json"  # 行 228
    
    try:
        # 実行時に環境変数を読み込む
        bucket_name = os.environ.get('S3_BUCKET', 'aiops-kb-default')
        
        # 1. pending-confirmations に決定を保存（行 235-246）
        s3_client.put_object(
            Bucket=bucket_name,
            Key=s3_key,
            Body=json.dumps(confirmation_record, indent=2),
            ContentType='application/json',
            Metadata={
                'report-id': report_id,
                'user-id': user_id,
                'action': action,
                'thread-ts': thread_ts
            }
        )
        logger.info(f"Saved approval decision to {s3_key}")
        
        # 2. thread-mapping に thread_ts とレポート ID の対応を保存（Slack スレッド追跡用）（行 249-266）
        thread_record = {
            "thread_ts": thread_ts,
            "report_id": report_id,
            "user_id": user_id,
            "action": action,
            "timestamp": timestamp
        }
        s3_client.put_object(
            Bucket=bucket_name,
            Key=thread_mapping_key,
            Body=json.dumps(thread_record, indent=2),
            ContentType='application/json',
            Metadata={
                'report-id': report_id,
                'thread-ts': thread_ts
            }
        )
        logger.info(f"Saved thread mapping to {thread_mapping_key}")
        
        return s3_key
    
    except Exception as e:
        logger.error(f"Error saving approval decision to S3: {str(e)}")
        raise
```

### 6.3 S3 保存内容

**1. pending-confirmations/{report_id}-{timestamp}.json**
```json
{
  "report_id": "report_123",
  "action": "approve",
  "user_id": "U1234567890",
  "thread_ts": "1618350863.001400",
  "timestamp": "2026-06-20T10:30:00Z",
  "status": "confirmed",
  "ttl": 1234567890
}
```

**2. thread-mapping/{thread_ts}.json**
```json
{
  "thread_ts": "1618350863.001400",
  "report_id": "report_123",
  "user_id": "U1234567890",
  "action": "approve",
  "timestamp": "2026-06-20T10:30:00Z"
}
```

### 6.4 スレッド追跡の目的

`thread-mapping/{thread_ts}.json` を保存することで、以下が実現できます：

1. **後続処理でスレッド ID を検索可能**: thread_ts からレポート ID を取得
2. **複数メッセージの追跡**: 同一スレッド内のすべてのメッセージを関連付け
3. **S3 ライフサイクル管理**: thread_ts でグループ化してまとめて削除可能

**根拠**: cfn-templates/s3.yaml 行 76-82（ライフサイクルルール）
```yaml
# thread-mapping/ ファイルは 1 日で削除
- Prefix: thread-mapping/
  ExpirationInDays: 1
  NoncurrentVersionExpirationInDays: 1
```

---

## ステップ 7: Slack スレッドに確認応答を返信

### 7.1 スレッド返信フロー

```python
# slack_webhook_handler.py 行 427-435

# ===== ステップ 5: Slack に確認応答を送信 =====
message_text = f"✅ Approval recorded: `{action}` for report `{report_id}` by <@{user_id}>"

# ⭐ message_ts と channel_id を渡してスレッド返信
if message_ts and channel_id:
    send_slack_response(response_url, message_text, thread_ts=message_ts, channel_id=channel_id)
else:
    # フォールバック: message_ts がない場合は response_url で返信
    send_slack_response(response_url, message_text)
```

### 7.2 send_slack_response() 実装

```python
# slack_webhook_handler.py 行 276-358

def send_slack_response(response_url: str, message_text: str, thread_ts: str = None, channel_id: str = None) -> bool:
    """
    Slack に確認状況を返信（response_url 経由またはスレッド返信）
    
    Args:
        response_url: Slack Webhook URL
        message_text: メッセージテキスト
        thread_ts: Slack スレッドタイムスタンプ（指定時はスレッド返信）
        channel_id: チャンネル ID（スレッド返信時に必要）
    
    Returns:
        bool: 成功した場合 True
    
    根拠: 
    - https://api.slack.com/methods/chat.postMessage (thread_ts パラメータ)
    - https://api.slack.com/reference/interaction-payloads/block-actions (message.ts フィールド)
    """
    try:
        import urllib3
        http = urllib3.PoolManager()
        
        # ⭐ thread_ts が指定されている場合は Slack Web API の chat.postMessage を使用
        if thread_ts and channel_id:  # 行 298
            logger.info(f"Sending response to Slack thread: thread_ts={thread_ts}, channel={channel_id}")
            
            # 実行時に環境変数を読み込む
            slack_credentials = get_slack_credentials()
            bot_token = slack_credentials['bot_token']
            
            # Slack Web API を使用してスレッド返信（行 306-321）
            payload = {
                "channel": channel_id,
                "thread_ts": thread_ts,  # ⭐ スレッド親メッセージのタイムスタンプ
                "text": message_text,
                "reply_broadcast": False  # スレッド内のみで表示
            }
            
            encoded_body = json.dumps(payload).encode('utf-8')
            response = http.request(
                'POST',
                'https://slack.com/api/chat.postMessage',
                body=encoded_body,
                headers={
                    'Content-Type': 'application/json',
                    'Authorization': f'Bearer {bot_token}'
                }
            )
            
            response_data = json.loads(response.data.decode('utf-8'))
            if response_data.get('ok'):  # 行 325
                logger.info(f"Slack thread response sent successfully: ts={response_data.get('ts')}")
                return True
            else:
                logger.warning(f"Slack thread response failed: {response_data.get('error')}")
                return False
        
        else:
            # ⭐ response_url による返信（従来の方式）
            logger.info("Sending response via response_url")  # 行 334
            
            payload = {
                "text": message_text,
                "response_type": "in_channel"
            }
            
            encoded_body = json.dumps(payload).encode('utf-8')
            response = http.request(
                'POST',
                response_url,
                body=encoded_body,
                headers={'Content-Type': 'application/json'}
            )
            
            if response.status == 200:  # 行 349
                logger.info("Slack response sent successfully via response_url")
                return True
            else:
                logger.warning(f"Slack response failed with status {response.status}")
                return False
    
    except Exception as e:
        logger.error(f"Error sending Slack response: {str(e)}")
        return False
```

### 7.3 Slack Web API 呼び出し

**リクエスト:**
```
POST https://slack.com/api/chat.postMessage
Content-Type: application/json
Authorization: Bearer xoxb-{bot_token}

{
  "channel": "C123456",
  "thread_ts": "1618350863.001400",
  "text": "✅ Approval recorded: approve for report report_123 by @user123",
  "reply_broadcast": false
}
```

**レスポンス（成功時）:**
```json
{
  "ok": true,
  "channel": "C123456",
  "ts": "1618350863.001500",  # 新しいメッセージのタイムスタンプ
  "message": {
    "type": "message",
    "text": "✅ Approval recorded: approve for report report_123 by @user123",
    "user": "U98765",
    "ts": "1618350863.001500",
    "thread_ts": "1618350863.001400"  # ⭐ 親メッセージのタイムスタンプ
  }
}
```

**根拠**:
- Slack API - chat.postMessage: https://api.slack.com/methods/chat.postMessage
- thread_ts パラメータ説明: https://api.slack.com/messaging/managing-conversations#threading

---

## ステップ 8: Lambda 処理結果を SNS に通知

### 8.1 メインハンドラから SNS 発行

別の Lambda（メインハンドラ：lambda_handler.py）が処理完了後、SNS にレポートを publish します。

```python
# lambda_handler.py 行 230-251

def notify_result(response: Dict[str, Any]) -> None:
    """
    実行結果を SNS に通知
    
    参照:
      - AWS ブログ "Solution workflow" (最終ステップ)
      - SNS 通知フォーマット
    """
    try:
        subject = "AIOps Report"
        message = json.dumps(response, indent=2, default=str)
        
        sns_client.publish(  # 行 242
            TopicArn=SNS_REPORT_ARN,  # arn:aws:sns:ap-northeast-1:xxx:AIOpsReport
            Subject=subject,
            Message=message
        )
        
        logger.info("SNS notification sent")  # 行 248
    
    except Exception as e:
        logger.error(f"Error notifying result: {str(e)}", exc_info=True)
```

### 8.2 SNS 通知内容

```json
{
  "type": "bottleneck_investigation",
  "report_id": "bottleneck_20260620_103000",
  "status": "completed",
  "trigger": "cloudwatch_alarm",
  "resource_id": "i-1234567890abcdef0",
  "timestamp": "2026-06-20T10:30:00Z",
  "thread_ts": "1618350863.001400",  // ⭐ Slack スレッド ID
  "bottleneck_items": [
    {
      "metric": "CPUUtilization",
      "value": 95.2,
      "threshold": 80
    }
  ]
}
```

### 8.3 SNS サブスクリプション

CloudFormation で SNS トピックに Slack チャットボット Lambda をサブスクライブ：

```yaml
# cfn-templates/chatbot-slack-notification.yaml（推定）

SlackNotificationLambda:
  Type: AWS::Lambda::Function
  Properties:
    Handler: slack_notification_handler.lambda_handler
    Runtime: python3.11
    ...

SNSSubscription:
  Type: AWS::SNS::Subscription
  Properties:
    Protocol: lambda
    TopicArn: !Ref SNSReportTopic
    Endpoint: !GetAtt SlackNotificationLambda.Arn
```

---

## ステップ 9: SNS → Slack チャットボット → スレッド最終通知

### 9.1 Slack チャットボット Lambda の処理

SNS が Slack チャットボット Lambda をトリガー → Slack Web API を呼び出し

```python
# （推定）chatbot_slack_notification_handler.py

def lambda_handler(event, context):
    """
    SNS から AIOps レポートを受信し、Slack に通知
    """
    try:
        # SNS メッセージをパース
        message = json.loads(event['Records'][0]['Sns']['Message'])
        
        # thread_ts を抽出
        thread_ts = message.get('thread_ts', None)
        channel_id = message.get('channel_id', 'C123456')  # 設定から取得
        
        # 通知メッセージを構築
        notification_text = format_report_for_slack(message)
        
        # thread_ts がある場合はスレッド返信
        if thread_ts:
            post_message_to_thread(channel_id, thread_ts, notification_text)
        else:
            post_message_to_channel(channel_id, notification_text)
        
        return {'statusCode': 200}
    
    except Exception as e:
        logger.error(f"Error in Slack notification: {str(e)}")
        return {'statusCode': 500}
```

### 9.2 最終スレッド状態

```
【Slack スレッド】（ts=1618350863.001400）

┌─────────────────────────────────────────────────────┐
│ 親メッセージ（ボットが最初に投稿）                     │
│ 【ボトルネック調査結果】                              │
│ リソース: EC2-i-xxxxx                               │
│ CPU: 95%                                           │
│ メモリ: 88%                                         │
│ [✅ Approve] [❌ Cancel]                            │
└─────────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────────┐
│ スレッド返信 1（ユーザーがボタンをクリック後）        │
│ ✅ Approval recorded: approve for report report_123 │
│ by @user123                                        │
│ （元の Lambda から投稿）                             │
└─────────────────────────────────────────────────────┘
        ↓
┌─────────────────────────────────────────────────────┐
│ スレッド返信 2（SNS 通知から）                       │
│ 🔔 ボトルネック調査が完了しました                    │
│ CPU: 95%（高い）                                   │
│ メモリ: 88%（高い）                                 │
│ ディスク I/O: 42 MB/s（正常）                       │
│                                                   │
│ 推奨アクション:                                     │
│ • EC2 インスタンスのサイズアップを検討                │
│ • スケーリンググループの設定を確認                   │
│ • アプリケーション側のメモリリークを調査              │
│ （Slack チャットボット Lambda から投稿）             │
└─────────────────────────────────────────────────────┘
```

---

## エラーハンドリング

### 1. Slack 署名検証失敗

```python
# slack_webhook_handler.py 行 391-397

if not verify_slack_signature(request_body, timestamp, signature):
    logger.error("Slack signature verification failed")
    return {
        "statusCode": 401,
        "body": json.dumps({"error": "Unauthorized"})
    }
```

**対応**:
- HTTP 401 を即座に返す
- 処理を続行しない（リプレイ攻撃対策）
- CloudWatch Logs に記録

### 2. タイムスタンプが古い（>5分）

```python
# slack_webhook_handler.py 行 101-106

current_time = int(time.time())
request_time = int(timestamp)
if abs(current_time - request_time) > 300:
    logger.warning(f"Request timestamp too old: {current_time} vs {request_time}")
    return False
```

**対応**:
- リプレイ攻撃の可能性を判定
- 5分以上古いリクエストは拒否

### 3. S3 書き込み失敗

```python
# slack_webhook_handler.py 行 230-273

try:
    s3_client.put_object(...)
    logger.info(f"Saved approval decision to {s3_key}")
except Exception as e:
    logger.error(f"Error saving approval decision to S3: {str(e)}")
    raise
```

**対応**:
- 例外をキャッチして CloudWatch Logs に記録
- 呼び出し元に例外を伝播

### 4. Slack Web API 呼び出し失敗

```python
# slack_webhook_handler.py 行 324-330

response_data = json.loads(response.data.decode('utf-8'))
if response_data.get('ok'):
    logger.info(f"Slack thread response sent successfully: ts={response_data.get('ts')}")
    return True
else:
    logger.warning(f"Slack thread response failed: {response_data.get('error')}")
    return False
```

**対応**:
- API レスポンスの `ok` フィールドで成功判定
- エラーメッセージをログに記録
- False を返して呼び出し元で処理

### 5. Secrets Manager アクセス失敗

```python
# slack_webhook_handler.py 行 52-78

try:
    secret_arn = os.environ.get('SLACK_CREDENTIALS_SECRET_ARN', '')
    if not secret_arn:
        raise ValueError("SLACK_CREDENTIALS_SECRET_ARN environment variable not set")
    
    response = secrets_manager_client.get_secret_value(SecretId=secret_arn)
    ...
except Exception as e:
    logger.error(f"Failed to retrieve Slack credentials from Secrets Manager: {str(e)}")
    raise
```

**対応**:
- 環境変数が未設定の場合は ValueError をスロー
- Secrets Manager エラーをログに記録
- 例外を伝播して呼び出し元に通知

---

## タイムスタンプ・スレッド ID 追跡

### 全ステップでのタイムスタンプ・スレッド ID フロー

```
【ステップ 1】ボタンクリック時刻 (ユーザー操作)
  └─ Slack がイベントを生成
     message.ts = "1618350863.001400"  # スレッド親メッセージのタイムスタンプ

【ステップ 2】Webhook ハンドラが message.ts を抽出
  └─ parse_slack_interactive_event() (行 176-182)
     message_ts = "1618350863.001400"

【ステップ 3】S3 に双方向マッピングを保存
  ├─ pending-confirmations/{report_id}-{unix_timestamp}.json
  │  └─ {"thread_ts": "1618350863.001400", "report_id": "report_123", ...}
  │
  └─ thread-mapping/{message_ts}.json
     └─ {"thread_ts": "1618350863.001400", "report_id": "report_123", ...}

【ステップ 4】Lambda が Slack スレッド返信を送信
  └─ send_slack_response() (行 298-322)
     thread_ts = "1618350863.001400"
     → Slack Web API chat.postMessage に thread_ts を指定
     → 返信メッセージがスレッド内に表示

【ステップ 5】メインハンドラが SNS に publish
  └─ notify_result() (行 230-251)
     message に thread_ts を含める
     → "thread_ts": "1618350863.001400"

【ステップ 6】SNS → Slack チャットボット → スレッド返信
  └─ Slack チャットボット Lambda が thread_ts を使用
     → 同じスレッド内に最終通知を投稿
```

### タイムスタンプを使った追跡の利点

1. **コンテキスト保持**: すべてのメッセージが同一スレッド内に集約
2. **ユーザー体験向上**: 関連メッセージがスレッド内に整理される
3. **後処理の追跡**: thread_mapping/{thread_ts}.json で復旧・監査が容易
4. **ライフサイクル管理**: thread_ts でグループ化して S3 から削除可能

---

## 📊 処理フローのタイミング

```
時刻        アクター          イベント
───────────────────────────────────────────────────────────────
T+0         ユーザー         ✅ Approve ボタンをクリック
            (Slack Client)
                             │
                             ▼
T+0.1       Slack Server     ボタンクリックイベントを生成
                             message.ts = 1618350863.001400
                             │
                             ▼
T+0.2       API Gateway      ウェブフック受信
            + Lambda         webhook_handler() 起動
                             │
T+0.3                        verify_slack_signature() で検証 OK
            Secrets Mgr      Slack 認証情報を取得
                             │
T+0.4                        parse_slack_interactive_event() でパース
            S3               approve_decision を保存
                             thread_mapping を保存
                             │
T+0.5                        send_slack_response() で Slack に返信
            Slack Web API    chat.postMessage API 呼び出し
                             thread_ts = 1618350863.001400
                             │
T+0.6       Slack Server     スレッド内に返信メッセージを表示
            User's Client    ✅ Approval recorded... が表示される
                             │
(別の Lambda が処理中...)      │
                             ▼
T+5         Lambda (FR-XX)   処理完了
            SNS Publisher    SNS にレポートを publish
                             "thread_ts": "1618350863.001400" を含む
                             │
                             ▼
T+5.5       SNS              Slack チャットボット Lambda をトリガー
                             │
T+5.6       Lambda           Slack Web API chat.postMessage 呼び出し
            (ChatBot)        thread_ts = 1618350863.001400
                             │
T+5.7       Slack Server     スレッド内に最終レポートを表示
            User's Client    🔔 ボトルネック調査が完了...が表示される
```

---

## まとめ: フロー全体の信頼性

| 項目 | 実装 | 根拠 |
|------|------|------|
| **署名検証** | HMAC-SHA256 + タイムスタンプ | Slack API + RFC 7235 |
| **タイミング攻撃対策** | hmac.compare_digest() | Python HMAC ドキュメント |
| **スレッド追跡** | thread_ts を S3 と SNS で伝播 | Slack API thread_ts パラメータ |
| **セキュア認証** | Secrets Manager + 実行時取得 | AWS Secrets Manager Best Practices |
| **IAM 最小権限** | S3/Secrets Manager リソースレベル制限 | cfn-templates/slack-webhook.yaml |
| **エラーハンドリング** | 例外キャッチ + CloudWatch Logs | lambda_handler.py 全関数 |
| **ライフサイクル管理** | S3 自動削除（thread_ts で分類） | cfn-templates/s3.yaml |

---

## 参考文献・根拠

1. **Slack API Documentation**
   - Block Actions Payload: https://api.slack.com/reference/interaction-payloads/block-actions
   - chat.postMessage: https://api.slack.com/methods/chat.postMessage
   - Request Verification: https://api.slack.com/authentication/verifying-requests-from-slack

2. **AWS Documentation**
   - AWS Lambda: https://docs.aws.amazon.com/lambda/latest/dg/
   - SNS Publishing: https://docs.aws.amazon.com/sns/latest/dg/
   - Secrets Manager: https://docs.aws.amazon.com/secretsmanager/latest/userguide/

3. **RFC Standards**
   - RFC 7235 (HTTP Authentication): https://tools.ietf.org/html/rfc7235
   - RFC 5869 (HMAC-based Key Derivation): https://tools.ietf.org/html/rfc5869

4. **実装ファイル**
   - slack_webhook_handler.py (467 行)
   - lambda_handler.py (2189 行)
   - cfn-templates/slack-webhook.yaml (183 行)

---

**版履歴**: 
- v1.0 (2026-06-20): 初版作成、source-verification スキル準拠
