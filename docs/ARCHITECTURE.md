# Architecture

```text
 RealSense camera / joint_states / task prompt
                   │
           ROS 2 Humble Bridge
         [timestamp sync, queue]
                   │
          /v1/predict over LAN
                   ▼
           Inference Service
   [registry -> adapter -> preprocessing]
     ├── mock                   (test only)
     ├── LeRobot ACT            (planned)
     ├── LeRobot Diffusion      (planned)
     ├── LeRobot π₀.₅           (planned)
     └── custom Gemma 4 E2B    (research)
                   │
  [denormalized, typed action chunk]
                   ▼
       Bridge action validator
                   ▼
       Controller adapter router
         ├── joint trajectory
         └── MoveIt Servo
                   ▼
         simulated / real Piper
```

## Ownership rules

**Bridge**: selected model ID and robot config; owns observation timestamps, deadline, stale-response filtering, safe motor state, executing only an approved prefix of a predicted chunk. Never converts untyped floats directly to hardware commands.

**Server**: registry, model lifecycle (unload/reload while idle), checkpoint integrity and license metadata, model-native preprocessing, normalization/denormalization, action schema and generation. Must not initiate motor commands. Separate per-model process/container when dependency environments conflict.

**Controller adapters**: selected by explicitly registered `action.kind` and frame convention, never from vector length or model family; Robot-side dynamic limits, E-stop, and collision guards are independent.

## Model switch lifecycle

IDLE -> requested model ID -> registry verification -> load -> warmup -> introspect input/output schema -> READY. In-flight requests and execution must be cancelled when switching; no mid-episode hot switch by default. Reject unknown, incompatible or unpublished remote URLs.

## Time synchronization

Record image capture timestamp, joint-state timestamp, bridge send time and response receipt time in a common time domain (ROS simulation time must be distinguished from wall clock). Reject stale or future-dated observations. Action chunk starts against a defined robot state and epoch. Never replay an old chunk after reconnect.

## Robot autonomy

For initial research, selected VLA alone decides task-level actions. Safety limits, kinematic interpolation, fixed low-level servo controllers and operator E-stop remain mandatory. No SAM3/Nav2/FlexBE task-planning fallback during evaluation.

## Model adapter contract

```python
class PolicyAdapter(Protocol):
    def metadata(self) -> ModelMetadata: ...
    def load(self) -> None: ...
    def infer(self, observation: Observation, task: str) -> ActionChunk: ...
    def unload(self) -> None: ...
```

Future adapters can wrap third-party policies without forking this bridge. Pass action quantities with units and named joints; do not erase normalization or frame metadata.

## Related references

- https://github.com/huggingface/lerobot
- https://github.com/Physical-Intelligence/openpi
- https://moveit.picknik.ai/humble/doc/examples/realtime_servo/realtime_servo_tutorial.html
