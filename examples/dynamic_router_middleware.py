#!/usr/bin/env python3
"""
Example of using a dynamic router middleware with aiohttp server.

This example shows how to add and remove routes at runtime — after
``web.run_app()`` has been called and the router is frozen — by using a
server-side middleware that intercepts requests before the built-in router.

This is useful for plugin systems, hardware discovery, or any scenario where
endpoints must be registered or unregistered without restarting the application.

See https://github.com/aio-libs/aiohttp/issues/11840 for context.
"""

import asyncio
import logging
import re
from typing import Any

from aiohttp import web
from aiohttp.typedefs import Handler

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
_LOGGER = logging.getLogger(__name__)

# Type alias for a compiled dynamic route entry
_RouteEntry = tuple[re.Pattern[str], Handler, str]


class DynamicRouterMiddleware:
    """Middleware that dispatches requests to dynamically registered routes.

    Routes added via ``add_route`` are checked **before** the normal
    (frozen) router, so they can be registered or removed at any time —
    even from background tasks running after ``web.run_app()``.
    """

    def __init__(self) -> None:
        # method -> list of (compiled regex, handler, original_path)
        self._routes: dict[str, list[_RouteEntry]] = {}

    def add_route(self, method: str, path: str, handler: Handler) -> None:
        """Register a handler for *method* + *path* at runtime.

        Supports ``{param}`` placeholders, e.g. ``/devices/{device_id}``.
        """
        regex = self._compile_path(path)
        entry: _RouteEntry = (regex, handler, path)
        self._routes.setdefault(method.upper(), []).append(entry)
        _LOGGER.info("Dynamic route added: %s %s", method.upper(), path)

    def remove_route(self, method: str, path: str) -> bool:
        """Remove a previously added dynamic route. Returns True if found."""
        method = method.upper()
        entries = self._routes.get(method, [])
        for i, (_, _, orig_path) in enumerate(entries):
            if orig_path == path:
                entries.pop(i)
                _LOGGER.info("Dynamic route removed: %s %s", method, path)
                return True
        return False

    # -- middleware entry-point (new-style, no @web.middleware) --

    async def __call__(
        self, request: web.Request, handler: Handler
    ) -> web.StreamResponse:
        for regex, dyn_handler, _ in self._routes.get(request.method, []):
            match = regex.match(request.path)
            if match:
                request.match_info.update(match.groupdict())
                return await dyn_handler(request)
        # No dynamic match — fall through to normal router / 404
        return await handler(request)

    # -- helpers --

    @staticmethod
    def _compile_path(path: str) -> re.Pattern[str]:
        """Convert ``/a/{param}/b`` into a compiled regex with named groups."""
        regex_str = re.sub(r"\{(\w+)\}", r"(?P<\1>[^/]+)", path)
        return re.compile("^" + regex_str + "$")


# ===================== demo handlers =====================


async def handle_health(request: web.Request) -> web.Response:
    return web.Response(text="OK")


async def handle_device_status(request: web.Request) -> web.Response:
    device_id = request.match_info["device_id"]
    return web.json_response({"device": device_id, "status": "online"})


async def handle_calibrate(request: web.Request) -> web.Response:
    sensor_id = request.match_info["sensor_id"]
    return web.json_response({"sensor": sensor_id, "calibrated": True})


async def handle_live(request: web.Request) -> web.Response:
    name = request.match_info["name"]
    return web.json_response({"live": name})


# ===================== demo server =====================


def create_app(dynamic: DynamicRouterMiddleware) -> web.Application:
    app = web.Application(middlewares=[dynamic])
    app.router.add_get("/health", handle_health)
    return app


async def run_test_server(
    dynamic: DynamicRouterMiddleware,
) -> web.AppRunner:
    app = create_app(dynamic)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", 8080)
    await site.start()
    return runner


async def register_late_route(dynamic: DynamicRouterMiddleware) -> None:
    """Simulate a plugin that discovers hardware 1 s after boot."""
    await asyncio.sleep(1)
    dynamic.add_route("GET", "/live/{name}", handle_live)


# ===================== demo tests =====================


async def _get_json(session: Any, url: str) -> dict[str, Any]:
    async with session.get(url) as resp:
        return {"status": resp.status, "body": await resp.json()}


async def run_tests(dynamic: DynamicRouterMiddleware) -> None:
    """Run inline tests against the running server."""
    import aiohttp

    base = "http://localhost:8080"

    async with aiohttp.ClientSession() as session:
        # 1 — static route
        async with session.get(f"{base}/health") as resp:
            assert resp.status == 200
            assert await resp.text() == "OK"
        print("✓  Static /health works")

        # 2 — dynamic GET with path param (registered before start)
        data = await _get_json(session, f"{base}/hardware/sensor-42")
        assert data["status"] == 200
        assert data["body"]["device"] == "sensor-42"
        print("✓  Dynamic GET /hardware/{{device_id}} works")

        # 3 — dynamic POST
        async with session.post(f"{base}/sensors/temp-1/calibrate") as resp:
            assert resp.status == 200
            body = await resp.json()
            assert body["sensor"] == "temp-1"
        print("✓  Dynamic POST /sensors/{{sensor_id}}/calibrate works")

        # 4 — 404 for unknown path
        async with session.get(f"{base}/unknown") as resp:
            assert resp.status == 404
        print("✓  Unknown path returns 404")

        # 5 — late-registered route (added after server started)
        await asyncio.sleep(1.5)  # wait for the background task
        data = await _get_json(session, f"{base}/live/camera-1")
        assert data["status"] == 200
        assert data["body"]["live"] == "camera-1"
        print("✓  Late-registered /live/{{name}} works")

        # 6 — remove a route
        removed = dynamic.remove_route("GET", "/live/{name}")
        assert removed is True
        async with session.get(f"{base}/live/camera-1") as resp:
            assert resp.status == 404
        print("✓  Removed route returns 404")

    print("\nAll tests passed!")


# ===================== main =====================


async def main() -> None:
    dynamic = DynamicRouterMiddleware()

    # Register some routes before the server starts
    dynamic.add_route("GET", "/hardware/{device_id}", handle_device_status)
    dynamic.add_route("POST", "/sensors/{sensor_id}/calibrate", handle_calibrate)

    runner = await run_test_server(dynamic)

    # Simulate a plugin that registers a route after startup
    asyncio.create_task(register_late_route(dynamic))

    try:
        await run_tests(dynamic)
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
