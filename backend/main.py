from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


from backend.core.config import settings
from backend.database import Base, engine

# Import Routers
from backend.api.world import router as world_router
from backend.api.agents import router as agents_router
from backend.api.analytics import router as analytics_router
from backend.api.disaster_api import router as disaster_router
from backend.api.simulation import router as simulation_router
from backend.api.websocket import router as websocket_router
from backend.api.egl_api import router as egl_router

# Initialize Database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.BACKEND_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API Routers
app.include_router(world_router, prefix=settings.API_V1_STR)
app.include_router(agents_router, prefix=settings.API_V1_STR)
app.include_router(analytics_router, prefix=settings.API_V1_STR)
app.include_router(disaster_router, prefix=settings.API_V1_STR)
app.include_router(simulation_router, prefix=settings.API_V1_STR)
app.include_router(websocket_router, prefix=settings.API_V1_STR)
app.include_router(egl_router, prefix=settings.API_V1_STR)
