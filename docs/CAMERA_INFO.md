# CameraInfoと登録モデルの意味

## CameraInfoの実装

kotyaka-websimのPiper単体は、piper_rosのrealsense2_cameraが使う
`updateStreamCalibData` と同じK/R/Pの配置でCameraInfoを生成する。
実ドライバはlibrealsenseの `video_profile.get_intrinsics()` から校正値を取得する。
シミュレータは `simulation/config.ts` のカメラprofileを値の正本とし、
カラー描画・カラー整列深度・点群・CameraInfoを同じprofileから構成する。

```text
K = [fx,0,cx, 0,fy,cy, 0,0,1]
R = [1,0,0, 0,1,0, 0,0,1]
P = [fx,0,cx,0, 0,fy,cy,0, 0,0,1,0]
D = [0,0,0,0,0]  (plumb_bob、歪みなしのシミュレーション)
```

640×480、fx=618.9、fy=618.7、cx=320、cy=240を参照値として使用する。
Kだけでなく描画projection、深度ray、点群逆投影の幾何も揃え、半画素差を処理している。
color/camera_infoとaligned_depth_to_color/camera_infoは、同じ内参・時刻・color optical frameを持つ。
深度と点群もこのカラー光学座標系を使う。

修正前は3要素のkに4値を追加してKが7要素となり、rosbridgeがROS型へ変換する段階で
`could not broadcast input array from shape (7,) into shape (9,)` として拒否していた。
これはVLAサーバの拒否ではない。現在は9要素へ修正済み。
修正前の固定画角69.4度とfy=618.7の不整合も、内参からfrustumを生成する方式で解消した。

2026-10-15の実ブラウザ→rosbridge→Humble検証では、20秒間に各CameraInfoを18件受信し、
RGB・深度・点群と18組の取得時刻が一致した。点群60点の再投影最大誤差は約0.000019画素。
詳細はkotyaka-websimの `docs/PIPER_CAMERA.md`。

実RealSense個体の数値を読み出したものではなく、個体固有の歪み・ノイズ・ステレオ遮蔽も再現しない。
実機と数値まで一致させるには、その機器のstream profileと歪みモデルが必要。
実機への接続は行っていない。
Bridgeのcamera_calibration_idsは宣言したprofileの識別子であり、CameraInfoの自動取得や実機校正検証ではない。
Piper sim例は `piper_websim_pinhole_v1` を指定する。

## 登録モデルとは何か

サーバが選択可能な推論器を、IDと入出力契約を組にして明示登録したもの。
`GET /v1/models` で確認でき、Bridgeのmodel_idで選ぶ。
ロボットのURDF/MJCF自体ではない。

| model_id | 推論器 | 観測契約 |
|---|---|---|
| mock_piper | 合成zero Policy | 接続テスト用joint_1/joint_2、画像なし |
| mock_rgb | 合成zero Policy | 同じ2関節＋front画像 |
| mock_piper_rgb6 | 合成zero Policy | Piper joint1～6 rad＋独立した指変位m＋front画像 |

いずれも接続試験用で、ACT/Diffusion/π₀.₅の重みは未登録。
BridgeはROS上の関節順・画像型・時刻を共通APIへ揃え、モデル固有処理はサーバAdapterが担当する。
