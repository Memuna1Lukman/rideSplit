from fastapi import FastAPI,Response
from . import models
from .database import engine
from .routes import auth,user
from fastapi.middleware.cors import CORSMiddleware


app = FastAPI()


app.include_router(auth.router)
app.include_router(user.router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"], # React Vite dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)