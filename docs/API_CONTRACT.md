# API contract v0 (provisional)

HTTP JSON is a smoke-test transport. Production transfer of images should use gRPC/Protobuf or efficient binary framing to avoid JSON base64 overhead; freeze v1 only after integration tests.

## GET /health

Returns `{"status":"ok","actuation":false}`. This service **never** executes actions.

## GET /v1/models

Metadata including ID, supported observation keys, action schema, readiness, policy family and checkpoint provenance. Unknown/not-ready model -> error.

## POST /v1/predict

Example *mock* payload (all IDs, timestamps and numeric values synthetic):

```json
{
  "request_id": "smoke-1",
  "model_id": "mock_piper",
  "observation": {
    "timestamp_ns": 1000000000,
    "joint_names": ["joint_1", "joint_2"],
    "joint_positions_rad": [0.0, 0.0],
    "images": {}
  },
  "task": "move test fixture"
}
```

The `images` map will be expanded to binary RGB payload with timestamp, frame ID, encoding, width/height, calibration ID. No image data in server logs by default. State includes gripper calibration and optionally joint velocity.

Example mock response:

```json
{
  "request_id": "smoke-1",
  "model_id": "mock_piper",
  "action_schema": "mock_joint_position_v1",
  "action_kind": "joint_position",
  "joint_names": ["joint_1", "joint_2"],
  "action_hz": 20.0,
  "actions": [[0.0, 0.0], [0.0, 0.0]],
  "source_timestamp_ns": 1000000000,
  "inference_ms": 0.0
}
```

Mock response consists only of fixture data, NOT a safe robot command. All actions must be finite numeric rectangular arrays; values alone do not authorize hardware actuation.

## Action schema

`joint_position`: absolute joint positions **radians**; `joint_delta`: delta radians relative to observation state; `joint_velocity`: rad/s; `ee_pose`/`ee_delta` or `ee_twist`: separate translation metres, orientation representation, frame and angular units. Gripper uses an explicit calibrated independent definition. Joint names/order and robot model ID must match controller config.

Every checkpoint must declare the real observation normalization, action normalization (and inverse), episode horizon, action rate, camera order, trained robot embodiment, license, sha/checkpoint source and adapter version. Reject missing or conflicting metadata.

## Reject / errors

- 400: malformed payload, nonfinite values, unexpected shape
- 404: unknown model ID
- 409: model is not loaded/ready or registry schema mismatch
- 413: oversized frame
- 422: invalid observation or unsupported camera/state features
- 503: inference backend unavailable

Future: request deadlines, session token, sequence number, trace ID, stale observation rejection, model switch protocol, bounded queues and mTLS in non-local deployment.

**Security note:** no remote checkpoint URLs or arbitrary file paths in public request body; model IDs are allowlisted server-side.
