"""The processing pipeline behind the Lambda function.

For each event delivered by EventBridge (the CloudEvent is in `detail`):

1. Validate it. An invalid event is archived under `rejected/` and sent to the dead-letter
   queue with the reason. The handler returns normally, so EventBridge does not retry it:
   retrying cannot fix bad data.
2. Archive the raw event in S3 under `raw/dt=<date>/type=<type>/<id>.json`.
3. Store it in DynamoDB with a conditional write, so a re-delivered event is detected
   (status "duplicate") and does not create a second item.

Transient failures (DynamoDB or S3 errors) are not caught. The exception fails the
invocation and EventBridge retries it, which is what we want for those.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from typing import Any

from botocore.exceptions import ClientError

from .events import Event, EventError, validate_event

ENV_TABLE = "TABLE_NAME"
ENV_BUCKET = "ARCHIVE_BUCKET"
ENV_DLQ = "DLQ_URL"

PROCESSED = "processed"
DUPLICATE = "duplicate"
REJECTED = "rejected"


def _sort_key(event: Event) -> str:
    return f"{event.time.strftime('%Y-%m-%dT%H:%M:%S.%fZ')}#{event.id}"


class Pipeline:
    def __init__(self, *, table: Any, s3: Any, sqs: Any, bucket: str, queue_url: str):
        self._table = table
        self._s3 = s3
        self._sqs = sqs
        self._bucket = bucket
        self._queue_url = queue_url

    def handle(self, detail: Any) -> str:
        try:
            event = validate_event(detail)
        except EventError as exc:
            self._reject(detail, exc)
            return REJECTED

        self._s3.put_object(
            Bucket=self._bucket,
            Key=f"raw/dt={event.time:%Y-%m-%d}/type={event.type}/{event.id}.json",
            Body=json.dumps(detail, sort_keys=True).encode("utf-8"),
            ContentType="application/json",
        )
        try:
            self._table.put_item(
                Item={
                    "pk": event.entity_key,
                    "sk": _sort_key(event),
                    "event_id": event.id,
                    "type": event.type,
                    "source": event.source,
                    "subject": event.subject,
                    "occurred_at": event.time.isoformat(),
                    "data": json.dumps(event.data, sort_keys=True),
                },
                ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)",
            )
        except ClientError as exc:
            if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
                return DUPLICATE
            raise
        return PROCESSED

    def _reject(self, detail: Any, error: EventError) -> None:
        raw = json.dumps(detail, sort_keys=True, default=str)
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self._s3.put_object(
            Bucket=self._bucket,
            Key=f"rejected/dt={today}/{digest}.json",
            Body=raw.encode("utf-8"),
            ContentType="application/json",
        )
        self._sqs.send_message(
            QueueUrl=self._queue_url,
            MessageBody=json.dumps({"error": str(error), "detail": detail}, default=str),
            MessageAttributes={"error_path": {"DataType": "String", "StringValue": error.path}},
        )


_pipeline: Pipeline | None = None


def _default_pipeline() -> Pipeline:
    global _pipeline
    if _pipeline is None:
        import boto3

        _pipeline = Pipeline(
            table=boto3.resource("dynamodb").Table(os.environ[ENV_TABLE]),
            s3=boto3.client("s3"),
            sqs=boto3.client("sqs"),
            bucket=os.environ[ENV_BUCKET],
            queue_url=os.environ[ENV_DLQ],
        )
    return _pipeline


def lambda_handler(event: Any, context: Any = None) -> dict[str, str]:
    detail = event.get("detail") if isinstance(event, dict) else None
    return {"status": _default_pipeline().handle(detail)}
