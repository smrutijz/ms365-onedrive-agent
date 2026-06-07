from fastapi import FastAPI

from src.api.v1 import auth, onedrive, mail

app = FastAPI(title="MS365 Agent — OneDrive & Mail API")

app.include_router(auth.router)
app.include_router(onedrive.router)
app.include_router(mail.router)
