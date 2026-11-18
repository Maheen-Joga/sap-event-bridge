"""Checks that template.yaml and the Python code agree. The template is linted separately
with cfn-lint in CI; these tests catch drift between the two."""

import importlib
from pathlib import Path

import pytest
import yaml

from sapbridge import handler
from sapbridge.mock_source import EVENTBRIDGE_SOURCE

TEMPLATE = Path(__file__).resolve().parent.parent / "template.yaml"


class _Loader(yaml.SafeLoader):
    pass


def _intrinsic(loader, suffix, node):
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node, deep=True)
    else:
        value = loader.construct_mapping(node, deep=True)
    return {suffix: value}


_Loader.add_multi_constructor("!", _intrinsic)


@pytest.fixture(scope="module")
def resources():
    return yaml.load(TEMPLATE.read_text(), Loader=_Loader)["Resources"]


def of_type(resources, resource_type):
    return {k: v for k, v in resources.items() if v["Type"] == resource_type}


def test_lambda_environment_matches_what_the_handler_reads(resources):
    (function,) = of_type(resources, "AWS::Lambda::Function").values()
    names = set(function["Properties"]["Environment"]["Variables"])
    assert names == {handler.ENV_TABLE, handler.ENV_BUCKET, handler.ENV_DLQ}


def test_lambda_handler_path_resolves_to_a_real_function(resources):
    (function,) = of_type(resources, "AWS::Lambda::Function").values()
    module_name, function_name = function["Properties"]["Handler"].rsplit(".", 1)
    assert callable(getattr(importlib.import_module(module_name), function_name))


def test_rule_matches_the_event_source_the_mock_publishes(resources):
    (rule,) = of_type(resources, "AWS::Events::Rule").values()
    assert rule["Properties"]["EventPattern"]["source"] == [EVENTBRIDGE_SOURCE]


def test_table_keys_match_what_the_handler_writes(resources):
    (table,) = of_type(resources, "AWS::DynamoDB::Table").values()
    keys = {k["AttributeName"]: k["KeyType"] for k in table["Properties"]["KeySchema"]}
    assert keys == {"pk": "HASH", "sk": "RANGE"}


def test_bucket_blocks_all_public_access_and_is_encrypted(resources):
    (bucket,) = of_type(resources, "AWS::S3::Bucket").values()
    block = bucket["Properties"]["PublicAccessBlockConfiguration"]
    assert all(block[k] is True for k in
               ("BlockPublicAcls", "BlockPublicPolicy", "IgnorePublicAcls", "RestrictPublicBuckets"))
    assert bucket["Properties"]["BucketEncryption"]


def test_queues_are_encrypted(resources):
    queues = of_type(resources, "AWS::SQS::Queue")
    assert len(queues) == 2
    assert all(q["Properties"]["SqsManagedSseEnabled"] is True for q in queues.values())


def test_stateful_resources_are_retained_on_delete(resources):
    for kind in ("AWS::DynamoDB::Table", "AWS::S3::Bucket"):
        for resource in of_type(resources, kind).values():
            assert resource["DeletionPolicy"] == "Retain"


def test_iam_policy_is_least_privilege(resources):
    (role,) = of_type(resources, "AWS::IAM::Role").values()
    statements = role["Properties"]["Policies"][0]["PolicyDocument"]["Statement"]
    granted = set()
    for statement in statements:
        actions = statement["Action"] if isinstance(statement["Action"], list) else [statement["Action"]]
        assert "*" not in "".join(actions)
        assert statement["Resource"] != "*"
        granted.update(actions)
    assert granted == {"dynamodb:PutItem", "s3:PutObject", "sqs:SendMessage"}
