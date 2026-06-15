import logging
import os

from fastapi import FastAPI
from routers import feed, assess
from utils.json_response import NeatJSONResponse

_DEBUG = os.getenv("DEBUG", "").lower() == "true"

logging.basicConfig(
    level=logging.DEBUG if os.getenv("DEBUG", "").lower() == "true" else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

app = FastAPI(
    title="ai corrector",
    description="testtest",
    version="0.6.7",
    default_response_class=NeatJSONResponse,
)

app.include_router(feed.router)
app.include_router(assess.router)

if _DEBUG:
    from routers import debug
    app.include_router(debug.router)

@app.get("/")
async def root():
    return {"message": "api api. ->/docs"}