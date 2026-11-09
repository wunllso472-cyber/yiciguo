"""规格库查询、自定义规格、规格纠错（众包）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from ..db import SpecFeedback, User, get_db
from ..specs import BG_COLORS, CATEGORIES, library, make_custom_key, parse_custom
from .deps import client_ip, limiter, optional_user

router = APIRouter(prefix="/api/specs", tags=["specs"])


@router.get("")
def list_specs(q: str = "", category: str = ""):
    items = library.search(q, category)
    return {
        "items": [s.to_public(brief=True) for s in items],
        "categories": CATEGORIES,
        "bg_colors": {k: {"name": v["name"], "rgb": v["rgb"]} for k, v in BG_COLORS.items()},
        "total": len(library.all()),
    }


class CustomBody(BaseModel):
    width: int = Field(ge=60, le=2000)
    height: int = Field(ge=60, le=2000)
    kb_min: int | None = Field(default=None, ge=1, le=5000)
    kb_max: int | None = Field(default=None, ge=3, le=5000)
    dpi: int = Field(default=300, ge=72, le=1200)


@router.post("/custom")
def custom(body: CustomBody):
    key = make_custom_key(body.width, body.height, body.kb_min, body.kb_max, body.dpi)
    spec = parse_custom(key)
    if spec is None:
        raise HTTPException(400, "规格参数不合理，请检查像素和 KB 范围")
    return spec.to_public()


@router.get("/{key}")
def get_spec(key: str):
    spec = library.get(key)
    if spec is None:
        raise HTTPException(404, "规格不存在")
    return spec.to_public()


class FeedbackBody(BaseModel):
    spec_id: str = Field(max_length=64)
    content: str = Field(min_length=4, max_length=2000)
    url: str | None = Field(default=None, max_length=512)
    contact: str | None = Field(default=None, max_length=128)


@router.post("/feedback")
def feedback(body: FeedbackBody, request: Request, user: User | None = Depends(optional_user),
             db: Session = Depends(get_db)):
    limiter.check(f"fb:{client_ip(request)}", 10, 3600)
    db.add(SpecFeedback(user_id=user.id if user else None, spec_id=body.spec_id, content=body.content,
                        url=body.url, contact=body.contact))
    db.commit()
    return {"ok": True}
