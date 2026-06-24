# INTEGRATION DIAGRAMS
**System**: Lambda + Bedrock Agent AIOps Platform  
**Date**: 2026-06-24  
**Version**: v2.8.0

---

## DIAGRAM 1: CloudFormation Stack Dependencies

```
┌────────────────────────────────────────────────────────────┐
│                    main.yaml (Orchestrator)                │
│  Parameters: EnvName, FoundationModel, VectorIndexName     │
└────────────────────────────────────────────────────────────┘
           │
           ├──────────────────┬──────────────────┐
           ▼                  ▼                  ▼
      ┌─────────┐        ┌──────────┐      ┌──────────┐
      │ S3Stack │        │ SQSDLQStack  │  │SecretsStack│
      └─────────┘        └──────────┘      └──────────┘
           │                  │                  │
           │              (DLQArn)          (SecretArn)
           │                  │                  │
           ▼                  │                  ▼
      ┌──────────────────────────┐      ┌───────────────────┐
      │ KnowledgeBaseStack       │      │SlackWebhookStack  │
      ├──────────────────────────┤      └───────────────────┘
      │ - SecurityPolicies       │              │
      │ - OpensearchCollection   │              │
      │ - OpensearchIndex        │              ▼
      │ - BedrockKnowledgeBase   │      ┌──────────────────────┐
      │ - DataSource (S3)        │      │ChatbotSlackNotifStack│
      └──────────────────────────┘      └──────────────────────┘
           │
           │
      (KnowledgeBaseId)
           │
           ▼
      ┌──────────────────────────┐
      │ BedrockAgentStack        │
      ├──────────────────────────┤
      │ - BedrockAgentRole       │
      │ - BedrockAgent           │
      │ - ActionGroups (6x)      │
      │   ├─ LogInvestigation    │
      │   ├─ BottleneckAnalysis  │
      │   ├─ CreateSnapshot      │
      │   ├─ MaintenanceDisplay  │
      │   ├─ SlowQueryDetection  │
      │   └─ HighLoadQueryAnalysis│
      └──────────────────────────┘
           │
           │
      (AgentId)
           │
           ▼
      ┌──────────────────────────┐
      │ LambdaStack              │
      ├──────────────────────────┤
      │ - AiopsLambda            │
      │ - LambdaExecutionRole    │
      │ - Permissions            │
      │   ├─ bedrock:InvokeAgent │
      │   ├─ aoss:APIAccessAll   │
      │   ├─ sns:Publish         │
      │   └─ sqs:SendMessage     │
      └──────────────────────────┘
           │
           │
      (LambdaARN)
           │
           ▼
      ┌──────────────────────────┐
      │ EventBridgeAlarmsStack   │
      ├──────────────────────────┤
      │ 7 Rules:                 │
      │ ├─ EC2-HighCPU           │
      │ ├─ RDS-HighCPU           │
      │ ├─ RDS-HighConnections   │
      │ ├─ RDS-ReplicationLag    │
      │ ├─ Lambda-ErrorRate      │
      │ ├─ Lambda-Throttle       │
      │ └─ (1 more)              │
      └──────────────────────────┘
```

**Critical Notes**:
- S3Stack must deploy FIRST (provides BucketArn)
- KnowledgeBaseStack depends on S3 (bucket)
- KnowledgeBaseStack must complete before BedrockAgentStack (KB ID needed)
- BedrockAgentStack uses `!Sub` (not GetAtt) to break circular dependency with LambdaStack
- LambdaStack depends on BedrockAgentStack (Agent ID needed)
- LambdaStack must complete before EventBridgeAlarmsStack (Lambda ARN needed)

---

## DIAGRAM 2: Lambda Message Routing

