# GitHub Repository Analysis: improving-it-operations-efficiency-with-aiops

## EXECUTIVE SUMMARY

**Repository**: https://github.com/aws-samples/improving-it-operations-efficiency-with-aiops
**Language**: TypeScript (CDK) + Python (Lambda)
**Test Framework**: Jest (configured but no tests present)
**Deployment Model**: AWS CDK (NOT CloudFormation templates)
**Foundation Model**: Claude 3 Haiku (anthropic.claude-3-haiku-20240307-v1:0)

---

## KEY FINDING: SINGLE INPUT MODE ONLY

🚨 **CRITICAL DIFFERENCE FROM AIOPS-ALERT AGENTS.MD**

The GitHub repository implements **ONLY 1 input mode**:
- ✅ **USER INPUT MODE** (Bedrock Agent Console interaction)
- ❌ **NO CloudWatch Alarms auto-trigger mode**
- ❌ **NO Scheduled execution mode**

The repository demonstrates a **reactive, manual trigger pattern**, NOT an automated monitoring pipeline.

---

## 1. USER INPUT MODE

### Status: ✅ FULLY IMPLEMENTED

**Evidence Found**: Complete end-to-end flow

#### 1.1 Entry Point: User Query to Bedrock Agent

**Location**: `lib/bedrock-agent-cdk-stack.ts` lines 53-65

```typescript
const appStack = new BedrockAgentCdkStack(app, `BedrockAgentCDKStack`, {
  specAlertFile: specAlertFile,
  specRemediationFile: specRemediationFile,
  alertslambdaFile: alertslambdaFile,
  remediationlambdaFile: remediationlambdaFile,
  instruction:"find if there is any operational issue and fix using runbooks. It is manadatory to strictly follow runbook and do not perform any step not mentioned in runbook.",
  ec2InstanceId: ec2Stack.ec2.instanceId,
  // ...
});
```

**User Interaction Flow**:
1. User logs into Bedrock Agent Console
2. User enters query: "find any operational issue in account and fix issue as per knowledgebase"
3. Bedrock Agent receives query directly (NOT via Lambda)
4. Agent processes with Knowledge Base + Action Groups

#### 1.2 Agent Creation (Custom Resource)

**Location**: `lib/assets/lambdas/cdk-resource-bedrock-agent.py` lines 81-92

```python
def create_agent(agent_resource_role_arn, agent_name, instruction):
  response = agent_client.create_agent(
    agentName=agent_name,
    agentResourceRoleArn=agent_resource_role_arn,
    foundationModel="anthropic.claude-3-haiku-20240307-v1:0",
    description="Agent created by CDK.",
    idleSessionTTLInSeconds=1800,
    instruction=instruction,
  )
  return response['agent']['agentId']
```

**Agent Properties**:
- **Name**: `cdk-agent-{randomPrefix}` or custom via context
- **Model**: Claude 3 Haiku (NOT Haiku 4.5)
- **Session TTL**: 1800 seconds (30 minutes)
- **Instruction**: "find if there is any operational issue and fix using runbooks..."

#### 1.3 Action Groups Configuration

**Location**: `lib/assets/lambdas/cdk-resource-bedrock-agent.py` lines 96-113

```python
def create_agent_action_group(agent_id, lambda_arn, bucket, key, group_name, group_description):
    agent_client.create_agent_action_group(
        agentId=agent_id,
        agentVersion='DRAFT',
        actionGroupExecutor={
            'lambda': lambda_arn
        },
        actionGroupName=group_name,
        apiSchema={
            's3': {
                's3BucketName': bucket,
                's3ObjectKey': key
            }
        },
        description=group_description
    )
```

**Action Groups Created** (2 total):
1. **GetAlertsActionGroup** (Lambda: `get-all-alerts.py`)
   - Description: "Get a list of all resources in AWS account in alert state and send email notificaitons..."
   - API Schema: `/get_all_alerts` (GET)

2. **RemediationActionGroup** (Lambda: `issue-remediation.py`)
   - Description: "APIs for managing EC2 and take remediation steps to fix operational issues"
   - API Schema: `/create_snapshot_of_EC2_volume` (POST), `/restart_ec2_instance` (POST)

