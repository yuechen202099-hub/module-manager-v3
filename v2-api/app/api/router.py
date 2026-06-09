from fastapi import APIRouter

from app.api.routes import auth, catalog, exports, groups, jobs, projects, scan, tasks

api_router = APIRouter()
api_router.include_router(auth.router, tags=["auth"])
api_router.include_router(projects.router, tags=["projects"])
api_router.include_router(catalog.router, tags=["catalog"])
api_router.include_router(scan.router, tags=["scan"])
api_router.include_router(tasks.router, tags=["tasks"])
api_router.include_router(groups.router, tags=["groups"])
api_router.include_router(exports.router, tags=["exports"])
api_router.include_router(jobs.router, tags=["jobs"])

