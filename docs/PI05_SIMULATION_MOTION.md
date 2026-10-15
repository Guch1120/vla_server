# π₀.₅のシミュレーション動作実験

ユーザーの明示指示で、ベースモデルの出力を未校正の実験用対応でWeb MuJoCoに送る。
Piper用に学習済み・校正済みとは扱わず、把持・配置のベンチマーク結果に混ぜない。
通常のHTTP APIとROS dry-runブリッジは従来どおり実機出力を拒否する。

## 入出力の仮定

`experimental_pi05_first7_delta_rad_finger_m_v1` として以下を固定する。
これはベースモデルに付属する正規化統計ではない。

- 入力: 画像は実シミュレータの手首RGB、他2カメラ欠測mask。
- 状態: joint1〜6 radとjoint7の指変位mをMJCFの関節範囲から[-1,1]へ線形変換。
  残り25次元は0。モデル固有の処理はサーバ側 `sim_projection.py` に置く。
- 出力0〜5: chunk開始時の観測角からのrad変位と仮定。各変位を±0.5radに制限し、
  joint1〜6のMJCF範囲へ制限する。
- 出力6: [-1,1]の開度と仮定し、指変位[0,0.035]mへ線形変換する。
  joint8はシミュレータのmimicで追従させる。
- 50点のうち先頭10点を10Hzのシミュレーション時刻で送信し、新しい画像・状態で再推論する。
  有限8chunkで終了。IKや手作業のタスク方策へのfallbackはない。

## 分離と拒否条件

推論プロセス `scripts/pi05_sim_worker.py` は `--network none` のGPUコンテナで動作し、
共有ディレクトリのファイルIPCだけを使用する。重みは固定SHA256で検査する。
ブリッジ `scripts/pi05_sim_bridge.py` だけがROS指令を送る。
ROS_DOMAIN_ID=94 / ROS_LOCALHOST_ONLY=1と `--enable-simulation-motion` が必須。
出力先は固定 `/sim/piper_standalone/joint_targets`、sensor_msgs/JointState。
実機ドライバ、CAN/USBデバイス、リーダーフォロワー、host networkは使用しない。
Web側の双方向実機連携は無効のままにする。

画像と関節は有界バッファで時刻差50ms以内の組を待つ。実行側/clockに対し取得時刻が1秒以内、
推論応答は3秒以内のシミュレーション時刻かつ5秒以内の単調時計で検査する。
request_id、epoch、schema、行動点数、関節範囲、有限値を検査し、不一致で送信を止める。
時計停止・巻戻りでも停止する。終了時は最後に受信した関節位置を送って保持する。
これは実機の停止・E-stopを保証する実装ではない。

同じROSコンテナ内でブリッジを動かす。別コンテナでnetworkだけを共有すると、
DDS共有メモリの分離で受信できない場合があった。
Web接続時はカメラOFFで先にトピックを登録し、その後カメラをONにする。
カメラONのまま再接続すると送信バッファが登録メッセージを破棄する場合があった。

## 起動するプログラム

それぞれ、リポジトリと同じ共有ディレクトリをマウントしたDocker内で実行する。
共有先は実験ごとに新しい空ディレクトリを使い、過去のready/応答を再利用しない。
`vla-server-pi05:pinned` は `docker/pi05/Dockerfile` からビルドする。

```bash
# GPUコンテナ。/workspaceはソースと重み、/exchangeは実験用IPCディレクトリ。
PYTHONPATH=/workspace/server python scripts/pi05_sim_worker.py
# 隔離ROSコンテナ。/opt/ros/humble/setup.bashを先にsourceする。
python3 scripts/pi05_sim_bridge.py --enable-simulation-motion --exchange /exchange
```

推論プロセスは最大15分で終了する。即時終了は共有先に `shutdown` ファイルを作る。
ブリッジの指令終了とモデルのunloadを分離し、観測待ちの失敗で重みの再ロードを繰り返さない。
実験ログ・画像・応答はignore済みの領域だけに保存する。

## 2026-10-15の動作結果

実ChromeのWeb MuJoCoの画像と関節状態を取得し、π₀.₅で再推論して8chunkを実行した。
ROSの実測関節状態365件を記録。旋回joint1は約0から-2.618rad（-150°）、
前腕joint4は約-0.004から-1.743rad（-100°）、手首joint6は約0から0.818rad（47°）に変化した。
joint1/joint4/joint5は指令が関節範囲端に達した。把持・配置の成功は確認していない。
単なる画面上の補間やダミー出力ではなく、画像・関節の再観測から得たモデル出力を使用した。
実機接続・追加学習・IK fallbackはない。

初回推論1.35秒、以降は約0.22秒。共通APIへの学習モデル統合とWP03全体は未完了。
最初の試行では画像が対応関節より先に届き、50ms検査で指令前に停止した。
到着順に依存せず、有効な組を待つ修正後に8chunkを完走した。
テスト75 passed / ROS依存1 skipped、Ruff成功。終了後は保持・Web一時停止・ROS切断し、
GPUプロセスも終了した。動作記録はプライベートなローカル成果物として保存した。
