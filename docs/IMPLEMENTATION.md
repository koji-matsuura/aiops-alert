# 実装詳細

## ファイル一覧と役割

### 新規作成

| ファイル | 役割 | 参照元 |
|---------|------|-------|
| `lambda/handler.py` | EventBridge → AgentCore thin proxy | `lib/lambda_handler.py` 行48-230 |
| `agentcore/app.py` | BedrockAgentCoreApp エントリポイント | `cfn-infra-base/app.py` のパターン |
| `agentcore/tools/fr_tools.py` | FR-01〜FR-06 AWS API 関数 | `lib/lambda_handler.py` 行1519-2198 |
| `Dockerfile` | agentcore/ コンテナ化（port 8080） | `cfn-infra-base/Dockerfile` のパターン |
| `requirements-agentcore.txt` | AgentCore 用依存パッケージ | `cfn-infra-base/requirements.txt` |
| `cfn-templates/agentcore-runtime.yaml` | AgentCore Runtime CFN テンプレート | `cfn-infra-base/cfn_agentcore_runtime.yml` |

### 変更

| ファイル | 変更内容 | 根拠 |
|---------|---------|------|
| `cfn-templates/lambda-function.yaml` | IAM: `bedrock:InvokeAgent` → `bedrock-agentcore:InvokeAgentRuntime`、Permission 削除、env var 変更 | lambda-function.yaml 行79-123 |
| `cfn-templates/main.yaml` | BedrockAgentStack 削除・AgentCoreRuntimeStack 追加 | main.yaml 行111-123 |
| `cfn-pipeline.yml` | ECR リポジトリ追加・Docker ビルドステップ追加 | cfn-infra-base/cfn-pipeline.yml 行91-509 |

### 削除

| ファイル | 理由 |
|---------|------|
| `cfn-templates/bedrock-agent.yaml` | AWS::Bedrock::Agent が不要 |
| `lib/lambda_handler.py` | lambda/ と agentcore/ に分離後に削除 |
| `lib/` ディレクトリ | 全関数移行後に削除 |

---

## lambda/handler.py

**役割：** thin proxy。AgentCore Runtime 呼び出しのみ担当。

**関数：**
- `handler(event, context)` — エントリポイント
- `extract_event_info(event)` — AWS 公式フィールド抽出（source, detail-type, detail, time）
- `build_prompt(event_info)` — AgentCore Runtime 向けプロンプト構築
- `invoke_agent_runtime(prompt, session_id)` — `bedrock-agentcore:InvokeAgentRuntime` 呼び出し

**環境変数：**
- `AGENTCORE_RUNTIME_ARN` — AgentCore Runtime ARN（`AgentCoreRuntimeStack` の Output から設定）
- `SNS_REPORT_ARN` — エラー通知用（既存）

**IAM 権限（`lambda-function.yaml` に定義）：**
```
bedrock-agentcore:InvokeAgentRuntime
```

---

## agentcore/app.py

**役割：** BedrockAgentCoreApp エントリポイント。AI 推論と AWS API 呼び出しを担当。

**処理フロー：**
1. Lambda から受け取った payload（prompt + event_info）を解析
2. Knowledge Base `bedrock-agent-runtime:Retrieve` でランブック検索
   - `KNOWLEDGE_BASE_ID` 環境変数（`AgentCoreRuntimeStack` から設定）
   - metadata フィルタ（`applicable_to` で RDS/EC2/Lambda を絞り込み）
3. Claude Haiku 4.5 `bedrock:InvokeModel` で状況分析・FR 関数を選択
4. `agentcore/tools/fr_tools.py` の該当 FR 関数を呼び出し
5. SNS `sns:Publish` で結果通知

**エントリポイントパターン（`cfn-infra-base/app.py` 行58-132 参照）：**
```python
from bedrock_agentcore.runtime import BedrockAgentCoreApp
app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload):
    ...

app.run()
```

**環境変数（`agentcore-runtime.yaml` の EnvironmentVariables から設定）：**
- `KNOWLEDGE_BASE_ID` — Knowledge Base ID（`OQZNQIPJTS`）
- `SNS_REPORT_ARN` — SNS 通知先
- `BEDROCK_KB_MODEL_ARN` — Claude Haiku 4.5 ARN

---

## agentcore/tools/fr_tools.py

