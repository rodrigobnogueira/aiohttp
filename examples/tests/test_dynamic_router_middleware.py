"""Tests for the dynamic router middleware example."""

import asyncio

from aiohttp import web
from aiohttp.pytest_plugin import AiohttpClient

from examples.dynamic_router_middleware import (
    DynamicRouterMiddleware,
    handle_calibrate,
    handle_device_status,
    handle_health,
    handle_live,
)


def create_app(dynamic: DynamicRouterMiddleware) -> web.Application:
    application = web.Application(middlewares=[dynamic])
    application.router.add_get("/health", handle_health)
    return application


# -- tests --


async def test_static_route_still_works(
    loop: asyncio.AbstractEventLoop,
    aiohttp_client: AiohttpClient,
) -> None:
    dynamic = DynamicRouterMiddleware()
    app = create_app(dynamic)
    client = await aiohttp_client(app)
    async with client.get("/health") as resp:
        assert resp.status == 200
        assert await resp.text() == "OK"


async def test_dynamic_get_with_path_param(
    loop: asyncio.AbstractEventLoop,
    aiohttp_client: AiohttpClient,
) -> None:
    dynamic = DynamicRouterMiddleware()
    app = create_app(dynamic)
    dynamic.add_route("GET", "/hardware/{device_id}", handle_device_status)
    client = await aiohttp_client(app)

    async with client.get("/hardware/sensor-42") as resp:
        assert resp.status == 200
        body = await resp.json()
        assert body == {"device": "sensor-42", "status": "online"}


async def test_dynamic_post_route(
    loop: asyncio.AbstractEventLoop,
    aiohttp_client: AiohttpClient,
) -> None:
    dynamic = DynamicRouterMiddleware()
    app = create_app(dynamic)
    dynamic.add_route("POST", "/sensors/{sensor_id}/calibrate", handle_calibrate)
    client = await aiohttp_client(app)

    async with client.post("/sensors/temp-1/calibrate") as resp:
        assert resp.status == 200
        body = await resp.json()
        assert body == {"sensor": "temp-1", "calibrated": True}


async def test_dynamic_route_404_no_match(
    loop: asyncio.AbstractEventLoop,
    aiohttp_client: AiohttpClient,
) -> None:
    dynamic = DynamicRouterMiddleware()
    app = create_app(dynamic)
    client = await aiohttp_client(app)
    async with client.get("/unknown/path") as resp:
        assert resp.status == 404


async def test_add_route_after_startup(
    loop: asyncio.AbstractEventLoop,
    aiohttp_client: AiohttpClient,
) -> None:
    dynamic = DynamicRouterMiddleware()
    app = create_app(dynamic)
    client = await aiohttp_client(app)

    # Before adding, should 404
    async with client.get("/live/cam-1") as resp:
        assert resp.status == 404

    # Add route after the client (and thus the app) is already running
    dynamic.add_route("GET", "/live/{name}", handle_live)

    async with client.get("/live/cam-1") as resp:
        assert resp.status == 200
        body = await resp.json()
        assert body == {"live": "cam-1"}


async def test_remove_route(
    loop: asyncio.AbstractEventLoop,
    aiohttp_client: AiohttpClient,
) -> None:
    dynamic = DynamicRouterMiddleware()
    app = create_app(dynamic)
    dynamic.add_route("GET", "/live/{name}", handle_live)
    client = await aiohttp_client(app)

    # Route works
    async with client.get("/live/cam-1") as resp:
        assert resp.status == 200

    # Remove it
    assert dynamic.remove_route("GET", "/live/{name}") is True

    # Now 404
    async with client.get("/live/cam-1") as resp:
        assert resp.status == 404


async def test_remove_nonexistent_route() -> None:
    dynamic = DynamicRouterMiddleware()
    assert dynamic.remove_route("GET", "/does-not-exist") is False


async def test_dynamic_overrides_static(
    loop: asyncio.AbstractEventLoop,
    aiohttp_client: AiohttpClient,
) -> None:
    """Dynamic routes take priority over static routes for the same path."""

    async def custom_health(request: web.Request) -> web.Response:
        return web.Response(text="DYNAMIC-OK")

    dynamic = DynamicRouterMiddleware()
    app = create_app(dynamic)
    dynamic.add_route("GET", "/health", custom_health)
    client = await aiohttp_client(app)

    async with client.get("/health") as resp:
        assert resp.status == 200
        assert await resp.text() == "DYNAMIC-OK"
