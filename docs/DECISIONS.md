# Design decisions

Short records of the choices that were not obvious, and what they cost.

## 1. A CloudEvents-style envelope inside EventBridge `detail`
EventBridge already has its own envelope. Putting a CloudEvent in `detail` keeps the payload
portable: the same JSON could travel over HTTP or Kafka. The cost is a little redundancy
(`detail-type` repeats `type`).

## 2. The handler sends invalid events to the dead-letter queue itself
Letting an invalid event fail the invocation would make EventBridge and Lambda retry it, and
retrying cannot fix bad data. So the handler returns normally and sends the event and the
reason to a queue. Transient failures are the opposite: they raise, so they are retried.
The cost is that "success" no longer means "stored", so the return value says which of
`processed`, `duplicate` or `rejected` happened.

## 3. DynamoDB keyed by purchase order, one item per event, conditional put
Storing every event (not just the latest state) keeps history and makes the write idempotent:
`attribute_not_exists` on the key rejects a redelivery. One query returns an order's events in
time order. The cost is that "current state" must be derived by reading the history. The
sort key is built from the event time and id, so the same event id with a different `time`
would not be detected as a duplicate. The mock source never does that.

## 4. Archive to S3 before writing to DynamoDB
If the DynamoDB write fails after the archive succeeds, the retry archives the same key again
(idempotent overwrite) and then writes. The raw copy therefore exists for every event that
was accepted, even if the item write is retried.

## 5. CloudFormation, linted offline
CDK and Terraform are common choices. Plain CloudFormation can be checked with `cfn-lint` in CI
without credentials or a toolchain beyond pip, and a test checks that the template and the Python
code agree (environment variable names, table keys, event source). The cost is verbosity.

## 6. moto, not LocalStack, for tests
moto runs in-process under pytest with no Docker. It is not the real AWS: behaviour differs in
edge cases such as throttling and eventual consistency, which is why the README says the stack
has not been deployed to a real account.
