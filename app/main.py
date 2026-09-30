from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.database import close, connect
from app.routers import (announcements, attendance, auth, company, dashboard, departments, files,
                         holidays, leaves, payroll, sessions, users)
from app.services.company import seed


@asynccontextmanager
async def lifespan(app: FastAPI):
    await connect()
    await seed()
    yield
    await close()


app = FastAPI(title="HRMS API", version="1.0.0", lifespan=lifespan)

# Allow every domain. Auth uses a Bearer token header (not cookies), so credentials aren't needed.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

for module in (auth, users, departments, attendance, leaves, holidays, announcements,
               payroll, sessions, company, files, dashboard):
    app.include_router(module.router, prefix="/api")


@app.get("/api/health", tags=["health"])
async def health():
    return {"status": "ok"}
