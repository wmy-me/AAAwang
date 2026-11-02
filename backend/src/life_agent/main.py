"""FastAPI application entry point."""

import logging

from fastapi import FastAPI

from life_agent.api.router import api_router
from life_agent.core.config import get_settings

settings = get_settings()

logging.basicConfig(level=settings.log_level.upper())

app = FastAPI(title=settings.app_name, version="0.1.0")
app.include_router(api_router, prefix="/api")

# 便于 IDE（如 PyCharm）直接运行 main.py；命令行启动方式见 backend/README.md。
if __name__ == "__main__":
    import uvicorn

    uvicorn.run("life_agent.main:app", host="127.0.0.1", port=8000)
