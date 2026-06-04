---
name: cfncheck
description: CloudFormationファイルの作成・編集時に、AWS MCPサーバーを用いて正確なリソース仕様を確認し、cfn-lintによる静的解析で構文とベストプラクティスを自動検証するスキルです。
license: MIT
compatibility: ">=1.0.0"
metadata:
  category: "IaC / DevOps"
  tools: "aws-mcp-server, cfn-lint"
  language: "yaml, json"
---

# AWS CloudFormation Developer & Validator Skill

## 1. 概要 (Overview)
AWS CloudFormation（以下、CFn）テンプレートの作成および編集において、AWS MCP（Model Context Protocol）サーバーを活用して正確なリソース定義を行い、`cfn-lint` を用いて構文およびベストプラクティスの検証を徹底します。

## 2. 対象（トリガー条件）
* 拡張子が `.yaml`, `.yml`, `.json` のファイルを対象に、AWS CloudFormation テンプレートを新規作成、または編集・修正する場合。
* ユーザーからAWSリソースのインフラ構築コード（IaC）の生成・レビューを求められた場合。

## 3. コア・ワークフロー (Core Workflow)
CFnファイルを扱う際は、必ず以下の3ステップのサイクルを遵守してください。

### ステップ 1: AWS MCPサーバーによるリソース仕様の確認
リソースを追加・編集する前に、必ず **AWS MCPサーバー** のツールやリソースを活用し、最新かつ正しいリソース定義（プロパティ、データ型、必須項目、制約条件）を確認します。
* **行動:** 独自の記憶や古い知識だけに頼らず、MCPサーバーから正確なスキーマやリファレンスを取得する。

### ステップ 2: テンプレートの作成・編集
ステップ1で確認した正しい仕様に基づき、可読性が高く再利用可能なCFnテンプレート（YAML推奨）を記述します。
* **考慮事項:** `Outputs`, `Parameters`, `Mappings` を適切に活用し、ハードコーディングを避ける。

### ステップ 3: `cfn-lint` による静的解析と修正
コードを確定またはユーザーに提示する前に、必ず環境内で `cfn-lint` コマンドを実行し、構文エラーや警告（Wxxxx, Exxxx）がないか確認します。
* **コマンド例:** `cfn-lint path/to/template.yaml`
* **行動:** * エラーや警告が出力された場合は、その内容を分析し、**ステップ1（MCP確認）に戻って** 正しい定義へ修正する。
  * `cfn-lint` でエラー（全件パス）がなくなるまでこのサイクルを繰り返す。

## 4. 行動原則 (Rules & Principles)
* **妥協のない検証:** 「おそらく正しい」コードを出力しない。必ず `cfn-lint` でクリーンであることを確認してから最終回答とする。
* **最新仕様の追求:** AWS MCPサーバーを活用し、非推奨（Deprecated）になったプロパティの使用を避け、最新のAWSベストプラクティス（セキュリティ、コスト最適化など）を反映する。
* **エラーの透明性:** 万が一 `cfn-lint` のエラーが解消できない場合は、その理由と現在のエラーログをユーザーに明示し、相談すること。