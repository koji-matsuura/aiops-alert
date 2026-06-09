# GitHub リポジトリコード構造分析レポート

## リポジトリ情報

**プロジェクト**: Improving IT Operations Efficiency With AIOps  
**URL**: https://github.com/aws-samples/improving-it-operations-efficiency-with-aiops  
**ライセンス**: MIT No Attribution (MIT-0)  
**主言語**: TypeScript (CDK), Python (Lambda)  

---

## 1. コード統計

### 言語別行数

| 言語 | ファイル数 | 行数 | 備考 |
|------|----------|------|------|
| **TypeScript** | 10 | 830 | CDK Stack + Constructs |
| **Python** | 3 | 285 | Lambda ハンドラー + Custom Resource |
| **JSON** | 5 | 5,028 | package-lock + OpenAPI スキーマ |
| **その他** | 2 | 147+ | README.md + jest.config.js |
| **合計** | 20 | 6,143+ | ※node_modules 除外 |

### ファイル構成

```
improving-it-operations-efficiency-with-aiops/
├── bin/
│   └── bedrock-agent-cdk.ts              (66 行) - CDK App エントリポイント
├── lib/
│   ├── bedrock-agent-cdk-stack.ts        (131 行) - メイン CDK Stack
│   ├── ec2-cdk-stack.ts                  (26 行) - EC2 Stack
│   ├── constructs/
│   │   ├── bedrock-agent-iam-construct.ts      (95 行) - Bedrock IAM Role
│   │   ├── custom-bedrock-agent-construct.ts   (134 行) - Custom Resource for Agent
│   │   ├── lambda-construct.ts                 (42 行) - Lambda 関数デプロイ
│   │   ├── lambda-iam-construct.ts             (148 行) - Lambda IAM Role
│   │   ├── s3-bucket-construct.ts              (60 行) - API Schema S3 バケット
│   │   ├── s3-kb-bucket-construct.ts           (58 行) - Knowledge Base S3 バケット
│   │   ├── ec2-construct.ts                    (52 行) - EC2 インスタンス作成
│   │   └── ses-construct.ts                    (25 行) - SES Email Identity
│   └── assets/
│       ├── lambdas/
│       │   ├── cdk-resource-bedrock-agent.py   (152 行) - Custom Resource Handler
│       │   ├── agent/alerts/
│       │   │   └── get-all-alerts.py           (79 行) - CloudWatch Alert Handler
│       │   └── agent/remediation/
│       │       └── issue-remediation.py        (54 行) - EC2 Remediation Handler
│       └── api-schema/
│           ├── operations-api.json             (107 行) - Alert Operations OpenAPI
│           └── remediation-api.json            (108 行) - Remediation OpenAPI
├── package.json                         (30 行) - npm 依存関係
├── tsconfig.json                        (31 行) - TypeScript 設定
├── cdk.json                             (55 行) - CDK コンテキスト設定
├── jest.config.js                       (8 行) - Jest テスト設定
└── README.md                            (147 行) - ドキュメント
```

---

## 2. CDK Stack 構造

### 2.1 Entry Point: `bin/bedrock-agent-cdk.ts`

**役割**: CDK App の初期化と Stack の構成

```typescript
// key elements:
- cdk-nag AwsSolutionsChecks の適用（セキュリティ検証）
- glob を使用した API schema ファイルの動的検出
- EC2CdkStack と BedrockAgentCdkStack の依存関係設定
- 環境変数から AWS アカウント・リージョン を取得
```

**重要なパラメータ**:
- `specAlertFile`: operations-api.json
- `specRemediationFile`: remediation-api.json
- `alertslambdaFile`: get-all-alerts
- `remediationlambdaFile`: issue-remediation
- `instruction`: Agent 実行時の指示書

### 2.2 Main Stack: `lib/bedrock-agent-cdk-stack.ts`

**役割**: Bedrock Agent、Lambda、IAM ロール、S3 を統合

**Props インターフェース**:
```typescript
export interface BedrockAgentCdkProps extends cdk.StackProps {
  readonly specAlertFile: string;              // Alert API スキーマ
  readonly specRemediationFile: string;        // Remediation API スキーマ
  readonly alertslambdaFile: string;           // Alert Lambda ハンドラー名
  readonly remediationlambdaFile: string;      // Remediation Lambda ハンドラー名
  readonly ec2InstanceId: string;              // CloudWatch Alarm 対象インスタンス ID
  readonly instruction: string;                // Agent 実行時指示書
}
```

