from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app import incidents_api, ingestion, workers
from app.config import get_settings
from app.logging_setup import configure_logging, get_logger
from app.models import HealthOut, SignalAccepted, SignalIn
from app.storage import mongo, postgres, redis_cache

settings = get_settings()
configure_logging(settings.log_level)
log = get_logger(__name__)

limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[],
    storage_uri="memory://",
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    log.info("startup.begin")
    postgres.init_engine()
    mongo.init_client()
    redis_cache.init_client()
    try:
        await mongo.ensure_indexes()
    except Exception as e:
        log.warning("mongo.index.skip", error=str(e))
    await workers.start_workers()
    log.info("startup.complete")
    yield
    log.info("shutdown.begin")
    await workers.stop_workers()
    await postgres.close_engine()
    await mongo.close_client()
    await redis_cache.close_client()
    log.info("shutdown.complete")


app = FastAPI(title="Incident Management System", version="0.1.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(incidents_api.router)


@app.get("/health", response_model=HealthOut)
async def health() -> JSONResponse:
    checks: dict[str, bool] = {}
    errors: dict[str, str] = {}
    for name, fn in (
        ("postgres", postgres.ping),
        ("mongo", mongo.ping),
        ("redis", redis_cache.ping),
    ):
        try:
            checks[name] = bool(await fn())
        except Exception as e:
            checks[name] = False
            errors[name] = str(e)
    healthy = all(checks.values())
    body: dict[str, object] = {"status": "ok" if healthy else "degraded", "checks": checks}
    if errors:
        body["errors"] = errors
    return JSONResponse(status_code=200 if healthy else 503, content=body)


@app.post("/signals", status_code=status.HTTP_202_ACCEPTED, response_model=None)
@limiter.limit(f"{settings.rate_limit_per_second}/second")
async def post_signal(request: Request, signal: SignalIn) -> SignalAccepted | JSONResponse:
    accepted = await ingestion.offer(signal)
    if not accepted:
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "backpressure",
                "detail": "ingest queue at or above backpressure threshold",
                "queue_pct_full": ingestion.queue_pct_full(),
            },
            headers={"Retry-After": "5"},
        )
    snap = ingestion.snapshot()
    return SignalAccepted(
        accepted=True,
        queue_depth=int(snap["queue_depth"]),
        queue_pct_full=float(snap["queue_pct_full"]),
    )


@app.get("/metrics")
async def metrics() -> dict[str, object]:
    snap = ingestion.snapshot()
    redis_metrics = await redis_cache.get_metrics()
    return {"queue": snap, "throughput": redis_metrics}
