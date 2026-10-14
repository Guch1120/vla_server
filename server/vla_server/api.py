"""Mock-only API. NEVER use output for real hardware."""
from __future__ import annotations
import time
from fastapi import FastAPI, HTTPException
from .registry import REGISTRY
from .schemas import PredictRequest, PredictResponse

app = FastAPI(title="vla_server", version="0.0.1")

@app.get("/health")
def health():
    return {"status": "ok", "actuation": False, "trained_models_loaded": False}

@app.get("/v1/models")
def list_models():
    return [{"model_id": s.model_id, "adapter": s.adapter,
             "action_schema": s.action_schema, "action_kind": s.action_kind,
             "joint_names": list(s.joint_names), "action_hz": s.action_hz,
             "output_horizon": s.output_horizon, "trained": False}
            for s in REGISTRY.values()]

@app.post("/v1/predict", response_model=PredictResponse)
def predict(req: PredictRequest):
    t0 = time.perf_counter()
    s = REGISTRY.get(req.model_id)
    if s is None:
        raise HTTPException(404, "unknown model_id")
    if s.adapter != "mock":
        raise HTTPException(503, "model adapter not implemented")
    if tuple(req.observation.joint_names) != s.joint_names:
        raise HTTPException(422, "joint schema mismatch")
    # This is an intentionally inert synthetic fixture; not a learned policy.
    return PredictResponse(
        request_id=req.request_id, model_id=s.model_id,
        action_schema=s.action_schema, action_kind=s.action_kind,
        joint_names=list(s.joint_names), action_hz=s.action_hz,
        actions=[[0.0] * len(s.joint_names) for _ in range(s.output_horizon)],
        source_timestamp_ns=req.observation.timestamp_ns,
        inference_ms=(time.perf_counter()-t0)*1000,
    )
