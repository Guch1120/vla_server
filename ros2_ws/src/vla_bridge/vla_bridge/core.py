"""ROS非依存のdry-run同期・通信・応答検査。"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlparse
import httpx
from vla_server.schemas import Observation, PredictResponse


def controller_route(kind):
    if kind == "joint_position":
        return "joint_trajectory"
    if kind in ("joint_velocity", "ee_twist"):
        return "moveit_servo"
    raise ValueError("unsupported action kind")


class DryRunClient:
    def __init__(
        self, server_url, model_id, task="", timeout=1.0, client=None, dry_run=True
    ):
        if not dry_run:
            raise ValueError("live actuation disabled")
        url = urlparse(server_url)
        if (
            url.scheme not in ("http", "https")
            or not url.hostname
            or url.username
            or url.password
        ):
            raise ValueError("invalid server URL")
        if timeout <= 0 or timeout > 10:
            raise ValueError("invalid timeout")
        self.client = client or httpx.Client(
            base_url=server_url, timeout=timeout, trust_env=False
        )
        self.model_id = model_id
        self.task = task
        self.timeout = timeout
        self.spec = None

    def predict(self, observation):
        start = time.monotonic()
        obs = Observation.model_validate(observation)
        if self.spec is None:
            response = self.client.get("/v1/models")
            response.raise_for_status()
            self.spec = next(
                (s for s in response.json() if s["model_id"] == self.model_id), None
            )
            if not self.spec or not self.spec["ready"]:
                raise ValueError("model unavailable")
        request_id = str(uuid.uuid4())
        response = self.client.post(
            "/v1/predict",
            json=dict(
                request_id=request_id,
                model_id=self.model_id,
                observation=obs.model_dump(),
                task=self.task,
                dry_run=True,
            ),
        )
        response.raise_for_status()
        result = PredictResponse.model_validate(response.json())
        now = time.time_ns()
        if (
            time.monotonic() - start > self.timeout
            or now - obs.timestamp_ns > 1_000_000_000
            or obs.timestamp_ns - now > 50_000_000
            or result.source_timestamp_ns != obs.timestamp_ns
            or result.generated_timestamp_ns < obs.timestamp_ns - 50_000_000
            or result.generated_timestamp_ns > now + 50_000_000
            or now - result.generated_timestamp_ns > 1_000_000_000
            or result.request_id != request_id
            or result.model_id != self.model_id
        ):
            raise ValueError("expired or mismatched response")
        for key in (
            "action_schema",
            "action_kind",
            "unit",
            "frame_id",
            "robot_id",
            "joint_names",
            "action_hz",
        ):
            if getattr(result, key) != self.spec[key]:
                raise ValueError("action schema mismatch")
        if (
            obs.joint_names != result.joint_names
            or len(result.actions) != self.spec["output_horizon"]
        ):
            raise ValueError("action shape mismatch")
        controller_route(result.action_kind)
        return result

    def close(self):
        self.client.close()


class LatestWorker:
    """処理中1件と最新待機1件のみ保持し、失敗時は保持状態へ戻す。"""

    def __init__(self, client):
        self.client = client
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.pending = None
        self.state = "HOLD"
        self.closed = False
        self.last_source_ns = 0

    def offer(self, observation):
        if self.closed:
            return
        self.pending = observation

    def poll(self):
        result = None
        if time.time_ns() - self.last_source_ns > 1_000_000_000:
            self.state = "HOLD"
        if self.future is not None and self.future.done():
            try:
                result = self.future.result()
                if time.time_ns() - result.source_timestamp_ns > 1_000_000_000:
                    raise ValueError("expired queued response")
                self.state = "DRY_RUN"
                self.last_source_ns = result.source_timestamp_ns
            except Exception:
                result = None
                self.state = "HOLD"
                self.client.spec = None
                self.pending = None
            self.future = None
        if self.future is None and self.pending is not None and not self.closed:
            obs = self.pending
            self.pending = None
            self.future = self.pool.submit(self.client.predict, obs)
        return result

    def close(self):
        self.closed = True
        self.pending = None
        self.state = "HOLD"
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.client.close()
