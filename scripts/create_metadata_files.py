#!/usr/bin/env python3
"""
Create metadata files for Bedrock Knowledge Base.

This script generates .metadata.json files for each runbook document
and uploads them to AWS S3 for the Knowledge Base data source.

AWS S3 Data Source Metadata File Format:
  - Filename: <document-name>.md.metadata.json
  - Location: S3 bucket runbooks/ prefix
  - Format: JSON with metadataAttributes union type

Reference:
  AWS Bedrock Knowledge Base - Document metadata fields
  https://docs.aws.amazon.com/bedrock/latest/userguide/s3-data-source-connector.html
"""

import json
import boto3

# ============================================================================
# Configuration
# ============================================================================

KB_BUCKET = f"aiops-kb-{boto3.client('sts').get_caller_identity()['Account']}-ap-northeast-1-dev"
S3_CLIENT = boto3.client('s3', region_name='ap-northeast-1')
REGION = 'ap-northeast-1'

# ============================================================================
# Metadata Definitions for Runbooks (FR-01 ~ FR-06)
# ============================================================================

metadata_definitions = {
    'FR-01-log-investigation.md': {
        "category": "Log Investigation",
        "priority": 1,
        "applicable_to": ["EC2", "Lambda", "RDS"],
        "difficulty": "Medium",
        "estimated_resolution_time_minutes": 30
    },
    'FR-02-bottleneck-investigation.md': {
        "category": "Bottleneck Investigation",
        "priority": 1,
        "applicable_to": ["EC2", "RDS", "Lambda"],
        "difficulty": "Medium",
        "estimated_resolution_time_minutes": 45
    },
    'FR-03-create-db-snapshot.md': {
        "category": "Database Operations",
        "priority": 2,
        "applicable_to": ["RDS"],
        "difficulty": "Low",
        "estimated_resolution_time_minutes": 15
    },
    'FR-04-maintenance-display.md': {
        "category": "Maintenance Management",
        "priority": 2,
        "applicable_to": ["RDS", "Systems Manager"],
        "difficulty": "Low",
        "estimated_resolution_time_minutes": 10
    },
    'FR-05-slow-query-detection.md': {
        "category": "Database Performance",
        "priority": 1,
        "applicable_to": ["RDS"],
        "difficulty": "High",
        "estimated_resolution_time_minutes": 60
    },
    'FR-06-high-load-query-detection.md': {
        "category": "Database Performance",
        "priority": 1,
        "applicable_to": ["RDS"],
        "difficulty": "High",
        "estimated_resolution_time_minutes": 90
    }
}

# ============================================================================
# Main Execution
# ============================================================================

def main():
    """Create and upload metadata files to S3."""
    
    print("=" * 70)
    print("【メタデータファイル作成 & S3 アップロード】")
    print("=" * 70)
    print(f"Target Bucket: {KB_BUCKET}\n")

    # Delete old metadata files (backward compatibility)
    print("【既存ファイルの削除（古い形式）】")
    for doc_name in metadata_definitions.keys():
        old_key = f'runbooks/{doc_name.replace(".md", "")}.metadata.json'
        
        try:
            S3_CLIENT.head_object(Bucket=KB_BUCKET, Key=old_key)
            S3_CLIENT.delete_object(Bucket=KB_BUCKET, Key=old_key)
            print(f"  🗑️  {old_key}")
        except:
            pass

    # Upload new metadata files in AWS S3 Data Source format
    print("\n【新しいメタデータファイルのアップロード（正しい形式）】")
    for doc_name, metadata in metadata_definitions.items():
        # Build AWS S3 Data Source format metadata structure
        s3_metadata = {
            "metadataAttributes": {}
        }
        
        for key, value in metadata.items():
            if isinstance(value, list):
                # List type - includes in embedding for semantic search
                s3_metadata["metadataAttributes"][key] = {
                    "value": {
                        "type": "STRING_LIST",
                        "stringListValue": value
                    },
                    "includeForEmbedding": True
                }
            elif isinstance(value, (int, float)):
                # Number type - for filtering only, not in embedding
                s3_metadata["metadataAttributes"][key] = {
                    "value": {
                        "type": "NUMBER",
                        "numberValue": value
                    },
                    "includeForEmbedding": False
                }
            else:
                # String type - includes in embedding for semantic search
                s3_metadata["metadataAttributes"][key] = {
                    "value": {
                        "type": "STRING",
                        "stringValue": str(value)
                    },
                    "includeForEmbedding": True
                }
        
        # Filename format: <document-name>.md.metadata.json
        # This is AWS S3 Data Source standard format
        key = f'runbooks/{doc_name}.metadata.json'
        
        try:
            S3_CLIENT.put_object(
                Bucket=KB_BUCKET,
                Key=key,
                Body=json.dumps(s3_metadata, indent=2),
                ContentType='application/json'
            )
            print(f"  ✅ {key}")
        except Exception as e:
            print(f"  ❌ {key}: {str(e)}")

    # Verify uploaded files
    print("\n【S3 にアップロードされたファイル一覧】")
    response = S3_CLIENT.list_objects_v2(
        Bucket=KB_BUCKET,
        Prefix='runbooks/',
    )

    docs = {}
    for obj in response.get('Contents', []):
        path = obj['Key']
        if '.metadata.json' in path:
            doc_name = path.replace('runbooks/', '').replace('.metadata.json', '')
            if doc_name not in docs:
                docs[doc_name] = {}
            docs[doc_name]['metadata'] = '✓'
        else:
            doc_name = path.replace('runbooks/', '')
            if doc_name not in docs:
                docs[doc_name] = {}
            docs[doc_name]['document'] = '✓'

    print("\nドキュメント | ドキュメント本体 | メタデータ")
    print("-" * 60)
    for doc in sorted(docs.keys()):
        has_doc = '✓' if docs[doc].get('document') else '✗'
        has_meta = '✓' if docs[doc].get('metadata') else '✗'
        print(f"{doc:40} | {has_doc:15} | {has_meta}")

    print("\n✅ メタデータアップロード完了")


if __name__ == '__main__':
    main()