```
┌──────────────────────────────────────────────────────────────┐
│            Lambda handler(event, context)                    │
│            Entry Point (Lines 48-103)                        │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │ Check: messageVersion == '1.0'?      │
        └──────────────────────────────────────┘
                     YES│         │NO
                       │         │
        ┌──────────────▼─┐    ┌─▼───────────────────────┐
        │   EXECUTION    │    │   ORCHESTRATION PATH    │
        │      PATH      │    │   (EventBridge/Alarms)  │
        └────────────────┘    └────────────────────────┘
             │                        │
             │                        ▼
             │                  extract_event_info()
             │                  (Lines 106-138)
             │                        │
             │                        ├─ version, id
             │                        ├─ source, detail-type
             │                        ├─ account, time, region
             │                        ├─ resources, detail
             │                        │
             │                        ▼
             │                  build_prompt()
             │                  (Lines 142-175)
             │                        │
             │                        ├─ "【イベント受信】"
             │                        ├─ Event details in NL
             │                        ├─ KB search hints
             │                        │
             │                        ▼
             │                  invoke_bedrock_agent()
             │                  (Lines 178-227)
             │                        │
             │                        ├─ bedrock_agent_runtime
             │                        │  .invoke_agent()
             │                        ├─ sessionId
             │                        ├─ inputText (prompt)
             │                        ├─ enableTrace
             │                        │
             │                        ▼
             │                  notify_result()
             │                  (Lines 230-251)
             │                        │
             │                        └─ SNS publish
             │
             ▼
    handle_bedrock_agent_message()
    (Lines 1330-1457)
             │
             ├─ Extract: actionGroup
             ├─ Extract: function_name
             ├─ Extract: parameters[]
             │
             ▼
    Convert parameters to dict
    (Lines 1402-1407)
             │
             ▼
    dispatch_function()
    (Lines 1460-1513)
             │
             ├─ Lookup function_map
             │  ├─ LogInvestigation → log_investigation_fr01
             │  ├─ BottleneckAnalysis → bottleneck_investigation_fr02
             │  ├─ CreateSnapshot → create_db_snapshot_fr03
             │  ├─ MaintenanceDisplay → maintenance_window_display_fr04
             │  ├─ SlowQueryDetection → slow_query_detection_fr05
             │  └─ HighLoadQueryAnalysis → high_load_query_detection_fr06
             │
             ▼
    Execute FR function
    (FR-01 to FR-06)
             │
             ├─ AWS API calls (Logs, Metrics, PI, etc.)
             ├─ Error handling & fallbacks
             ├─ Result aggregation
             │
             ▼
    Build messageVersion 1.0 response
    (Lines 1412-1434)
             │
             ├─ responseState: SUCCESS/FAILURE
             ├─ functionResponse.responseBody.TEXT.body
             │
             ▼
    Return to Bedrock Agent
```

---

## DIAGRAM 3: Bedrock Agent RAG Search Flow

