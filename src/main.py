from fastapi import FastAPI
from fastapi.requests import Request
from fastapi.responses import JSONResponse

from src.api.v1 import auth, onedrive, mail

app = FastAPI(
    title="MS365 Agent API",
    description="A FastAPI application to interact with Microsoft 365 services, including OneDrive and Mail.",
    version="1.0.0",
    )

app.include_router(auth.router)
app.include_router(onedrive.router)
app.include_router(mail.router)


@app.exception_handler(PermissionError)
async def domain_not_allowed_handler(request: Request, exc: PermissionError) -> JSONResponse:
    return JSONResponse(status_code=403, content={"detail": str(exc)})
