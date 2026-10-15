"""推論のみを提供し、モータへの経路を持たない。"""

import threading
import time
from collections import OrderedDict
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from .registry import default_registry
from .schemas import PredictRequest, PredictResponse

MAX_BODY = 5_000_000
MAX_AGE_NS = 1_000_000_000
FUTURE_NS = 50_000_000


def create_app(registry=None):
    registry = registry if registry is not None else default_registry()
    app = FastAPI(title="vla_server", version="0.2.0")
    app.state.registry = registry
    seen = OrderedDict()
    lock = threading.Lock()

    @app.middleware("http")
    async def bounded_body(request: Request, call_next):
        if request.method == "POST":
            body = bytearray()
            async for chunk in request.stream():
                body.extend(chunk)
                if len(body) > MAX_BODY:
                    return JSONResponse(
                        {"detail": "request too large"}, status_code=413
                    )
            request._body = bytes(body)
        return await call_next(request)

    @app.get("/health")
    def health():
        return {"status": "ok", "actuation": False, "trained_models_loaded": False}

    @app.get("/v1/models")
    def models():
        return [s.model_dump() for s in registry.specs.values()]

    @app.post("/v1/predict", response_model=PredictResponse)
    def predict(req: PredictRequest):
        start = time.perf_counter()
        spec = registry.specs.get(req.model_id)
        if spec is None:
            raise HTTPException(404, "unknown model_id")
        if not spec.ready:
            raise HTTPException(409, "model not ready")
        obs = req.observation
        reference_ns = req.execution_timestamp_ns
        if reference_ns is None:
            reference_ns = time.time_ns()
        age = reference_ns - obs.timestamp_ns
        if age > MAX_AGE_NS or age < -FUTURE_NS:
            raise HTTPException(422, "stale or future observation")
        if obs.joint_names != spec.joint_names or list(obs.images) != spec.camera_order:
            raise HTTPException(422, "observation schema mismatch")
        if (obs.gripper.calibration_id if obs.gripper else None) != spec.gripper_schema:
            raise HTTPException(422, "gripper schema mismatch")
        with lock:
            now = time.monotonic()
            while seen and next(iter(seen.values())) < now - 60:
                seen.popitem(last=False)
            if req.request_id in seen:
                raise HTTPException(409, "duplicate request_id")
            if len(seen) >= 4096:
                raise HTTPException(503, "request cache full")
            seen[req.request_id] = now
        try:
            actions = registry.adapters[req.model_id].infer(req)
            result = PredictResponse(
                request_id=req.request_id,
                model_id=spec.model_id,
                **{
                    k: getattr(spec, k)
                    for k in (
                        "action_schema",
                        "action_kind",
                        "unit",
                        "frame_id",
                        "robot_id",
                        "joint_names",
                        "action_hz",
                    )
                },
                actions=actions,
                source_timestamp_ns=obs.timestamp_ns,
                source_clock_domain=obs.clock_domain,
                source_clock_epoch=obs.clock_epoch,
                generated_timestamp_ns=time.time_ns(),
                inference_ms=(time.perf_counter() - start) * 1000,
            )
            if len(result.actions) != spec.output_horizon:
                raise ValueError("horizon mismatch")
        except (ValueError, ValidationError):
            raise HTTPException(409, "adapter action contract violation") from None
        except Exception:
            raise HTTPException(503, "inference backend unavailable") from None
        if result.inference_ms > req.max_inference_ms:
            raise HTTPException(504, "inference deadline exceeded")
        if (
            req.execution_timestamp_ns is None
            and time.time_ns() - obs.timestamp_ns > MAX_AGE_NS
        ):
            raise HTTPException(504, "response expired")
        return result

    return app


app = create_app()
