from fastapi import FastAPI
from routers import feed

app = FastAPI(
    title="ai corrector",
    description="testtest",
    version="0.0.1"
)

app.include_router(feed.router)

@app.get("/")
async def root():
    return {"message": "api api. ->/docs"}