---

## 2. CLOUDWATCH ALARMS MODE

### Status: ❌ NOT IMPLEMENTED

**Evidence**: 
- ❌ No EventBridge Rules in CDK constructs
- ❌ No EventBridge configuration for automatic alarm detection
- ❌ Alarms are created for demo purposes only, NOT as triggers

#### 2.1 CloudWatch Alarm Creation (Demo Only)

**Location**: `lib/assets/lambdas/cdk-resource-bedrock-agent.py` lines 115-138

```python
def create_cloudwatch_alarm(instanceId):
    cloudwatch = boto3.client('cloudwatch')
    cloudwatch.put_metric_alarm(
        AlarmName='Web_Server_CPU_Utilization',
        ComparisonOperator='GreaterThanThreshold',
        EvaluationPeriods=2,
        DatapointsToAlarm=1,
        MetricName='CPUUtilization',
        Namespace='AWS/EC2',
        Period=60,
        Statistic='Maximum',
        Threshold=90.0,
        ActionsEnabled=False,  # ⚠️ DISABLED - No automatic actions!
        AlarmDescription='Alarm when server CPU exceeds 90%',
        Dimensions=[
            {'Name': 'InstanceId', 'Value': instanceId},
        ]
    )
```

**Key Issue**: `ActionsEnabled=False`
- Alarms are created but **NOT connected to any trigger**
- They exist for **demonstration/testing purposes only**
- User must manually check alerts in CloudWatch Console

#### 2.2 Alert Detection (Manual Query Only)

**Location**: `lib/assets/lambdas/agent/alerts/get-all-alerts.py` lines 8-23

```python
if (event['apiPath']=='/get_all_alerts'):
    cw_client = boto3.client('cloudwatch')
    response = cw_client.describe_alarms(
        AlarmNames=['Web_Server_CPU_Utilization'],
        StateValue='ALARM'  # Query ALARM state
    )
    if (len(response["MetricAlarms"])==0):
        response_body = {
            'application/json': {
                'body': 'There no no operational issue in AWS account, all alarms are in OK state'
            }
        }
    else:
        response_body = {
            'application/json': {
                'body': json.dumps([
                    {
                        'ID': response["MetricAlarms"][0]["Dimensions"][0]["Value"],
                        'ResourceType': 'EC2',
                        'State': 'High CPU Utilization, instance in alert state'
                    }
                ])
            }
        }
```

**Query Pattern**:
- Agent calls `/get_all_alerts` endpoint via Action Group
- Lambda queries `describe_alarms()` with specific alarm name
- Returns alert status (ALARM or OK)
- **This is pull-based, not push-based**
- **Requires user to ask agent for alerts**

#### 2.3 Why No Auto-Trigger

No EventBridge Rule implementation:
```typescript
// NOT FOUND in codebase:
// - AWS::Events::Rule
// - EventBridgeRule construct
// - SNS subscription
// - Lambda invoke policies for EventBridge
```

---

## 3. SCHEDULED EXECUTION MODE

### Status: ❌ NOT IMPLEMENTED

**Evidence**: 
- ❌ No cron expressions found
- ❌ No EventBridge Schedule Rule
- ❌ No Scheduled Lambda function
- ❌ No periodic batch job configuration

**Search Results**:
```bash
grep -r "cron\|Schedule\|Scheduled\|periodic" /lib --include="*.ts" --include="*.py"
# Result: (no matches)
```

---

## 4. MESSAGE FORMAT SPECIFICATION

### 4.1 Lambda Request Format (messageVersion 1.0)

**Location**: `lib/assets/lambdas/agent/alerts/get-all-alerts.py` lines 4-67

The Lambda functions receive the following event structure:

```python
# Inbound Event (FROM Bedrock Agent)
event = {
    'apiPath': '/get_all_alerts',  # API endpoint being called
    'actionGroup': 'GetAlertsActionGroup',  # Action Group name
    'httpMethod': 'GET',  # HTTP method
    'requestBody': {  # Only for POST requests
        'content': {
            'application/json': {
                'properties': [
                    {'value': 'param1'},
                    {'value': 'param2'}
                ]
            }
        }
    },
    'promptSessionAttributes': {...}  # Session context
}
```

