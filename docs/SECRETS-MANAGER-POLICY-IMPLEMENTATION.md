# Secrets Manager Resource Policy 実装ガイド

## 問題

CloudFormation で Secrets Manager ResourcePolicy を直接定義すると、循環依存エラーが発生します。

```
【エラー】
E3004 Circular Dependencies for resource SecretsManagerStack
```

### 根本原因

```
【依存構造】
SlackWebhookStack:
  ├─ WebhookLambdaRole 作成
  └─ パラメータ: SlackCredentialsSecretArn (!GetAtt SecretsManagerStack)

SecretsManagerStack:
  └─ SlackCredentialsSecretPolicy
     └─ Principal: arn:aws:iam::...:role/aiops-webhook-lambda-role-${EnvironmentName}

【循環】
SlackWebhookStack → SecretsManagerStack (!GetAtt)
SecretsManagerStack → SlackWebhookStack (Principal 参照)
```

## 解決方法

### **実装: Lambda 初期化での Policy 設定**

CloudFormation デプロイ後、Lambda 関数の初期化処理で Resource Policy を設定します。

```python
# Lambda 初期化コード
import boto3
import json

secrets_client = boto3.client('secretsmanager', region_name='ap-northeast-1')

def setup_secret_policy():
    """Set up Secrets Manager resource policy during Lambda initialization"""
    
    policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AllowLambdaRead",
                "Effect": "Allow",
                "Principal": {
                    "AWS": f"arn:aws:iam::582765029153:role/aiops-webhook-lambda-role-dev"
                },
                "Action": "secretsmanager:GetSecretValue",
                "Resource": "*"
            }
        ]
    }
    
    try:
        response = secrets_client.put_resource_policy(
            SecretId='aiops/dev/slack',
            ResourcePolicy=json.dumps(policy)
        )
        print(f"✅ Policy attached successfully: {response['ARN']}")
    except Exception as e:
        print(f"⚠️ Policy attachment may have failed: {e}")
        # Not critical - manual setup allowed
```

### **代替: 手動設定**

```bash
aws secretsmanager put-resource-policy \
  --secret-id aiops/dev/slack \
  --resource-policy '{
    "Version": "2012-10-17",
    "Statement": [
      {
        "Effect": "Allow",
        "Principal": {
          "AWS": "arn:aws:iam::582765029153:role/aiops-webhook-lambda-role-dev"
        },
        "Action": "secretsmanager:GetSecretValue",
        "Resource": "*"
      }
    ]
  }'
```

## 検証

```bash
# Policy が設定されているか確認
aws secretsmanager get-resource-policy \
  --secret-id aiops/dev/slack
```

## 参考

- AWS ドキュメント: https://docs.aws.amazon.com/secretsmanager/latest/userguide/auth-and-access_resource-policies.html
- Principal 形式: `arn:aws:iam::ACCOUNT_ID:role/ROLE_NAME`
- Zelkova 検証: AWS は Principal を自動検証し、存在しないロール ARN は「unsupported principal」エラーを出す
