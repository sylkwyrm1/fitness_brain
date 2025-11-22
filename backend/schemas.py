from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, EmailStr


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr

    class Config:
        orm_mode = True


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class BiometricsData(BaseModel):
    data: Dict[str, Any]


class BiometricsOut(BiometricsData):
    pass
