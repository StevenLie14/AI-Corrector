import os

# Best practice untuk container: 1 proses per container, scale REPLICA (bukan menumpuk
# worker dalam satu instance yang bikin memory berlipat -> OOM). Override via WEB_CONCURRENCY.
workers = int(os.getenv("WEB_CONCURRENCY", "1"))
worker_class = "uvicorn.workers.UvicornWorker"

# Honor $PORT (App Service / Container Apps), default 3100 — samakan dengan
# PORT/SERVER_PORT/WEBSITES_PORT di .env dan --target-port Container Apps.
bind = f"0.0.0.0:{os.getenv('PORT', '3100')}"

# Feed satu file bisa 60-90 dtk (extract + vision + embed); batch lebih lama.
timeout = 600
graceful_timeout = 120

# Recycle worker berkala supaya memory tidak menumpuk seumur proses.
max_requests = 1000
max_requests_jitter = 50

log_file = "-"
