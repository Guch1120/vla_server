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

## WP01 / WP02実装範囲（2026-10-15）

HTTP JSONを初期transportに採用。`Registry.register`でAdapterを明示登録し、
`load → infer → unload`を分離する。現在の二つの登録は合成zero fixtureのみ。
YAMLからコードを動的importしたり、呼出側指定の重みをロードしたりしない。
モデル固有変換はAdapter内に置く。共通画像型のRGB検査はサーバ契約の検査である。
モデル切替・GPU排他ロード・学習済みモデルは未実装。

BridgeはHumble `sensor_msgs/Image`（rgb8）と`JointState`を購読し、
各カメラ最大8フレームと最新関節状態を用いて50ms以内の時刻整合を確認する。
カメラ順序はcamera_namesの順序で固定しRegistryと照合する。
HTTP待機は単一workerに分離し、処理中1件＋最新待機1件に制限。
欠測・通信失敗・期限切れで結果を破棄し、通信失敗時は待機観測も破棄する。
再接続時はメタデータを再取得し、新しい観測のみ送信する。
HOLDはdry-run内部状態であり、実機停止コマンドを実装したものではない。

`controller_route`はaction_kindを明示的にJointTrajectory／MoveIt Servoへ対応させる。
現時点ではルート選択のみで、制御メッセージ生成・publisher・実行はWP03に残す。
MoveIt ServoのJointJogとTwistStampedの使い分けは
[Humble公式資料](https://moveit.picknik.ai/humble/doc/examples/realtime_servo/realtime_servo_tutorial.html)に従う。
唯一の結果publisherは `~/dry_run_actions`（std_msgs/String JSON）。
実機publisherは存在せず、dry_run=falseを拒否する。
