import pytest
from vla_server.sim_projection import project_chunk, probe_state, LIMITS


def test_experimental_projection_units_and_limits():
    start = [0.0, 1.0, -1.0, 0.0, 0.0, 0.0, 0.0]
    row = [0.1, -0.2, 0.3, -0.4, 0.5, -0.6, 1.0] + [0.0] * 25
    target = project_chunk([row] * 50, start)[0]
    assert target == pytest.approx([0.1, 0.8, -0.7, -0.4, 0.5, -0.5, 0.035])
    assert probe_state([lo for lo, hi in LIMITS]) == [-1.0] * 7 + [0.0] * 25
    for target in project_chunk([[100.0] * 32] * 50, [hi for lo, hi in LIMITS]):
        assert all(lo <= v <= hi for v, (lo, hi) in zip(target, LIMITS))


@pytest.mark.parametrize("actions", [[[0.0] * 32], [[float("nan")] * 32] * 50])
def test_projection_rejects_bad_chunk(actions):
    with pytest.raises(ValueError):
        project_chunk(actions, [0.0] * 7)
