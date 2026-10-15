# vla_server

ROS 2 robot-to-policy bridge and multi-model VLA inference platform.

> **Status: experimental scaffold.** No learned policy is integrated yet. **Robot motion must remain disabled until model-specific action semantics, safety interlocks, and hardware validation are complete.**

## Goal

Run end-to-end robot tasks using one selected policy (not a fallback to handcrafted skills), then compare policy families on the **same** robot datasets, action definitions, and metrics:

- ACT (CVAE / action-chunking Transformer)
- Diffusion Policy (noise-based action-sequence generation)
- π₀.₅ (vision-language model + flow-matching action expert)
- Future: Gemma 4 E2B-based experimental policies and iPhone inference backend

The ROS 2 bridge selects the registered model, synchronizes camera and joint observations, sends inference requests, and owns safe action execution. The server hosts model adapters and returns **typed** action chunks. New checkpoints must be explicitly registered and validated; model names never imply motor commands.

## Start here

1. [Implementation plan](docs/IMPLEMENTATION_PLAN.md) — milestones, acceptance criteria, delegation sequence.
2. [Architecture](docs/ARCHITECTURE.md) — responsibility boundaries.
3. [Wire/API contract](docs/API_CONTRACT.md) — schema/units/time/synchronization.
4. [Safety and public-repository policy](docs/SECURITY.md).
5. [Agent handoff](AGENTS.md) — instructions for coding agents.

The Python service scaffold offers a *deterministic dummy policy* for transport tests only; it never demonstrates a trained VLA. Checkpoints, ROS hardware integration, and learned-policy adapters are deliberately deferred to implementation milestones.

## Layout

```text
docs/                    Technical plan, interface and safety specifications
server/                  Inference API, registry, model-adapter contracts
ros2_ws/src/vla_bridge/  ROS 2 Humble bridge package (scaffold)
configs/                 Example registry and bridge settings (non-secret)
training/                Dataset/training interface notes
benchmarks/              Evaluation protocol
edge/ios/                Future edge-backend contract
tests/                   Transport and schema tests
```

## Security and licensing

Public repo: do **not** commit credentials, network details, robot camera footage, datasets, weights, identifiable objects/people, or private third-party code. Use environment variables for secrets and local private configuration. See [docs/SECURITY.md](docs/SECURITY.md). External model licenses (especially PaliGemma / π₀.₅ and Gemma-family weights) must be separately reviewed before redistribution.

## Upstream references

- LeRobot: https://github.com/huggingface/lerobot
- OpenPI: https://github.com/Physical-Intelligence/openpi
- LeRobot async inference: https://github.com/huggingface/lerobot/blob/main/docs/source/async.mdx

No upstream code is vendored by this scaffold.

## 開発と検証

WP01の共通API・明示Registry・合成Adapter、WP02のHumble dry-runブリッジを実装。
学習モデルや実機制御は未実装。Docker内だけでビルド・テストする。
コマンドと検証範囲は [検証手順](docs/VERIFICATION.md) を参照。

Piperシミュレータ用のdry-run設定は [bridge.piper_sim.example.yaml](configs/bridge.piper_sim.example.yaml)。
時計は実行側に合わせ、実機の場合はロボット側の時計を使います。
[CameraInfoと登録モデルの説明](docs/CAMERA_INFO.md)も参照してください。