```
┌──────────────────────────────────────────────────────────────┐
│  Bedrock Agent Decision Point                               │
│  (Claude Haiku 4.5, using Agent Instruction)                │
└──────────────────────────────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Parse prompt from Lambda:           │
        │  "EC2-HighCPU alarm detected"        │
        └──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  RETRIEVE Stage (RAG)                │
        │  Knowledge Base Search               │
        └──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  1. Embed query (1024-dim)           │
        │     Titan Embed v2 Model             │
        │     Query: "EC2 CPU high issue"      │
        │                                       │
        │  2. OpenSearch k-NN Search           │
        │     - vector_field (similarity)      │
        │     - metadata_field filter          │
        │       applicable_to contains "EC2"   │
        │                                       │
        │  3. Return top-5 results:            │
        │     - FR-02 (bottleneck)  score 0.92 │
        │     - FR-01 (logs)        score 0.89 │
        │     - FR-06 (high load)   score 0.85 │
        │     - FR-03 (snapshot)    score 0.72 │
        │     - FR-04 (maintenance) score 0.68 │
        └──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  READ Stage (Runbook Content)        │
        │  Load FR-02, FR-01 markdown          │
        │  Parse metadata attributes:          │
        │  - priority (1 = highest)            │
        │  - category (Bottleneck, Log)        │
        │  - applicable_to (EC2, RDS, Lambda)  │
        └──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  GENERATE Stage (LLM Reasoning)      │
        │                                       │
        │  Using Instruction prompt:           │
        │  "Action priority:                   │
        │   1. FR-01 (log investigation)       │
        │   2. FR-02 (bottleneck)              │
        │   3. FR-05 (slow queries)            │
        │   ..."                               │
        │                                       │
        │  Agent decision:                     │
        │  "Execute FR-01 first (priority),    │
        │   then FR-02 for deeper analysis"    │
        └──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  ACTION Stage (Call Lambda)          │
        │  Invoke Lambda via Action Group      │
        │  with messageVersion 1.0 payload:    │
        │  {                                    │
        │    function: "LogInvestigation",     │
        │    parameters: [                     │
        │      log_group, log_stream, 3600     │
        │    ]                                 │
        │  }                                    │
        └──────────────────────────────────────┘
                           │
                           ▼
        [Lambda executes FR-01, returns result]
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Agent synthesizes findings:         │
        │  "45 errors found (FR-01),           │
        │   now checking bottlenecks..."       │
        └──────────────────────────────────────┘
                           │
                           ▼
        [Same process: Invoke FR-02]
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Agent combines results:             │
        │  - FR-01: 45 connection errors       │
        │  - FR-02: CPU 92%, Network HIGH      │
        │  Root cause: Resource exhaustion     │
        │  Recommendation: Scale up EC2        │
        └──────────────────────────────────────┘
                           │
                           ▼
        SNS Notification with findings
```

---

## DIAGRAM 4: Complete End-to-End Flow

```
                    ┌─────────────────────┐
                    │  CloudWatch Alarm   │
                    │  EC2-HighCPU        │
                    │  State: OK → ALARM  │
                    └─────────────────────┘
                           │
                           ▼
                    ┌─────────────────────┐
                    │ EventBridge Rule    │
                    │ Pattern Match:      │
                    │ source: aws.        │
                    │ cloudwatch          │
                    │ alarmName prefix:   │
                    │ EC2-HighCPU         │
                    └─────────────────────┘
                           │
                           ▼
           ┌───────────────────────────────────┐
           │  Lambda handler(event)            │
           │                                   │
           │  Detects: NO messageVersion       │
           │  Routes: ORCHESTRATION PATH       │
           │                                   │
           │  1. extract_event_info()          │
           │     → AWS fields extracted        │
           │                                   │
           │  2. build_prompt()                │
           │     → Natural language prompt     │
           │                                   │
           │  3. invoke_bedrock_agent()        │
           │     → Call Agent                  │
           └───────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Bedrock Agent (Claude Haiku 4.5)   │
        │                                      │
        │  1. RAG Search:                      │
        │     OpenSearch k-NN + metadata       │
        │     → FR-01, FR-02 retrieved         │
        │                                      │
        │  2. Reasoning:                       │
        │     Using Agent Instruction         │
        │     → FR-01 priority > FR-02         │
        │                                      │
        │  3. Action: Invoke FR-01             │
        └──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Lambda handler(event)               │
        │                                      │
        │  Detects: messageVersion == '1.0'    │
        │  Routes: EXECUTION PATH              │
        │                                      │
        │  1. handle_bedrock_agent_message()   │
        │     → Parse function name            │
        │                                      │
        │  2. dispatch_function()              │
        │     → "LogInvestigation"             │
        │        = log_investigation_fr01()    │
        │                                      │
        │  3. Execute FR-01:                   │
        │     - CloudWatch Logs API call       │
        │     - Error filtering                │
        │     - Result aggregation             │
        │                                      │
        │  4. Return messageVersion 1.0        │
        │     responseState: SUCCESS           │
        │     body: {error_count: 45}          │
        └──────────────────────────────────────┘
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Bedrock Agent                       │
        │                                      │
        │  1. Receives FR-01 result:           │
        │     45 errors found                  │
        │                                      │
        │  2. Reasoning:                       │
        │     "Errors serious, need metrics"   │
        │                                      │
        │  3. Action: Invoke FR-02             │
        │     (BottleneckAnalysis)             │
        └──────────────────────────────────────┘
                           │
                    [Repeat Lambda flow]
                           │
                    [FR-02 returns result]
                           │
                           ▼
        ┌──────────────────────────────────────┐
        │  Bedrock Agent                       │
        │                                      │
        │  1. Synthesizes:                     │
        │     FR-01 + FR-02 → findings         │
        │                                      │
        │  2. Formats recommendations          │
        │                                      │
        │  3. Publishes SNS notification       │
        │     with complete analysis           │
        └──────────────────────────────────────┘
                           │
                           ▼
                    ┌─────────────────────┐
                    │  SNS Topic          │
                    │  dev-aiops-report   │
                    │                     │
                    │  Message: JSON      │
                    │  - findings         │
                    │  - recommendations  │
                    │  - actions taken    │
                    └─────────────────────┘
                           │
                   ┌───────┴───────┐
                   ▼               ▼
            [Email]         [Slack Webhook]
                   │               │
        Operators receive notification
```

