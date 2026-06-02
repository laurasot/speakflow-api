from functools import lru_cache
from typing import Annotated

from fastapi import Depends

from app.services.session_manager import SessionManager


@lru_cache(maxsize=1)
def get_session_manager() -> SessionManager:
    return SessionManager()


SessionManagerDep = Annotated[SessionManager, Depends(get_session_manager)]
