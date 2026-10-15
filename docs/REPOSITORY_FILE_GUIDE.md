# リポジトリ内フォルダ・ファイル案内

このメモは、現在Gitで管理しているファイルをフォルダごとに説明するための案内です。作業中のファイルを探す入口として使ってください。実装状態は2026-10-16時点の計画書・API契約と対応しています。

## 全体の流れ

```text
ROS 2 Bridge ──観測──> Inference API ──> Model Registry / Adapter
      ^                                          │
      └──────── dry-run action chunk ────────────┘
```

現時点で登録されているのは合成zero fixtureです。ACT、Diffusion Policy、π₀.₅の学習済みAdapter・重みや実機制御はまだありません。Bridgeの出力はdry-run用ログトピックに限られます。詳しい仕様と進捗は[実装計画](IMPLEMENTATION_PLAN.md)、[構成](ARCHITECTURE.md)、[API契約](API_CONTRACT.md)、[検証手順](VERIFICATION.md)を参照してください。

## フォルダ別

### リポジトリ直下

| ファイル | 目的 |
| --- | --- |
| `README.md` | プロジェクトの狙い、対応する方策ファミリー、主要フォルダと開始点を案内します。 |
| `AGENTS.md` | 開発エージェント向けの作業ルールと実装優先順位です。 |
| `pyproject.toml` | Pythonパッケージ情報、共通API依存、開発用テスト依存を定義します。 |
| `requirements-tested.txt` | Docker検証で使用したPython依存バージョンを固定します。 |
| `Dockerfile` | ROSを使わないAPI・テスト用Pythonコンテナを作ります。 |
| `Dockerfile.ros` | ROS 2 Humble環境でBridgeをビルド・テストするコンテナ定義です。ローカル開発用基底イメージに依存します。 |
| `.env.example` | 秘密情報を含まないローカルAPI設定の例です。実際の`.env`はGit管理しません。 |
| `.gitignore` | キャッシュ、ローカル設定、ログ、モデル重み、データ、ROS生成物などをGit対象外にします。 |
| `.dockerignore` | Docker build contextへ不要なキャッシュ・秘密・データ類を含めないための除外設定です。 |

### `docs/` — 設計・契約・検証記録

| ファイル | 目的 |
| --- | --- |
| `IMPLEMENTATION_PLAN.md` | WP01以降の作業項目、受け入れ条件、現在の実装状況・未完了項目です。 |
| `ARCHITECTURE.md` | Bridge、推論サーバ、Adapter、制御器の責務と時刻同期・モデル切替の設計です。 |
| `API_CONTRACT.md` | HTTPリクエスト／応答、観測とActionの型・単位・制約、エラー仕様です。 |
| `SECURITY.md` | 公開リポジトリに含めてはいけない情報と、dry-run・実機安全境界を定めます。 |
| `VERIFICATION.md` | Docker内でのビルド・テスト手順、実測結果と未検証範囲を記録します。 |
| `REPOSITORY_FILE_GUIDE.md` | このファイルです。各フォルダ・ファイルを探すための索引です。 |

### `server/vla_server/` — 推論APIとモデル登録

| ファイル | 目的 |
| --- | --- |
| `api.py` | FastAPIエンドポイント（health、モデル一覧、predict）、入力制限、時刻・重複要求検査、Adapter呼び出しを実装します。 |
| `schemas.py` | Observation、画像、予測要求・応答の厳密な型検査と画像サイズ・Action形状・単位検証を定義します。 |
| `registry.py` | ModelSpec、Adapterプロトコル、合成MockPolicy、明示登録Registryと既定の合成モデルを定義します。 |
| `__init__.py` | Pythonパッケージとして認識させるファイルです。 |

モデル固有の前処理・正規化・出力変換は将来もサーバ側Adapterへ置きます。現状のMockPolicyは合成ゼロ出力のみで、学習済み方策ではありません。

### `ros2_ws/src/vla_bridge/` — ROS 2 Humble Bridge

