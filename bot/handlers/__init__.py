"""Handlers package initialization."""
from bot.handlers.start import router as start_router
from bot.handlers.project import router as project_router
from bot.handlers.editor import router as editor_router
from bot.handlers.build import router as build_router
from bot.handlers.assets import router as assets_router
from bot.handlers.settings import router as settings_router

all_routers = [
    start_router,
    project_router,
    editor_router,
    build_router,
    assets_router,
    settings_router,
]
