import asyncio
import json
from pathlib import Path
import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import config
from .agent import Run, ACTIVE

app = FastAPI(title="HelmOps")
RUNS: dict[str, Run] = {}
app.mount("/artifacts", StaticFiles(directory=config.ARTIFACTS), name="artifacts")


class GoalIn(BaseModel):
    goal: str


class Decision(BaseModel):
    approve: bool


class FaultIn(BaseModel):
    mode: str = "commit_then_500"
    count: int = 1


def get(rid) -> Run:
    if rid not in RUNS:
        raise HTTPException(404, "unknown run")
    return RUNS[rid]


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/api/runs")
async def start(body: GoalIn):
    if any(r.status in ACTIVE for r in RUNS.values()):
        raise HTTPException(409, "a run is already active")
    if not body.goal.strip():
        raise HTTPException(400, "goal is empty")
    run = Run(body.goal.strip())
    RUNS[run.id] = run
    run.task = asyncio.create_task(run.execute())
    return {"id": run.id}


@app.get("/api/runs/{rid}")
def show(rid: str):
    return get(rid).snapshot()


@app.post("/api/runs/{rid}/pause")
def pause(rid: str):
    get(rid).pause()
    return {"ok": True}


@app.post("/api/runs/{rid}/resume")
def resume(rid: str):
    get(rid).resume()
    return {"ok": True}


@app.post("/api/runs/{rid}/cancel")
def cancel(rid: str):
    get(rid).cancel()
    return {"ok": True}


@app.post("/api/runs/{rid}/approvals/{item_id}")
def approve(rid: str, item_id: str, d: Decision):
    if not get(rid).decide(item_id, d.approve):
        raise HTTPException(409, "no pending approval for that item")
    return {"ok": True}


@app.get("/api/runs/{rid}/stream")
async def stream(rid: str):
    run = get(rid)

    async def gen():
        sent, last = 0, ""
        while True:
            while sent < len(run.events):
                yield f"event: log\ndata: {json.dumps(run.events[sent])}\n\n"
                sent += 1
            snap = json.dumps(run.snapshot())
            if snap != last:
                last = snap
                yield f"event: state\ndata: {snap}\n\n"
            if run.status not in ACTIVE and sent >= len(run.events):
                break
            await asyncio.sleep(0.4)

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/erp/reset")
async def erp_reset():
    async with httpx.AsyncClient() as c:
        return (await c.post(f"{config.ERP_URL}/admin/reset")).json()


@app.post("/api/erp/fault")
async def erp_fault(f: FaultIn):
    async with httpx.AsyncClient() as c:
        return (await c.post(f"{config.ERP_URL}/admin/fault", json=f.model_dump())).json()