| ファイル／フォルダ | 目的 |
| --- | --- |
| `package.xml` | ROSパッケージ名、ビルド方式、ROS実行依存をcolconへ伝えます。 |
| `setup.py` | Pythonパッケージと`bridge_node`実行コマンドをamentへ登録します。 |
| `setup.cfg` | ROS 2 Python実行スクリプトの配置先を設定します。 |
| `resource/vla_bridge` | amentがパッケージを検出するための空のリソースマーカーです。 |
| `vla_bridge/__init__.py` | Bridge Pythonパッケージの初期化ファイルです。 |
| `vla_bridge/bridge_node.py` | ROSノード、パラメータ、カメラ／関節購読、HTTP推論ワーカー、dry-run結果発行をつなぎます。 |
| `vla_bridge/core.py` | ROSメッセージに依存しない同期・キュー・応答検査・Actionルート選択の共通処理です。 |
| `launch/dry_run.launch.py` | dry-runノードを起動し、サーバURL・モデルID・タスクを指定するlaunch定義です。 |

Action種別からJointTrajectory／MoveIt Servoの経路を選ぶ設計要素はありますが、実際の制御メッセージ発行・実行は未実装です。sim time対応も未実装です。実機モータ用publisherはありません。

### `configs/` — 秘密を含まない設定例

| ファイル | 目的 |
| --- | --- |
| `bridge.example.yaml` | 合成カメラ・合成関節状態を使うBridgeパラメータ例です。dry-runが有効です。 |
| `models.example.yaml` | Registryメタデータの記述例です。サーバはこのYAMLを自動ロードせず、コード内の明示登録を使います。 |

### `tests/` — オフライン検証

| ファイル | 目的 |
| --- | --- |
| `conftest.py` | pytest共通fixtureやテスト用Python import pathを設定します。 |
| `test_mock_api.py` | API、Registry、型・時刻・画像検査、拒否ケース、backend失敗を検証します。 |
| `test_bridge.py` | Bridge共通処理、dry-run往復、Actionルート、期限切れ・切断・キュー挙動を検証します。 |
| `test_ros_integration.py` | ROS 2 Humble上で合成topicからAPIへの往復と切断時の挙動を統合検証します。ROSのない環境ではskip対象です。 |

### 計画・将来機能の説明フォルダ

| フォルダ | ファイル | 目的と現在の状態 |
| --- | --- | --- |
| `benchmarks/` | `README.md` | 共通条件で方策を評価する領域の案内です。評価Runner・結果一式はまだありません。 |
| `training/` | `README.md` | データセット・学習手順の将来領域の案内です。学習コードやデータはまだありません。 |
| `edge/ios/` | `README.md` | iPhone推論Backendの将来領域の案内です。iOSアプリや推論実装はまだありません。 |

## Git管理外のローカル生成物

テスト・実験でできるPythonキャッシュ、pytest/Ruffキャッシュ、ROSの`build/`・`install/`・`log/`、ログ、チェックポイント、重み、データセット、記録ファイルは`.gitignore`等で除外します。ローカルに存在しても、この案内のGit管理ファイル一覧には含めません。公開用の差分を作るときは`git status --short --ignored`で確認し、秘密情報・実機接続情報・私有データ・重みを追加しないでください。

## 目的から探す

- APIの型やHTTP仕様を確認する: `server/vla_server/schemas.py`、`docs/API_CONTRACT.md`
- モデル登録やAdapterを確認する: `server/vla_server/registry.py`、`server/vla_server/api.py`
- ROS入出力や同期を確認する: `ros2_ws/src/vla_bridge/vla_bridge/`
- dry-run設定を確認する: `configs/bridge.example.yaml`、`ros2_ws/src/vla_bridge/launch/dry_run.launch.py`
- 何が未実装か確認する: `docs/IMPLEMENTATION_PLAN.md`、`docs/VERIFICATION.md`
- 公開前の安全境界を確認する: `docs/SECURITY.md`、`.gitignore`