---

## DIAGRAM 5: Metadata Flow Through System

```
S3 Storage
  runbooks/
  ├─ FR-01-log-investigation.md
  ├─ FR-01-log-investigation.md.metadata.json
  │  {
  │    "category": "Log Investigation",
  │    "applicable_to": ["EC2", "Lambda", "RDS"],
  │    "priority": 1
  │  }
  ├─ FR-02-bottleneck-investigation.md
  ├─ FR-02-bottleneck-investigation.md.metadata.json
  │  {
  │    "category": "Bottleneck Investigation",
  │    "applicable_to": ["EC2", "RDS", "Lambda"],
  │    "priority": 1
  │  }
  └─ ... (6 runbooks + metadata)
           │
           ▼
CloudFormation (knowledge-base.yaml)
  ├─ BedrockKnowledgeBase
  ├─ DataSource (S3 runbooks/)
       │
       │ AWS Bedrock scans:
       │ ├─ Detects *.md files
       │ ├─ Detects *.md.metadata.json
       │ ├─ Parses metadata attributes
       │
       ▼
OpenSearch Serverless Collection
  Vector Index: aiops-kb-index
  Document storage:
  ├─ vector_field: 1024-dim k-NN vector
  │  (from Titan Embed v2)
  │
  ├─ text_field: Document content
  │  "# Log Investigation Guide..."
  │
  └─ metadata_field: Metadata JSON
     {
       "category": "Log Investigation",
       "applicable_to": ["EC2", "Lambda", "RDS"],
       "priority": 1
     }
           │
           ▼
Agent RAG Search
  1. Query: "EC2 CPU high" → embed to 1024-dim
  
  2. Filters:
     applicable_to CONTAINS "EC2"
     
  3. k-NN search in vector_field
     Top-5 by cosine similarity
     
  4. Ranking:
     - metadata filter (EC2)
     - similarity score (0.92 best)
     - priority field (1 = highest)
     
  5. Results:
     [1] FR-02 (0.92) ← Best match
     [2] FR-01 (0.89)
     [3] FR-06 (0.85) ← Also EC2-compatible
     [4] FR-03 (0.72)
     [5] FR-04 (0.68)
           │
           ▼
Agent Decision
  "FR-02 best match + highest priority
   Execute now"
           │
           ▼
Lambda: log_investigation_fr01(...)
         bottleneck_investigation_fr02(...)
         ...
```

---

## DIAGRAM 6: Error Propagation Paths

