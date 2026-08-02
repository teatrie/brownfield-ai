"""
Helper functions for setting up test environments in AWS (via LocalStack/Moto).

These functions initialize mock AWS infrastructure components like Glue databases,
S3 buckets, and RDS clusters directly via boto3 using the configured moto server.
"""

import os

import boto3
from botocore.exceptions import ClientError


def setup_glue_catalog(
    database_name: str,
    table_name: str,
    columns: list,
    partition_keys: list | None = None,
    parameters: dict | None = None,
):
    """
    Creates a mock Glue Database and Table with the specified columns.
    """
    client = _create_client("glue")

    try:
        client.create_database(DatabaseInput={"Name": database_name})
    except ClientError as e:
        if e.response["Error"]["Code"] not in ["AlreadyExistsException"]:
            raise

    # Verify creation to prevent race condition in Moto's internal state
    try:
        client.get_database(Name=database_name)
    except ClientError:
        pass

    table_input = {
        "Name": table_name,
        "StorageDescriptor": {
            "Columns": columns,
            "Location": "s3://mock/",
        },
        "PartitionKeys": partition_keys or [],
        "TableType": "EXTERNAL_TABLE",
    }
    if parameters:
        table_input["Parameters"] = parameters

    client.create_table(
        DatabaseName=database_name,
        TableInput=table_input,
    )


def setup_s3_object(bucket_name: str, object_key: str, object_content: str = "test data"):
    """
    Creates a mock S3 bucket and uploads an object with the specified content.
    """
    client = _create_client("s3")
    try:
        client.create_bucket(Bucket=bucket_name)
    except ClientError as e:
        if e.response["Error"]["Code"] not in ["BucketAlreadyExists", "BucketAlreadyOwnedByYou"]:
            raise

    client.put_object(Bucket=bucket_name, Key=object_key, Body=object_content)


def setup_rds_cluster(cluster_identifier: str):
    """
    Creates a mock RDS Aurora PostgreSQL cluster.
    """
    client = _create_client("rds")
    try:
        client.create_db_cluster(
            DBClusterIdentifier=cluster_identifier,
            Engine="aurora-postgresql",
            MasterUsername="admin",
            MasterUserPassword="password",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] not in ["DBClusterAlreadyExistsFault"]:
            raise


def setup_dynamodb_table(table_name: str, key_schema: list, attribute_definitions: list):
    """
    Creates a mock DynamoDB Table with the specified schema.
    """
    client = _create_client("dynamodb")
    try:
        client.create_table(
            TableName=table_name,
            KeySchema=key_schema,
            AttributeDefinitions=attribute_definitions,
            BillingMode="PAY_PER_REQUEST",
        )
    except ClientError as e:
        if e.response["Error"]["Code"] not in ["ResourceInUseException"]:
            raise


def _create_client(service_name: str):
    """Create a boto3 client configured to connect to the LocalStack Moto server."""
    # Assumes AWS credentials and endpoint URL are set in the environment (e.g., via pytest fixtures).
    # Fail immediately if not configured to avoid silent connection issues.
    return boto3.client(
        service_name,
        region_name=os.environ["AWS_DEFAULT_REGION"],
        endpoint_url=os.environ["AWS_ENDPOINT_URL"],
        aws_access_key_id=os.environ["AWS_ACCESS_KEY_ID"],
        aws_secret_access_key=os.environ["AWS_SECRET_ACCESS_KEY"],
    )
