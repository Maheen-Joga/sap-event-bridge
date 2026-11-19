"""Command line: `sapbridge generate` prints mock events; `sapbridge demo` runs the whole
pipeline locally against mocked AWS (moto). Nothing here talks to a real AWS account."""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter

from .mock_source import generate_events

REGION = "eu-central-1"


def _count_items(table) -> int:
    total, kwargs = 0, {"Select": "COUNT"}
    while True:
        page = table.scan(**kwargs)
        total += page["Count"]
        if "LastEvaluatedKey" not in page:
            return total
        kwargs["ExclusiveStartKey"] = page["LastEvaluatedKey"]


def _count_objects(s3, prefix: str) -> int:
    paginator = s3.get_paginator("list_objects_v2")
    return sum(page.get("KeyCount", 0) for page in paginator.paginate(Bucket="archive", Prefix=prefix))


def run_demo(n: int, seed: int, invalid_rate: float, duplicates: int) -> dict:
    """Run the pipeline on mocked AWS and return a summary. Requires the `demo` extra."""
    import boto3
    from moto import mock_aws

    from .handler import DUPLICATE, PROCESSED, REJECTED, Pipeline

    with mock_aws():
        table = boto3.resource("dynamodb", region_name=REGION).create_table(
            TableName="events",
            KeySchema=[{"AttributeName": "pk", "KeyType": "HASH"}, {"AttributeName": "sk", "KeyType": "RANGE"}],
            AttributeDefinitions=[{"AttributeName": "pk", "AttributeType": "S"},
                                  {"AttributeName": "sk", "AttributeType": "S"}],
            BillingMode="PAY_PER_REQUEST",
        )
        s3 = boto3.client("s3", region_name=REGION)
        s3.create_bucket(Bucket="archive", CreateBucketConfiguration={"LocationConstraint": REGION})
        sqs = boto3.client("sqs", region_name=REGION)
        queue_url = sqs.create_queue(QueueName="dlq")["QueueUrl"]
        pipeline = Pipeline(table=table, s3=s3, sqs=sqs, bucket="archive", queue_url=queue_url)

        events = generate_events(n, seed=seed, invalid_rate=invalid_rate)
        outcomes = Counter()
        processed = []
        for event in events:
            result = pipeline.handle(event)
            outcomes[result] += 1
            if result == PROCESSED:
                processed.append(event)

        resent = processed[:duplicates]  # redeliver events that were already stored
        for event in resent:
            outcomes[pipeline.handle(event)] += 1

        attributes = sqs.get_queue_attributes(QueueUrl=queue_url, AttributeNames=["ApproximateNumberOfMessages"])
        return {
            "unique_events": len(events),
            "resent": len(resent),
            "processed": outcomes[PROCESSED],
            "duplicate": outcomes[DUPLICATE],
            "rejected": outcomes[REJECTED],
            "table_items": _count_items(table),
            "raw_objects": _count_objects(s3, "raw/"),
            "rejected_objects": _count_objects(s3, "rejected/"),
            "dlq_messages": int(attributes["Attributes"]["ApproximateNumberOfMessages"]),
            "by_type": dict(sorted(Counter(e["type"] for e in processed).items())),
        }


def render_demo(summary: dict) -> str:
    lines = [
        f"Sent {summary['unique_events']} events, then re-sent {summary['resent']} of them (simulated redelivery)",
        f"  processed  {summary['processed']:>4}",
        f"  duplicate  {summary['duplicate']:>4}   (detected, not stored twice)",
        f"  rejected   {summary['rejected']:>4}   (invalid; archived and sent to the dead-letter queue)",
        "",
        f"DynamoDB items    {summary['table_items']:>4}   (equals processed)",
        f"S3 raw/ objects   {summary['raw_objects']:>4}",
        f"S3 rejected/      {summary['rejected_objects']:>4}",
        f"DLQ messages      {summary['dlq_messages']:>4}",
        "",
        "Processed by type:",
    ]
    lines += [f"  {name:<34}{count:>4}" for name, count in summary["by_type"].items()]
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="sapbridge", description="Mock SAP event pipeline (synthetic data).")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, help_text in (("generate", "print mock events as JSON lines"),
                            ("demo", "run the pipeline locally on mocked AWS")):
        command = sub.add_parser(name, help=help_text)
        command.add_argument("--n", type=int, default=50, help="number of events (default 50)")
        command.add_argument("--seed", type=int, default=1)
        command.add_argument("--invalid-rate", type=float, default=0.1)
        if name == "demo":
            command.add_argument("--duplicates", type=int, default=5, help="events to re-send (default 5)")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "generate":
            for event in generate_events(args.n, seed=args.seed, invalid_rate=args.invalid_rate):
                print(json.dumps(event))
            return 0
        try:
            summary = run_demo(args.n, args.seed, args.invalid_rate, args.duplicates)
        except ImportError:
            print('error: the demo needs boto3 and moto. Install them with: pip install -e ".[demo]"',
                  file=sys.stderr)
            return 1
        print(render_demo(summary))
        return 0
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