### 4.2 Lambda Response Format (messageVersion 1.0)

**Location**: `lib/assets/lambdas/agent/alerts/get-all-alerts.py` lines 61-77

```python
api_response = {
    'messageVersion': '1.0',  # Required: Message format version
    'response': {
        'actionGroup': event['actionGroup'],
        'apiPath': event['apiPath'],
        'httpMethod': event['httpMethod'],
        'httpStatusCode': 200,
        'responseBody': {
            'application/json': {
                'body': 'response content here'  # Can be JSON string or plain text
            }
        }
    },
    'promptSessionAttributes': event['promptSessionAttributes']  # Echoed back
}
```

**Example Response**:
```json
{
  "messageVersion": "1.0",
  "response": {
    "actionGroup": "GetAlertsActionGroup",
    "apiPath": "/get_all_alerts",
    "httpMethod": "GET",
    "httpStatusCode": 200,
    "responseBody": {
      "application/json": {
        "body": "[{\"ID\": \"i-1234567890abcdef0\", \"ResourceType\": \"EC2\", \"State\": \"High CPU Utilization\"}]"
      }
    }
  },
  "promptSessionAttributes": {...}
}
```

---

## 5. LAMBDA FUNCTION INVENTORY

### 5.1 Lambda Functions Deployed

| Function | File | Trigger | Purpose | Action Group |
|----------|------|---------|---------|--------------|
| Alert Lambda | `get-all-alerts.py` | Bedrock Agent Action Group | Query CloudWatch alarms; Send email notifications | GetAlertsActionGroup |
| Remediation Lambda | `issue-remediation.py` | Bedrock Agent Action Group | Create EC2 snapshots; Restart EC2 instances | RemediationActionGroup |
| Custom Resource Lambda | `cdk-resource-bedrock-agent.py` | CDK Custom Resource | Deploy Bedrock Agent & Action Groups during stack creation | N/A (CDK infrastructure) |

### 5.2 Alert Lambda Handler

**Location**: `lib/assets/lambdas/agent/alerts/get-all-alerts.py`

**Handler Signature**:
```python
def lambda_handler(event, context):
```

**Actions Supported** (via apiPath):

1. **GET /get_all_alerts** (lines 8-23)
   - Queries CloudWatch for `Web_Server_CPU_Utilization` alarm
   - Returns list of resources in ALARM state
   - Returns: `[{ID, ResourceType, State}]`

2. **POST /send-Notification** (lines 25-58)
   - Sends email via SES
   - Extracts email subject/body from requestBody
   - Returns: "email notification sent"

**Key Code**:
```python
if (event['apiPath']=='/get_all_alerts'):
    # Query alarms logic
else:
    # Send email logic
    client = boto3.client('ses')
    response = client.send_email(
        Destination={'ToAddresses': [os.environ.get('EMAIL_ADDRESS')]},
        Message={
            'Body': {'Text': {'Data': event['requestBody']['content']['application/json']['properties'][2]['value']}},
            'Subject': {'Data': event['requestBody']['content']['application/json']['properties'][0]['value']}
        },
        Source=os.environ.get('EMAIL_ADDRESS')
    )
```

### 5.3 Remediation Lambda Handler

**Location**: `lib/assets/lambdas/agent/remediation/issue-remediation.py`

**Handler Signature**:
```python
def lambda_handler(event, context):
```

**Actions Supported** (via apiPath):

1. **POST /create_snapshot_of_EC2_volume** (lines 8-22)
   - Extracts EC2 instance ID from requestBody
   - Gets volume ID from instance metadata
   - Creates EBS snapshot
   - Returns: Snapshot ID

2. **POST /restart_ec2_instance** (lines 23-34)
   - Extracts EC2 instance ID from requestBody
   - Calls `reboot_instances()`
   - Returns: "instance restarted"

**Key Code**:
```python
if (event['apiPath']=='/create_snapshot_of_EC2_volume'):
    instanceid = event['requestBody']['content']['application/json']['properties'][0]['value']
    if (len(instanceid.split('/'))>1):
        instanceid = instanceid.split('/')[1]
    volume_id = ec2.describe_instances(InstanceIds=[instanceid])['Reservations'][0]['Instances'][0]['BlockDeviceMappings'][0]['Ebs']['VolumeId']
    response = ec2.create_snapshot(VolumeId=volume_id)
    response_body = {
        'application/json': {
            'body': response['SnapshotId']
        }
    }
```

