from collections.abc import Iterator
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.config import Settings


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_session(request: Request) -> Iterator[Session]:
    session: Session = request.app.state.session_factory()
    try:
        yield session
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_now(request: Request) -> datetime:
    return request.app.state.clock()


def get_ai_transport(request: Request) -> Any:
    return request.app.state.ai_transport


SessionDep = Annotated[Session, Depends(get_session)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
NowDep = Annotated[datetime, Depends(get_now)]
TransportDep = Annotated[Any, Depends(get_ai_transport)]
