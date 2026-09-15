import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.config import settings
from app.routers import auth, channels, comments, feed, searches, ws
from app.worker.scheduler import run_forever

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_forever())
    try:
        yield
    finally:
        task.cancel()


app = FastAPI(title="HR Parser", lifespan=lifespan)
app.add_middleware(SessionMiddleware, secret_key=settings.secret_key)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

app.include_router(auth.router)
app.include_router(feed.router)
app.include_router(searches.router)
app.include_router(channels.router)
app.include_router(comments.router)
app.include_router(ws.router)