**リソース作成フロー**:

```
1. SESConstruct
   └─ SES Email Identity 作成

2. LambdaIamConstruct
   ├─ CloudWatch Alarm 読み取り権限
   ├─ EC2 操作権限（Snapshot, Reboot）
   ├─ Lambda ログ 書き込み権限
   └─ SES メール送信権限

3. S3Construct (API Schema)
   ├─ S3 バケット作成
   └─ api-schema/ をデプロイ

4. S3KBConstruct (Knowledge Base)
   ├─ S3 バケット作成
   └─ kb/ をデプロイ

5. BedrockIamConstruct
   ├─ Bedrock Agent IAM Role 作成
   ├─ Lambda 実行権限
   ├─ S3 読み取り権限
   ├─ Bedrock Model 呼び出し権限
   └─ Knowledge Base 検索権限

6. LambdaConstruct (Alerts) × 2
   ├─ Alert Lambda デプロイ
   └─ Remediation Lambda デプロイ

7. CustomBedrockAgentConstruct
   ├─ Custom Resource Lambda 作成
   └─ Bedrock Agent 作成（on_create フェーズ）
```

**NagSuppressions（セキュリティ例外）**:
- `AwsSolutions-IAM5`: EC2 スナップショット権限ワイルドカード
- `AwsSolutions-S1`: S3 アクセスログ（KB 作成時のみ使用）
- `AwsSolutions-IAM4`: Custom Resource は Admin 権限が必要

### 2.3 EC2 Stack: `lib/ec2-cdk-stack.ts`

**役割**: テスト用 EC2 インスタンスの作成

```typescript
public readonly ec2;  // EC2Construct インスタンス

// EC2 インスタンスの詳細は ec2-construct.ts で定義
```

---

## 3. Constructs 構造

### 3.1 LambdaConstruct (42 行)

**目的**: Lambda 関数のデプロイと権限設定

```typescript
export interface LambdaProps extends cdk.StackProps {
  readonly lambdaRoleName: string;      // IAM Role 名
  readonly lambdaFile: string;          // ハンドラー関数名（拡張子なし）
  readonly lambdaName: string;          // Lambda 関数名
  readonly iamRole: cdk.aws_iam.Role;   // 実行用 IAM Role
  readonly assetFilePath: string;       // ソースコード パス
  readonly opsEmailAddress: string;     // 運用チームメール
}
```

**生成される Lambda**:
- Runtime: Python 3.13
- Handler: `${lambdaFile}.lambda_handler`
- Timeout: 300 秒
- Environment: `EMAIL_ADDRESS`
- Bedrock 実行権限: 付与

### 3.2 BedrockIamConstruct (95 行)

**目的**: Bedrock Agent 実行用 IAM Role の作成

**ポリシー**:

| No | ポリシー名 | リソース | アクション |
|----|-----------|---------|----------|
| 1 | BedrockAgentLambdaPolicy | Lambda ARN | lambda:InvokeFunction |
| 2 | BedrockAgentS3BucketPolicy | S3 バケット | s3:GetObject |
| 3 | BedrockAgentBedrockModelPolicy | Claude モデル | bedrock:InvokeModel |
| 4 | BedrockAgentKBPolicy | Knowledge Base | bedrock:Retrieve |

**Service Principal**: `bedrock.amazonaws.com`

### 3.3 LambdaIamConstruct (148 行)

**目的**: Lambda 関数実行用 IAM Role の作成

**ポリシー**:

