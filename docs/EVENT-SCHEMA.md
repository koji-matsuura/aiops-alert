# イベント形式仕様

**対象**: Lambda ハンドラが受け取る AWS 公式イベント構造の仕様

---

## 📋 概要

すべてのトリガー（CloudWatch Alarms、EventBridge Scheduled Events）が AWS 公式イベント形式で Lambda に渡されます。

Lambda は `extract_event_info()` 関数を使用して、AWS 公式フィールドから必要な情報を抽出し、統一されたデータ構造に変換します。

---

## 🎯 統一されたイベント情報構造

Lambda 内部で使用される統一形式：

```python
{
    "source": str,              # "aws.cloudwatch" または "aws.events"
    "detail_type": str,         # イベント種別
    "detail": dict,             # イベント詳細（構造はイベント種別により異なる）
    "time": str,                # ISO 8601 形式のタイムスタンプ
    "raw_event": dict           # 元の AWS イベントオブジェクト
}
```

---

## 📊 CloudWatch Alarms イベント形式

### AWS 公式フィールド

**EventBridge が CloudWatch Alarms の状態変化を検出したとき：**

```json
{
    "version": "0",
    "id": "cdc73f9d-aea0-11e3-9d5a-835b769c0d9c",
    "detail-type": "CloudWatch Alarm State Change",
    "source": "aws.cloudwatch",
    "account": "123456789012",
    "time": "2026-06-08T10:30:00Z",
    "region": "ap-northeast-1",
    "resources": [
        "arn:aws:cloudwatch:ap-northeast-1:123456789012:alarm:EC2-HighCPU-i-xxxxx"
    ],
    "detail": {
        "alarmName": "EC2-HighCPU-i-xxxxx",
        "state": {
            "value": "ALARM",
            "reasonData": "...",
            "timestamp": "2026-06-08T10:30:00Z"
        },
        "previousState": {
            "value": "OK",
            "reasonData": "...",
            "timestamp": "2026-06-08T09:00:00Z"
        },
        "alarmDescription": "EC2 instance CPU utilization > 80%",
        "alarmArn": "arn:aws:cloudwatch:ap-northeast-1:123456789012:alarm:EC2-HighCPU-i-xxxxx"
    }
}
```

### Lambda による抽出

```python
event_info = extract_event_info(event)
# 返り値:
# {
#     "source": "aws.cloudwatch",
#     "detail_type": "CloudWatch Alarm State Change",
#     "detail": {
#         "alarmName": "EC2-HighCPU-i-xxxxx",
#         "state": {"value": "ALARM", ...},
#         "alarmDescription": "EC2 instance CPU utilization > 80%",
#         ...
#     },
#     "time": "2026-06-08T10:30:00Z",
#     "raw_event": {...}
# }
```

### アラーム種別の判定方法

EventBridge ルールのパターン定義で事前に絞り込まれます：

```yaml
EventPattern:
  source:
    - aws.cloudwatch
  detail-type:
    - CloudWatch Alarm State Change
  detail:
    alarmName:
      - prefix: EC2-HighCPU          # EC2 高 CPU
      - prefix: RDS-HighCPU          # RDS 高 CPU
      - prefix: RDS-HighConnections  # RDS 接続数
      - prefix: RDS-ReplicationLag   # RDS レプリケーション遅延
      - prefix: Lambda-ErrorRate     # Lambda エラー率
      - prefix: Lambda-Throttle      # Lambda スロットル
```

**重要**: Lambda は `source="aws.cloudwatch"` と `detail-type="CloudWatch Alarm State Change"` で判定します。

---

## 🗓️ EventBridge Scheduled Event 形式

### AWS 公式フィールド

**EventBridge Schedule が実行されたとき：**

```json
{
    "version": "0",
    "id": "cdc73f9d-aea0-11e3-9d5a-835b769c0d9c",
    "detail-type": "Scheduled Event",
    "source": "aws.events",
    "account": "123456789012",
    "time": "2026-06-08T00:00:00Z",
    "region": "ap-northeast-1",
    "resources": [
        "arn:aws:events:ap-northeast-1:123456789012:rule/dev-aiops-scheduled-maintenance"
    ],
    "detail": {}
}
```

### Lambda による抽出

```python
event_info = extract_event_info(event)
# 返り値:
# {
#     "source": "aws.events",
#     "detail_type": "Scheduled Event",
#     "detail": {},
#     "time": "2026-06-08T00:00:00Z",
#     "raw_event": {...}
# }
```

### 判定方法

Lambda は `source="aws.events"` と `detail-type="Scheduled Event"` で判定します。

---

## 🔍 Lambda 抽出関数の実装

### `extract_event_info(event)` の実装