**役割：** FR-01〜FR-06 の AWS API 呼び出し関数。`lib/lambda_handler.py` 行1519-2198 から移行。

**関数一覧（移行元の行番号）：**

| 関数名 | 移行元行 | 使用 AWS API |
|-------|---------|------------|
| `log_investigation_fr01(**kwargs)` | 行1519 | `logs:GetLogEvents` |
| `bottleneck_investigation_fr02(**kwargs)` | 行1591 | `cloudwatch:GetMetricStatistics` |
| `get_rds_metrics(...)` | 行1659 | `cloudwatch:GetMetricStatistics` |
| `get_ec2_metrics(...)` | 行1719 | `cloudwatch:GetMetricStatistics` |
| `create_db_snapshot_fr03(**kwargs)` | 行1752 | `rds:CreateDBSnapshot` |
| `maintenance_window_display_fr04(**kwargs)` | 行1825 | `rds:DescribeDBInstances`, `rds:DescribePendingMaintenanceActions` |
| `slow_query_detection_fr05(**kwargs)` | 行1912 | `pi:GetResourceMetrics`, `logs:GetLogEvents` |
| `high_load_query_detection_fr06(**kwargs)` | 行2036 | `pi:GetResourceMetrics`, `cloudwatch:GetMetricStatistics` |

**Boto3 クライアント（移行元の行24-31 に準拠）：**
```python
logs_client = boto3.client('logs')
cloudwatch_client = boto3.client('cloudwatch')
rds_client = boto3.client('rds')
pi_client = boto3.client('pi')
sns_client = boto3.client('sns')
```

---

## Dockerfile

**ベース：** `cfn-infra-base/Dockerfile` 行1-42 のパターン  
**Python：** 3.12-slim（`lambda-function.yaml` 行38 の Runtime と合わせる）  
**ポート：** 8080（HTTP プロトコル、`get_runtime_guide()` Protocol Contracts より）

```dockerfile
FROM public.ecr.aws/docker/library/python:3.12-slim
WORKDIR /app
COPY requirements-agentcore.txt .
RUN pip install --no-cache-dir -r requirements-agentcore.txt
COPY agentcore/ ./agentcore/
COPY app_entry.py .          # BedrockAgentCoreApp エントリポイント
EXPOSE 8080
ENTRYPOINT ["python", "app_entry.py"]
```

**注：** `agentcore/` のみコピー。`lambda/` はコンテナに含まれない。

---

## requirements-agentcore.txt

**ソース：** `cfn-infra-base/requirements.txt` 行8-10

```
boto3>=1.28.0
aioboto3>=12.0.0
bedrock-agentcore>=0.1.0
```

---

## cfn-templates/agentcore-runtime.yaml

**ソース：** `cfn-infra-base/cfn_agentcore_runtime.yml`

**含めるリソース：**
- `AWS::BedrockAgentCore::Runtime`（行126-161）
  - `ProtocolConfiguration: HTTP`（MCP ではなく HTTP を採用）
  - `ContainerUri`：ECR リポジトリ URI（`cfn-pipeline.yml` の ECR Output を参照）
  - `EnvironmentVariables`：KNOWLEDGE_BASE_ID, SNS_REPORT_ARN, BEDROCK_KB_MODEL_ARN
- `AgentCoreRuntimeRole`（行201-400）
  - Trust: `bedrock-agentcore.amazonaws.com`
  - `bedrock:Retrieve`、`bedrock:InvokeModel`、`sns:Publish` 権限を含む

**除外するリソース（AIOps に不要）：**
- `AWS::BedrockAgentCore::Memory`
- `AWS::BedrockAgentCore::Gateway`
- `AWS::BedrockAgentCore::GatewayTarget`
- `AgentCoreMemoryExecutionRole`

**パラメータ：**
- `BedrockKnowledgeBaseArn` — `main.yaml` の `KnowledgeBaseStack.Outputs.KnowledgeBaseArn` から渡す
- `KnowledgeBaseId` — `KnowledgeBaseStack.Outputs.KnowledgeBaseId` から渡す
- `ImgRepoName` — `cfn-pipeline.yml` の ECR リポジトリ名
- `SNSTopicArn` — 既存 SNS Topic ARN

**Output：**
- `AgentRuntimeArn` — `main.yaml` の LambdaStack に `AGENTCORE_RUNTIME_ARN` として渡す

---