| No | Policy | Resource | Actions |
|----|--------|----------|---------|
| 0 | CloudWatch | Alarm ARN | cloudwatch:DescribeAlarms |
| 1 | EC2 Volume | vol-* | ec2:CreateSnapshot, ec2:CreateTags |
| 2 | EC2 Snapshot | snapshot/* | ec2:CreateSnapshot |
| 3 | CloudWatch Logs | Log Group | logs:CreateLogGroup, logs:CreateLogStream, logs:PutLogEvents |
| 4 | SES | Identity + ConfigSet | ses:SendEmail |
| 5 | EC2 Instance | instance/${instanceId} | ec2:StartInstances, ec2:StopInstances, ec2:RebootInstances |
| 6 | EC2 Describe | * (ワイルドカード) | ec2:DescribeInstances |

### 3.4 CustomBedrockAgentConstruct (134 行)

**目的**: Custom CDK Resource による Bedrock Agent の作成と Action Group の登録

**機構**:
```typescript
// 環境変数として設定:
{
  COLLECTION_ID: "BEDROCK_AGENT_CUSTOM_RESOURCE",
  S3_BUCKET: S3 バケット名,
  AGENT_NAME: Agent 名,
  BEDROCK_AGENT_ROLE_ARN: Bedrock IAM Role ARN,
  BEDROCK_AGENT_ALERT_LAMBDA_ARN: Alert Lambda ARN,
  BEDROCK_AGENT_REMEDIATION_LAMBDA_ARN: Remediation Lambda ARN,
  S3_BUCKET_ALERT_KEY: "api-schema/operations-api.json",
  S3_BUCKET_REMEDIATION_KEY: "api-schema/remediation-api.json",
  InstanceId: EC2 インスタンス ID,
  BEDROCK_AGENT_INSTRUCTION: Agent 指示書
}
```

**Custom Resource Handler**: `cdk-resource-bedrock-agent.py`

### 3.5 S3Construct (60 行) & S3KBConstruct (58 行)

**目的**: Bedrock Agent が使用する S3 バケットの作成

**共通設定**:
- AutoDeleteObjects: true
- BlockPublicAccess: すべてブロック
- Encryption: S3 マネージド
- RemovalPolicy: DESTROY
- SSL 強制: true
- リソースベースポリシー: 非 HTTPS 接続を DENY

**S3Construct**:
- `lib/assets/api-schema` をデプロイ
- Prefix: `api-schema/`

**S3KBConstruct**:
- `lib/assets/kb` をデプロイ
- Knowledge Base 用データ

### 3.6 EC2Construct (52 行)

**目的**: テスト用 EC2 インスタンスの作成

```typescript
// 設定:
- Instance Type: t2.micro
- AMI: Amazon Linux 2 (最新)
- VPC: Default VPC
- Subnet: Public Subnet 0
- Tag Propagation: Volume にタグ伝播
```

**出力**: `instanceId` プロパティ

### 3.7 SESConstruct (25 行)

**目的**: SES メール送信設定

```typescript
// 作成されるリソース:
1. ConfigurationSet: "MyDemoConfigurationSet"
2. EmailIdentity: 指定されたメールアドレス
```

---

## 4. Lambda 関数

### 4.1 Custom Resource Handler: `cdk-resource-bedrock-agent.py` (152 行)

**役割**: CDK から呼び出される Custom Resource ハンドラー

**エントリポイント**: `on_event(event, context)`

**リクエスト タイプ別処理**:

#### Create フェーズ
```python
on_create():
  1. create_agent(agent_name, role_arn, instruction)
     └─ Bedrock Agent 作成
     └─ 返り値: agent_id
  
  2. time.sleep(15)  # Agent 準備待機
  
  3. create_agent_action_group() × 2
     ├─ Action Group 1: "GetAlertsActionGroup"
     │  └─ Lambda: get-all-alerts
     │  └─ Schema: operations-api.json
     └─ Action Group 2: "RemediationActionGroup"
        └─ Lambda: issue-remediation
        └─ Schema: remediation-api.json
  
  4. create_cloudwatch_alarm(instanceId)
     └─ CloudWatch Alarm: "Web_Server_CPU_Utilization"
```

#### Update フェーズ
```python
on_update():
  # 何もしない（実装なし）
```

#### Delete フェーズ
```python
on_delete():
  1. delete_agent(agent_name)
  2. delete CloudWatch Alarm
```

**関数シグネチャ**:

```python
# Agent 作成
create_agent(
  agent_resource_role_arn: str,
  agent_name: str,
  instruction: str
) -> str:  # agent_id を返す

# Action Group 作成
create_agent_action_group(
  agent_id: str,
  lambda_arn: str,
  bucket: str,
  key: str,
  group_name: str,
  group_description: str
) -> None

# CloudWatch Alarm 作成
create_cloudwatch_alarm(instanceId: str) -> None

# Agent 削除
delete_agent(agent_name: str) -> Optional[Dict]
```

**Bedrock Agent 設定**:
```python
response = agent_client.create_agent(
  agentName: Agent 名,
  agentResourceRoleArn: IAM Role ARN,
  foundationModel: "anthropic.claude-3-haiku-20240307-v1:0",  # Claude Haiku 3
  description: "Agent created by CDK.",
  idleSessionTTLInSeconds: 1800,
  instruction: 指示書
)
```

**CloudWatch Alarm 設定**:
```python
cloudwatch.put_metric_alarm(
  AlarmName: "Web_Server_CPU_Utilization",
  MetricName: "CPUUtilization",
  Namespace: "AWS/EC2",
  Statistic: "Maximum",
  Period: 60 秒,
  Threshold: 90.0 %,
  EvaluationPeriods: 2,
  DatapointsToAlarm: 1,
  ComparisonOperator: "GreaterThanThreshold",
  Dimensions: [{ Name: "InstanceId", Value: instanceId }]
)
```

### 4.2 Alert Handler: `get-all-alerts.py` (79 行)

**役割**: Bedrock Agent Action Group - CloudWatch アラーム確認とメール送信

**ハンドラー**: `lambda_handler(event, context)`

**入力 フォーマット** (Action Group から):
```json
{
  "apiPath": "/get_all_alerts" または "/send-Notification",
  "httpMethod": "GET" または "POST",
  "actionGroup": "GetAlertsActionGroup",
  "requestBody": {
    "content": {
      "application/json": {
        "properties": [
          { "name": "property1", "value": "..." },
          { "name": "property2", "value": "..." }
        ]
      }
    }
  },
  "promptSessionAttributes": { ... },
  "sessionAttributes": { ... }
}
```

**API Path 別処理**:

#### GET /get_all_alerts
```python
# CloudWatch から ALARM 状態のアラームを取得
response = cw_client.describe_alarms(
  AlarmNames=['Web_Server_CPU_Utilization'],
  StateValue='ALARM'
)

# レスポンス形式:
{
  'application/json': {
    'body': JSON.stringify([
      {
        'ID': 'i-xxxxx',           # EC2 Instance ID
        'ResourceType': 'EC2',
        'State': 'High CPU Utilization, instance in alert state'
      }
    ])
  }
}
```

#### POST /send-Notification
```python
# SES でメール送信
client.send_email(
  Destination: { 'ToAddresses': [EMAIL] },
  Message: {
    'Subject': { 'Data': requestBody['properties'][0]['value'] },
    'Body': { 'Text': { 'Data': requestBody['properties'][2]['value'] } }
  },
  Source: EMAIL_ADDRESS,
  ConfigurationSetName: 'MyDemoConfigurationSet'
)

# レスポンス:
{
  'application/json': {
    'body': 'email notification sent'
  }
}
```

**出力フォーマット** (messageVersion 1.0):
```json
{
  "messageVersion": "1.0",
  "response": {
    "actionGroup": "...",
    "apiPath": "...",
    "httpMethod": "...",
    "httpStatusCode": 200,
    "responseBody": { "application/json": { "body": "..." } }
  },
  "promptSessionAttributes": { ... }
}
```

### 4.3 Remediation Handler: `issue-remediation.py` (54 行)

**役割**: Bedrock Agent Action Group - EC2 スナップショット作成と再起動

**入力フォーマット**: Alert Handler と同じ

**API Path 別処理**:

#### POST /create_snapshot_of_EC2_volume
```python
# パラメータ抽出:
instanceid = requestBody['properties'][0]['value']  # EC2 ARN or ID

# Volume ID 取得:
response = ec2.describe_instances(InstanceIds=[instanceid])
volume_id = response['Reservations'][0]['Instances'][0]['BlockDeviceMappings'][0]['Ebs']['VolumeId']

# Snapshot 作成:
response = ec2.create_snapshot(VolumeId=volume_id)
snapshot_id = response['SnapshotId']

# レスポンス:
{
  'application/json': {
    'body': snapshot_id
  }
}
```

#### POST /restart_ec2_instance
```python
# パラメータ抽出:
instanceid = requestBody['properties'][0]['value']

# インスタンス再起動:
response = ec2.reboot_instances(InstanceIds=[instanceid])

# レスポンス:
{
  'application/json': {
    'body': 'instance restarted'
  }
}
```

**出力フォーマット**: Alert Handler と同じ (messageVersion 1.0)

---

## 5. API スキーマ定義

### 5.1 Operations API (`operations-api.json`) - 107 行

**OpenAPI 3.0.0** 仕様

**基本情報**:
```json
{
  "title": "AWS Infrastructure & Operations Automation API",
  "version": "1.0.0",
  "description": "APIs for managing AWS Infrastructure..."
}
```

**Endpoint 1: GET /get_all_alerts**

```json
{
  "summary": "Get a list of all resources in AWS account in alert state",
  "operationId": "get_all_alerts",
  "responses": {
    "200": {
      "content": {
        "application/json": {
          "schema": {
            "type": "array",
            "items": {
              "type": "object",
              "properties": {
                "ID": { "type": "string" },              # Resource ID
                "ResourceType": { "type": "string" },    # EC2, DynamoDB, Lambda
                "State": { "type": "string" }            # Issue description
              }
            }
          }
        }
      }
    }
  }
}
```

**Endpoint 2: POST /send-Notification**

```json
{
  "summary": "Send Notification to operations team",
  "operationId": "sendNotification",
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "emailaddress": { "type": "string" },  # 送信先メール
            "subject": { "type": "string" },       # メール件名
            "email_body": { "type": "string" }     # メール本文
          },
          "required": ["emailaddress", "subject", "email_body"]
        }
      }
    }
  },
  "responses": {
    "200": {
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "sendReminderTrackingId": { "type": "string" },
              "sendReminderStatus": { "type": "string" }
            }
          }
        }
      }
    }
  }
}
```

### 5.2 Remediation API (`remediation-api.json`) - 108 行

**Endpoint 1: POST /create_snapshot_of_EC2_volume**

```json
{
  "summary": "Create snapshot of EBS volume of affected EC2 instance",
  "operationId": "create_snapshot_of_EC2_volume",
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "instanceARN": {
              "type": "string",
              "description": "ARN of affected EC2 instance"
            }
          },
          "required": ["instanceARN"]
        }
      }
    }
  },
  "responses": {
    "200": {
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "snapshotARN": {
                "type": "string",
                "description": "ARN of EBS volume's snapshot"
              }
            }
          }
        }
      }
    }
  }
}
```

**Endpoint 2: POST /restart_ec2_instance**

```json
{
  "summary": "Restart affected EC2 instance",
  "operationId": "restart_ec2_instance",
  "requestBody": {
    "required": true,
    "content": {
      "application/json": {
        "schema": {
          "type": "object",
          "properties": {
            "instanceARN": {
              "type": "string",
              "description": "ARN of affected EC2 instance"
            }
          },
          "required": ["instanceARN"]
        }
      }
    }
  },
  "responses": {
    "200": {
      "content": {
        "application/json": {
          "schema": {
            "type": "object",
            "properties": {
              "snapshotARN": {
                "type": "bool",
                "description": "True if restarted EC2 instance"
              }
            }
          }
        }
      }
    }
  }
}
```

---

## 6. 設定ファイル

### 6.1 `package.json` - 30 行

**プロジェクト情報**:
```json
{
  "name": "bedrock-agent-cdk",
  "version": "0.1.0",
  "bin": {
    "bedrock-agent-cdk": "bin/bedrock-agent-cdk.js"
  }
}
```

**スクリプト**:
| スクリプト | コマンド | 用途 |
|-----------|---------|------|
| `build` | `tsc` | TypeScript コンパイル |
| `watch` | `tsc -w` | ファイル監視 + 自動コンパイル |
| `test` | `jest` | Jest テスト実行 |
| `cdk` | `cdk` | CDK CLI コマンド |

**devDependencies**:
- `@types/jest`: ^29.5.1
- `@types/node`: 20.1.7
- `aws-cdk`: ^2.178.0
- `jest`: ^29.5.0
- `ts-jest`: ^29.1.0
- `ts-node`: ^10.9.1
- `typescript`: ~5.1.3

**dependencies**:
- `aws-cdk-lib`: ^2.178.0
- `cdk`: ^2.178.0
- `cdk-nag`: ^2.35.11（セキュリティ検証）
- `constructs`: ^10.0.0
- `glob`: ^10.3.10（ファイル検出）
- `source-map-support`: ^0.5.21

### 6.2 `tsconfig.json` - 31 行

**コンパイラ設定**:
```json
{
  "compilerOptions": {
    "target": "ES2020",
    "module": "commonjs",
    "lib": ["es2020", "dom"],
    "declaration": true,              // .d.ts 生成
    "strict": true,                   // Strict mode
    "noImplicitAny": true,
    "strictNullChecks": true,
    "noImplicitThis": true,
    "alwaysStrict": true,
    "noImplicitReturns": true,
    "experimentalDecorators": true,
    "strictPropertyInitialization": false,
    "inlineSourceMap": true,
    "inlineSources": true
  },
  "exclude": ["node_modules", "cdk.out"]
}
```

### 6.3 `cdk.json` - 55 行

**CDK アプリ構成**:
```json
{
  "app": "npx ts-node --prefer-ts-exts bin/bedrock-agent-cdk.ts",
  "watch": {
    "include": ["**"],
    "exclude": [
      "README.md", "cdk*.json", "**/*.d.ts", "**/*.js",
      "tsconfig.json", "package*.json", "yarn.lock",
      "node_modules", "test"
    ]
  },
  "context": {
    "@aws-cdk/aws-lambda:recognizeLayerVersion": true,
    "@aws-cdk/core:checkSecretUsage": true,
    "@aws-cdk/core:target-partitions": ["aws", "aws-cn"],
    ... (その他 50+ の CDK context フラグ)
  }
}
```

### 6.4 `jest.config.js` - 8 行

```javascript
module.exports = {
  testEnvironment: 'node',
  roots: ['<rootDir>/test'],
  testMatch: ['**/*.test.ts'],
  transform: {
    '^.+\\.tsx?$': 'ts-jest'
  }
};
```

---

## 7. テスト構成

### 現状
- **テストファイル**: なし（test ディレクトリ未作成）
- **Jest 設定**: 用意されているが、実装なし
- **テストカバレッジ**: 0%

### 推奨テスト項目
1. **Lambda ハンドラー ユニットテスト**
   - Alert API レスポンス形式
   - Remediation API 実行
   - CloudWatch Alarm 処理

2. **CDK Stack テスト**
   - リソース生成確認
   - IAM ポリシー検証
   - 依存関係チェック

3. **統合テスト**
   - Bedrock Agent 呼び出し
   - Action Group 実行

---

## 8. デプロイメント

### デプロイコマンド

```bash
# 1. 準備
npm install
cdk bootstrap

