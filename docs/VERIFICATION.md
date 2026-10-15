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
