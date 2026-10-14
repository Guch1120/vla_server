from fastapi.testclient import TestClient
from vla_server.api import app

c = TestClient(app)

def payload(model="mock_piper", joints=None):
    return {
        "request_id": "test",
        "model_id": model,
        "observation": {
            "timestamp_ns": 1,
            "joint_names": ["joint_1", "joint_2"],
            "joint_positions_rad": [0.0, 0.0] if joints is None else joints,
            "images": {},
        },
        "task": "synthetic",
    }

def test_health_is_inert():
    assert c.get("/health").json()["actuation"] is False

def test_mock_predict():
    r = c.post("/v1/predict", json=payload())
    assert r.status_code == 200
    a = r.json()
    assert a["actions"] == [[0.0, 0.0], [0.0, 0.0]]
    assert a["action_schema"] == "mock_joint_position_v1"

def test_unknown_model():
    assert c.post("/v1/predict", json=payload("bad")).status_code == 404

def test_mismatched_shape():
    assert c.post("/v1/predict", json=payload(joints=[0.0])).status_code == 422

def test_non_finite_rejected():
    p = payload()
    p["observation"]["joint_positions_rad"] = ["nan", 0]
    assert c.post("/v1/predict", json=p).status_code == 422

def test_nonempty_images_rejected():
    p = payload()
    p["observation"]["images"] = {"front": "arbitrary"}
    assert c.post("/v1/predict", json=p).status_code == 422
