"""The public site as one process: the API at /api, the built page everywhere else.

Development does not use this (`make api` + `make web`, with Vite's proxy). The
image does. The page calls the relative `/api`, so nothing here or in the bundle
names a host: the same image runs on anyone's server.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.gzip import GZipMiddleware
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles
from starlette.types import Scope

from .api import app as api
from .fetch import ROOT

IMMUTABLE = "public, max-age=31536000, immutable"


class Page(StaticFiles):
    """web/dist, where a path that is not a file is the app: React Router owns it."""

    async def get_response(self, path: str, scope: Scope):
        try:
            response = await super().get_response(path, scope)
        except HTTPException as error:
            # A missing hashed asset is a real 404; only an app path falls back.
            if error.status_code != 404 or path.startswith("assets/"):
                raise
            response = await super().get_response("index.html", scope)
            path = "index.html"
        # Vite hashes every file under assets/, so they never change in place.
        response.headers["Cache-Control"] = IMMUTABLE if path.startswith("assets/") else "no-cache"
        return response


def create_app(dist: Path) -> FastAPI:
    site = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    site.add_middleware(GZipMiddleware, minimum_size=1024)
    site.mount("/api", api)
    site.mount("/", Page(directory=dist, html=True, check_dir=False), name="page")
    return site


app = create_app(Path(os.environ.get("ATLAS_WEB_DIST") or ROOT / "web" / "dist"))
