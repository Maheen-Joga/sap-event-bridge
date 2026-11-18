import json
from types import SimpleNamespace

import boto3
import pytest
from boto3.dynamodb.conditions import Key
from moto import mock_aws

from sapbridge import handler
from sapbridge.handler import DUPLICATE, PROCESSED, REJECTED, Pipeline
from sapbridge.mock_source import generate_events

REGION = "eu-central-1"


@pytest.fixture
def aws(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", REGION)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "testing")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "testing")
    monkeypatch.setattr(handler, "_pipeline", None)
    with mock_aws():
        table = boto3.resource("dynamodb").create_table(
            TableName="events",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                  {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3")
        s3.create_bucket(Bucket="archive", CreateBucketConfiguration={"LocationConstraint": REGION})
        sqs = boto3.client("sqs")
        queue_url = sqs.create_queue(QueueName="dlq")["QueueUrl"]
        yield SimpleNamespace(
            table=table, s3=s3, sqs=sqs, queue_url=queue_url,
            pipeline=Pipeline(table=table, s3=s3, sqs=sqs, bucket="archive", queue_url=queue_url),
        )


def keys(aws, prefix):
    listing = aws.s3.list_objects_v2(Bucket="archive", Prefix=prefix)
    return [obj["Key"] for obj in listing.get("Contents", [])]


def dlq_messages(aws):
    response = aws.sqs.receive_message(QueueUrl=aws.queue_url, MaxNumberOfMessages=10,
                                       MessageAttributeNames=["All"])
    return response.get("Messages", [])


def test_valid_event_is_stored_and_archived(aws):
    event = generate_events(1, seed=1)[0]
    assert aws.pipeline.handle(event) == PROCESSED

    items = aws.table.scan()["Items"]
    assert len(items) == 1
    assert items[0]["event_id"] == event["id"]
    assert json.loads(items[0]["data"])["po_id"] == event["data"]["po_id"]

    (raw_key,) = keys(aws, "raw/")
    assert raw_key.endswith(f"/{event['id']}.json")
    body = aws.s3.get_object(Bucket="archive", Key=raw_key)["Body"].read()
    assert json.loads(body) == event


def test_redelivered_event_is_detected_and_not_stored_twice(aws):
    event = generate_events(1, seed=1)[0]
    assert aws.pipeline.handle(event) == PROCESSED
    assert aws.pipeline.handle(event) == DUPLICATE
    assert aws.table.scan()["Count"] == 1
    assert len(keys(aws, "raw/")) == 1


def test_invalid_event_goes_to_dlq_and_rejected_archive_not_to_table(aws):
    event = generate_events(1, seed=1)[0]
    event["data"]["po_id"] = "ABC"
    assert aws.pipeline.handle(event) == REJECTED

    assert aws.table.scan()["Count"] == 0
    assert keys(aws, "raw/") == []
    assert len(keys(aws, "rejected/")) == 1
    (message,) = dlq_messages(aws)
    body = json.loads(message["Body"])
    assert "$.data.po_id" in body["error"]
    assert body["detail"]["id"] == event["id"]
    assert message["MessageAttributes"]["error_path"]["StringValue"] == "$.data.po_id"


@pytest.mark.parametrize("detail", [None, "not an object", 42, ["list"]])
def test_non_object_detail_is_rejected_without_crashing(aws, detail):
    assert aws.pipeline.handle(detail) == REJECTED
    assert len(dlq_messages(aws)) == 1


def test_events_for_one_purchase_order_share_a_key_and_sort_by_time(aws):
    events = generate_events(60, seed=9)
    for event in events:
        aws.pipeline.handle(event)
    po_id = events[0]["data"]["po_id"]
    related = [e for e in events if e["data"]["po_id"] == po_id]
    assert len(related) >= 2
    items = aws.table.query(KeyConditionExpression=Key("pk").eq(f"PO#{po_id}"))["Items"]
    assert [i["event_id"] for i in items] == [e["id"] for e in related]


def test_lambda_handler_unwraps_the_eventbridge_envelope(aws, monkeypatch):
    monkeypatch.setenv(handler.ENV_TABLE, "events")
    monkeypatch.setenv(handler.ENV_BUCKET, "archive")
    monkeypatch.setenv(handler.ENV_DLQ, aws.queue_url)
    event = generate_events(1, seed=1)[0]
    envelope = {"version": "0", "source": "sapbridge.mock", "detail-type": event["type"], "detail": event}
    assert handler.lambda_handler(envelope, None) == {"status": "processed"}
    assert handler.lambda_handler({"detail-type": "x"}, None) == {"status": "rejected"}
    assert handler.lambda_handler("garbage", None) == {"status": "rejected"}


def test_transient_aws_errors_are_not_swallowed(aws):
    event = generate_events(1, seed=1)[0]
    aws.s3.delete_bucket(Bucket="archive")
    with pytest.raises(Exception):
        aws.pipeline.handle(event)
