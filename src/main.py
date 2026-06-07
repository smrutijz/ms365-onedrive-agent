from fastapi import FastAPI

from src.api.v1 import auth, onedrive, mail

app = FastAPI(
    title="MS365 Agent API",
    description="A FastAPI application to interact with Microsoft 365 services, including OneDrive and Mail.",
    version="1.0.0",
    )

app.include_router(auth.router)
app.include_router(onedrive.router)
app.include_router(mail.router)
