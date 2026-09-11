"""异步数据库会话。数据库不可用时整体降级为内置兜底数据，保证页面永远能打开。"""
import ssl
from contextlib import asynccontextmanager
from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings

_engine = None
_session_factory = None
_db_available: bool = False


def _ssl_context():
    mode = (settings.SUPABASE_DB_SSLMODE or "require").lower()
    if mode == "disable":
        return None
    ctx = ssl.create_default_context()
    if mode == "require-no-verify":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
    return ctx


def init_engine() -> bool:
    """建引擎并探活。返回数据库是否可用。"""
    global _engine, _session_factory, _db_available
    if not settings.db_password_set:
        _db_available = False
        return False
    try:
        kwargs = {"pool_pre_ping": True, "pool_size": 5, "max_overflow": 5}
        ssl_ctx = _ssl_context()
        if ssl_ctx is not None:
            kwargs["connect_args"] = {"ssl": ssl_ctx}
        _engine = create_async_engine(settings.database_url, **kwargs)
        _session_factory = async_sessionmaker(
            _engine, expire_on_commit=False, autoflush=False
        )
        _db_available = True
        return True
    except Exception:
        _engine = None
        _session_factory = None
        _db_available = False
        return False


async def dispose_engine() -> None:
    global _engine
    if _engine is not None:
        await _engine.dispose()
        _engine = None


def db_available() -> bool:
    return _db_available


def set_db_available(value: bool) -> None:
    """启动探活失败时手动降级，让所有查询走内置兜底。"""
    global _db_available
    _db_available = value


@asynccontextmanager
async def session_scope() -> AsyncIterator[AsyncSession | None]:
    """拿到一个会话；数据库不可用时返回 None，调用方走兜底逻辑。"""
    if not _db_available or _session_factory is None:
        yield None
        return
    async with _session_factory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI Depends 版本：数据库不可用时直接抛 503。"""
    if not _db_available or _session_factory is None:
        from fastapi import HTTPException

        raise HTTPException(status_code=503, detail="database not configured")
    async with _session_factory() as session:
        yield session
