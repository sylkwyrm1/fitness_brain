from __future__ import annotations

import json

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from .. import models, schemas
from ..auth import get_current_user
from ..database import get_db

router = APIRouter(prefix="/me", tags=["me"])


def _deserialize(data_json: str | None) -> dict:
    if not data_json:
        return {}
    try:
        return json.loads(data_json)
    except json.JSONDecodeError:
        return {}


@router.get("/biometrics", response_model=schemas.BiometricsOut)
def get_biometrics(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    record = db.query(models.BiometricsProfile).filter(models.BiometricsProfile.user_id == user.id).first()
    return {"data": _deserialize(record.data_json if record else None)}


@router.put("/biometrics", response_model=schemas.BiometricsOut)
def put_biometrics(
    payload: schemas.BiometricsData,
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    record = db.query(models.BiometricsProfile).filter(models.BiometricsProfile.user_id == user.id).first()
    if record is None:
        record = models.BiometricsProfile(user_id=user.id, data_json=json.dumps(payload.data))
        db.add(record)
    else:
        record.data_json = json.dumps(payload.data)
    db.commit()
    db.refresh(record)
    return {"data": _deserialize(record.data_json)}


@router.get("/shared-state")
def get_shared_state(
    db: Session = Depends(get_db),
    user: models.User = Depends(get_current_user),
):
    biometrics = db.query(models.BiometricsProfile).filter(models.BiometricsProfile.user_id == user.id).first()
    biometrics_data = _deserialize(biometrics.data_json if biometrics else None)

    return {
        "biometrics": biometrics_data,
        "workout": {},
        "nutrition": {},
        "supplements": {},
        "recipes": {"schema_version": 1, "recipes": []},
        "pantry": {"schema_version": 1, "items": []},
        "planner": {},
        "workout_history": {},
        "preferences": {},
    }