# 2. デプロイ
cdk deploy BedrockAgentCDKStack \
  --require-approval never \
  --parameters BedrockAgentCDKStack:EmailAddressParam=operations@example.com

# 3. カスタム Agent 名
cdk deploy BedrockAgentCDKStack \
  -c agentName="AI-Ops-Agent" \
  --require-approval never \
  --parameters BedrockAgentCDKStack:EmailAddressParam=operations@example.com
```

### スタック出力

| 出力 | 説明 |
|-----|------|
| `BedrockAgentLambdaArn` | Alert Lambda の ARN |
| `LambdaRoleArn` | Lambda 実行ロール ARN |
| `BedrockAgentRoleArn` | Bedrock Agent IAM Role ARN |
| `agent-assets-xxx-spec-bucket` | API Schema S3 バケット |
| `agent-kb-xxx-kb-bucket` | Knowledge Base S3 バケット |
| `BedrockAgentFunctionArn` | Custom Resource Lambda ARN |

---

## 9. アーキテクチャ図

```
┌─────────────────────────────────────────────────────────────┐
│                      Bedrock Agent                           │
│  ┌──────────────────────────────────────────────────────┐  │
│  │ Foundation Model: Claude 3 Haiku                      │  │
│  │ Instruction: "find if there is any operational      │  │
│  │              issue and fix using runbooks..."       │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
            ↓                          ↓
    ┌──────────────────┐     ┌──────────────────┐
    │ Action Group 1   │     │ Action Group 2   │
    │ GetAlerts        │     │ Remediation      │
    └────────┬─────────┘     └────────┬─────────┘
             ↓                         ↓
    ┌──────────────────┐     ┌──────────────────┐
    │ get-all-alerts   │     │ issue-remediation│
    │ Lambda           │     │ Lambda           │
    └────────┬─────────┘     └────────┬─────────┘
             ↓                         ↓
      ┌──────────────────────┐ ┌──────────────────┐
      │ CloudWatch Alarms    │ │ EC2 Operations   │
      │ (Metrics, Logs)      │ │ (Snapshots,      │
      │                      │ │  Restart)        │
      │ SES (Email)          │ │                  │
      └──────────────────────┘ └──────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      Custom Resource                         │
