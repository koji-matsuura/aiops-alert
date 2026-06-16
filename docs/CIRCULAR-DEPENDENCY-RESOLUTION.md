# CloudFormation 循環依存の解決パターン

## 問題

ネストスタック間で Output と Parameter が互いに参照する場合、循環依存エラーが発生します。

```yaml
【エラー例】
E3004 Circular Dependencies for resource SecretsManagerStack

【原因】
SlackWebhookStack:
  Outputs: WebhookLambdaRoleArn
  
SecretsManagerStack:
  Parameters: WebhookLambdaRoleArn (← SlackWebhookStack から取得)
  Outputs: SlackCredentialsSecretArn
  
SlackWebhookStack:
  Parameters: SlackCredentialsSecretArn (← SecretsManagerStack から取得)

【構造】
SlackWebhookStack --参照--> SecretsManagerStack --参照--> SlackWebhookStack
```

## 解決方法

### **推奨：Principal を Parameter としてハードコード可能にする**

```yaml
【アプローチ】
1. Role ARN は環境に応じて決定可能
2. AWSAccountId + EnvironmentName から ARN を構成
3. CloudFormation Parameter として外部から注入
4. 循環参照を回避

【実装】
secrets-manager.yaml:
  Parameters:
    AWSAccountId: 
      Type: String
      Default: '582765029153'
    EnvironmentName:
      Type: String
      Default: dev
  
  Resources:
    SlackCredentialsSecretPolicy:
      Principal:
        AWS: !Sub 'arn:aws:iam::${AWSAccountId}:role/aiops-webhook-lambda-role-${EnvironmentName}'

main.yaml:
  SecretsManagerStack:
    Parameters:
      AWSAccountId: !Ref AWS::AccountId
      EnvironmentName: !Ref EnvName
```

**利点**:
- ✅ CloudFormation のみで完結（手動作業なし）
- ✅ IaC 原則を守る
- ✅ 循環依存なし
- ✅ 環境ごとに柔軟に対応可能

### **代替案 1：Principal を Service Principal に変更**

```yaml
Principal:
  Service: lambda.amazonaws.com
```

**欠点**: 同じアカウント内のすべての Lambda に権限を付与（セキュリティ上不適切）

### **代替案 2：デプロイ後に手動設定**

```bash
aws secretsmanager put-resource-policy \
  --secret-id aiops/dev/slack \
  --resource-policy '{...}'
```

**欠点**: 
- ❌ 手動作業（IaC 原則に反する）
- ❌ 自動化されない
- ❌ デプロイ後の追加ステップが必要

## 根本的な理由：AWS Secrets Manager の Principal 検証

AWS は Secrets Manager Policy を作成する際、Principal の ARN が「有効か」を検証します。

```
【検証プロセス】
1. CloudFormation が SlackCredentialsSecretPolicy を処理
2. Zelkova（AWS の自動推論エンジン）が Principal ARN を検証
3. ロールがまだ作成されていない場合 → "unsupported principal" エラー
4. ロールが存在しない → "unsupported principal" エラー
```

**つまり**:
- Principal ARN は「確定した値」である必要がある
- 存在しないロールを参照することはできない
- 循環参照で「どちらを先に作成すればいい」を決められない場合、手詰まり

## ベストプラクティス

1. **ネストスタック間の Output 参照は最小限に**
   - 必要なデータだけを Parameter として外部から注入
   
2. **ロール ARN は事前に決定可能に**
   - Account ID + Role Name Prefix で構成可能にする
   - Output に依存しない

3. **複雑な依存関係は分離**
   - スタックを分割する
   - Policy 設定は別のスタックで管理する

4. **検証は cfn-lint で**
   ```bash
   cfn-lint cfn-templates/*.yaml
   ```

## 参考

- AWS CloudFormation DependsOn: https://docs.aws.amazon.com/AWSCloudFormation/latest/TemplateReference/aws-attribute-dependson.html
- Implicit Dependency: `!Ref`, `!GetAtt`, `!Sub` は自動的に依存関係を作成
- Explicit Dependency: `DependsOn` 属性で明示的に指定

