# Implementation Plan — VLA-first robot policy platform

Updated 2026-10-15. Status: **WP01実装・検証済み、WP02 dry-run検証済み。実機未対応**.

## Objective and scope

Compare three standalone VLA/policy families (ACT, Diffusion Policy, π₀.₅) for end-to-end task execution on a common robot and dataset. **Do not** silently invoke Nav2, SAM3, FlexBE or handcrafted fallback skills during benchmark runs. Existing ROS 2 controllers may perform low-level motor control, safety monitoring, and interpolation; this is not a fallback decision-making policy.

The ROS 2 bridge selects the model at startup (future runtime switching only while stopped), assembles timestamped RGB camera and robot state observations, requests action chunks, validates the reply against a registered action schema, and owns execution. The inference server supports multiple local, explicitly approved checkpoints via adapters. Models may be loaded lazily, one at a time, to respect VRAM constraints.

## Non-goals for initial deployment

- No claim of zero-shot Piper compatibility from a publicly released checkpoint.
- No autonomous physical actuation until hardware-in-the-loop gate passes.
- No direct remote model upload or arbitrary code executed by model registry.
- No iOS inference during the first three baseline milestones.
- No comparisons that attribute performance differences to the action generator alone while vision backbones/training datasets differ.

## Phases and deliverables

### P0 — contracts, infrastructure, mock (first task)

- [x] Define Python API types and Protobuf/gRPC choice (JSON/HTTP mock may precede gRPC).
- [x] Registry entry includes immutable checkpoint identifier, action schema, observation schema, preprocessing/normalization version, model adapter and license.
- [x] Add synthetic *mock* adapter; strict shape/type/unit validation; predictable return data; no motor outputs.
- [x] Health/model introspection, request_id, observation timestamps, errors and latency fields.
- [x] Tests covering unknown model, stale observation, non-finite action, schema mismatch, stale response, duplicate request, oversized images and unsafe mode.
- **Gate:** `pytest` passes without ROS/hardware and no request can actuate hardware.

### P1 — ROS 2 Humble bridge + controller adapters

- [x] ROS 2 Python package with a launch file and parameters `server_url`, `model_id`, `task`, camera topics, joint state topic, `dry_run=true`.
- [x] RGB frames and joint states aligned by timestamps; define image encoding, camera ordering and clock synchronization.
- [x] Async inference worker; bounded queue (drop stale frames); deadline, backpressure, server disconnect behavior.
- [ ] Controller abstraction: `JointTrajectory` for absolute joint positions; `MoveIt Servo` for correctly framed jog/twist. **Never infer action type from length.**
- [ ] Arm stopped or held on timeout; manual enabling, E-stop and bounded position/velocity/accel per robot configuration.
- [ ] RViz/log-only and simulated controller tests before hardware.
- **Gate:** synthetic policy round trip ROS -> server -> dry-run ROS; stop on disconnect; no unsafe execution.

### P2 — common dataset and model adapters

- [ ] Record episodes including camera calibration, joint positions/velocities, gripper units, command/action targets, timestamps, task and success annotation.
- [ ] Version the canonical schema; convert to LeRobot dataset without changing physical meaning.
- [ ] Register explicit `lerobot_act`, `lerobot_diffusion`, `lerobot_pi05` adapters; integrate against pinned compatible upstream releases (verify current names and dependencies).
- [ ] Confirm camera count, history/action horizons and action normalization are model-specific; prohibit mismatched checkpoints.
- [ ] Baseline training/fine-tuning experiments on identical robot split; document π₀.₅ compute feasibility and licensing.
- **Gate:** each model produces validated offline action chunks on the same held-out observations; inference failures logged rather than silently switched to another model.

### P3 — real-robot isolated tasks

- [ ] Calibrated cameras, low-speed test workspace, tested E-stop, operator nearby; start with stationary-arm reach, then grasp, then task completion.
- [ ] Closed-loop/receding horizon: generate H, execute only k < H, observe again; tune k using p95 inference latency.
- [ ] Record task success, collisions/safety intervention, temporal consistency, endpoint error, jerk, p50/p95 inference delay, peak VRAM/RAM, transport delay.
- [ ] Hold model fixed during each episode. Randomize order, object placement and lighting; repeat trials.
- **Gate:** reproducible metrics with confidence intervals and explicit fail cases for all three models.

