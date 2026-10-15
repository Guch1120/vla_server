"""ROS非依存の実行時計・型整合・dry-run通信。"""

import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from urllib.parse import urlparse
import httpx
from vla_server.schemas import Observation, PredictResponse


@dataclass(frozen=True)
class ClockSample:
    timestamp_ns: int
    domain: str
    epoch: str
    valid: bool = True


class WallClock:
    def read(self):
        return ClockSample(time.time_ns(), "unix", "unix")


class ExecutionClock:
    """実行側の時計を保持し、巻き戻りと配信停止を検出する。"""

    def __init__(self, domain, stall_s=1.0):
        if domain not in ("robot", "ros_sim") or not 0 < stall_s <= 10:
            raise ValueError("invalid execution clock configuration")
        self.domain = domain
        self.stall_s = stall_s
        self.timestamp_ns = 0
        self.epoch = str(uuid.uuid4())
        self.last_progress = time.monotonic()

    def update(self, timestamp_ns):
        reset = timestamp_ns < self.timestamp_ns
        if reset:
            self.epoch = str(uuid.uuid4())
        if reset or timestamp_ns > self.timestamp_ns:
            self.last_progress = time.monotonic()
        self.timestamp_ns = timestamp_ns
        return reset

    def read(self):
        return ClockSample(
            self.timestamp_ns,
            self.domain,
            self.epoch,
            self.timestamp_ns > 0
            and time.monotonic() - self.last_progress < self.stall_s,
        )


def controller_route(kind):
    if kind == "joint_position":
        return "joint_trajectory"
    if kind in ("joint_velocity", "ee_twist"):
        return "moveit_servo"
    raise ValueError("unsupported action kind")


class DryRunClient:
    def __init__(
        self,
        server_url,
        model_id,
        task="",
        timeout=1.0,
        client=None,
        dry_run=True,
        clock=None,
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
        if not 0 < timeout <= 10:
            raise ValueError("invalid timeout")
        self.client = client or httpx.Client(
            base_url=server_url, timeout=timeout, trust_env=False
        )
        self.model_id = model_id
        self.task = task
        self.timeout = timeout
        self.spec = None
        self.clock = clock or WallClock()

    def validate_clock(self, result):
        now = self.clock.read()
        if (
            not now.valid
            or result.source_clock_domain != now.domain
            or result.source_clock_epoch != now.epoch
            or not -50_000_000
            <= now.timestamp_ns - result.source_timestamp_ns
            <= 1_000_000_000
        ):
            raise ValueError("expired response or execution clock changed")

    def predict(self, observation):
        start = time.monotonic()
        obs = Observation.model_validate(observation)
        now = self.clock.read()
        if (
            not now.valid
            or obs.clock_domain != now.domain
            or obs.clock_epoch != now.epoch
            or not -50_000_000 <= now.timestamp_ns - obs.timestamp_ns <= 1_000_000_000
        ):
            raise ValueError("stale observation or execution clock changed")
        if self.spec is None:
            response = self.client.get("/v1/models")
            response.raise_for_status()
            self.spec = next(
                (s for s in response.json() if s["model_id"] == self.model_id), None
            )
            if not self.spec or not self.spec["ready"]:
                raise ValueError("model unavailable")
        request_id = str(uuid.uuid4())
        now = self.clock.read()
        if now.epoch != obs.clock_epoch or not now.valid:
            raise ValueError("execution clock changed before send")
        response = self.client.post(
            "/v1/predict",
            json=dict(
                request_id=request_id,
                model_id=self.model_id,
                observation=obs.model_dump(),
                task=self.task,
                dry_run=True,
                execution_timestamp_ns=now.timestamp_ns,
                max_inference_ms=self.timeout * 1000,
            ),
        )
        response.raise_for_status()
        result = PredictResponse.model_validate(response.json())
        if (
            time.monotonic() - start > self.timeout
            or result.source_timestamp_ns != obs.timestamp_ns
            or result.request_id != request_id
            or result.model_id != self.model_id
        ):
            raise ValueError("expired or mismatched response")
        self.validate_clock(result)
        # 旧Unixクライアントだけは同一Unix時計を前提に生成時刻も検査する。
        if (
            now.domain == "unix"
            and not -50_000_000
            <= time.time_ns() - result.generated_timestamp_ns
            <= 1_000_000_000
        ):
            raise ValueError("expired server timestamp")
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
    """処理中1件と最新待機1件。時計リセット前の応答は破棄する。"""

    def __init__(self, client):
        self.client = client
        self.pool = ThreadPoolExecutor(max_workers=1)
        self.future = None
        self.pending = None
        self.state = "HOLD"
        self.closed = False
        self.generation = 0
        self.future_generation = 0
        self.last_success = 0.0

    def offer(self, observation):
        if not self.closed:
            self.pending = observation

    def invalidate(self):
        self.generation += 1
        self.pending = None
        self.state = "HOLD"
        self.client.spec = None

    def poll(self):
        result = None
        if time.monotonic() - self.last_success > 1.0:
            self.state = "HOLD"
        if self.future is not None and self.future.done():
            try:
                result = self.future.result()
                if self.future_generation != self.generation:
                    raise ValueError("clock reset while inference was running")
                if hasattr(self.client, "validate_clock"):
                    self.client.validate_clock(result)
                elif time.time_ns() - result.source_timestamp_ns > 1_000_000_000:
                    raise ValueError("expired queued response")
                self.state = "DRY_RUN"
                self.last_success = time.monotonic()
            except Exception:
                result = None
                self.state = "HOLD"
                self.client.spec = None
                self.pending = None
            self.future = None
        if self.future is None and self.pending is not None and not self.closed:
            obs = self.pending
            self.pending = None
            self.future_generation = self.generation
            self.future = self.pool.submit(self.client.predict, obs)
        return result

    def close(self):
        self.closed = True
        self.pending = None
        self.state = "HOLD"
        self.pool.shutdown(wait=True, cancel_futures=True)
        self.client.close()
