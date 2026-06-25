# AIOps-Alert — 開発ガイド

## 概要

Amazon Bedrock AgentCore Runtime を使用した AIOps 基盤。  
CloudWatch アラームを EventBridge で検知し、AI が Knowledge Base を検索して自律的に AWS API を呼び出し、調査・対応を実行する。

**参照ドキュメント：**
- [アーキテクチャ設計](docs/ARCHITECTURE.md)
- [実装詳細](docs/IMPLEMENTATION.md)

---

## システム要件

- Python 3.12
- Docker（AgentCore Runtime コンテナビルド用）
- AWS CLI（`ap-northeast-1`）
- CodePipeline（全デプロイはパイプライン経由）

---

## リポジトリ構造

```
aiops-alert/
├── lambda/                    # Lambda thin proxy（EventBridge → AgentCore）
│   └── handler.py
├── agentcore/                 # AgentCore Runtime コード
│   ├── app.py
│   └── tools/fr_tools.py     # FR-01〜FR-06 AWS API 関数
├── Dockerfile                 # agentcore/ コンテナ化
├── requirements-agentcore.txt
├── cfn-templates/             # CloudFormation テンプレート
│   ├── main.yaml              # ルートスタック
│   ├── agentcore-runtime.yaml # AgentCore Runtime（新規）
│   ├── lambda-function.yaml
│   ├── eventbridge-alarms.yaml
│   ├── knowledge-base.yaml
│   └── ...
├── cfn-pipeline.yml           # CodePipeline 定義（ECR 含む）
├── runbooks/                  # Knowledge Base ドキュメント（FR-01〜FR-06.md）
└── docs/                      # 設計ドキュメント
```

---

## デプロイ方法

**AWS CLI による CloudFormation 直接操作は禁止。**  
コードを修正して GitHub に push → CodePipeline が自動デプロイする。

```bash
git add .
git commit -m "変更内容"
git push origin main
```

---

## Knowledge Base

| 項目 | 値 |
|-----|---|
| Knowledge Base ID | `OQZNQIPJTS` |
| Data Source ID | `9TZ9MCQRGH` |
| OpenSearch Index | `aiops-kb-index` |
| Embedding Model | `amazon.titan-embed-text-v2:0` |

Runbook の追加・更新は `runbooks/` に配置して push すると CodePipeline が S3 に同期する。  
インジェストは手動で実行：
```bash
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id OQZNQIPJTS \
  --data-source-id 9TZ9MCQRGH
```

---

## EventBridge アラーム命名規則

| アラーム種別 | プレフィックス |
|-----------|-------------|
| EC2 高 CPU | `EC2-HighCPU-` |
| RDS 高 CPU | `RDS-HighCPU-` |
| RDS 接続数 | `RDS-HighConnections-` |
| RDS レプリケーション遅延 | `RDS-ReplicationLag-` |
| Lambda エラー率 | `Lambda-ErrorRate-` |
| Lambda スロットル | `Lambda-Throttle-` |

---

## 変更履歴

| バージョン | 日付 | 内容 |
|----------|------|------|
| v3.0.0 | 2026-06-25 | Bedrock Agent → AgentCore Runtime 移行。AI が Knowledge Base を直接検索し AWS API を自律呼び出しする構成に変更。lambda/ と agentcore/ にコードを分離。 |
| v2.8.0 | 2026-06-23 | IaC 準拠完成。メタデータファイルを Git で版管理。 |
| v2.0.0 | 2026-06-14 | Python Lambda に統合。CodePipeline ビルドに Lambda パッケージング処理を追加。 |
| v1.0.0 | 2026-06-02 | CDK 版から CloudFormation 版へ完全移行。 |