---

## 6. API SCHEMA DEFINITIONS

### 6.1 Operations API Schema

**Location**: `lib/assets/api-schema/operations-api.json`

**Endpoints**:

1. **GET /get_all_alerts** (lines 9-43)
   ```json
   {
     "summary": "Get a list of all resources in AWS account in alert state",
     "operationId": "get_all_alerts",
     "responses": {
       "200": {
         "schema": {
           "type": "array",
           "items": {
             "properties": {
               "ID": "unique ID of the AWS resource",
               "ResourceType": "EC2, DynamoDB table, Lambda Function",
               "State": "High CPU utilization, throttling or high error rate"
             }
           }
         }
       }
     }
   }
   ```

2. **POST /send-Notification** (lines 45-105)
   ```json
   {
     "summary": "Send Notification to operations team",
     "operationId": "sendNotification",
     "requestBody": {
       "properties": {
         "emailaddress": "email address to send notifications",
         "subject": "subject of email notification",
         "email_body": "body of email notification"
       }
     }
   }
   ```

### 6.2 Remediation API Schema

**Location**: `lib/assets/api-schema/remediation-api.json`

**Endpoints**:

1. **POST /create_snapshot_of_EC2_volume** (lines 10-57)
   ```json
   {
     "summary": "Create snapshot of EBS volume of affected EC2 instance",
     "operationId": "create_snapshot_of_EC2_volume",
     "requestBody": {
       "properties": {
         "instanceARN": "arn of affected EC2 instance"
       }
     }
   }
   ```

2. **POST /restart_ec2_instance** (lines 59-106)
   ```json
   {
     "summary": "Restart affected ec2 instance",
     "operationId": "restart_ec2_instance",
     "requestBody": {
       "properties": {
         "instanceARN": "arn of affected EC2 instance"
       }
     }
   }
   ```

---

## 7. KNOWLEDGE BASE INTEGRATION

### 7.1 Manual Knowledge Base Setup (NOT Automated)

**NOTE**: Knowledge Base is **NOT created by CDK**. It must be created manually via AWS Console.

**Setup Process** (from README.md):

1. Create Knowledge Base manually in Bedrock console
   - Name: `knowledge-base-quick-start-xxxx`
   - Model: Titan Embeddings G1 - Text v1.2
   - Vector Store: OpenSearch Serverless

2. Create Data Source
   - S3 bucket: `agent-kb-xxxx-bucket`
   - Prefix: `runbooks/`

3. Add to Agent manually
   - Via "Additional settings" in agent builder
   - Instruction: "Knowledge base contains runbooks to fix operational issues..."

4. Upload runbooks manually
   - No automation in CDK

**Bedrock Agent IAM Permissions** (automated):

**Location**: `lib/constructs/bedrock-agent-iam-construct.ts` lines 64-76