│  Bedrock Agent + Action Groups の初期化                      │
│  ├─ create_agent()                                          │
│  ├─ create_agent_action_group() × 2                         │
│  └─ create_cloudwatch_alarm()                              │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                    AWS Services                              │
│  ├─ S3: API Schema, Knowledge Base                          │
│  ├─ IAM: Role + Policies                                    │
│  ├─ Lambda: 関数実行                                        │
│  ├─ EC2: インスタンス + CloudWatch                          │
│  ├─ SES: メール送信                                         │
│  └─ Bedrock: Agent + Models                                 │
└─────────────────────────────────────────────────────────────┘
```

---

## 10. 主要な設計パターン

### 10.1 CDK Constructs パターン

- **Reusable Components**: 各機能を独立した Construct に分割
- **Props Interface**: 型安全な設定管理
- **Dependency Management**: `node.addDependency()` で明示的な依存関係管理

### 10.2 Custom Resource パターン

- **Python Lambda**: CDK Stack 作成時に Bedrock Agent を動的作成
- **Create/Update/Delete**: カスタマイズ可能なライフサイクル

### 10.3 Action Group パターン

- **OpenAPI スキーマ**: API 仕様の標準化
- **messageVersion 1.0**: Lambda から Bedrock へのレスポンス形式
- **複数 Lambda**: Alert と Remediation を分離

### 10.4 IAM セキュリティ

- **最小権限**: リソースとアクション を明示的に限定
- **cdk-nag**: セキュリティスキャン + 例外管理
- **リソースベースポリシー**: S3 の非 HTTPS 接続 DENY

---

## 11. 今後の改善提案

### 短期
1. **ユニットテスト追加**: Jest でテストカバレッジ向上
2. **エラーハンドリング**: Lambda に try-catch 追加
3. **ロギング強化**: CloudWatch Logs への詳細出力

### 中期
1. **Knowledge Base 統合**: AI が ランブック検索可能に
2. **複数 Action Group**: RDS、Lambda など他のサービス対応
3. **監視・ダッシュボード**: CloudWatch ダッシュボード追加

### 長期
1. **マルチアカウント**: Organizations への対応
2. **CI/CD パイプライン**: GitHub Actions 統合
3. **ML モデル**: 異常検知の精度向上

---

## 12. ファイル別 URL 参照

| ファイル | URL |
|---------|-----|
| Entry Point | https://github.com/aws-samples/improving-it-operations-efficiency-with-aiops/blob/main/bin/bedrock-agent-cdk.ts |
| Main Stack | https://github.com/aws-samples/improving-it-operations-efficiency-with-aiops/blob/main/lib/bedrock-agent-cdk-stack.ts |
| EC2 Stack | https://github.com/aws-samples/improving-it-operations-efficiency-with-aiops/blob/main/lib/ec2-cdk-stack.ts |
| Lambda Constructs | https://github.com/aws-samples/improving-it-operations-efficiency-with-aiops/tree/main/lib/constructs |
| Alert Lambda | https://github.com/aws-samples/improving-it-operations-efficiency-with-aiops/blob/main/lib/assets/lambdas/agent/alerts/get-all-alerts.py |
| Remediation Lambda | https://github.com/aws-samples/improving-it-operations-efficiency-with-aiops/blob/main/lib/assets/lambdas/agent/remediation/issue-remediation.py |
| Custom Resource | https://github.com/aws-samples/improving-it-operations-efficiency-with-aiops/blob/main/lib/assets/lambdas/cdk-resource-bedrock-agent.py |
| API Schemas | https://github.com/aws-samples/improving-it-operations-efficiency-with-aiops/tree/main/lib/assets/api-schema |

---

## 13. まとめ

このリポジトリは **AWS CDK を使用した Bedrock Agent のエンタープライズ実装例** として以下の特徴があります:

✅ **構造化設計**
- 9 つの独立した Construct に分割
- 型安全な Props インターフェース
- 明示的な依存関係管理

✅ **セキュリティ重視**
- cdk-nag による自動スキャン
- 最小権限の IAM ポリシー
- S3 SSL 強制

✅ **自動化**
- Custom Resource で Agent を動的作成
- CloudFormation ネスティングで複数 Stack 管理
- API スキーマの外部化

✅ **拡張性**
- Action Group パターンで新機能追加が容易
- OpenAPI スキーマで API 契約を明示
- Lambda 関数の独立した管理

📊 **コード品質**
- TypeScript strict mode
- Python 3.13 対応
- Jest テストフレームワーク

---

**レポート作成日**: 2026-06-08  
**分析対象ブランチ**: main  
**GitHub Stars**: 7  
**Forks**: 3  