### P4 — Gemma 4 E2B experimental branch

- [ ] First measure image/text fused hidden-state extraction in native training runtime and target GGUF/iOS runtime, not merely text embedding endpoint.
- [ ] Freeze Gemma 4 VLM; compare pooled MLP, cross-attention CVAE/ACT-like, diffusion and flow-matching heads on an identical dataset.
- [ ] Preserve visual token spatial information where possible; compare pooled vs full tokens.
- [ ] Test LoRA/QLoRA *from appropriate training weights* rather than training a Q4 GGUF file directly. After training, export and quantize.
- [ ] Controlled paired tests against baseline with architecture size, training compute and data volume logged.
- **Gate:** native and quantized inference produce appropriately close action distributions and meet measured real-robot latency (no predefined assertion).

### P5 — iPhone backend

- [ ] Implement compatible inference API on the existing iOS LLM server or through a local gateway.
- [ ] Confirm fused per-token hidden states from model runtime; if unavailable, implement custom access and test.
- [ ] Export compact action head to Core ML / Metal or supported inference stack; validate dynamic shapes and memory.
- [ ] Compare native desktop vs iPhone correctness, latency, thermals, sustained throughput, battery and stability.
- **Gate:** same ROS bridge works by endpoint switch; fail closed on device suspension or network loss.

## Evaluation methodology

**Whole-policy track:** baseline ACT, diffusion, π₀.₅ as shipped/finetuned; different vision models and pretraining are part of the comparison.

**Controlled head track:** same Gemma backbone and frozen features, different action generators. Report compute, checkpoint, random seed and dataset split separately. Standard ACT and Diffusion Policy typically do not use language in default configurations; do not misreport language-generalization comparisons as controlled across all baselines.

Use a single action schema for the primary experiment (prefer measured absolute joint target in radians + separately calibrated gripper), but leave model-specific transforms inside the server adapter. Control adapters must never normalize an already denormalized action again.

## Resources & deployment decisions

Start with one GPU model loaded at a time; isolate incompatible upstream stacks via containers if required. Do not assume π₀.₅ fine-tuning fits a 16GB card. Training may require remote/Colab resources and license acceptance. Release only source, synthetic fixtures, and documentation in this public repository.

## Work packages for coding AI agent

1. **WP01:** implement typed request/response and strict validation, mock adapter, unit tests; PR with proof.
2. **WP02:** ROS 2 Humble dry-run bridge and synchronization; automated integration fake-topic tests.
3. **WP03:** controller adapter interfaces with simulated joint/servo endpoints, refusal and timeout tests.
4. **WP04:** LeRobot dataset conversion/recording tools; golden sample and split validation.
5. **WP05:** ACT adapter and reproducible pinned training/inference recipe.
6. **WP06:** Diffusion adapter and reproducible pinned training/inference recipe.
7. **WP07:** π₀.₅ adapter; document compute/license constraints and checkpoint compatibility.
8. **WP08:** benchmark runner, episode protocol and reporting.
9. **WP09:** Gemma 4 feature extraction and head experiments.
10. **WP10:** iOS action-head serving/edge evaluation.

Implement in order; each PR must contain test results, limitations, public-data review, and update the relevant docs. Do not turn on motors for a passing software test.

## WP01 / WP02進捗（2026-10-15）

WP01: HTTP JSON暫定契約、厳密な型/画像/時刻検査、明示Registry、
2つの合成Adapter登録、メタデータ照会、重複要求拒否、backend失敗/期限切れ検査を実装。
P0のGateはROSなしのDocker pytestで検証する。学習済み方策は追加していない。

WP02: Humble購読、50ms同期、上限付き非同期worker、起動launch、
dry-run結果トピック、サーバ切断時のHOLDを実装。
合成トピック→HTTP→dry-run ROSの往復・切断試験を追加。
P1全体の完了は宣言しない。Controllerメッセージ/模擬endpoint、
実機hold/E-stop/制限はWP03以降。sim time対応・実カメラ校正も未実装。
検証コマンド・制約は `docs/VERIFICATION.md`。
