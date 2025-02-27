import datetime

import fastapi.responses
from fastapi import APIRouter, FastAPI, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import ORJSONResponse
from sqlalchemy import text
from starlette.middleware.authentication import AuthenticationMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from apps.authorization.managers import AuthorizationManager
from apps.authorization.middlewares import JWTTokenBackend
from apps.authorization.routers import groups_router, permissions_router, roles_router
from apps.CORE.db import async_engine, async_session_factory, engine, redis, session_factory
from apps.CORE.enums import JSENDStatus
from apps.CORE.exceptions import BackendException
from apps.CORE.handlers import backend_exception_handler, validation_exception_handler
from apps.CORE.managers import TokensManager
from apps.CORE.responses import Responses
from apps.CORE.schemas import JSENDOutSchema
from apps.users.routers import register_router, tokens_router, users_router
from apps.wishmaster.routers import wish_router, wishlist_router
from loggers import get_logger, setup_logging
from settings import Settings

logger = get_logger(name=__name__)

app = FastAPI(
    debug=Settings.DEBUG,
    title="FastAPI Quickstart",
    description="",
    version="0.0.1",
    openapi_url="/openapi.json" if Settings.ENABLE_OPENAPI else None,
    redoc_url=None,  # Redoc disabled
    docs_url="/docs/" if Settings.ENABLE_OPENAPI else None,
    default_response_class=ORJSONResponse,
    responses=Responses.BASE,
)

# State objects
app.state.tokens_manager = TokensManager(
    secret_key=Settings.TOKENS_SECRET_KEY,
    default_token_lifetime=datetime.timedelta(seconds=Settings.TOKENS_ACCESS_LIFETIME_SECONDS),
)
authorization_manager = AuthorizationManager(engine=engine)
app.state.authorization_manager = authorization_manager
app.state.redis = redis  # proxy Redis client to request.app.state.redis

# Add exception handlers
app.add_exception_handler(BackendException, backend_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)

# Add middlewares stack (FIRST IN => LATER EXECUTION)
app.add_middleware(middleware_class=GZipMiddleware, minimum_size=512)  # №5
# app.add_middleware(middleware_class=CasbinMiddleware, enforcer=enforcer)  # №4
app.add_middleware(
    middleware_class=AuthenticationMiddleware,
    backend=JWTTokenBackend(scheme_prefix="Bearer"),
    on_error=lambda conn, exc: fastapi.responses.ORJSONResponse(
        content={"status": JSENDStatus.FAIL, "data": None, "message": str(exc), "code": status.HTTP_401_UNAUTHORIZED},
        status_code=status.HTTP_401_UNAUTHORIZED,
    ),
)  # №3
app.add_middleware(
    middleware_class=CORSMiddleware,
    allow_origins=Settings.CORS_ALLOW_ORIGINS,
    allow_credentials=Settings.CORS_ALLOW_CREDENTIALS,
    allow_methods=Settings.CORS_ALLOW_METHODS,
    allow_headers=Settings.CORS_ALLOW_HEADERS,
)  # №2
app.add_middleware(middleware_class=ProxyHeadersMiddleware, trusted_hosts=Settings.TRUSTED_HOSTS)  # №1


@app.on_event(event_type="startup")
def enable_logging() -> None:
    setup_logging()
    logger.debug(msg="Logging configuration completed.")


@app.on_event(event_type="startup")
async def _check_sync_engine() -> None:
    logger.debug(msg="Checking connection with sync engine 'SQLAlchemy + psycopg2'...")
    with session_factory() as session:
        result = session.execute(statement=text("SELECT current_timestamp;")).scalar()
    logger.debug(msg=f"Result of sync 'SELECT current_timestamp;' is: {result.isoformat() if result else result}")


@app.on_event(event_type="startup")
async def _check_async_engine() -> None:
    logger.debug(msg="Checking connection with async engine 'SQLAlchemy + asyncpg'...")
    async with async_session_factory() as async_session:
        result = await async_session.execute(statement=text("SELECT current_timestamp;"))
        result = result.scalar()
    logger.debug(msg=f"Result of async 'SELECT current_timestamp;' is: {result.isoformat() if result else result}")


@app.on_event(event_type="startup")
async def _check_redis() -> None:
    logger.debug(msg="Checking connection with Redis...")
    async with redis.client() as conn:
        result = await conn.ping()
        if result is not True:
            msg = "Connection to Redis failed."
            logger.error(msg=msg)
            raise RuntimeError(msg)
        logger.debug(msg=f"Result of Redis 'PING' command: {result}")


@app.on_event(event_type="shutdown")
async def _dispose_all_connections() -> None:
    logger.debug(msg="Closing PostgreSQL connections...")
    await async_engine.dispose()
    engine.dispose()
    logger.debug(msg="All PostgreSQL connections closed.")


@app.on_event(event_type="shutdown")
async def _close_redis() -> None:
    logger.debug(msg="Closing Redis connection...")
    await redis.close()
    logger.debug(msg="Redis connection closed.")


api_router = APIRouter()


@api_router.get(
    path="/",
    response_model=JSENDOutSchema,
    status_code=status.HTTP_200_OK,
    summary="Health check.",
    description="Health check endpoint.",
)
async def healthcheck() -> ORJSONResponse:
    """Check that API endpoints works properly.

    Returns:
        ORJSONResponse: json object with JSENDResponseSchema body.
    """
    return ORJSONResponse(
        content={
            "status": JSENDStatus.SUCCESS,
            "data": None,
            "message": "Health check.",
            "code": status.HTTP_200_OK,
        },
        status_code=status.HTTP_200_OK,
    )


API_PREFIX = "/api/v1"
# Include routers:
app.include_router(router=api_router, prefix=API_PREFIX)
app.include_router(router=wishlist_router, prefix=API_PREFIX)
app.include_router(router=wish_router, prefix=API_PREFIX)
app.include_router(router=register_router, prefix=API_PREFIX)
app.include_router(router=users_router, prefix=API_PREFIX)
app.include_router(router=tokens_router, prefix=API_PREFIX)
app.include_router(router=groups_router, prefix=API_PREFIX)
app.include_router(router=roles_router, prefix=API_PREFIX)
app.include_router(router=permissions_router, prefix=API_PREFIX)


if __name__ == "__main__":  # pragma: no cover
    # Use this for debugging purposes only
    import uvicorn

    uvicorn.run(
        app="apps.main:app",
        host=Settings.HOST,
        port=Settings.PORT,
        loop="uvloop",
        reload=True,
        reload_delay=5,
        log_level=Settings.LOG_LEVEL,
        use_colors=Settings.LOG_USE_COLORS,
    )
