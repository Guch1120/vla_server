# π₀.₅ベースの推論検査

学習は行わず `lerobot/pi05_base` の公開済み重みを検査する。
これは推論専用の検査器であり、型・単位の不明な出力を既存のPiper Action Schemaへ登録しない。
ベースの32次元行動にPiperの6関節を対応付ける根拠と正規化統計がないため、
出力はモデル空間の数値として保存し、モータ・シミュレータへの指令に使用しない。

- LeRobot: `8975047fbb76e7fef3f482988ceccc17e2102a90`
- モデル: `lerobot/pi05_base@22c30e5b34f9e7ab738b1b34fc2fc5ecfe2d28f0`
- ライセンス: モデルカードはGemma、LeRobot実装はApache-2.0。重みは再配布しない。
- Tokenizer: OpenPI公式実装が使うGoogle公開 `gs://big_vision/paligemma_tokenizer.model`。
  HFのgated tokenizerへ認証情報を渡さず、公開SentencePieceを取得してSHA256を保存する。
- 重み・取得manifestはgitignore済み `checkpoints/`、結果はgitignore済み `logs/` に保存。
- 3カメラのうち手首画像1枚のみ入力し、他2台は上流の欠測maskを使用。
- 32次元状態は正規化済みzero fixture。Piperの実測関節を未校正で正規化したものではない。
- 前処理はサーバ側 `pi05_probe.py` に集約。Bridgeのモデル固有処理は追加しない。
- 上流 `from_pretrained` の例外後継続を避け、state_dictを変換後 `strict=True` でロード。

Dockerに既存の `vlm-finetune:dev`（Python3.12/CUDA12.8/PyTorch2.11）が必要。
検証時の基底image IDは `sha256:74f7d5e35c181f385dcd952232fe5da73db82348a8b1520303b3ed78679e299c`。
このローカルイメージ自体の配布・別ホストでの完全再現は対象外。
依存は `docker/pi05/requirements-tested.txt` で固定する。基底イメージを保全するため
system-site-packages付きのコンテナ内仮想環境に導入する。ホストへの導入は行わない。

```bash
docker build -f docker/pi05/Dockerfile -t vla-server-pi05:base .
docker run --rm -v "$PWD:/workspace" -w /workspace vla-server-pi05:base \
  python scripts/download_pi05.py --output checkpoints/pi05_base
docker run --rm --network none --gpus all \
  -v "$PWD:/workspace" -v /path/to/simulation-input:/input:ro \
  -e PYTHONPATH=/workspace/server vla-server-pi05:base \
  python scripts/pi05_base_smoke.py --checkpoint checkpoints/pi05_base \
  --image /input/scene-camera.png --output logs/pi05/run
```

画像・指示の変更で出力が変化しても、正しい物体を選択・把持した証拠にはならない。
評価するのは重み読込、有限な50×32出力、推論時間、VRAM、固定乱数の再現性、入力への反応のみ。
ACT/Diffusionはタスクごとの学習済みcheckpointが必要であり、今回はダウンロード対象にしていない。

## 2026-10-15実測

RTX 5060 Ti 16GB、PyTorch2.11.0+cu128、Transformers5.5.4、LeRobot0.6.2（上記commit）。
重み14,467,165,872 bytes。上流の混合精度を保持する。
上流constructorへは `config.dtype=torch.bfloat16` を渡す（文字列指定はこの版では失敗する）。
state_dict変換後に全キーのstrict loadが通り、4,143,404,816パラメータをロードした。
モデル構築・ロードは初回139.2秒。固定依存コンテナでの再検証はSHA256照合込み104.5秒。
モータ出力を持たないnetwork=noneコンテナで検証し、再検証でも全出力が初回と一致した。
以下は固定依存コンテナの再検証値。

| 条件（乱数seed=7固定） | 推論時間 | 備考 |
|---|---:|---|
| 初回 | 1.624秒 | GPU warmupを含む |
| 同じ赤キューブ指示 | 0.226秒 | 初回出力との差の最大絶対値0 |
| 青キューブ指示へ変更 | 0.220秒 | 赤指示との差の平均絶対値0.01730 |
| 同じ指示、黒画像へ変更 | 0.223秒 | 実画像との差の平均絶対値0.03802 |

全て50×32の有限値。10ステップのflow matchingを使用し、推論ステップ数は削減していない。
赤指示の生出力範囲は-0.16591〜0.14459。数値をradやmとは解釈しない。
PyTorchの最大GPU確保量9,525,160,448 bytes（約8.87GiB）。ドライバ全体のVRAM使用量とは異なる。
推論3回の値であり、p95や持続性能の測定ではない。
追加学習は実施していない。Piper実測状態を含む閉ループ制御・把持・配置は未評価。

オフラインテストは63 passed / ROS依存1 skipped。既存APIとdry-run挙動も検証範囲に含む。
Ruffも成功。Starlette/anyioの既存DeprecationWarningが1件ある。
取得manifestのrevision・サイズ、重みとTokenizerの固定SHA256を検査し、破損時は推論前に停止する。

公式参照:
- https://huggingface.co/lerobot/pi05_base
- https://github.com/huggingface/lerobot/blob/8975047fbb76e7fef3f482988ceccc17e2102a90/src/lerobot/policies/pi05/modeling_pi05.py
- https://github.com/Physical-Intelligence/openpi/blob/main/src/openpi/models/tokenizer.py
