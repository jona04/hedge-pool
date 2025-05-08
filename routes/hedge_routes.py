from fastapi import APIRouter
from schemas.hedge_config_schema import HedgeConfigSchema
from entities.hedge_config_entity import HedgeConfig
from services.hedge_executor_service import start_hedge_execution, stop_hedge_execution, hedge_task
import asyncio

router = APIRouter()

@router.post("/hedge/start", tags=["hedge"])
async def start_hedge(config: HedgeConfigSchema):
    config_entity = HedgeConfig(**config.dict())
    await start_hedge_execution(config_entity)
    return {"status": "Hedge execution started or already running"}

@router.post("/hedge/stop", tags=["hedge"])
async def stop_hedge():
    await stop_hedge_execution()
    return {"status": "Hedge execution stopped"}

@router.get("/hedge/status", tags=["hedge"])
async def hedge_status():
    running = hedge_task is not None and not hedge_task.done()
    return {"running": running}