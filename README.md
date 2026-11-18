# sap-event-bridge

A pipeline for **mock** SAP business events on AWS: EventBridge, Lambda, DynamoDB, S3 and a
dead-letter queue. All data is synthetic.

**Status: early development.** Built in small steps; checked items exist and are tested.

- [x] Event schema and strict validation (CloudEvents-style, mock data only)
- [x] Deterministic mock SAP event source, including deliberately bad events
- [x] Pipeline handler: validate, archive to S3, idempotent write to DynamoDB, dead-letter queue
- [x] CloudFormation template, checked with cfn-lint
- [ ] Local demo CLI on mocked AWS
- [ ] CI, architecture, design decisions and cost drivers

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT
