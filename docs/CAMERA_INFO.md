# CameraInfoと登録モデルの意味

## CameraInfoは実RealSenseと同一か

メッセージ型は同じ `sensor_msgs/CameraInfo` を意図しているが、現在の
kotyaka-websim/Piperの内容は実カメラの校正値と同一ではない。

参照したpiper_rosの `realsense2_camera/src/base_realsense_node.cpp`
`updateStreamCalibData` は librealsense の `video_profile.get_intrinsics()` から
解像度、fx/fy、主点ppx/ppy、歪みモデルと係数を取得し、K/R/Pを組み立てる。
実機の個体・解像度・ストリームに依存するため、型番だけで同じ値にはならない。
今回は実RealSenseを接続していないので、実機の具体的な数値との一致は未検証。

一方、websimのPiper設定は固定の fx=618.9、fy=618.7、cx=320、cy=240 を使う。
`RosMessages.ts` は `[...intrinsics.k, fx, fy, cx, cy]` としており、
元のkが3要素なので合計7要素になる。

Kは行優先の3×3行列でなければならない。

```text
[ fx,  0, cx,
   0, fy, cy,
   0,  0,  1 ]
```

実ROSメッセージへ変換するrosbridgeが、長さ9の固定配列へ7要素を代入する段階で
`could not broadcast input array from shape (7,) into shape (9,)` を返す。
VLAサーバの拒否ではない。カラーImageの配信とは別経路である。

さらに、websimのPerspectiveCameraは垂直画角69.4度を使う一方、
設定されたfy=618.7は480画素の画像では垂直画角約42.4度に相当する。
配列長を9に直すだけでは、描画と校正の幾何的一致まで保証できない。
将来の修正では描画の投影行列からK/Pを作り、歪みなしのシミュレーションであれば
その前提に対応するDを明示する必要がある。
本変更はvla_server内のBridge対応であり、参照リポジトリ自体は変更していない。
現在のBridgeはCameraInfoを購読せず、設定したcalibration_idを保持する。
`piper_websim_uncalibrated` は未校正を意味し、実機の校正完了を意味しない。

## 登録モデルとは何か

サーバが選択可能な推論器を、IDと入出力契約を組にして明示登録したもの。
`GET /v1/models` で確認でき、Bridgeのmodel_idで選ぶ。
ロボットのURDF/MJCFや、関節名一覧そのものを「モデル」と呼んだものではない。

| model_id | 推論器 | 観測契約 |
|---|---|---|
| mock_piper | 合成zero Policy | 接続テスト用のjoint_1/joint_2、画像なし |
| mock_rgb | 合成zero Policy | 同じ2関節＋front画像 |
| mock_piper_rgb6 | 合成zero Policy | Piper joint1～6 rad＋独立した指変位m＋front画像 |

名前にPiperを含む旧2件も、学習済みPiper方策ではない。
新しい6軸登録も接続試験用であり、ACT/Diffusion/π₀.₅の重みは未登録。
BridgeがROS上の関節順・画像形式・時刻を共通APIへ揃え、
各学習モデル固有のresize/crop・正規化・tokenize・出力逆変換はサーバAdapterが担う。
契約に合わないデータを、同じ長さになるよう切り詰めたりrad/mを混在させたりしない。
