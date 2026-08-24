"""
services/kms_service.py
------------------------
Wraps AWS KMS encrypt/decrypt calls for sensitive fields we choose to
encrypt at the application layer in addition to RDS-level encryption
at rest (defense in depth) -- e.g. phone numbers, or any PII field a
tenant flags as sensitive.
"""

import base64

import boto3
from botocore.exceptions import ClientError

from config import config
from logging_config import app_logger


def _get_kms_client():
    return boto3.client("kms", region_name=config.AWS_REGION)


def encrypt_field(plaintext: str) -> str:
    """
    Encrypts a string value with the configured KMS CMK and returns a
    base64-encoded ciphertext suitable for storage in a text column.
    """
    if not plaintext:
        return plaintext

    if config.DEMO_MODE or not config.KMS_KEY_ID:
        # In demo mode we don't have a real CMK -- store a clearly
        # marked pseudo-encrypted value so the data flow is visible
        # without requiring live AWS access.
        return "demo-enc:" + base64.b64encode(plaintext.encode()).decode()

    try:
        client = _get_kms_client()
        response = client.encrypt(KeyId=config.KMS_KEY_ID, Plaintext=plaintext.encode())
        return base64.b64encode(response["CiphertextBlob"]).decode()
    except ClientError:
        app_logger.exception("KMS encryption failed")
        raise


def decrypt_field(ciphertext: str) -> str:
    """Reverses encrypt_field(). Returns the original plaintext string."""
    if not ciphertext:
        return ciphertext

    if ciphertext.startswith("demo-enc:"):
        return base64.b64decode(ciphertext[len("demo-enc:"):]).decode()

    try:
        client = _get_kms_client()
        blob = base64.b64decode(ciphertext)
        response = client.decrypt(CiphertextBlob=blob, KeyId=config.KMS_KEY_ID)
        return response["Plaintext"].decode()
    except ClientError:
        app_logger.exception("KMS decryption failed")
        raise
