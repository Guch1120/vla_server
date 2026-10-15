# HTTP JSON API v0.1（研究用・暫定）

推論専用。実機出力経路は存在しない。gRPC/binary画像転送は後続課題。
Python型の正本は `server/vla_server/schemas.py`。
全オブジェクトは未知フィールドと暗黙の文字列/boolean数値変換を拒否する。

## エンドポイント

- `GET /health`: status、actuation=false、trained_models_loaded=false。
- `GET /v1/models`: 登録ModelSpecの全メタデータ。現在mock_piper（カメラなし）、mock_rgb（front RGB）。
- `POST /v1/predict`: request_id、model_id、observation、task、dry_run=true。

Observationはtimestamp_ns（Unix epoch ns）、clock_domain="unix"、joint_names、
joint_positions_rad、imagesを持つ。関節名は一意で、値は有限、順序はRegistryと一致すること。
imagesはカメラ名をキーとし、timestamp_ns、frame_id、calibration_id、encoding="rgb8"、
width、height、data_base64を持つ。RGBのバイト数はwidth×height×3と一致すること。
最大4カメラ、各辺1024、HTTP本文全体5,000,000バイトまで。
カメラ順序はRegistryのcamera_orderと一致し、関節時刻との差は50ms以内。
ROS simulation timeは未対応で拒否する。端末間のUnix時計同期は運用側の前提。
観測は1秒より古い、または50msより未来の場合に拒否する。

Responseはrequest_id、model_id、action_schema、action_kind、unit、frame_id、robot_id、
joint_names、action_hz、actions、source_timestamp_ns、generated_timestamp_ns、inference_msを持つ。
配列は有限値の矩形で、登録horizonと一致する。source_timestamp_nsは観測をそのまま参照する。
生成終了時に観測が1秒以上古ければ成功応答を返さない。
BridgeもID、時刻、Registryメタデータ、horizonを照合し、期限切れ応答を捨てる。

対応Actionはjoint_position（絶対rad）、joint_velocity（rad/s）、ee_twist
（並進3軸m/s＋角速度3軸rad/s、明示frame）。joint_delta、pose、gripperは未実装として拒否する。
物理単位へ戻す処理はAdapter内で実行し、Bridgeでは再正規化しない。
合成zero fixtureは安全な実機指令を意味しない。

Registryはcheckpoint識別子、license、Adapter版、前処理版、正規化版、
観測schema、camera_order、robot_id、action schema/kind、unit/frame、joint_names、
action_hz、output_horizon、ready、trainedを必須とする。
モデル追加はサーバ側の明示登録のみ。YAMLは文書例であり自動ロードしない。
現在の合成fixtureのidentity正規化は学習モデルの統計を代用しない。

## エラー

- 404: 未登録モデル。
- 409: 未ready、Adapter出力契約違反、重複request_id。
- 413: 本文サイズ超過。
- 422: JSON/型/形状/時刻/単位/画像/unsafe modeなどの入力違反。
- 503: backend失敗、重複防止キャッシュ容量超過。
- 504: 推論後の期限切れ。

request_idはプロセス内で60秒保持し、成功・失敗にかかわらず受理済みIDを再実行しない。
最大4096件で、容量超過時に未期限切れIDを追い出さない。永続的exactly-once保証ではない。
HTTP malformed JSONの詳細はFastAPI標準の422を使用する。
エラーレスポンスにbackend例外の秘密情報を含めない。画像・観測本文はログ出力しない。
非ローカル公開用の認証/TLS、分散Registry、remote checkpoint、session切替は未実装。
