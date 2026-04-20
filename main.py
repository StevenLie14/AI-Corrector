from fastapi import FastAPI
from routers import feed , assess

app = FastAPI(
    title="ai corrector",
    description="testtest",
    version="0.0.1"
)

app.include_router(feed.router)
app.include_router(assess.router)

@app.get("/")
async def root():
    return {"message": "api api. ->/docs"}