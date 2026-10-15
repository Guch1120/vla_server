"""ROSの表現を共通物理量へ変換する。モデル用の正規化は行わない。"""

import io
import math


def joint_observation(
    names,
    positions,
    joint_names,
    source_names,
    gripper_name="",
    gripper_scale=1.0,
    gripper_offset_m=0.0,
    gripper_calibration_id="",
):
    if (
        len(names) != len(positions)
        or len(set(names)) != len(names)
        or len(joint_names) != len(source_names)
        or len(set(source_names)) != len(source_names)
        or len(set(joint_names)) != len(joint_names)
        or gripper_name in source_names
    ):
        raise ValueError("invalid joint mapping")
    values = dict(zip(names, positions))
    if not all(math.isfinite(value) for value in values.values()):
        raise ValueError("non-finite joint state")
    if any(name not in values for name in source_names):
        raise ValueError("required arm joint missing")
    result = dict(
        joint_names=list(joint_names),
        joint_positions_rad=[float(values[name]) for name in source_names],
    )
    if gripper_name:
        if (
            gripper_name not in values
            or not gripper_calibration_id
            or not math.isfinite(gripper_scale)
            or not gripper_scale
            or not math.isfinite(gripper_offset_m)
        ):
            raise ValueError("invalid gripper mapping")
        result["gripper"] = dict(
            joint_name=gripper_name,
            position_m=float(values[gripper_name] * gripper_scale + gripper_offset_m),
            calibration_id=gripper_calibration_id,
        )
    return result


def raw_rgb(msg):
    channels = {"rgb8": 3, "bgr8": 3, "rgba8": 4, "bgra8": 4}.get(msg.encoding)
    if (
        not channels
        or not 0 < msg.width <= 1024
        or not 0 < msg.height <= 1024
        or msg.step < msg.width * channels
        or len(msg.data) != msg.step * msg.height
    ):
        raise ValueError("invalid raw color image")
    raw = bytes(msg.data)
    packed = b"".join(
        raw[i * msg.step : i * msg.step + msg.width * channels]
        for i in range(msg.height)
    )
    if channels == 4:
        output = bytearray(msg.width * msg.height * 3)
        for channel in range(3):
            output[channel::3] = packed[channel::4]
        packed = bytes(output)
    if msg.encoding in ("bgr8", "bgra8"):
        output = bytearray(packed)
        output[0::3] = packed[2::3]
        output[2::3] = packed[0::3]
        packed = bytes(output)
    return msg.width, msg.height, packed


def compressed_rgb(msg):
    from PIL import Image

    if len(msg.data) > 4_194_304:
        raise ValueError("compressed frame too large")
    try:
        with Image.open(io.BytesIO(bytes(msg.data))) as image:
            if (
                image.format not in ("PNG", "JPEG")
                or not 0 < image.width <= 1024
                or not 0 < image.height <= 1024
            ):
                raise ValueError("unsupported compressed frame")
            return image.width, image.height, image.convert("RGB").tobytes()
    except Image.DecompressionBombError as exc:
        raise ValueError("compressed frame dimensions too large") from exc
