"""Human-like behavior: Bezier mouse movement, natural delays."""

import asyncio
import random
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page


def _bezier_point(t: float, p0: tuple[float, float], p1: tuple[float, float],
                  p2: tuple[float, float], p3: tuple[float, float]) -> tuple[float, float]:
    """Cubic Bezier: B(t) = (1-t)³P0 + 3(1-t)²tP1 + 3(1-t)t²P2 + t³P3."""
    u = 1 - t
    x = u**3 * p0[0] + 3 * u**2 * t * p1[0] + 3 * u * t**2 * p2[0] + t**3 * p3[0]
    y = u**3 * p0[1] + 3 * u**2 * t * p1[1] + 3 * u * t**2 * p2[1] + t**3 * p3[1]
    return (x, y)


def _generate_control_points(
    start: tuple[float, float],
    end: tuple[float, float],
    viewport_width: int,
    viewport_height: int,
) -> tuple[tuple[float, float], tuple[float, float]]:
    """Generate control points with slight randomness for natural curves."""
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    dist = (dx**2 + dy**2) ** 0.5 or 1
    # Control points offset perpendicular to the line, with jitter
    jitter = min(dist * 0.3, 80)
    c1 = (
        start[0] + dx * 0.2 + random.uniform(-jitter, jitter),
        start[1] + dy * 0.2 + random.uniform(-jitter, jitter),
    )
    c2 = (
        start[0] + dx * 0.8 + random.uniform(-jitter, jitter),
        start[1] + dy * 0.8 + random.uniform(-jitter, jitter),
    )
    # Clamp to viewport
    c1 = (max(0, min(viewport_width, c1[0])), max(0, min(viewport_height, c1[1])))
    c2 = (max(0, min(viewport_width, c2[0])), max(0, min(viewport_height, c2[1])))
    return c1, c2


async def human_mouse_move(
    page: "Page",
    to_x: float,
    to_y: float,
    *,
    from_x: float | None = None,
    from_y: float | None = None,
    steps: int | None = None,
) -> tuple[float, float]:
    """
    Move mouse along a Bezier curve for human-like movement.
    Uses cubic Bezier with randomized control points and variable step delays.
    """
    viewport = page.viewport_size or {"width": 1280, "height": 720}
    vw = viewport["width"]
    vh = viewport["height"]

    if from_x is None or from_y is None:
        from_x = random.uniform(vw * 0.2, vw * 0.8)
        from_y = random.uniform(vh * 0.2, vh * 0.8)

    start = (from_x, from_y)
    end = (max(0, min(vw, to_x)), max(0, min(vh, to_y)))

    c1, c2 = _generate_control_points(start, end, vw, vh)

    steps = steps or random.randint(15, 35)
    # Easing: slower at start and end (ease-in-out)
    for i in range(1, steps + 1):
        t = i / steps
        # Ease-in-out cubic
        t_eased = t * t * (3 - 2 * t)
        x, y = _bezier_point(t_eased, start, c1, c2, end)
        await page.mouse.move(x, y)
        # Variable delay: 2-8ms per step, slightly longer at start/end
        base_ms = random.uniform(2, 6)
        if i < 3 or i > steps - 2:
            base_ms *= 1.5
        await asyncio.sleep(base_ms / 1000)

    await page.mouse.move(end[0], end[1])
    return end


async def human_mouse_wander(page: "Page", count: int = 2) -> None:
    """
    Perform a few random mouse movements to simulate browsing.
    Moves to random points within the viewport, chaining Bezier paths.
    """
    viewport = page.viewport_size or {"width": 1280, "height": 720}
    vw = viewport["width"]
    vh = viewport["height"]

    from_x, from_y = None, None
    for _ in range(count):
        x = random.uniform(vw * 0.1, vw * 0.9)
        y = random.uniform(vh * 0.2, vh * 0.8)
        from_x, from_y = await human_mouse_move(
            page, x, y, from_x=from_x, from_y=from_y
        )
        await asyncio.sleep(random.uniform(0.1, 0.4))


async def human_scroll(page: "Page", amount: int | None = None) -> None:
    """
    Simulate human scroll: scroll down a bit, pause, scroll back up.
    Mimics reading behavior.
    """
    viewport = page.viewport_size or {"width": 1280, "height": 720}
    vh = viewport["height"]
    amount = amount or random.randint(int(vh * 0.15), int(vh * 0.35))

    await page.mouse.wheel(0, amount)
    await asyncio.sleep(random.uniform(0.3, 0.8))
    await page.mouse.wheel(0, -amount)
