import time
import uuid
import pytest
from fastapi.testclient import TestClient
from vla_server.api import create_app
from vla_server.registry import default_registry


@pytest.fixture
def client():
    return TestClient(create_app())


def payload(model="mock_piper"):
    return dict(
        request_id=str(uuid.uuid4()),
        model_id=model,
        observation=dict(
            timestamp_ns=time.time_ns(),
            joint_names=["joint_1", "joint_2"],
            joint_positions_rad=[0.0, 0.0],
            images={},
        ),
        task="synthetic",
    )


def test_health_models(client):
    assert client.get("/health").json()["actuation"] is False
    models = client.get("/v1/models").json()
    assert len(models) == 3
    assert all(
        m["checkpoint"] and m["normalization_version"] and not m["trained"]
        for m in models
    )


def test_predict_duplicate(client):
    p = payload()
    r = client.post("/v1/predict", json=p)
    assert r.status_code == 200
    assert r.json()["actions"] == [[0.0, 0.0], [0.0, 0.0]]
    assert client.post("/v1/predict", json=p).status_code == 409


@pytest.mark.parametrize(
    "change,code",
    [({"model_id": "unknown"}, 404), ({"dry_run": False}, 422), ({"extra": 1}, 422)],
)
def test_request_errors(client, change, code):
    p = payload()
    p.update(change)
    assert client.post("/v1/predict", json=p).status_code == code


@pytest.mark.parametrize(
    "change",
    [
        {"timestamp_ns": 1},
        {"timestamp_ns": time.time_ns() + 10**12},
        {"joint_positions_rad": [0.0]},
        {"joint_positions_rad": ["nan", 0.0]},
        {"joint_positions_rad": [True, 0.0]},
        {"joint_names": ["joint_1", "joint_1"]},
        {"images": {"front": "invalid"}},
        {"clock_domain": "ros_sim"},
    ],
)
def test_observation_errors(client, change):
    p = payload()
    p["observation"].update(change)
    assert client.post("/v1/predict", json=p).status_code == 422


def test_oversize(client):
    assert client.post("/v1/predict", content=b"x" * 5_000_001).status_code == 413


@pytest.mark.parametrize("actions", [[[float("nan"), 0.0]], [[0.0]], [[0.0, 0.0]]])
def test_bad_adapter(actions):
    registry = default_registry()
    registry.adapters["mock_piper"].infer = lambda req: actions
    c = TestClient(create_app(registry))
    assert c.post("/v1/predict", json=payload()).status_code == 409


def test_backend_disconnect():
    registry = default_registry()

    def fail(req):
        raise ConnectionError("private detail")

    registry.adapters["mock_piper"].infer = fail
    r = TestClient(create_app(registry)).post("/v1/predict", json=payload())
    assert r.status_code == 503
    assert "private" not in r.text


def test_not_ready():
    registry = default_registry()
    registry.specs["mock_piper"] = registry.specs["mock_piper"].model_copy(
        update={"ready": False}
    )
    assert (
        TestClient(create_app(registry)).post("/v1/predict", json=payload()).status_code
        == 409
    )


def test_expired_inference(monkeypatch):
    import vla_server.api as api

    registry = default_registry()
    original = registry.adapters["mock_piper"].infer
    p = payload()
    stamp = p["observation"]["timestamp_ns"]

    def slow(req):
        monkeypatch.setattr(api.time, "time_ns", lambda: stamp + 2_000_000_000)
        return original(req)

    registry.adapters["mock_piper"].infer = slow
    assert (
        TestClient(create_app(registry)).post("/v1/predict", json=p).status_code == 504
    )


def test_camera_roundtrip(client):
    p = payload("mock_rgb")
    stamp = p["observation"]["timestamp_ns"]
    p["observation"]["images"] = {
        "front": dict(
            timestamp_ns=stamp,
            frame_id="fixture",
            calibration_id="synthetic",
            width=1,
            height=1,
            data_base64="AAAA",
        )
    }
    assert client.post("/v1/predict", json=p).status_code == 200
    p["request_id"] = str(uuid.uuid4())
    p["observation"]["images"]["front"]["timestamp_ns"] -= 100_000_000
    assert client.post("/v1/predict", json=p).status_code == 422


def test_registry_rejects_duplicate_and_metadata_mutation():
    registry = default_registry()
    spec = registry.specs["mock_piper"]
    with pytest.raises(ValueError):
        spec.checkpoint = "other"
    with pytest.raises(ValueError):
        registry.register(spec, registry.adapters["mock_piper"])


@pytest.mark.parametrize("domain", ["ros_sim", "robot"])
def test_execution_clock_is_authoritative(client, domain):
    p = payload()
    obs = p["observation"]
    obs.update(
        timestamp_ns=123_000_000_000, clock_domain=domain, clock_epoch="execution-1"
    )
    p["execution_timestamp_ns"] = 123_020_000_000
    response = client.post("/v1/predict", json=p)
    assert response.status_code == 200
    assert response.json()["source_timestamp_ns"] == 123_000_000_000
    assert response.json()["source_clock_domain"] == domain
    assert response.json()["source_clock_epoch"] == "execution-1"
    p["request_id"] = str(uuid.uuid4())
    p["execution_timestamp_ns"] += 2_000_000_000
    assert client.post("/v1/predict", json=p).status_code == 422


def test_simulation_requires_clock_reference(client):
    p = payload()
    p["observation"]["clock_domain"] = "ros_sim"
    assert client.post("/v1/predict", json=p).status_code == 422


def test_execution_clock_deadline_is_monotonic(monkeypatch):
    import vla_server.api as api

    registry = default_registry()
    p = payload()
    p["observation"].update(timestamp_ns=100, clock_domain="ros_sim")
    p["execution_timestamp_ns"] = 100
    p["max_inference_ms"] = 10.0
    ticks = [0.0]
    original = registry.adapters["mock_piper"].infer

    def delayed(req):
        ticks[0] = 0.1
        return original(req)

    registry.adapters["mock_piper"].infer = delayed
    monkeypatch.setattr(api.time, "perf_counter", lambda: ticks[0])
    assert (
        TestClient(create_app(registry)).post("/v1/predict", json=p).status_code == 504
    )
