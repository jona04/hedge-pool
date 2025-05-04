from fastapi import APIRouter
from schemas.hedge_config_schema import HedgeConfigSchema
from entities.hedge_config_entity import HedgeConfig
from services.hedge_executor_service import start_hedge_execution
import asyncio

router = APIRouter()

@router.post("/hedge/start", tags=["hedge"])
async def start_hedge(config: HedgeConfigSchema):
    config_entity = HedgeConfig(**config.dict())
    asyncio.create_task(start_hedge_execution(config_entity))
    return {"status": "Hedge execution started"}