```
┌─────────────────────────────────────────┐
│  Error Scenarios & Recovery Paths       │
└─────────────────────────────────────────┘

SCENARIO 1: CloudWatch Logs API Failure
  ├─ try: logs_client.get_log_events()
  ├─ except: ResourceNotFoundException
  ├─ return: {"status": "error", "error": "..."}
  ├─ wrap: messageVersion 1.0 FAILURE
  ├─ agent: receives error, may retry
  └─ sns: notification with error details

SCENARIO 2: Bedrock Agent Invocation Error
  ├─ try: invoke_agent()
  ├─ except: TimeoutError, ServiceUnavailable
  ├─ lambda: returns 500 status
  ├─ eventbridge: retry (configurable)
  ├─ dlq: message goes to Dead Letter Queue
  └─ operator: reviews DLQ for manual intervention

SCENARIO 3: Missing Agent Parameter
  ├─ Agent calls: FR-01 without log_group_name
  ├─ FR-01: uses empty string
  ├─ CloudWatch: returns error
  ├─ FR-01: catches, logs specific error
  ├─ return: {"status": "error"}
  ├─ Agent: "Parameter missing, reprompt?"
  └─ sns: incomplete investigation report

SCENARIO 4: OpenSearch Search Failure
  ├─ Agent: tries KB retrieval
  ├─ OpenSearch: collection offline (rare)
  ├─ Agent: graceful fallback to default prompt
  ├─ Execution continues without RAG
  └─ Quality degraded but functional

RECOVERY LAYERS:
  1. Function-level: try/except in FR-01~06
  2. Lambda-level: handle_bedrock_agent_message exception
  3. Agent-level: retry logic, reprompting
  4. EventBridge-level: rule retry policy
  5. DLQ: capture unrecoverable failures
  6. Monitoring: CloudWatch Logs + SNS alerts
```

---

## DIAGRAM 7: OpenSearch Index Architecture

```
OpenSearch Serverless Collection
  └─ VECTORSEARCH type (required for k-NN)
     │
     └─ Collection Endpoint (managed)
        │
        └─ Security Policies
           ├─ EncryptionSecurityPolicy
           ├─ NetworkSecurityPolicy
           └─ DataAccessPolicy (IAM)
              │
              └─ Index: aiops-kb-index
                 │
                 ├─ Settings:
                 │  ├─ knn: true
                 │  ├─ Engine: faiss
                 │  ├─ Name: hnsw
                 │  └─ SpaceType: l2
                 │
                 └─ Mappings:
                    │
                    ├─ vector_field (knn_vector)
                    │  ├─ Dimension: 1024 (Titan v2)
                    │  ├─ Method: HNSW
                    │  └─ Distance: L2 (Euclidean)
                    │
                    ├─ text_field (text)
                    │  ├─ Analyzer: standard
                    │  └─ Content: Document body
                    │
                    └─ metadata_field (text)
                       ├─ Content: Metadata JSON
                       ├─ Example:
                       │  {
                       │    "category": "...",
                       │    "priority": 1,
                       │    "applicable_to": [...]
                       │  }
                       └─ Used for: Filtering + ranking

Query Flow:
  Agent query: "EC2 CPU investigation"
       │
       ▼
  Titan Embed v2 Model
  1024-dim vector
       │
       ▼
  OpenSearch Query DSL
  {
    "query": {
      "knn": {
        "vector_field": {
          "vector": [0.12, 0.34, ...],  ← 1024 values
          "k": 5
        }
      },
      "bool": {
        "filter": {
          "term": {
            "metadata_field.applicable_to": "EC2"
          }
        }
      }
    }
  }
       │
       ▼
  HNSW Graph Search
  (fast approximate nearest neighbor)
       │
       ▼
  Top-5 Results
  [Ranked by similarity + metadata]
```

---

**All diagrams completed** | **System v2.8.0** | **Date: 2026-06-24**