```python
def extract_event_info(event: Dict[str, Any]) -> Dict[str, Any]:
    """
    AWS 公式イベント構造から情報を抽出
    
    すべてのトリガーが以下の共通フィールドを含みます:
    - source: イベントソース ("aws.cloudwatch", "aws.events")
    - detail-type: イベント種別
    - detail: イベント詳細
    - time: タイムスタンプ
    """
    return {
        "source": event.get("source", "unknown"),
        "detail_type": event.get("detail-type", "unknown"),
        "detail": event.get("detail", {}),
        "time": event.get("time", datetime.utcnow().isoformat()),
        "raw_event": event
    }
```

### `build_prompt(event_info)` の実装

```python
def build_prompt(event_info: Dict[str, Any]) -> str:
    """
    Bedrock Agent への統一 prompt を構築
    
    Bedrock Agent が以下を判定します:
    1. このアラームに対応すべきか
    2. 定期メンテナンスを実行すべきか
    3. 実行対象 Lambda (FR-01~FR-06) は何か
    """
    prompt = f"""
【イベント受信】

イベントソース: {event_info['source']}
イベント種別: {event_info['detail_type']}
タイムスタンプ: {event_info['time']}
イベント詳細:
{json.dumps(event_info['detail'], indent=2, ensure_ascii=False)}

このイベントについて:
1. Knowledge Base から関連ランブックを検索してください
2. 状況を分析してください
3. 必要なアクション（調査、対応、メンテナンス実行など）を判定してください
4. 実行結果をまとめて報告してください

ランブック検索のヒント:
- CloudWatch アラーム: EC2, RDS, Lambda, CloudWatch などの運用手順
- 定期メンテナンス: スロークエリ検出、高負荷クエリ分析、パフォーマンス改善
"""
    
    return prompt
```

---

## ✅ 重要なポイント

### 1. カスタムフィールドは使用しない

❌ **使用しないフィールド**（InputTransformer で生成されていた）：
```json
{
    "trigger": "alarm",           # ← 削除
    "alarmName": "...",           # ← AWS フィールドから抽出
    "customField": "value"        # ← 削除
}
```

✅ **使用するフィールド**（AWS 公式）：
```json
{
    "source": "aws.cloudwatch",         # AWS 公式
    "detail-type": "...",               # AWS 公式
    "detail": {"alarmName": "...", ...} # AWS 公式
    "time": "..."                       # AWS 公式
}
```

### 2. Lambda が AWS イベント構造を理解する

Lambda は AWS 公式イベント形式を理解し、必要な情報を抽出します：

- `event.get("source")` → `"aws.cloudwatch"` or `"aws.events"`
- `event.get("detail-type")` → `"CloudWatch Alarm State Change"` or `"Scheduled Event"`
- `event.get("detail")` → アラーム詳細またはスケジュール詳細
- `event.get("time")` → ISO 8601 形式のタイムスタンプ

### 3. Bedrock Agent が判定する

Lambda は単に「情報を抽出して prompt を作る」だけで、**何をすべきかは Bedrock Agent が判定します**：

```
Lambda: 「ここに CloudWatch Alarms イベントがあります。」
Bedrock Agent: 「このアラームから判断して、以下を実行すべき...」
```

---

## 📝 テストケース

### CloudWatch Alarms イベントのテスト

```python
def test_extract_cloudwatch_alarm_event():
    from lambda_handler import extract_event_info

    event = {
        "source": "aws.cloudwatch",
        "detail-type": "CloudWatch Alarm State Change",
        "detail": {"alarmName": "EC2-HighCPU-i-12345"},
        "time": "2026-06-08T10:30:00Z"
    }

    result = extract_event_info(event)
    
    assert result["source"] == "aws.cloudwatch"
    assert result["detail_type"] == "CloudWatch Alarm State Change"
    assert result["detail"]["alarmName"] == "EC2-HighCPU-i-12345"
```

### Scheduled Event のテスト

```python
def test_extract_scheduled_event():
    from lambda_handler import extract_event_info

    event = {
        "source": "aws.events",
        "detail-type": "Scheduled Event",
        "detail": {},
        "time": "2026-06-08T00:00:00Z"
    }

    result = extract_event_info(event)
    
    assert result["source"] == "aws.events"
    assert result["detail_type"] == "Scheduled Event"
```

---

## 🔗 関連ドキュメント

- `AGENTS.md` セクション 0: トリガーパターン説明
- `lib/lambda_handler.py`: `extract_event_info()`, `build_prompt()` の実装
- `tests/test_lambda_handler.py`: テストケース

---

**最終更新**: 2026-06-08  
**設計意図**: AWS 公式イベント形式を使用し、シンプルで透明な設計を実現する
