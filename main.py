from fastapi import FastAPI
from routers import feed, assess
from utils.json_response import NeatJSONResponse

app = FastAPI(
    title="ai corrector",
    description="testtest",
    version="0.0.1",
    default_response_class=NeatJSONResponse,
)

app.include_router(feed.router)
app.include_router(assess.router)

@app.get("/")
async def root():
    return {"message": "api api. ->/docs"}