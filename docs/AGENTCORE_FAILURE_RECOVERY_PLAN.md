# AgentCore 移行失敗シナリオと復帰戦略【完全版】

**作成日**: 2026年6月24日  
**対象**: aiops-alert プロジェクト (v2.8.0 → AgentCore 移行)  
**目的**: 移行プロセス中の10以上の技術リスク、プロセスリスク、本番リスクに対する包括的な対応戦略

---

## 📋 目次
1. [リスク評価マトリックス](#リスク評価マトリックス)
2. [技術リスク詳細分析](#技術リスク詳細分析)
3. [プロセスリスク](#プロセスリスク)
4. [本番リスク](#本番リスク)
5. [復帰戦略](#復帰戦略)
6. [予防策・テスト戦略](#予防策テスト戦略)
7. [段階的フェーズ実行計画](#段階的フェーズ実行計画)

---

## リスク評価マトリックス

```
リスク評価：確度（Likelihood）× 影響度（Impact）

          高影響 (Critical)  │ 中影響 (High)      │ 低影響 (Low)
高確度    CR-01,CR-04        │ HR-03,HR-05,HR-08 │ LR-02
          CR-02,CR-06        │ HR-07,HR-09       │
          CR-10              │ HR-11             │
          ─────────────────────────────────────────────────────
中確度    MR-01              │ MR-02,MR-03       │ MR-04,MR-05
          MR-06              │                   │
          ─────────────────────────────────────────────────────
低確度    LR-03              │ LR-04             │ LR-05,LR-06
          LR-07              │ LR-08             │
```

### リスク凡例
- **CR**: Critical Risk（復帰時間 30分以上、ユーザー影響大）
- **HR**: High Risk（復帰時間 15～30分、ユーザー影響中）
- **MR**: Medium Risk（復帰時間 5～15分、ユーザー影響小）
- **LR**: Low Risk（復帰時間 <5分、ユーザー影響極小）

---

## 技術リスク詳細分析

### **🔴 CR-01: Bedrock ⇔ AgentCore 互換性不足**

**リスク ID**: CR-01  
**確度**: 高（70%）  
**影響度**: 極大（100%のリクエスト失敗）  
**復帰時間**: 45～60分

#### 原因
- Bedrock Agent の messageVersion 1.0 API 互換性が AgentCore で変更
- Action Group の Tool Definition フォーマット差異
- Session State 管理方式の非互換性
- invocation format の差異

#### 症状
```
ERROR: ClientError - Invalid invoke request format
ERROR: ToolSchema validation failed
ERROR: Unexpected response format from AgentCore
503 Service Unavailable (Bedrock API)
```

#### 検出方法
```bash
# 監視項目
1. Lambda 実行ログで以下のパターン検出
   - "ToolSchema validation failed"
   - "Unexpected message format version"
   - "AgentCore API response parsing error"

2. CloudWatch メトリクス
   - Lambda Duration が通常の 3倍以上（>5秒）
   - Lambda Error Rate > 50%

3. X-Ray トレース
   - bedrock-agent-runtime.invoke*() の呼び出し失敗
   - Tool invocation で400/403エラー
```

#### 復帰手順
**Step 1: 影響範囲の特定（2分）**
```bash
# CloudWatch Logs Insights クエリ
fields @timestamp, @message, @duration, error_type
| filter ispresent(error_type)
| stats count() by error_type
| sort count() desc

# 結果例
ToolSchema validation failed: 234件（過去15分）
AgentCore API response parsing: 156件
```

**Step 2: 互換性マッピング検証（10分）**
```python
# スクリプト: verify_agentcore_compatibility.py
import json
import boto3

bedrock = boto3.client('bedrock-agents-runtime')

# 既存 messageVersion 1.0 リクエスト
legacy_request = {
    "actionGroup": "AIOpsActionGroup",
    "function": "LogInvestigation",
    "parameters": [
        {"name": "log_group_name", "value": "/aws/lambda/aiops"},
        {"name": "log_stream_name", "value": "2026-06-24"},
    ]
}

# AgentCore 互換形式に変換
agentcore_request = {
    "tool": {
        "toolUseId": "tool-001",
        "toolName": "LogInvestigation",
        "toolInput": {
            "log_group_name": "/aws/lambda/aiops",
            "log_stream_name": "2026-06-24",
        }
    }
}

# 互換性チェック
try:
    # 1. Tool Definition 検証
    validate_tool_definition(agentcore_request['tool'])
    # 2. Input schema 検証
    validate_input_schema(agentcore_request['tool']['toolInput'])
    # 3. Response format 検証
    validate_response_format()
    print("✅ Compatibility check PASSED")
except Exception as e:
    print(f"❌ Compatibility issue detected: {e}")
    return {"action": "ROLLBACK"}
```

**Step 3: 即座のロールバック（5分）**
```bash
# Lambda コード を旧版に戻す
cd ~/aiops-alert
git log --oneline | grep "AgentCore migration" | head -1
# 出力例: a1b2c3d AgentCore migration - initial commit

# ロールバック
git revert a1b2c3d --no-edit
git push origin main

# CodePipeline が自動トリガーして Lambda を再デプロイ
# 確認（最大 3分待機）
aws lambda get-function --function-name aiops-lambda \
  --query 'Configuration.LastModified'
```

**Step 4: 互換性レイヤー導入（20分）**
```python
# lib/agentcore_compatibility_layer.py
class AgentCoreCompatibility:
    """Bedrock Agent 1.0 <-> AgentCore 間の互換性層"""
    
    @staticmethod
    def convert_request_to_agentcore(legacy_request: dict) -> dict:
        """messageVersion 1.0 → AgentCore Tool Spec"""
        return {
            "tool": {
                "toolUseId": legacy_request.get("invocationId", "default"),
                "toolName": legacy_request.get("function"),
                "toolInput": {
                    param["name"]: param["value"]
                    for param in legacy_request.get("parameters", [])
                }
            }
        }
    
    @staticmethod
    def convert_response_to_bedrock(agentcore_response: dict) -> dict:
        """AgentCore response → messageVersion 1.0 format"""
        return {
            "responseBody": {
                "TEXT": {
                    "body": agentcore_response.get("toolResult", {}).get("content", [{}])[0].get("text", "")
                }
            },
            "actionGroupInvocationCount": 1
        }

# lib/lambda_handler.py で使用
from agentcore_compatibility_layer import AgentCoreCompatibility

def handle_bedrock_agent_message(event, context):
    """AgentCore メッセージ処理"""
    
    # AgentCore → Bedrock 1.0 形式に変換
    legacy_event = AgentCoreCompatibility.convert_request_to_agentcore(event)
    
    # 既存の処理を実行
    result = process_legacy_format(legacy_event)
    
    # Bedrock 1.0 → AgentCore 形式に変換
    agentcore_response = AgentCoreCompatibility.convert_response_to_bedrock(result)
    
    return agentcore_response
```

**Step 5: 監視強化（継続）**
```python
# CloudWatch Alarms 設定
import boto3

cloudwatch = boto3.client('cloudwatch')

cloudwatch.put_metric_alarm(
    AlarmName='AgentCore-API-Error-Rate',
    MetricName='Errors',
    Namespace='AWS/Lambda',
    Statistic='Sum',
    Period=60,
    EvaluationPeriods=2,
    Threshold=10,
    ComparisonOperator='GreaterThanThreshold',
    AlarmActions=['arn:aws:sns:ap-northeast-1:123456789012:CriticalAlerts']
)
```

**復帰判定基準**
- ✅ Lambda Error Rate が 5% 以下に低下
- ✅ Tool invocation 成功率 > 95%
- ✅ 互換性レイヤーが 500+ リクエストを正常処理

---

### **🔴 CR-02: Knowledge Base ベクトル化失敗**

**リスク ID**: CR-02  
**確度**: 高（60%）  
**影響度**: 極大（RAG 完全不可）  
**復帰時間**: 30～45分

#### 原因
- OpenSearch Serverless のインデックススキーマ変更
- Embedding Model（Titan v2）の出力次元数差異（1024D → 1536D など）
- Vector Field のマッピング エラー
- Ingestion Job のタイムアウト

#### 症状
```
ERROR: Ingestion job failed: NL1JQROICX
ERROR: Vector dimension mismatch - expected 1024, got 1536
ERROR: Index mapping conflict
⚠️ RAG クエリの空結果（検索精度 0%）
⚠️ Agent が「ランブック情報が見つかりません」を繰り返す
```

#### 検出方法
```bash
# 1. Bedrock Knowledge Base 状態確認
aws bedrock-agent describe-knowledge-base \
  --knowledge-base-id OQZNQIPJTS \
  --query 'knowledgeBase.status'

# 結果: FAILED, INGESTION_IN_PROGRESS

# 2. 最新 Ingestion Job 状態確認
aws bedrock-agent list-ingestion-jobs \
  --knowledge-base-id OQZNQIPJTS \
  --data-source-id 9TZ9MCQRGH \
  --sort-by UPDATE_TIME \
  --query 'ingestionJobSummaries[0]'

# 結果例
{
  "ingestionJobId": "NL1JQROICX",
  "status": "FAILED",
  "failureReasons": ["Vector field dimension mismatch"]
}

# 3. OpenSearch インデックス状態確認
aws opensearch-serverless batch-get-collection \
  --names aiops-kb-index \
  --query 'collectionDetails[0]'

# 4. CloudWatch Logs から詳細エラー検出
aws logs filter-log-events \
  --log-group-name '/aws/bedrock/knowledgebase' \
  --start-time $(date -d '15 minutes ago' +%s)000 \
  --filter-pattern 'vector' \
  --query 'events[0:5]'
```

#### 復帰手順
**Step 1: ベクトル化の再実行（5分）**
```bash
# 既存の失敗した Ingestion Job を確認
INGESTION_JOB_ID="NL1JQROICX"

# ドキュメントを再度 ingest（同じドキュメント ID で上書き）
aws bedrock-agent ingest-knowledge-base-documents \
  --knowledge-base-id OQZNQIPJTS \
  --data-source-id 9TZ9MCQRGH \
  --documents '[
    {
      "content": {
        "dataSourceType": "S3",
        "s3": {
          "uri": "s3://aiops-kb-000000000000-ap-northeast-1-dev/runbooks/FR-01-log-investigation.md"
        }
      }
    }
  ]'

# 出力例
{
  "ingestionJobId": "NL1JQROICX_RETRY_001"
}
```

**Step 2: ベクトル次元の修正（15分）**
```python
# スクリプト: fix_vector_dimensions.py
import boto3
import json

opensearch = boto3.client('opensearchserverless')
bedrock_agent = boto3.client('bedrock-agent')

# 1. 現在のインデックス情報取得
index_info = opensearch.describe_indexes(
    collectionName='aiops-kb-index'
)

# 2. vector_field のマッピング確認
vector_field_mapping = index_info['indexSummaries'][0]['mapping']
print("Current vector field mapping:", json.dumps(vector_field_mapping, indent=2))

# 3. Embedding Model の出力次元を確認
kb_config = bedrock_agent.describe_knowledge_base(
    knowledgeBaseId='OQZNQIPJTS'
)

embedding_model = kb_config['knowledgeBase']['knowledgeBaseConfiguration']['vectorKnowledgeBaseConfiguration']['embeddingModelArn']
# arn:aws:bedrock:ap-northeast-1::foundation-model/amazon.titan-embed-text-v2:0

# 4. モデルのスペック確認（1536次元確認）
print(f"Embedding model: {embedding_model}")
print(f"Expected dimension: 1536 (Titan v2)")

# 5. インデックスマッピングを 1536次元に修正
new_mapping = {
    "properties": {
        "vector_field": {
            "type": "knn_vector",
            "dimension": 1536,  # 1024 → 1536
            "method": {
                "name": "hnsw",
                "space_type": "cosinesimil",
                "engine": "nmslib",
                "parameters": {
                    "ef_construction": 512,
                    "m": 16
                }
            }
        },
        "text_field": {
            "type": "text"
        },
        "metadata_field": {
            "type": "keyword"
        }
    }
}

# 6. インデックス再作成（ダウンタイム必須）
print("⚠️ インデックス再作成を実行します（2～5分の KnowledgeBase ダウンタイム発生）")

# インデックスをクローズ
opensearch.update_collection(
    name='aiops-kb-index',
    action='CloseCollection'
)
time.sleep(30)

# インデックス削除
opensearch.delete_collection(
    name='aiops-kb-index'
)
time.sleep(60)

# インデックス再作成
opensearch.create_collection(
    name='aiops-kb-index',
    type='SEARCH',
    vectorSearchConfiguration={
        'dimension': 1536
    }
)

print("✅ インデックス再作成完了")

# 7. ドキュメント再インジェスト
print("ドキュメントを再度インジェストしています...")
ingest_documents_all()

print("✅ ベクトル化修正完了")
```

**Step 3: Ingestion Job モニタリング（30分間）**
```bash
#!/bin/bash
# monitor_ingestion.sh

KB_ID="OQZNQIPJTS"
DS_ID="9TZ9MCQRGH"
MAX_WAIT=1800  # 30分

for i in {1..60}; do
  STATUS=$(aws bedrock-agent list-ingestion-jobs \
    --knowledge-base-id $KB_ID \
    --data-source-id $DS_ID \
    --sort-by UPDATE_TIME \
    --query 'ingestionJobSummaries[0].status' \
    --output text)
  
  echo "[$(date)] Ingestion Status: $STATUS"
  
  if [ "$STATUS" == "COMPLETE" ]; then
    echo "✅ Ingestion COMPLETE!"
    exit 0
  elif [ "$STATUS" == "FAILED" ]; then
    echo "❌ Ingestion FAILED"
    # 失敗の詳細を取得
    aws bedrock-agent list-ingestion-jobs \
      --knowledge-base-id $KB_ID \
      --data-source-id $DS_ID \
      --query 'ingestionJobSummaries[0]'
    exit 1
  fi
  
  sleep 30  # 30秒ごとにポーリング
done

echo "❌ Ingestion timeout (30分超過)"
exit 1
```

**Step 4: RAG 検索テスト（5分）**
```python
# verify_rag_recovery.py
import boto3
import json

bedrock_agent = boto3.client('bedrock-agent-runtime')

test_queries = [
    "EC2 の CPU が高い場合の調査手順",
    "RDS のスロークエリ検出方法",
    "ログファイルの確認方法"
]

for query in test_queries:
    print(f"\n🔍 テストクエリ: {query}")
    
    response = bedrock_agent.retrieve_and_generate(
        input={"text": query},
        knowledgeBaseId="OQZNQIPJTS",
        modelArn="arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0",
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": 3,
                "overrideSearchType": "SEMANTIC"
            }
        }
    )
    
    # 検索結果を評価
    retrieved_references = response['output']['text']
    
    if len(retrieved_references) > 0:
        print(f"✅ 検索成功: {len(retrieved_references)} 件のドキュメント取得")
        for ref in retrieved_references[:1]:
            print(f"  - {ref['source']}")
    else:
        print("❌ 検索失敗: ドキュメントが見つかりません")
        raise Exception("RAG recovery FAILED")

print("\n✅ RAG recovery 完了")
```

**復帰判定基準**
- ✅ Ingestion Job status = COMPLETE
- ✅ Knowledge Base status = ACTIVE
- ✅ RAG 検索結果件数 > 0（全テストクエリ）
- ✅ 検索精度 > 70%（マニュアルレビュー）

---

### **🔴 CR-04: Lambda ハンドラ移行バグ - messageVersion 解析エラー**

**リスク ID**: CR-04  
**確度**: 高（75%）  
**影響度**: 極大（全 Action Group 呼び出し失敗）  
**復帰時間**: 20～30分

#### 原因
- messageVersion 1.0 → AgentCore 形式への変換ロジックバグ
- Tool parameter の名前マッピング誤り
- Response format の不正な変換
- Session ID/State の管理エラー

#### 症状
```
ERROR: KeyError: 'messageVersion' (line 67 of lambda_handler.py)
ERROR: Tool parameters mismatch - expected ['log_group_name', 'log_stream_name'], got ['param_0', 'param_1']
ERROR: Response format validation failed
⚠️ Agent が Tool 呼び出し後フリーズ（60秒タイムアウト）
⚠️ "申し訳ございません。処理に失敗しました" というエラーメッセージを繰り返す
```

#### 検出方法
```bash
# 1. Lambda ログからの即座の検出
aws logs tail /aws/lambda/aiops-lambda \
  --follow \
  --since 1m \
  --filter-pattern 'ERROR'

# 出力
2026-06-24T10:30:45.123Z e1b2c3d4-e5f6-7a8b-9c0d-e1f2g3h4i5j6 ERROR  KeyError: 'messageVersion'
Traceback (most recent call last):
  File "/var/task/lambda_function.py", line 67, in handler
    if isinstance(event, dict) and event.get('messageVersion') == '1.0':
  File "/var/task/lambda_handler.py", line 543, in handle_bedrock_agent_message
    params = event['parameters']  # ❌ KeyError
KeyError: 'parameters'

# 2. CloudWatch メトリクスの異常検出
aws cloudwatch get-metric-statistics \
  --namespace AWS/Lambda \
  --metric-name Errors \
  --dimensions Name=FunctionName,Value=aiops-lambda \
  --start-time $(date -d '15 min ago' -Iseconds) \
  --end-time $(date -Iseconds) \
  --period 60 \
  --statistics Sum \
  --output json | jq '.Datapoints | sort_by(.Timestamp) | .[]'

# 出力
{
  "Timestamp": "2026-06-24T10:30:00Z",
  "Sum": 142  # 通常: <10, 異常: >50
}

# 3. X-Ray トレース分析
aws xray get-trace-summaries \
  --start-time $(date -d '15 min ago' -Iseconds) \
  --end-time $(date -Iseconds) \
  --query 'TraceSummaries[?Status==`false`]' \
  --max-items 10

# 出力
[
  {
    "Id": "1-66b9a4ac-a1b2c3d4e5f6g7h8i9j0k",
    "Duration": 61.234,
    "HasError": true,
    "HasFault": true,
    "Http": {
      "Status": 500
    }
  }
]
```

#### 復帰手順
**Step 1: エラー内容の特定（3分）**
```bash
# 直近のエラーメッセージを全件取得
aws logs filter-log-events \
  --log-group-name /aws/lambda/aiops-lambda \
  --start-time $(date -d '15 min ago' +%s)000 \
  --filter-pattern 'ERROR' \
  --query 'events[*].message' \
  --output text > /tmp/error_log.txt

# 集計
cat /tmp/error_log.txt | grep -o "KeyError\|TypeError\|ValueError" | sort | uniq -c | sort -rn
```

**Step 2: 互換性層の即座のフィックス（5分）**
```python
# lib/lambda_handler.py の修正

# ❌ 修正前（バグあり）
def handle_bedrock_agent_message(event, context):
    try:
        function_name = event['function']
        parameters = event['parameters']  # ❌ KeyError発生の原因
        # ...
    except KeyError as e:
        logger.error(f"Parameter missing: {e}")

# ✅ 修正後（修正版）
def handle_bedrock_agent_message(event, context):
    """AgentCore messageVersion 1.0 ハンドラ - 改良版"""
    
    try:
        # messageVersion 確認（デフォルト1.0を想定）
        msg_version = event.get('messageVersion', '1.0')
        logger.info(f"Processing messageVersion: {msg_version}")
        
        # Event タイプを判定
        invocation_id = event.get('invocationId', 'unknown')
        action_group = event.get('actionGroup', 'unknown')
        function_name = event.get('function', '')
        
        # Parameters を正確に抽出（複数形式に対応）
        parameters = _extract_parameters_safely(event)
        
        logger.info(f"Function: {function_name}, Parameters: {parameters}")
        
        # Function dispatcher
        result = dispatch_function(function_name, parameters, context)
        
        # Response を messageVersion 1.0 形式で返す
        response = {
            "invocationId": invocation_id,
            "actionGroup": action_group,
            "function": function_name,
            "responseBody": {
                "TEXT": {
                    "body": json.dumps(result)
                }
            }
        }
        
        logger.info(f"Response: {response}")
        return response
        
    except Exception as e:
        logger.error(f"Error in handle_bedrock_agent_message: {str(e)}", exc_info=True)
        return {
            "invocationId": event.get('invocationId', 'unknown'),
            "actionGroup": event.get('actionGroup', 'unknown'),
            "function": event.get('function', 'unknown'),
            "responseBody": {
                "TEXT": {
                    "body": json.dumps({
                        "error": str(e),
                        "status": "FAILED"
                    })
                }
            }
        }

def _extract_parameters_safely(event: dict) -> dict:
    """Parameters を複数形式から安全に抽出"""
    
    # 形式1: parameters が array of objects の場合
    if 'parameters' in event and isinstance(event['parameters'], list):
        params_dict = {}
        for param in event['parameters']:
            if isinstance(param, dict) and 'name' in param and 'value' in param:
                params_dict[param['name']] = param['value']
        if params_dict:
            return params_dict
    
    # 形式2: parameters が直接 dict の場合（AgentCore）
    if 'parameters' in event and isinstance(event['parameters'], dict):
        return event['parameters']
    
    # 形式3: tool.toolInput の場合
    if 'tool' in event and 'toolInput' in event['tool']:
        return event['tool']['toolInput']
    
    # 形式4: その他のキーから推測
    result = {}
    for key in ['log_group_name', 'log_stream_name', 'resource_id', 'resource_type',
                'db_instance_id', 'snapshot_identifier', 'analysis_period_days']:
        if key in event:
            result[key] = event[key]
    
    if result:
        return result
    
    # パラメータが見つからない場合は空 dict を返す（エラーにしない）
    logger.warning("No parameters found in event, returning empty dict")
    return {}
```

**Step 3: ホットデプロイ（3分）**
```bash
# 修正したコードをデプロイ
cd ~/aiops-alert

# テスト
python -m pytest tests/test_lambda_handler.py::test_messageversion_1_0 -v

# コミット＆プッシュ
git add lib/lambda_handler.py
git commit -m "Fix: messageVersion parameter extraction robustness"
git push origin main

# CodePipeline が自動的にデプロイ（1～2分）
# デプロイ状況確認
aws lambda get-function \
  --function-name aiops-lambda \
  --query 'Configuration.[LastModified, LastUpdateStatus]'
```

**Step 4: サーキットブレーカー の実装（10分）**
```python
# lib/circuit_breaker.py
import time
from enum import Enum
from datetime import datetime, timedelta

class CircuitState(Enum):
    CLOSED = "CLOSED"        # 正常状態、リクエスト許可
    OPEN = "OPEN"            # 障害状態、リクエスト拒否
    HALF_OPEN = "HALF_OPEN"  # 復帰テスト中

class CircuitBreaker:
    def __init__(self, failure_threshold: int = 5, timeout_seconds: int = 60):
        self.failure_threshold = failure_threshold
        self.timeout_seconds = timeout_seconds
        self.failure_count = 0
        self.last_failure_time = None
        self.state = CircuitState.CLOSED
    
    def call(self, func, *args, **kwargs):
        """サーキットブレーカー経由で関数を呼び出し"""
        
        if self.state == CircuitState.OPEN:
            # タイムアウト経過を確認
            if self._should_attempt_reset():
                self.state = CircuitState.HALF_OPEN
                logger.info("Circuit breaker: HALF_OPEN (recovery attempt)")
            else:
                raise CircuitBreakerOpenException(
                    f"Circuit is OPEN. Retry in {self._time_until_retry()} seconds"
                )
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        
        except Exception as e:
            self._on_failure()
            raise
    
    def _on_success(self):
        self.failure_count = 0
        self.state = CircuitState.CLOSED
    
    def _on_failure(self):
        self.failure_count += 1
        self.last_failure_time = datetime.now()
        
        if self.failure_count >= self.failure_threshold:
            self.state = CircuitState.OPEN
            logger.warning(
                f"Circuit breaker: OPEN (failure_count={self.failure_count})"
            )
    
    def _should_attempt_reset(self) -> bool:
        if self.last_failure_time is None:
            return True
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return elapsed >= self.timeout_seconds
    
    def _time_until_retry(self) -> int:
        if self.last_failure_time is None:
            return 0
        elapsed = (datetime.now() - self.last_failure_time).total_seconds()
        return max(0, int(self.timeout_seconds - elapsed))

# lambda_handler.py で使用
circuit_breaker = CircuitBreaker(failure_threshold=5, timeout_seconds=60)

def handle_bedrock_agent_message(event, context):
    try:
        return circuit_breaker.call(_handle_message_impl, event, context)
    except CircuitBreakerOpenException:
        # フォールバック処理
        logger.warning("Using fallback response")
        return {
            "statusCode": 503,
            "body": json.dumps({
                "error": "Service temporarily unavailable",
                "retry_after": 60
            })
        }
```

**復帰判定基準**
- ✅ Lambda Error Rate < 5%
- ✅ Lambda Duration の平均 < 3秒（通常<1秒）
- ✅ Tool invocation 成功率 > 95%
- ✅ Successful-to-failed requests ratio > 19:1

---

### **🔴 CR-06: セッション管理の不具合**

**リスク ID**: CR-06  
**確度**: 高（65%）  
**影響度**: 極大（ステートフルな会話が不可）  
**復帰時間**: 40～50分

#### 原因
- Agent Session の状態がメモリ内のみに保持（分散環境で lost）
- Session タイムアウト管理が不正確
- Multi-turn conversation の context 喪失
- DynamoDB キャッシュの同期不備

#### 症状
```
⚠️ 前のメッセージ内容を Agent が忘れる
⚠️ "申し訳ございませんが、前回のコンテキストが見つかりません"
⚠️ Multi-turn conversation で失敗
⚠️ Session state validation error が CloudWatch Logs に頻出
```

#### 検出方法
```bash
# 1. Session 関連エラーのフィルタリング
aws logs filter-log-events \
  --log-group-name /aws/lambda/aiops-lambda \
  --start-time $(date -d '15 min ago' +%s)000 \
  --filter-pattern 'session' \
  --query 'events[*].[timestamp, message]'

# 2. Session state validation エラーの集計
aws logs filter-log-events \
  --log-group-name /aws/lambda/aiops-lambda \
  --filter-pattern 'Session state validation' \
  --query 'events | length(@)'

# 3. X-Ray トレース上でセッション ID の一貫性確認
aws xray batch_get_traces \
  --trace_ids '1-66b9a4ac-a1b2c3d4e5f6g7h8i9j0k' \
  | jq '.Traces[0].Segments[] | select(.name | contains("session"))'
```

#### 復帰手順
**Step 1: Session State をDynamoDB に永続化（15分）**
```python
# lib/session_manager.py
import boto3
import json
from datetime import datetime, timedelta
import hashlib

dynamodb = boto3.resource('dynamodb')
session_table = dynamodb.Table('aiops-session-state')

class SessionManager:
    """AgentCore Session State 管理"""
    
    TTL_SECONDS = 3600  # 1時間
    
    @staticmethod
    def save_session(session_id: str, state: dict) -> None:
        """Session State を DynamoDB に保存"""
        
        timestamp = int(datetime.now().timestamp())
        ttl = timestamp + SessionManager.TTL_SECONDS
        
        item = {
            'session_id': session_id,
            'state': json.dumps(state),
            'created_at': timestamp,
            'updated_at': timestamp,
            'ttl': ttl,
            'version': 1
        }
        
        session_table.put_item(Item=item)
        logger.info(f"Session saved: {session_id}, TTL: {ttl}")
    
    @staticmethod
    def load_session(session_id: str) -> dict:
        """Session State を DynamoDB から読み込み"""
        
        response = session_table.get_item(Key={'session_id': session_id})
        
        if 'Item' in response:
            item = response['Item']
            state = json.loads(item['state'])
            
            # TTL 確認
            current_time = int(datetime.now().timestamp())
            if item['ttl'] < current_time:
                logger.warning(f"Session expired: {session_id}")
                session_table.delete_item(Key={'session_id': session_id})
                return None
            
            logger.info(f"Session loaded: {session_id}")
            return state
        
        logger.warning(f"Session not found: {session_id}")
        return None
    
    @staticmethod
    def delete_session(session_id: str) -> None:
        """Session State を削除"""
        session_table.delete_item(Key={'session_id': session_id})
        logger.info(f"Session deleted: {session_id}")
    
    @staticmethod
    def list_active_sessions() -> list:
        """アクティブなセッション一覧"""
        
        current_time = int(datetime.now().timestamp())
        
        response = session_table.scan(
            FilterExpression='#ttl > :now',
            ExpressionAttributeNames={'#ttl': 'ttl'},
            ExpressionAttributeValues={':now': current_time}
        )
        
        return response.get('Items', [])

# CloudFormation で DynamoDB テーブルを作成
# cfn-templates/session-table.yaml
"""
Resources:
  SessionStateTable:
    Type: AWS::DynamoDB::Table
    Properties:
      TableName: aiops-session-state
      BillingMode: PAY_PER_REQUEST
      AttributeDefinitions:
        - AttributeName: session_id
          AttributeType: S
      KeySchema:
        - AttributeName: session_id
          KeyType: HASH
      TimeToLiveSpecification:
        AttributeName: ttl
        Enabled: true
      PointInTimeRecoverySpecification:
        PointInTimeRecoveryEnabled: true
      Tags:
        - Key: Environment
          Value: !Ref Environment
"""
```

**Step 2: Multi-turn conversation サポート（15分）**
```python
# lib/conversation_manager.py
from session_manager import SessionManager

class ConversationManager:
    """Multi-turn conversation 管理"""
    
    @staticmethod
    def start_conversation(session_id: str, initial_query: str) -> dict:
        """会話を開始"""
        
        state = {
            'session_id': session_id,
            'messages': [
                {'role': 'user', 'content': initial_query, 'timestamp': datetime.now().isoformat()}
            ],
            'turn_count': 1,
            'context': {}
        }
        
        SessionManager.save_session(session_id, state)
        
        return state
    
    @staticmethod
    def add_turn(session_id: str, user_message: str, agent_response: str) -> dict:
        """会話に Turn を追加"""
        
        state = SessionManager.load_session(session_id)
        
        if state is None:
            logger.warning(f"Session {session_id} not found, starting new conversation")
            return ConversationManager.start_conversation(session_id, user_message)
        
        state['messages'].append({
            'role': 'user',
            'content': user_message,
            'timestamp': datetime.now().isoformat()
        })
        
        state['messages'].append({
            'role': 'agent',
            'content': agent_response,
            'timestamp': datetime.now().isoformat()
        })
        
        state['turn_count'] += 1
        
        # Session の有効期限を延長
        SessionManager.save_session(session_id, state)
        
        return state
    
    @staticmethod
    def get_conversation_context(session_id: str, max_turns: int = 5) -> str:
        """会話の Context を構築（Agent プロンプトに使用）"""
        
        state = SessionManager.load_session(session_id)
        
        if state is None:
            return ""
        
        # 最新 max_turns の messages を抽出
        recent_messages = state['messages'][-(max_turns * 2):]
        
        context_lines = []
        for msg in recent_messages:
            role = msg['role'].upper()
            content = msg['content'][:200]  # 最初の200文字に制限
            context_lines.append(f"[{role}] {content}")
        
        return "\n".join(context_lines)

# lambda_handler.py で使用
from conversation_manager import ConversationManager

def invoke_bedrock_agent(prompt: str, session_id: str, is_first_turn: bool = False):
    """Bedrock Agent を呼び出し（Session 対応版）"""
    
    if is_first_turn:
        conversation = ConversationManager.start_conversation(session_id, prompt)
    else:
        conversation = SessionManager.load_session(session_id)
    
    # 会話の context を prompt に含める
    context = ConversationManager.get_conversation_context(session_id)
    
    enhanced_prompt = f"""{prompt}

【前の会話内容】
{context}

上記のコンテキストを考慮して、ユーザーの最新のリクエストに対応してください。
"""
    
    response = bedrock_agent_runtime.invoke_agent(
        agentId='AIOPS_AGENT_ID',
        agentAliasId='TSTALIASID',
        sessionId=session_id,
        inputText=enhanced_prompt,
        enableTrace=True
    )
    
    # Agent のレスポンスを会話に追加
    agent_text = response['completion']['responseContentBlock']['text']
    ConversationManager.add_turn(session_id, prompt, agent_text)
    
    return response
```

**Step 3: Session Timeout Policy の設定（5分）**
```python
# lib/session_timeout_policy.py
from datetime import datetime, timedelta

class SessionTimeoutPolicy:
    """Session Timeout ポリシー"""
    
    # Timeout 定義（秒）
    FIRST_TURN_TIMEOUT = 300        # 最初の Turn: 5分
    SUBSEQUENT_TURN_TIMEOUT = 600   # その後の Turn: 10分
    MAX_SESSION_DURATION = 3600     # Session 最大時間: 1時間
    
    @staticmethod
    def should_expire_session(state: dict) -> bool:
        """Session が期限切れかどうかを判定"""
        
        turn_count = state.get('turn_count', 1)
        created_at = datetime.fromisoformat(state.get('created_at', datetime.now().isoformat()))
        last_turn_at = datetime.fromisoformat(state.get('last_turn_at', created_at.isoformat()))
        
        # Session 全体の最大時間チェック
        total_duration = (datetime.now() - created_at).total_seconds()
        if total_duration > SessionTimeoutPolicy.MAX_SESSION_DURATION:
            return True
        
        # Turn ごとのタイムアウトチェック
        if turn_count == 1:
            timeout = SessionTimeoutPolicy.FIRST_TURN_TIMEOUT
        else:
            timeout = SessionTimeoutPolicy.SUBSEQUENT_TURN_TIMEOUT
        
        idle_time = (datetime.now() - last_turn_at).total_seconds()
        if idle_time > timeout:
            return True
        
        return False

# DynamoDB TTL + Application logic で二重管理
```

**復帰判定基準**
- ✅ Session state persistence rate > 99%
- ✅ Multi-turn conversation success rate > 90%
- ✅ Session data retrieval latency < 100ms
- ✅ No "Session not found" errors in CloudWatch Logs

---

### **🔴 CR-10: IAM 権限エラー（Agent Runtime Invoke 権限喪失）**

**リスク ID**: CR-10  
**確度**: 高（50% だが復帰時間が長い）  
**影響度**: 極大（すべての Agent 呼び出し失敗）  
**復帰時間**: 60～90分

#### 原因
- bedrock:InvokeAgent 権限が削除または名前変更
- Lambda Execution Role の信頼関係が破損
- Resource ARN の指定ミス
- CloudFormation IAM role の更新失敗

#### 症状
```
ERROR: AccessDeniedException: User: arn:aws:iam::ACCOUNT:role/aiops-lambda-role is not authorized to perform: bedrock:InvokeAgent on resource: arn:aws:bedrock:ap-northeast-1::agent/AIOPS_AGENT_ID/*
⚠️ すべての Agent 呼び出しが失敗（100% エラー）
```

#### 検出方法
```bash
# 1. CloudTrail で権限エラーを検出
aws cloudtrail lookup-events \
  --lookup-attributes AttributeKey=EventName,AttributeValue=InvokeAgent \
  --max-results 10 \
  --query 'Events[?CloudTrailEvent like `*AccessDenied*`]'

# 2. CloudWatch Logs で権限エラーを検出
aws logs filter-log-events \
  --log-group-name /aws/lambda/aiops-lambda \
  --filter-pattern 'AccessDeniedException\|is not authorized'

# 3. Lambda IAM Role の権限を確認
ROLE_NAME="aiops-lambda-role"
aws iam get-role-policy \
  --role-name $ROLE_NAME \
  --policy-name aiops-agent-invoke-policy \
  --query 'RolePolicyDocument.Statement[?Action contains `bedrock`]'

# 4. Lambda Trust Relationship の確認
aws iam get-role \
  --role-name $ROLE_NAME \
  --query 'Role.AssumeRolePolicyDocument'
```

#### 復帰手順
**Step 1: IAM 権限の即座の追加（5分）**
```bash
#!/bin/bash
# add_bedrock_permissions.sh

ROLE_NAME="aiops-lambda-role"
ACCOUNT_ID=$(aws sts get-caller-identity --query Account --output text)
AGENT_ID="AIOPS_AGENT_ID"

# Lambda Role に bedrock:InvokeAgent 権限を追加
aws iam put-role-policy \
  --role-name $ROLE_NAME \
  --policy-name bedrock-agent-invoke \
  --policy-document '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Action": [
          "bedrock:InvokeAgent",
          "bedrock:InvokeModel"
        ],
        "Resource": [
          "arn:aws:bedrock:ap-northeast-1::agent/'$AGENT_ID'/*",
          "arn:aws:bedrock:ap-northeast-1::foundation-model/anthropic.claude-haiku-4-5-20251001-v1:0"
        ]
      }
    ]
  }'

echo "✅ Permissions added"

# 確認
aws iam get-role-policy \
  --role-name $ROLE_NAME \
  --policy-name bedrock-agent-invoke \
  --query 'RolePolicyDocument.Statement[0]'
```

**Step 2: CloudFormation IAM テンプレートの修正（10分）**
```yaml
# cfn-templates/iam-roles.yaml
Resources:
  AiopsLambdaExecutionRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: !Sub 'aiops-lambda-${Environment}-role'
      AssumeRolePolicyDocument:
        Version: '2012-10-17'
        Statement:
          - Effect: Allow
            Principal:
              Service: lambda.amazonaws.com
            Action: sts:AssumeRole
      
      # インラインポリシー - Bedrock Agent Invoke
      Policies:
        - PolicyName: bedrock-agent-invoke-policy
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - bedrock:InvokeAgent
                  - bedrock:InvokeModel
                Resource:
                  - !Sub 'arn:aws:bedrock:${AWS::Region}::agent/*'
                  - !Sub 'arn:aws:bedrock:${AWS::Region}::foundation-model/*'
              
              # Bedrock Knowledge Base アクセス
              - Effect: Allow
                Action:
                  - bedrock:Retrieve
                  - bedrock:RetrieveAndGenerate
                Resource:
                  - !Sub 'arn:aws:bedrock:${AWS::Region}::knowledge-base/*'
        
        # CloudWatch Logs へのアクセス
        - PolicyName: cloudwatch-logs-policy
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - logs:CreateLogGroup
                  - logs:CreateLogStream
                  - logs:PutLogEvents
                Resource: !Sub 'arn:aws:logs:${AWS::Region}:${AWS::AccountId}:log-group:/aws/lambda/*'
        
        # SNS Publish
        - PolicyName: sns-publish-policy
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - sns:Publish
                Resource: !GetAtt SnsReportTopic.TopicArn
        
        # X-Ray Write
        - PolicyName: xray-write-policy
          PolicyDocument:
            Version: '2012-10-17'
            Statement:
              - Effect: Allow
                Action:
                  - xray:PutTraceSegments
                  - xray:PutTelemetryRecords
                Resource: '*'
      
      Tags:
        - Key: Environment
          Value: !Ref Environment
```

**Step 3: CloudFormation デプロイ（10分）**
```bash
# IAM テンプレートをデプロイ
aws cloudformation deploy \
  --template-file cfn-templates/iam-roles.yaml \
  --stack-name aiops-iam-stack-$(date +%s) \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides Environment=dev \
  --region ap-northeast-1

# デプロイ完了を待機
aws cloudformation wait stack-create-complete \
  --stack-name aiops-iam-stack-* \
  --region ap-northeast-1

echo "✅ IAM role updated"
```

**Step 4: Lambda 環境変数の確認と更新（5分）**
```bash
# Lambda に現在の Role ARN を確認
LAMBDA_ARN=$(aws lambda get-function \
  --function-name aiops-lambda \
  --query 'Configuration.Role' \
  --output text)

echo "Lambda Role: $LAMBDA_ARN"

# Role に正しい権限があるか確認
ROLE_NAME=$(echo $LAMBDA_ARN | cut -d'/' -f2)

aws iam get-role-policy \
  --role-name $ROLE_NAME \
  --policy-name bedrock-agent-invoke-policy \
  --query 'RolePolicyDocument.Statement[0].Action'
```

**Step 5: Lambda の再デプロイ（3分）**
```bash
# Lambda を再デプロイして新しい权限を反映
aws lambda update-function-code \
  --function-name aiops-lambda \
  --zip-file fileb://dist/lambda.zip

# Lambda が新しい权限で実行するまで待機（<1分）
sleep 30

# テスト
aws lambda invoke \
  --function-name aiops-lambda \
  --payload '{"test": "true"}' \
  /tmp/test_response.json

cat /tmp/test_response.json
```

**復帰判定基準**
- ✅ Lambda Role に bedrock:InvokeAgent 権限がある
- ✅ Lambda invocation 成功率 > 99%
- ✅ CloudTrail に AccessDenied エラーが 0 件

---

### **🟡 HR-03: OpenSearch スキーマ互換性エラー**

**リスク ID**: HR-03  
**確度**: 中（40%）  
**影響度**: 高（検索機能が部分的に不可）  
**復帰時間**: 15～25分

#### 原因
- Field mapping の不一致（text → keyword など）
- Dynamic mapping が期待と異なる
- Ingestion process でフィールドが追加される

#### 症状
```
⚠️ RAG 検索が遅延（>2秒）
⚠️ 一部のメタデータフィルタが機能しない
ERROR: Field type mismatch - expected 'text', got 'keyword'
```

#### 検出・復帰方法
```bash
# 検出
aws opensearchserverless batch-get-collection \
  --names aiops-kb-index \
  --query 'collectionDetails[0].collectionArn'

# OpenSearch インデックスマッピング確認
curl -X GET "https://aiops-kb-collection.ap-northeast-1.aoss.amazonaws.com/aiops-kb-index/_mapping?pretty" \
  -H "Authorization: Bearer $(aws opensearchserverless get-access-token --query 'accessToken' --output text)"

# 復帰
# Ingestion Job を再実行
aws bedrock-agent ingest-knowledge-base-documents \
  --knowledge-base-id OQZNQIPJTS \
  --data-source-id 9TZ9MCQRGH \
  --documents '[...]'
```

---

### **🟡 HR-05: キャッシング層の問題**

**リスク ID**: HR-05  
**確度**: 中（45%）  
**影響度**: 高（レスポンス時間が倍加）  
**復帰時間**: 10～20分

#### 原因
- Lambda 関数内のメモリキャッシュが古い状態で固着
- ElastiCache（使用している場合）の同期エラー
- TTL の不適切な設定

#### 症状
```
⚠️ Agent が古いランブック情報を返す
⚠️ Lambda Duration が通常の 2倍以上
Lambda cold start 後も改善しない
```

#### 検出・復帰方法
```python
# 検出
import boto3

cloudwatch = boto3.client('cloudwatch')

metrics = cloudwatch.get_metric_statistics(
    Namespace='AWS/Lambda',
    MetricName='Duration',
    StartTime=datetime.now() - timedelta(minutes=30),
    EndTime=datetime.now(),
    Period=60,
    Statistics=['Average', 'Maximum']
)

avg_duration = [m['Average'] for m in metrics['Datapoints']]
if max(avg_duration or [0]) > 3000:  # 3秒以上
    logger.warning("Abnormal Lambda duration detected")

# 復帰: キャッシュをクリア
def clear_cache():
    """全キャッシュをクリア"""
    global _cache
    _cache = {}
    logger.info("Cache cleared")

# Lambda を再デプロイ
aws lambda update-function-code --function-name aiops-lambda --zip-file fileb://dist/lambda.zip
```

---

### **🟡 HR-07: エラーハンドリング不足**

**リスク ID**: HR-07  
**確度**: 中（55%）  
**影響度**: 高（予測不可能な障害）  
**復帰時間**: 20～30分

#### 原因
- Try-except ブロックが不十分
- 予期しない例外がそのまま伝播
- Graceful degradation がない

#### 症状
```
ERROR: Unhandled exception in Lambda
Lambda timeout frequently
503 Internal Server Error が返される
```

#### 復帰方法
```python
# 改善されたエラーハンドリング
def handle_bedrock_agent_message(event, context):
    """改善版エラーハンドリング"""
    
    execution_id = context.aws_request_id
    
    try:
        # 主処理
        result = process_message(event)
        logger.info(f"Success: {execution_id}")
        return result
    
    except ValueError as e:
        logger.error(f"ValueError: {e}", exc_info=True)
        return create_error_response("INVALID_INPUT", str(e), 400)
    
    except TimeoutError as e:
        logger.error(f"TimeoutError: {e}", exc_info=True)
        return create_error_response("TIMEOUT", "Request timeout", 408)
    
    except AccessDeniedException as e:
        logger.error(f"AccessDeniedException: {e}", exc_info=True)
        return create_error_response("PERMISSION_DENIED", "Access denied", 403)
    
    except Exception as e:
        logger.error(f"Unhandled exception: {e}", exc_info=True)
        # Fallback response を返す
        return create_error_response(
            "INTERNAL_ERROR",
            f"An unexpected error occurred: {str(e)[:100]}",
            500
        )

def create_error_response(error_code, message, http_status):
    """エラーレスポンスの標準化"""
    return {
        "statusCode": http_status,
        "body": json.dumps({
            "error": {
                "code": error_code,
                "message": message
            }
        })
    }
```

---

### **🟡 HR-09: パフォーマンス劣化**

**リスク ID**: HR-09  
**確度**: 中（50%）  
**影響度**: 高（ユーザー体験悪化）  
**復帰時間**: 15～25分

#### 原因
- AgentCore の LLM 呼び出しオーバーヘッド
- Vector search の N+1 クエリ
- 不正なデータベースクエリ

#### 症状
```
Lambda Duration が通常の 3倍以上（>3秒）
CloudWatch Logs の P99 latency が 5秒超
Agent のレスポンス時間が 10秒以上
```

#### 検出・復帰方法
```python
# パフォーマンス監視
import time
from functools import wraps

def measure_duration(func):
    """関数実行時間を測定"""
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.time()
        try:
            result = func(*args, **kwargs)
            return result
        finally:
            duration = (time.time() - start) * 1000  # ミリ秒
            logger.info(f"{func.__name__} duration: {duration:.2f}ms")
            
            # CloudWatch メトリクスに送信
            if duration > 1000:  # 1秒超過の場合は警告
                logger.warning(f"Slow execution: {func.__name__} took {duration:.2f}ms")
    
    return wrapper

@measure_duration
def invoke_bedrock_agent(prompt, session_id):
    # Agent 呼び出し
    pass

# 復帰: プロファイリングと最適化
aws lambda update-function-configuration \
  --function-name aiops-lambda \
  --timeout 60 \
  --memory-size 1024
```

---

### **🟡 HR-11: OpenSearch スケーリング不足**

**リスク ID**: HR-11  
**確度**: 中（35%）  
**影響度**: 高（検索が遅延または失敗）  
**復帰時間**: 20～40分

#### 原因
- Serverless OpenSearch の OCU（Compute Unit）が不足
- Auto-scaling が機能していない
- Index fragmentation

#### 症状
```
OpenSearch Search latency が 2秒超
503 Unavailable エラーが頻出
Knowledge Base の検索応答が遅延
```

#### 復帰方法
```bash
# OCU スケール アップ
aws opensearchserverless update-account-settings \
  --capacity-limits '{
    "MaxSearchCapacityUnits": 100,
    "MaxIndexingCapacityUnits": 100
  }'

# インデックス最適化
curl -X POST "https://aiops-kb-collection.ap-northeast-1.aoss.amazonaws.com/aiops-kb-index/_forcemerge" \
  -H "Authorization: Bearer $(aws opensearchserverless get-access-token --query 'accessToken' --output text)"
```

---

### **🟠 MR-01: Bedrock Model の出力フォーマット変更**

**リスク ID**: MR-01  
**確度**: 中（40%）  
**影響度**: 中（部分的なエラー）  
**復帰時間**: 10～15分

#### 原因
- Claude Haiku 4.5 の出力フォーマットが予期と異なる
- Tool use フォーマットが変更

#### 症状
```
JSON parse error が断続的に発生
```

#### 復帰方法
```python
# Output フォーマットの柔軟性を追加
import json

def parse_agent_response(response_text: str) -> dict:
    """複数のフォーマットに対応"""
    
    try:
        # 形式1: 純粋な JSON
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass
    
    # 形式2: JSON が ```json ... ``` で囲まれている
    if response_text.startswith('```'):
        json_str = response_text.split('```')[1]
        if json_str.startswith('json'):
            json_str = json_str[4:]
        return json.loads(json_str.strip())
    
    # 形式3: マークダウンテーブル
    # 形式4: プレーンテキスト
    
    raise ValueError(f"Unexpected response format: {response_text[:100]}")
```

---

## プロセスリスク

### **チーム間の連携不足**

| 項目 | リスク | 対策 |
|------|--------|------|
| **ドキュメント更新遅延** | 旧世代の情報に基づく実装 | Wiki / Confluence を毎日更新 |
| **テスト不足** | バグが本番で発見 | Integration test を CI/CD に統合 |
| **デプロイ手順ミス** | CloudFormation スタック破損 | デプロイ前チェックリスト実行 |
| **ロールバック未訓練** | 本番障害時に対応できない | 月1回のロールバック演習実施 |

### **対策**

```yaml
# .github/workflows/deployment-checklist.yml
name: Pre-Deployment Checklist
on: [workflow_dispatch]

jobs:
  pre-deployment-check:
    runs-on: ubuntu-latest
    steps:
      - name: Verify CloudFormation Templates
        run: cfn-lint cfn-templates/*.yaml
      
      - name: Run Unit Tests
        run: pytest tests/unit/ -v --cov
      
      - name: Run Integration Tests
        run: pytest tests/integration/ -v
      
      - name: Check Documentation
        run: |
          if [ ! -f docs/DEPLOYMENT_CHECKLIST.md ]; then
            echo "❌ DEPLOYMENT_CHECKLIST.md is missing"
            exit 1
          fi
      
      - name: Verify Rollback Procedure
        run: python scripts/verify_rollback.py
```

---

## 本番リスク

### **Canary フェーズでの失敗**

**シナリオ**: 5% トラフィックを AgentCore に誘導

```yaml
# Canary Deployment
TrafficWeights:
  Current: 95%     # 旧版 (Bedrock Agent)
  Canary:  5%      # 新版 (AgentCore)

監視項目:
  - Error Rate: 5% より大きい → 即座ロールバック
  - Latency P99: 2秒より大きい → Canary 中止
  - Bedrock Agent invocation count: 通常の 5% 増加を確認
```

**復帰手順**:
```bash
# 1. トラフィックを 0% に戻す
aws codedeploy update-deployment-group \
  --deployment-group-name aiops-canary \
  --traffic-rerouting-config 'type=TimeBasedCanary,timeBasedCanary={canaryPercentage=0}'

# 2. ロールバック
git revert $(git log --oneline | grep "AgentCore" | head -1 | cut -d' ' -f1) --no-edit
git push origin main

# CodePipeline が自動トリガー
```

### **Shadow フェーズでの失敗**

**シナリオ**: 100% トラフィックが AgentCore を呼び出すが、結果は本番に反映しない

```bash
# Shadow フェーズの監視
AWS Lambda Alias: shadow
Configuration:
  - 10% → shadow (AgentCore)
  - 90% → prod (Bedrock Agent)

CloudWatch Logs Insights:
  fields @timestamp, @message, @duration
  | filter (alias="shadow")
  | stats count(), pct(@duration, 99) by @message
```

**復帰方法**:
```python
# Shadow フェーズからの即座の退出
import boto3

lambda_client = boto3.client('lambda')

# Alias routing を 100% prod に戻す
lambda_client.update_alias(
    FunctionName='aiops-lambda',
    Name='prod',
    RoutingConfig={
        'AdditionalVersionWeights': {}  # shadow 側の weight を削除
    }
)

print("✅ Exited shadow phase")
```

---

## 復帰戦略

### **緊急ロールバック手順（分単位）**

```
【本番障害検出】（10秒）
    ↓
【Alarm 発火】（10秒）
    ↓
【On-call エンジニアへ通知】（20秒）
    ↓
【git revert + push】（2分）
    ↓
【CodePipeline デプロイ開始】（3分）
    ↓
【Lambda 更新完了】（2分）
    ↓
【動作確認】（1分）
    ↓
【復帰完了】（9分以内）
```

### **手順書**

```bash
#!/bin/bash
# scripts/emergency_rollback.sh

set -e

TIMESTAMP=$(date "+%Y-%m-%d %H:%M:%S")
echo "[$TIMESTAMP] Starting emergency rollback..."

# 1. 最新コミットを確認
LATEST_COMMIT=$(git log --oneline | head -1)
echo "Current commit: $LATEST_COMMIT"

# 2. AgentCore 移行以前のコミットを特定
AGENTCORE_COMMIT=$(git log --oneline | grep -i "agentcore.*migration" | head -1 | cut -d' ' -f1)

if [ -z "$AGENTCORE_COMMIT" ]; then
  echo "❌ Could not find AgentCore migration commit"
  exit 1
fi

echo "Target rollback commit: $AGENTCORE_COMMIT"

# 3. ロールバック
git revert $AGENTCORE_COMMIT --no-edit
echo "✅ Git revert completed"

# 4. プッシュ
git push origin main
echo "✅ Pushed to main"

# 5. CodePipeline デプロイを確認
PIPELINE_NAME="aiops-agentcore-pipeline"
EXECUTION_ID=$(aws codepipeline start-pipeline-execution \
  --name $PIPELINE_NAME \
  --query 'pipelineExecutionId' \
  --output text)

echo "Pipeline execution started: $EXECUTION_ID"

# 6. デプロイ完了を待機（最大 10分）
for i in {1..60}; do
  STATE=$(aws codepipeline get-pipeline-execution \
    --pipeline-name $PIPELINE_NAME \
    --pipeline-execution-id $EXECUTION_ID \
    --query 'pipelineExecution.status' \
    --output text)
  
  if [ "$STATE" == "Succeeded" ]; then
    echo "✅ Pipeline succeeded"
    break
  elif [ "$STATE" == "Failed" ]; then
    echo "❌ Pipeline failed"
    exit 1
  fi
  
  echo "Pipeline status: $STATE (${i}0 seconds elapsed)"
  sleep 10
done

# 7. Lambda 動作確認
echo "Running Lambda health check..."
aws lambda invoke \
  --function-name aiops-lambda \
  --payload '{"test": "health_check"}' \
  /tmp/health_check_response.json

RESPONSE=$(cat /tmp/health_check_response.json)

if [[ $RESPONSE == *"error"* ]]; then
  echo "❌ Lambda health check failed: $RESPONSE"
  exit 1
fi

echo "✅ Lambda health check passed"

# 8. SNS 通知
aws sns publish \
  --topic-arn "arn:aws:sns:ap-northeast-1:123456789012:CriticalAlerts" \
  --subject "🚨 Emergency Rollback Completed" \
  --message "AgentCore migration has been rolled back due to production issues. Current version: $LATEST_COMMIT. Rollback version: $AGENTCORE_COMMIT"

echo "✅ Notification sent"

echo "[$TIMESTAMP] Emergency rollback completed successfully"
```

---

## 予防策・テスト戦略

### **テスト戦略**

#### **ユニットテスト**
```python
# tests/test_lambda_handler_agentcore.py
import pytest
import json
from lib.lambda_handler import (
    handle_bedrock_agent_message,
    _extract_parameters_safely,
    dispatch_function
)

class TestAgentCoreMessageFormat:
    """messageVersion 1.0 フォーマットテスト"""
    
    def test_extract_parameters_from_array(self):
        """Parameters が array の場合"""
        event = {
            'parameters': [
                {'name': 'log_group_name', 'value': '/aws/lambda/test'},
                {'name': 'log_stream_name', 'value': '2026-06-24'}
            ]
        }
        
        params = _extract_parameters_safely(event)
        
        assert params['log_group_name'] == '/aws/lambda/test'
        assert params['log_stream_name'] == '2026-06-24'
    
    def test_extract_parameters_from_dict(self):
        """Parameters が dict の場合"""
        event = {
            'parameters': {
                'log_group_name': '/aws/lambda/test',
                'log_stream_name': '2026-06-24'
            }
        }
        
        params = _extract_parameters_safely(event)
        
        assert params == event['parameters']
    
    def test_extract_parameters_missing(self):
        """Parameters がない場合"""
        event = {}
        
        params = _extract_parameters_safely(event)
        
        assert params == {}
    
    @pytest.mark.mocked
    def test_message_version_1_0_handling(self, mocker):
        """messageVersion 1.0 メッセージの処理"""
        
        # Mock
        mock_dispatch = mocker.patch('lib.lambda_handler.dispatch_function')
        mock_dispatch.return_value = {'status': 'success'}
        
        event = {
            'messageVersion': '1.0',
            'invocationId': 'inv-001',
            'actionGroup': 'AIOpsActionGroup',
            'function': 'LogInvestigation',
            'parameters': [
                {'name': 'log_group_name', 'value': '/aws/lambda/test'}
            ]
        }
        
        context = type('Context', (), {'aws_request_id': 'req-001'})()
        
        # 実行
        response = handle_bedrock_agent_message(event, context)
        
        # 検証
        assert response['invocationId'] == 'inv-001'
        assert response['function'] == 'LogInvestigation'
        mock_dispatch.assert_called_once()

class TestCompatibilityLayer:
    """互換性層のテスト"""
    
    def test_bedrock_to_agentcore_conversion(self):
        """Bedrock 1.0 → AgentCore 形式への変換"""
        from lib.agentcore_compatibility_layer import AgentCoreCompatibility
        
        legacy_request = {
            'invocationId': 'inv-001',
            'function': 'LogInvestigation',
            'parameters': [
                {'name': 'log_group_name', 'value': '/aws/lambda/test'}
            ]
        }
        
        result = AgentCoreCompatibility.convert_request_to_agentcore(legacy_request)
        
        assert result['tool']['toolName'] == 'LogInvestigation'
        assert result['tool']['toolInput']['log_group_name'] == '/aws/lambda/test'
    
    def test_agentcore_to_bedrock_conversion(self):
        """AgentCore → Bedrock 1.0 形式への変換"""
        from lib.agentcore_compatibility_layer import AgentCoreCompatibility
        
        agentcore_response = {
            'toolResult': {
                'content': [
                    {'text': 'Investigation complete'}
                ]
            }
        }
        
        result = AgentCoreCompatibility.convert_response_to_bedrock(agentcore_response)
        
        assert 'responseBody' in result
        assert result['responseBody']['TEXT']['body'] == 'Investigation complete'
```

#### **統合テスト**
```python
# tests/integration/test_agentcore_integration.py
import pytest
import json
import time
from datetime import datetime

@pytest.mark.integration
class TestAgentCoreIntegration:
    """AgentCore との統合テスト"""
    
    @pytest.fixture
    def lambda_client(self):
        import boto3
        return boto3.client('lambda')
    
    def test_end_to_end_log_investigation(self, lambda_client):
        """E2E: Log Investigation"""
        
        payload = {
            'messageVersion': '1.0',
            'actionGroup': 'AIOpsActionGroup',
            'function': 'LogInvestigation',
            'parameters': [
                {'name': 'log_group_name', 'value': '/aws/lambda/aiops-lambda'},
                {'name': 'log_stream_name', 'value': '2026-06-24'}
            ]
        }
        
        # Lambda 実行
        start = time.time()
        response = lambda_client.invoke(
            FunctionName='aiops-lambda',
            InvocationType='RequestResponse',
            Payload=json.dumps(payload)
        )
        duration = time.time() - start
        
        # レスポンス検証
        assert response['StatusCode'] == 200
        assert duration < 30, f"Execution took {duration}s, expected < 30s"
        
        body = json.loads(response['Payload'].read())
        assert 'invocationId' in body
        assert body['function'] == 'LogInvestigation'
    
    def test_multi_turn_conversation(self, lambda_client):
        """Multi-turn 会話のテスト"""
        
        session_id = 'test-session-001'
        
        # Turn 1
        payload1 = {
            'messageVersion': '1.0',
            'sessionId': session_id,
            'function': 'LogInvestigation',
            'parameters': [
                {'name': 'log_group_name', 'value': '/aws/lambda/test'}
            ]
        }
        
        response1 = lambda_client.invoke(
            FunctionName='aiops-lambda',
            InvocationType='RequestResponse',
            Payload=json.dumps(payload1)
        )
        
        # Turn 2（同じ session_id）
        payload2 = {
            'messageVersion': '1.0',
            'sessionId': session_id,
            'function': 'BottleneckAnalysis',
            'parameters': [
                {'name': 'resource_id', 'value': 'i-123456'}
            ]
        }
        
        response2 = lambda_client.invoke(
            FunctionName='aiops-lambda',
            InvocationType='RequestResponse',
            Payload=json.dumps(payload2)
        )
        
        # 両方のレスポンスが成功
        assert response1['StatusCode'] == 200
        assert response2['StatusCode'] == 200
        
        # Session state が保持されていることを確認
        from lib.session_manager import SessionManager
        state = SessionManager.load_session(session_id)
        assert state is not None
        assert state['turn_count'] >= 2
```

#### **負荷テスト**
```bash
#!/bin/bash
# tests/load/run_load_test.sh

echo "🔥 Starting load test..."

# Apache JMeter を使用した負荷テスト
jmeter -n -t tests/load/agentcore_load_test.jmx \
  -l tests/load/results.jtl \
  -e -o tests/load/report \
  -Jthread_count=100 \
  -Jramp_up=60 \
  -Jduration=300 \
  -Jhost=lambda \
  -Jport=9001

# 結果を集計
python tests/load/analyze_results.py tests/load/results.jtl

# CloudWatch にメトリクスを送信
aws cloudwatch put-metric-data \
  --namespace AIOps/LoadTest \
  --metric-name AverageDuration \
  --value $(grep 'Average' tests/load/report/statistics.json | jq '.Average')
```

### **Canary フェーズの監視項目**

```yaml
MonitoringItems:
  # エラー率
  - MetricName: ErrorRate
    Threshold: 5%
    Window: 5分
    Action: RollbackIfExceeded
  
  # レスポンス時間
  - MetricName: P99Latency
    Threshold: 2秒
    Window: 5分
    Action: RollbackIfExceeded
  
  # Agent 呼び出し成功率
  - MetricName: BedrockAgentSuccessRate
    Threshold: 95%
    Window: 5分
    Action: AlertIfBelowThreshold
  
  # Knowledge Base 検索精度
  - MetricName: RAGRetrievalQuality
    Threshold: 70%
    Window: 10分
    Action: AlertIfBelowThreshold

AlertingRules:
  - Condition: ErrorRate > 5% for 5min
    Action: [PagerDuty Notification, Slack Notification, Auto Rollback]
  
  - Condition: P99Latency > 2s for 5min
    Action: [Slack Warning, Scale Up OpenSearch]
```

---

## 段階的フェーズ実行計画

```
【フェーズ 0】（Day 1-2）
  ├─ テスト環境での完全検証
  ├─ ユニット/統合テスト 100% パス
  ├─ 破壊テスト実施
  └─ ドキュメント完成

【フェーズ 1】（Day 3）Canary 5%
  ├─ 監視開始（リアルタイム）
  ├─ 30分間の安定性確認
  ├─ Error Rate < 1%
  └─ 拡大判断

【フェーズ 2】（Day 3-4）Shadow 10%
  ├─ 本番トラフィックの 10% が AgentCore を呼び出し
  ├─ 2時間の追跡観測
  ├─ ログ分析と改善
  └─ 本格投入判断

【フェーズ 3】（Day 4）本格投入 100%
  ├─ 全トラフィックを AgentCore に誘導
  ├─ 継続的な監視（72時間）
  └─ Bedrock Agent の廃止

【フェーズ 4】（Day 5+）安定化・最適化
  ├─ パフォーマンスチューニング
  ├─ Cost 最適化
  └─ ドキュメント更新
```

---

## リスク軽減総まとめ

| リスク | 確度 | 影響度 | 重要度 | 軽減方法 |
|--------|------|--------|--------|----------|
| CR-01: Bedrock 互換性不足 | 高 | 極大 | 🔴 | 互換性レイヤー + テスト |
| CR-02: KB ベクトル化失敗 | 高 | 極大 | 🔴 | Ingestion 再試行 + スキーマ検証 |
| CR-04: Lambda ハンドラバグ | 高 | 極大 | 🔴 | ホットデプロイ + サーキットブレーカー |
| CR-06: セッション管理不具合 | 高 | 極大 | 🔴 | DynamoDB 永続化 + TTL管理 |
| CR-10: IAM 権限エラー | 高 | 極大 | 🔴 | IAM テンプレート + 自動検証 |
| HR-03: OpenSearch スキーマ | 中 | 高 | 🟠 | マッピング検証 + Ingestion 再実行 |
| HR-05: キャッシング問題 | 中 | 高 | 🟠 | キャッシュ無効化 + Metrics 監視 |
| HR-07: エラーハンドリング不足 | 中 | 高 | 🟠 | Try-except強化 + Graceful degradation |
| HR-09: パフォーマンス劣化 | 中 | 高 | 🟠 | プロファイリング + Lambda スケール |
| HR-11: OpenSearch スケーリング不足 | 中 | 高 | 🟠 | OCU スケール + Auto-scaling |

---

