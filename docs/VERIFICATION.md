# WP01 / WP02検証

合成fixtureのみ使用する。ホストへPython依存を導入しない。

```bash
docker build -t vla-server-test:wp01 .
docker run --rm --network none vla-server-test:wp01
```

Humble検証は既存のローカル開発イメージ `piper-ros-humble-dev:latest` を基底にする。
このイメージはリポジトリに配布せず、ROS Humble・Python 3.10・pip・colconが必要。
GPUや実機接続は使用しない。Dockerfile.ros内でAPI依存を固定して導入し、
既存installがあれば読み込み、なければ `/opt/ros/humble/setup.bash` をunderlayとしてビルドする。
基底イメージの完全な再現性は未保証。

```bash
docker build -f Dockerfile.ros -t vla-server-test:humble .
docker run --rm --network none vla-server-test:humble
```

非ROS環境ではROS統合テストのみskipする。Humbleでは実rclpyの合成RGB/JointStateを
ローカルHTTPのmock_rgbへ送信し、ログ用ROSトピックを確認する。
続いてHTTPサーバを停止し、HOLD移行と新たな結果の発行停止を確認する。
関節/Servo指令publisherがないことも確認する。

実機E-stop、動的制限、collision、MoveIt/JointTrajectoryの模擬エンドポイント、
学習済みACT/Diffusion/π₀.₅、GPU、カメラ校正、LAN、iPhoneは未検証/未実装。

2026-10-15実測: Python 3.10コンテナは34 passed / ROSのみ1 skipped、
Humbleはcolcon build成功。Python-only側にはStarlette TestClientとanyio間の
DeprecationWarningが1件あり、テスト失敗ではない。
Humbleの最終テストは35 passed（skipなし）。実機へは接続していない。

コンテナ内で共通API依存導入・colcon build・setup読込後、以下で起動できる。
カメラ付きのパラメータ例はconfigs/bridge.example.yaml。

```bash
uvicorn vla_server.api:app --host 127.0.0.1 --port 8000
ros2 launch vla_bridge dry_run.launch.py model_id:=mock_piper
ros2 run vla_bridge bridge_node --ros-args --params-file configs/bridge.example.yaml
```
最終launchファイルもcolconで再ビルドし、`ros2 launch ... --show-args`で
server_url / model_id / task引数が解決することを確認した。

## 実行側時計とPiper型対応（v0.2）

新規テストはROS simulation clock、ロボットsystem clock、ロボット配信Clockを模擬する。
関節順の変更・余分な関節・グリッパm分離、BGR/RGBA/PNG変換、時計停止・巻き戻り、
旧世代応答、実行時計reference欠落、単調時計による推論期限を検証する。

```bash
docker build -t vla-server-test:wp01 .
docker run --rm --network none vla-server-test:wp01
docker build -f Dockerfile.ros -t vla-server-test:humble .
docker run --rm --network none vla-server-test:humble
```

### kotyaka-websim Piper単体との実測

2026-10-15、実ChromeのMuJoCo WASM → rosbridge 2.0.8 → Humble Bridge →
HTTP mock_piper_rgb6 → /vla_bridge/dry_run_actions の往復を確認。
20.02秒で640×480 RGBを18枚、関節状態を39件受信し、同期条件を満たす5件の推論応答を受信した。
source_timestamp_nsは約106秒のsim時刻のまま保持し、server Unix時刻への置換はしていない。
アームはjoint1～6、gripperは別のposition_mとしてサーバへ送信した。
実機指令publisherは作成せず、実機へ接続していない。

大画像は同時刻の関節に対して約3秒遅延して配送されたため、sim設定の受信猶予と
時計配信停止検出を5秒、clock/image/joint QoSをreliableへ調整した。
50msの同時刻整合・実行時計での鮮度1秒・HTTP期限1秒は維持。
表示約1 FPSの短時間検証であり、5 Hz画像や20 Hz制御の性能受入証拠ではない。

```bash
# 共通API起動後、隔離したROS環境のコンテナ内で実行
ros2 run vla_bridge bridge_node --ros-args --params-file configs/bridge.piper_sim.example.yaml
```

実機の時計はソフトウェア模擬まで。RealSense個体校正・実機gripper変換の同定・モータ動作は未検証。
参照websimのCameraInfo K=7要素の問題は残っており、本変更では参照リポジトリを編集していない。

最終Docker検証: Python 3.10のみは52 passed / ROS統合1 skipped、Humbleではcolcon build成功。
最終Humbleテストは **57 passed in 1.50s**（時計source設定の拒否検査を含む）。
