"""FastAPI application factory for Jarvis Mission Control."""

from typing import Literal

import uvicorn
from fastapi import FastAPI
from pydantic import BaseModel, ConfigDict

from jarvis_api.config import get_settings


class HealthResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    service: Literal["jarvis-api"] = "jarvis-api"
    status: Literal["ok"] = "ok"
    version: Literal["0.1.0"] = "0.1.0"


def create_app() -> FastAPI:
    app = FastAPI(title="Jarvis V1 API", version="0.1.0")

    @app.get("/health", response_model=HealthResponse, tags=["system"])
    async def health() -> HealthResponse:
        return HealthResponse()

    return app


app = create_app()


def run() -> None:
    settings = get_settings()
    uvicorn.run("jarvis_api.main:app", host=settings.api_host, port=settings.api_port)


if __name__ == "__main__":
    run()