## cfn-templates/lambda-function.yaml の変更点

**変更箇所（行番号は変更前の参照）：**

1. **IAM Policy 変更**（行76-85）
   ```yaml
   # 変更前
   - bedrock:InvokeAgent
   - bedrock:InvokeModel
   - bedrock:RetrieveAndGenerate
   
   # 変更後
   - bedrock-agentcore:InvokeAgentRuntime
   ```

2. **Lambda Permission 削除**（行117-123）
   ```yaml
   # 削除
   BedrockAgentInvokeLambdaPermission:
     Type: AWS::Lambda::Permission
     Principal: bedrock.amazonaws.com
   ```

3. **環境変数変更**（行56-57）
   ```yaml
   # 変更前
   BEDROCK_AGENT_ID: !Ref BedrockAgentId
   BEDROCK_AGENT_ALIAS: !Ref BedrockAgentAlias
   
   # 変更後
   AGENTCORE_RUNTIME_ARN: !Ref AgentCoreRuntimeArn
   ```

4. **Lambda コードパス変更**（行43-44）
   ```yaml
   # 変更前（lib/lambda_handler.py → lambda_function.py）
   S3Key: lambda.zip
   
   # 変更後（lambda/handler.py → lambda_function.py）
   S3Key: lambda.zip   # cfn-pipeline.yml のビルドソースを変更
   ```

---

## cfn-templates/main.yaml の変更点

1. **削除**（行111-123）
   ```yaml
   # 削除
   BedrockAgentStack:
     Type: AWS::CloudFormation::Stack
     TemplateURL: .../cfn-templates/bedrock-agent.yaml
   ```

2. **追加**
   ```yaml
   AgentCoreRuntimeStack:
     Type: AWS::CloudFormation::Stack
     Properties:
       TemplateURL: .../cfn-templates/agentcore-runtime.yaml
       Parameters:
         BedrockKnowledgeBaseArn: !GetAtt KnowledgeBaseStack.Outputs.KnowledgeBaseArn
         KnowledgeBaseId: !GetAtt KnowledgeBaseStack.Outputs.KnowledgeBaseId
         SNSTopicArn: !Sub 'arn:aws:sns:${AWS::Region}:${AWS::AccountId}:${EnvName}-aiops-notification'
         ImgRepoName: !Sub ${EnvName}-${ServiceName}-aiops-agentcore
   ```

3. **LambdaStack 変更**（行78）
   ```yaml
   # 変更前
   BedrockAgentId: !GetAtt BedrockAgentStack.Outputs.AgentId
   
   # 変更後
   AgentCoreRuntimeArn: !GetAtt AgentCoreRuntimeStack.Outputs.AgentRuntimeArn
   ```

---

## cfn-pipeline.yml の変更点

1. **ECR リポジトリ追加**（`cfn-infra-base/cfn-pipeline.yml` 行91-94 参照）
   ```yaml
   EcrRepositoryAiopsAgentcore:
     Type: AWS::ECR::Repository
     Properties:
       RepositoryName: !Sub ${EnvName}-${ServiceName}-aiops-agentcore
   ```
   Pipeline CFN スタック作成時に ECR が作成される。Build フェーズより前。

2. **BuildSpec 変更**
   ```yaml
   # Lambda ZIP ビルドのソースパス変更
   cp lambda/handler.py lambda_package/lambda_function.py   # lib/ → lambda/
   
   # Docker ビルドステップ追加
   - aws ecr get-login-password | docker login ...
   - docker build -t $IMAGE_REPO_NAME:$IMAGE_TAG .
   - docker push $ECR_URI:$IMAGE_TAG
   ```

---

## Knowledge Base メタデータフィルタリング（変更なし）

AgentCore Runtime の `retrieve()` 呼び出し時に使用するフィルタ。  
ソース：`AGENTS.md` Knowledge Base セクション（KB ID: OQZNQIPJTS, Data Source: 9TZ9MCQRGH）

```python
# applicable_to フィルタの例（RDS 関連アラームの場合）
retrieval_configuration = {
    "vectorSearchConfiguration": {
        "numberOfResults": 3,
        "filter": {
            "equals": {
                "key": "applicable_to",
                "value": {"stringValue": "RDS"}
            }
        }
    }
}
```

`includeForEmbedding: true` のメタデータ（category, applicable_to, difficulty）はセマンティック検索にも影響する。
