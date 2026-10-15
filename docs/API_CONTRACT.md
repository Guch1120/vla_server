# HTTP JSON API v0.2（研究用・暫定）

推論専用。実機出力経路は存在しない。gRPC/binary画像転送は後続課題。
Python型の正本は `server/vla_server/schemas.py`。
未知フィールドと暗黙の文字列/boolean数値変換を拒否する。

## エンドポイント

- `GET /health`: status、actuation=false、trained_models_loaded=false。
- `GET /v1/models`: 明示登録ModelSpecの全メタデータ。
- `POST /v1/predict`: request_id、model_id、observation、task、dry_run=true、execution_timestamp_ns、max_inference_ms。

model_idは推論器と入出力契約を選ぶID。現在の登録は全て接続試験用のzero Policyで、
学習済みACT/Diffusion/π₀.₅ではない。旧mock_piper/mock_rgbは合成2関節。
mock_piper_rgb6はPiperの6軸アーム＋独立した指変位m＋front RGBを受ける。
YAMLから任意のコードや重みをロードせず、Registry.registerで明示登録する。

## 実行側の時計

Observationは timestamp_ns、clock_domain（unix / ros_sim / robot）、clock_epoch を持つ。
画像capture timestampと関節timestampは同じ実行側時計を用い、取得時刻を保持する。
ros_sim/robotでは同じ時計の現在値 execution_timestamp_ns をBridgeが送信する。
サーバ自身のUnix時計とシミュレーション/ロボット時計を比較しない。
サーバは実行側現在値に対し1秒より古い、50msより未来の観測を拒否する。
旧unixリクエストだけはexecution_timestamp_nsを省略でき、その場合は従来のサーバUnix時計を使う。

BridgeはROSの実行側時計を選択する。

- シミュレータ: use_sim_time=true、clock_domain=ros_sim、既定のclock_topic=/clock。
- 実機上でBridgeを実行: use_sim_time=false、clock_domain=robot。ロボット側のROS system clockを使用。
- 別PCのBridgeへロボット時計を配信: clock_domain=robot、clock_topicにロボットのClockトピックを指定。
  /clockを購読する場合でもdomainをrobotと明示できる。未配信時はfail closed。
  ロボットがClockを配信しない場合は、Bridgeをロボット上で動かすか、Bridgeの時計をロボットへ同期させる。

clock_domain=autoはuse_sim_timeからros_sim/robotを選ぶ。
clock_qosはbest_effort/reliableを明示できる。大画像と同時配信するwebsimの例はreliableを使う。
clock_stall_s（既定1秒）以上時計が進まない場合はHOLDにし、観測/応答を破棄する。
時計が巻き戻るたびにclock_epochを更新し、受信バッファと旧要求世代を無効化する。
ROSメッセージ自体にepochフィールドはないため、publisher再起動で同じ時刻の遅延パケットを
完全識別する保証はない。継続的な実機実行には後続のsession/sequence契約が必要。

通信待ちと推論実行期限は単調時計で測る。max_inference_msの既定値は1000。
シミュレーションの速度変更・停止で通信期限が止まることはない。
Bridgeの監視タイマーもsteady clockを使う。

## 観測とROS型変換

joint_namesは一意の回転関節名、joint_positions_radは有限のrad値で、Registryと順序を一致させる。
Bridgeはjoint_source_namesから名前で選択し、joint_namesの順に並べ替える。
車輪やmimic関節などの余分な関節をアーム配列へ混入させない。欠測・重複・非有限値は破棄する。

Gripperは独立した gripper={joint_name, position_m, calibration_id} で表す。
position_mは指1本の変位で、指間の全幅やradではない。
Bridgeのgripper_scaleとgripper_offset_mで明示的に変換する。
現在の6軸mockはpiper_finger_displacement_m_v1を要求する。グリッパActionは未実装。

imagesはカメラ名をキーとし、timestamp_ns、frame_id、calibration_id、encoding=rgb8、
width、height、data_base64を持つ。RGBバイト数はwidth×height×3と一致する。
最大4カメラ、各辺1024、HTTP本文全体5,000,000バイト。
camera_orderと順序を合わせ、画像と関節の差は50ms以内。
BridgeはImageのrgb8/bgr8/rgba8/bgra8（行paddingを含む）、またはCompressedImageのJPEG/PNGを
共通rgb8へ変換する。画像の型変換であり、モデル用resize/crop/tokenize/正規化は行わない。
これらはサーバAdapterの責務である。

各カメラは最大8件・関節は最大32件を保持し、最新の整合する観測を選ぶ。
/clockより先に届いた観測も保持するが、受信後sync_receive_age_s（既定1秒）を超えたものは単調時計で捨てる。
image_transport、image_qos、camera_calibration_idsを起動時に指定できる。
CameraInfoの取得/校正検証は今回のBridgeには含めない。未校正IDを実校正済みと扱わない。

## 応答

request_id、model_id、action_schema、action_kind、unit、frame_id、robot_id、joint_names、
action_hz、actions、source_timestamp_ns、source_clock_domain、source_clock_epoch、
generated_timestamp_ns、inference_msを返す。
sourceの3項目は実行側時刻をそのまま参照し、Bridgeが現在の時計・epochと照合する。
generated_timestamp_nsはサーバUnix時計の診断値で、robot/ros_simの鮮度判定には使わない。
Bridgeは通信期限、型、ID、Registry、horizon、時計世代を検証してからdry-runトピックへ出す。

対応Actionはjoint_position（絶対rad）、joint_velocity（rad/s）、ee_twist
（並進3軸m/s＋角速度3軸rad/s、明示frame）。配列は有限値の矩形で登録horizonと一致する。
joint_delta、pose、gripper Actionは未実装。合成zero fixtureは安全な実機指令を意味しない。

## エラーと境界

- 404: 未登録モデル。
- 409: 未ready、Adapter出力契約違反、重複request_id。
- 413: 本文サイズ超過。
- 422: 型/形状/時刻/画像/関節・グリッパschema/unsafe modeなどの入力違反。
- 503: backend失敗、重複防止キャッシュ容量超過。
- 504: 推論期限超過、旧unix要求の推論後観測期限切れ。

request_idはプロセス内で60秒、最大4096件保持する。受理済みIDを再実行せず、
容量超過時に未期限切れIDを追い出さない。永続exactly-once保証ではない。
実行時刻referenceは信頼するBridgeが送信する値であり、サーバだけで実機安全性を保証するものではない。
画像・観測本文はログ出力せず、backend例外の詳細を返さない。
非ローカル公開用TLS/auth、学習済みモデル、モータ出力は未実装。

同じ実行中にシミュレータとロボット両方の/clockを混ぜない。
必要ならロボット専用の名前空間（例: /robot/clock）をclock_topicへ明示し、
同じauthorityで刻印された観測だけを渡す。実行中の時計source切替は再起動を必要とする。
