"""Base fetcher interface."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Awaitable, Callable, Optional, TypeVar

if TYPE_CHECKING:
    from playwright.async_api import Page

T = TypeVar("T")


async def extract_first_p_from_dom(page: "Page", timeout_ms: int = 5000) -> str | None:
    """Extract first <p> text from live DOM (after JS/React render)."""
    try:
        await page.wait_for_selector("p", timeout=timeout_ms)
        return await page.evaluate(
            "() => { const p = document.querySelector('p'); return p ? p.innerText.trim() : null; }"
        )
    except Exception:
        return None


@dataclass
class FetchResult:
    """Result of a fetch operation."""

    content: str
    tier: str
    elapsed: float
    success: bool = True
    status_code: int | None = None
    title: str | None = None
    first_p: str | None = None  # First <p> text from live DOM (after JS render)


@dataclass
class PostResult:
    """Result of a POST request."""

    url: str
    tier: str
    status: int
    body: str
    elapsed: float


class BaseFetcher(ABC):
    """Base class for all fetchers."""

    tier_name: str = "base"

    @abstractmethod
    async def fetch(self, url: str) -> Optional[FetchResult]:
        """Fetch URL and return result, or None on failure."""
        pass

    @abstractmethod
    async def post(
        self,
        url: str,
        *,
        data: dict | None = None,
        json_data: dict | None = None,
        headers: dict | None = None,
    ) -> Optional[PostResult]:
        """POST to URL. Returns PostResult or None on failure."""
        pass

    @abstractmethod
    async def with_page(
        self,
        callback: Callable[["Page"], Awaitable[T]],
        storage_path: str | None = None,
        storage_state: dict | None = None,
        *,
        headless: bool | None = None,
        allow_all: bool = False,
        discovery_layout: bool = False,
    ) -> Optional[T]:
        """Get a page, run callback(page), return result. None on failure.
        storage_state: optional dict (overrides storage_path). Pool/Cluster return None when provided.
        headless/allow_all: for interactive flows. Pool/Cluster return None when allow_all=True or headless=False.
        discovery_layout: discovery context opts (vs human run opts); both default to full-window viewport."""
        pass
