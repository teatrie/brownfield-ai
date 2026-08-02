import os

import boto3


def get_client(service_name: str):
    """
    Returns boto3 client for the specified AWS service.
    Configured to connect to LocalStack if AWS_ENDPOINT_URL is set.
    Args:
        service_name (str): The name of the AWS service (e.g., "s3", "rds", "dynamodb").
    """
    endpoint_url = os.environ.get("AWS_ENDPOINT_URL")
    region_name = os.environ.get("AWS_DEFAULT_REGION", "us-east-1")
    if endpoint_url:
        # If AWS_ENDPOINT_URL is set, we're in a testing environment.
        return boto3.client(service_name, endpoint_url=endpoint_url, region_name=region_name)
    return boto3.client(service_name, region_name=region_name)
