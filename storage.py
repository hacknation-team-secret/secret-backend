import os

import boto3
from dotenv import load_dotenv

load_dotenv()

def get_tigris_client():
    """
    Returns a boto3 client configured for Tigris storage.
    """
    endpoint_url = os.getenv("TIGRIS_STORAGE_ENDPOINT")
    access_key_id = os.getenv("TIGRIS_STORAGE_ACCESS_KEY_ID")
    secret_access_key = os.getenv("TIGRIS_STORAGE_SECRET_ACCESS_KEY")

    if not all([endpoint_url, access_key_id, secret_access_key]):
        # We don't raise an error here to allow the app to start without Tigris
        # but we might want to log a warning.
        return None

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key_id,
        aws_secret_access_key=secret_access_key,
        region_name="auto",
    )

# Singleton instance
tigris_client = get_tigris_client()