```typescript
const bedrockAgentKBPolicy = new cdk.aws_iam.Policy(this, "BedrockAgentKBPolicy", {
  policyName: "BedrockAgentKBPolicy",
  statements: [
    new cdk.aws_iam.PolicyStatement({
      effect: cdk.aws_iam.Effect.ALLOW,
      resources: [
        `arn:aws:bedrock:${region}:${account}:knowledge-base/*`
      ],
      actions: [
        'bedrock:Retrieve',
      ]
    })
  ]
});
```

---

## 8. TEST COVERAGE

### 8.1 Test Configuration

**Location**: `jest.config.js`

```javascript
module.exports = {
  // Jest config present but empty/minimal
};
```

### 8.2 Test Status

- ❌ **No tests found**
- Search: `find /lib -name "*.test.ts" -o -name "*.spec.ts" -o -name "*test*.py"`
- Result: (no matches)

### 8.3 Test Framework

- **Framework**: Jest (v29.5.0)
- **TypeScript Support**: ts-jest (v29.1.0)
- **Test Count**: 0

---

## 9. ARCHITECTURE COMPARISON

### 9.1 Event Trigger Model

**GitHub Repository**: **PUSH Model (User-Initiated)**
- User enters query in Bedrock Console
- Agent invokes Lambda via Action Groups
- Lambda sends response synchronously
- No automated monitoring

**AIOPS-ALERT AGENTS.MD**: **Hybrid Model (User + Push + Pull)**
- Pattern 1: User input (same as GitHub)
- Pattern 2: CloudWatch Alarms → EventBridge → Lambda (Push)
- Pattern 3: Scheduled cron job → EventBridge → Lambda (Pull)

### 9.2 Notification Method

**GitHub Repository**:
- **Primary**: SES email (via `/send-Notification` action)
- **Triggered by**: Agent decision, called explicitly
- **Example**: `client.send_email(Destination={...}, Message={...})`

**AIOPS-ALERT AGENTS.MD**:
- **Primary**: SNS Topic (AIOpsReport)
- **Triggered by**: Lambda automatically after each action
- **Pattern**: `sns_client.publish(TopicArn=..., Message=...)`

---

## 10. DEPLOYMENT MODEL

### 10.1 Infrastructure as Code

**Approach**: AWS CDK (NOT CloudFormation)

**Stack Structure**:
```
BedrockAgentCDKStack (root)
  ├─ EC2CdkStack
  │  └─ EC2Construct (creates demo EC2 instance)
  └─ BedrockAgentCdkStack
     ├─ SESConstruct (email configuration)
     ├─ S3Construct (Lambda code + API schemas)
     ├─ S3KBConstruct (Knowledge Base bucket)
     ├─ LambdaIamConstruct (Lambda IAM Role)
     ├─ BedrockIamConstruct (Bedrock Agent IAM Role)
     ├─ LambdaConstruct (Alert Lambda)
     ├─ LambdaConstruct (Remediation Lambda)
     └─ CustomBedrockAgentConstruct (Bedrock Agent + Action Groups)
```

### 10.2 Deployment Commands

```bash
npm install
cdk bootstrap
cdk deploy BedrockAgentCDKStack --require-approval never \
  --parameters BedrockAgentCDKStack:EmailAddressParam=operations@example.com
```

### 10.3 Key Difference from AIOPS-ALERT

**GitHub**: CDK-based deployment
```typescript
// AWS CDK
new cdk.CustomResource(this, 'BedrockCustomResource', {
  serviceToken: bedrockAgentCustomResourceProvider.serviceToken
});
```

**AIOPS-ALERT AGENTS.MD**: CloudFormation-based deployment
```yaml
# CloudFormation Templates
BedrockAgent:
  Type: AWS::Bedrock::Agent
  Properties:
    AgentName: AiopsAgent
    ...
```

---

## 11. RESOURCE PROVISIONING SUMMARY

| Resource | Automated by CDK | Manual Setup Required |
|----------|------------------|----------------------|
| EC2 Instance | ✅ | ❌ |
| Lambda Functions (Alert, Remediation) | ✅ | ❌ |
| Bedrock Agent | ✅ (Custom Resource) | ❌ |
| Action Groups | ✅ (Custom Resource) | ❌ |
| S3 Buckets | ✅ | ❌ |
| IAM Roles | ✅ | ❌ |
| SES Configuration | ✅ | ❌ |
| CloudWatch Alarm | ✅ (Demo only) | ❌ |
| **Knowledge Base** | ❌ | ✅ **MANUAL** |
| **KB Data Source** | ❌ | ✅ **MANUAL** |
| **Runbooks Upload** | ❌ | ✅ **MANUAL** |
| EventBridge Rules | ❌ | N/A (Not implemented) |

---

## 12. KEY DIFFERENCES FROM AIOPS-ALERT

| Feature | GitHub Repo | AIOPS-ALERT AGENTS.MD |
|---------|------------|-----------------------|
| **Input Modes** | 1 (User only) | 3 (User + Alarms + Cron) |
| **Auto-Trigger** | ❌ No | ✅ Yes (EventBridge) |
| **Lambda Invocation** | Only from Agent Action Groups | From Agent + EventBridge rules + Cron |
| **Infrastructure** | AWS CDK | CloudFormation templates |
| **Foundation Model** | Claude 3 Haiku | Claude Haiku 4.5 |
| **Message Format** | messageVersion 1.0 | messageVersion 1.0 |
| **Notification** | SES email | SNS topic |
| **KB Setup** | Manual console | CloudFormation automated |
| **EventBridge** | ❌ Not used | ✅ 7 alarm rules + 1 cron rule |
| **Alarm Detection** | Pull-based (agent queries) | Push-based (EventBridge triggers) |
| **Test Coverage** | 0 tests | Unknown (not provided) |
| **Runbooks Count** | Not specified | 6 (FR-01 to FR-06) |

---

## 13. SECURITY & IAM POLICIES

### 13.1 Bedrock Agent Role

**Location**: `lib/constructs/bedrock-agent-iam-construct.ts`

**Permissions**:
- `bedrock:InvokeModel` (foundation model access)
- `lambda:InvokeFunction` (invoke action group lambdas)
- `s3:GetObject` (read API schemas)
- `bedrock:Retrieve` (knowledge base access)

### 13.2 Lambda Role

**Location**: `lib/constructs/lambda-iam-construct.ts`

**Permissions**:
- `cloudwatch:DescribeAlarms`
- `ec2:CreateSnapshot`, `ec2:CreateTags`
- `ec2:DescribeInstances`, `ec2:RebootInstances`, `ec2:StopInstances`, `ec2:StartInstances`
- `ses:SendEmail`
- `logs:CreateLogGroup`, `logs:CreateLogStream`, `logs:PutLogEvents`

---

## 14. CRITICAL FINDINGS & IMPLICATIONS

### Finding 1: No Auto-Monitoring Implementation

❌ GitHub repo does NOT implement automated CloudWatch Alarms → Lambda trigger pipeline
- Only manual query-based alert detection
- User must explicitly ask agent "find any operational issue"
- Production readiness: LIMITED for reactive operations

### Finding 2: Knowledge Base is NOT Automated

❌ Knowledge Base setup is completely manual
- No CDK resource for Knowledge Base creation
- No Data Source definition in code
- Users must upload runbooks via AWS Console
- Production readiness: REQUIRES significant manual overhead

### Finding 3: No Scheduled Maintenance

❌ No periodic/batch job implementation
- No cron schedule support
- No recurring maintenance tasks
- Each operation is on-demand only

### Finding 4: Message Format Compatibility

✅ Both repos use **identical messageVersion 1.0 format**
```
✓ messageVersion: '1.0'
✓ response.actionGroup
✓ response.apiPath
✓ response.httpMethod
✓ response.httpStatusCode
✓ response.responseBody
✓ promptSessionAttributes
```

### Finding 5: Different Architectural Goals

- **GitHub**: Demonstrates "intelligent agent for IT ops analysis"
- **AIOPS-ALERT**: Implements "fully automated AIOps monitoring pipeline"

---

## 15. CODE QUALITY OBSERVATIONS

### Positive
- Clear CDK construct separation
- Proper IAM role isolation
- Type-safe TypeScript definitions
- API schema specifications

### Areas for Improvement
- No error handling in Lambda functions
- Hardcoded values (e.g., `Web_Server_CPU_Utilization`, `MyDemoConfigurationSet`)
- No logging beyond print statements
- No retry logic for API calls
- No resource cleanup procedures

---

## CONCLUSION

The GitHub repository provides a **foundational example** of Bedrock Agent integration with AWS resources, focused on **user-driven interactive queries**. 

The AIOPS-ALERT project extends this with:
1. **Automated event detection** (EventBridge integration)
2. **Scheduled operations** (cron-based maintenance)
3. **Production-grade deployment** (CloudFormation templates)
4. **Full automation pipeline** (end-to-end without manual intervention)

### Recommendation for Comparison Validation

When comparing implementations:
- ✅ Use messageVersion 1.0 format (proven compatibility)
- ✅ Reference Lambda response structure from GitHub repo
- ❌ Do NOT adopt single-mode (user-only) architecture
- ✅ Implement EventBridge for automated triggers (AIOPS-ALERT improvement)
- ✅ Automate Knowledge Base creation (avoid manual setup)

