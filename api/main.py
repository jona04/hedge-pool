from fastapi import FastAPI
from routes import hedge_routes

app = FastAPI(title="Uniswap Hedge Strategy API")

app.include_router(hedge_routes.router)
