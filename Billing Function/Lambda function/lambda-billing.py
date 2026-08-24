from datetime import datetime, timezone
import json
import os
import logging
import boto3
import pymysql

logger = logging.getLogger()
logger.setLevel(logging.INFO)

DB_SECRET_NAME = os.environ["DB_SECRET_NAME"]
AWS_REGION = os.environ.get("AWS_REGION", "ap-south-1")

secrets_client = boto3.client(
    "secretsmanager",
    region_name=AWS_REGION
)

connection = None
db_credentials = None


def get_db_credentials():
    global db_credentials

    if db_credentials is None:
        response = secrets_client.get_secret_value(
            SecretId=DB_SECRET_NAME
        )
        db_credentials = json.loads(response["SecretString"])

    return db_credentials


def get_db_connection():

    credentials = get_db_credentials()

    connection = pymysql.connect(
        host=credentials["host"],
        user=credentials["db_username"],
        password=credentials["db_password"],
        database=credentials.get("database", "saas_database"),
        port=int(credentials.get("port", 3306)),
        connect_timeout=10,
        read_timeout=10,
        write_timeout=10,
        autocommit=False,
        cursorclass=pymysql.cursors.DictCursor
    )

    return connection


def insert_usage_record(data):
    print("Incoming data:", data)

    conn = None

    try:
        conn = get_db_connection()

        sql = """
            INSERT INTO tenant_usage (
                event_id,
                tenant_id,
                user_id,
                action,
                api_path,
                http_method,
                status_code,
                usage_units,
                created_at
            )
            VALUES (
                %s, %s, %s, %s, %s,
                %s, %s, %s, %s
            )
            ON DUPLICATE KEY UPDATE
                event_id = event_id
        """

        values = (
            data["event_id"],
            data.get("tenant_id"),
            data.get("user_id"),
            data.get("action"),
            data.get("api_path"),
            data.get("http_method"),
            data.get("status_code"),
            data.get("usage_units", 1),
            data.get("created_at") or datetime.now(timezone.utc)
        )

        cursor = conn.cursor()
        cursor.execute(sql, values)

        conn.commit()

        cursor.close()
        conn.close()

        print("Usage record inserted successfully")

    except Exception as e:
        print("Database error:", str(e))

        if conn:
            conn.rollback()
            conn.close()

        raise e

    try:
        with conn.cursor() as cursor:
            cursor.execute(sql, values)

        conn.commit()

    except Exception:
        conn.rollback()
        raise


def lambda_handler(event, context):

    batch_failures = []

    for record in event.get("Records", []):

        message_id = record.get("messageId")

        try:
            data = json.loads(record["body"])

            required_fields = [
                "event_id",
                "tenant_id",
                "user_id",
                "action",
                "api_path",
                "http_method",
                "status_code",
                "usage_units"
            ]

            missing = [
                field for field in required_fields
                if field not in data
            ]

            if missing:
                raise ValueError(
                    f"Missing required fields: {missing}"
                )

            insert_usage_record(data)

            logger.info(
                "Usage event processed: %s",
                data["event_id"]
            )

        except Exception as e:

            logger.exception(
                "Failed processing message %s: %s",
                message_id,
                str(e)
            )

            batch_failures.append({
                "itemIdentifier": message_id
            })

    return {
        "batchItemFailures": batch_failures
    }