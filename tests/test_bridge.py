import time
import pytest
from fastapi.testclient import TestClient
from vla_server.api import create_app
from vla_bridge.core import DryRunClient, controller_route
from test_mock_api import payload


def test_roundtrip():
    bridge = DryRunClient(
        "http://localhost", "mock_piper", client=TestClient(create_app())
    )
    assert bridge.predict(payload()["observation"]).action_kind == "joint_position"
    bridge.close()


@pytest.mark.parametrize(
    "kind,route",
    [
        ("joint_position", "joint_trajectory"),
        ("joint_velocity", "moveit_servo"),
        ("ee_twist", "moveit_servo"),
    ],
)
def test_routes(kind, route):
    assert controller_route(kind) == route


def test_unsafe():
    with pytest.raises(ValueError):
        DryRunClient("http://localhost", "mock_piper", dry_run=False)
    with pytest.raises(ValueError):
        controller_route("joint_delta")


@pytest.mark.parametrize(
    "field,value",
    [
        ("request_id", "other"),
        ("source_timestamp_ns", 1),
        ("generated_timestamp_ns", 1),
        ("action_schema", "bad"),
        ("unit", "rad/s"),
    ],
)
def test_bad_response(field, value):
    class Mutated:
        def __init__(self):
            self.inner = TestClient(create_app())

        def get(self, *a, **kw):
            return self.inner.get(*a, **kw)

        def post(self, *a, **kw):
            r = self.inner.post(*a, **kw)
            data = r.json()
            data[field] = value
            import httpx

            return httpx.Response(200, json=data, request=r.request)

    bridge = DryRunClient("http://localhost", "mock_piper", client=Mutated())
    with pytest.raises(ValueError):
        bridge.predict(payload()["observation"])


def test_worker_backpressure_and_disconnect():
    import threading
    from vla_bridge.core import LatestWorker

    entered = threading.Event()
    release = threading.Event()

    class Client:
        spec = {}

        def predict(self, obs):
            entered.set()
            release.wait(1)
            raise ConnectionError("offline")

        def close(self):
            pass

    worker = LatestWorker(Client())
    try:
        worker.offer({"sequence": 0})
        worker.poll()
        assert entered.wait(1)
        for i in range(100):
            worker.offer({"sequence": i})
        assert worker.pending == {"sequence": 99}
        release.set()
        deadline = time.monotonic() + 2
        while not worker.future.done() and time.monotonic() < deadline:
            time.sleep(0.001)
        assert worker.poll() is None
        assert (
            worker.state == "HOLD"
            and worker.pending is None
            and worker.client.spec is None
        )
    finally:
        release.set()
        worker.close()


def test_expired_completed_chunk_is_not_emitted():
    from concurrent.futures import Future
    from types import SimpleNamespace
    from vla_bridge.core import LatestWorker

    class Client:
        spec = {}

        def close(self):
            pass

    worker = LatestWorker(Client())
    try:
        worker.future = Future()
        worker.future.set_result(SimpleNamespace(source_timestamp_ns=1))
        assert worker.poll() is None
        assert worker.state == "HOLD"
    finally:
        worker.close()
