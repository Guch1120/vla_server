"""未校正のπ₀.₅出力を可視化する実験用投影。実機契約として使用しない。"""

import math

SCHEMA = "experimental_pi05_first7_delta_rad_finger_m_v1"
JOINTS = [f"joint{i}" for i in range(1, 8)]
LIMITS = [
    (-2.618, 2.618),
    (0.0, 3.14),
    (-2.967, 0.0),
    (-1.745, 1.745),
    (-1.22, 1.22),
    (-2.0944, 2.0944),
    (0.0, 0.035),
]


def validate_positions(positions):
    if len(positions) != 7 or any(
        type(v) not in (int, float) or not math.isfinite(v) for v in positions
    ):
        raise ValueError("seven finite joint values required")


def probe_state(positions):
    """関節rangeによる仮の正規化。学習データの統計ではない。"""
    validate_positions(positions)
    return [
        max(-1.0, min(1.0, 2 * (v - lo) / (hi - lo) - 1))
        for v, (lo, hi) in zip(positions, LIMITS)
    ] + [0.0] * 25


def project_chunk(actions, positions):
    validate_positions(positions)
    if len(actions) != 50 or any(len(row) != 32 for row in actions):
        raise ValueError("expected 50x32 base actions")
    if any(
        type(v) not in (int, float) or not math.isfinite(v)
        for row in actions
        for v in row
    ):
        raise ValueError("non-finite base action")
    result = []
    for row in actions:
        # 先頭6次元をchunk開始姿勢からのrad変位と仮定。振幅は最大0.5rad。
        arm = [
            max(lo, min(hi, start + max(-0.5, min(0.5, value))))
            for value, start, (lo, hi) in zip(row[:6], positions[:6], LIMITS[:6])
        ]
        # 第7次元を[-1,1]の開閉量と仮定。joint8はシミュレータのmimicに任せる。
        finger = (max(-1.0, min(1.0, row[6])) + 1) * 0.0175
        result.append(arm + [finger])
    return result
