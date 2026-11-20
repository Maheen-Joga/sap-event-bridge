# Cost drivers

This project has **not** been priced or deployed, so there are no dollar figures here. Check the
current AWS pricing pages for your region before deploying.

| Component | What drives the bill |
|---|---|
| EventBridge | Number of custom events put on the bus |
| Lambda | Invocations, plus duration times memory (256 MB, arm64) |
| DynamoDB (on demand) | One write per accepted event, plus storage and point-in-time recovery |
| S3 | Objects stored and `PutObject` requests (one per event); `rejected/` expires after 90 days |
| SQS | Messages sent to the two queues (rejections and failed deliveries) |
| CloudWatch Logs | Log volume; retention is 30 days by default |

Cost per event is roughly constant, so total cost scales linearly with event volume. The retained
DynamoDB table and S3 bucket keep costing storage after the stack is deleted until you remove them.
