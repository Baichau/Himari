"""Tab control for Himari's own browser window.

These helpers only touch the Playwright session Himari started. The user's
everyday Chrome window is a different process and is never listed or edited
here. All calls run on the browser session thread.
"""

from urllib.parse import quote_plus

from .browser_manager import DEFAULT_TIMEOUT_MS, BrowserError
from .navigation import navigate
from .page_reader import read_page

SUPPORTED_ENGINES = {
    "duckduckgo": "https://duckduckgo.com/?q={query}",
    "google": "https://www.google.com/search?q={query}",
    "bing": "https://www.bing.com/search?q={query}",
}
MAX_LISTED_TABS = 20
MAX_OPEN_TABS = 5


def search_url(query, engine="duckduckgo"):
    query = str(query or "").strip()
    if not query:
        raise BrowserError("Tell me what to search for.")
    template = SUPPORTED_ENGINES.get(str(engine or "duckduckgo").casefold())
    if template is None:
        raise BrowserError(
            "Unsupported search engine. Choose from: "
            + ", ".join(sorted(SUPPORTED_ENGINES))
            + "."
        )
    return template.format(query=quote_plus(query))


def _summary(manager, page):
    pages = manager.pages()
    index = next((position for position, item in enumerate(pages, start=1) if item is page), 0)
    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        url = page.url
    except Exception:
        url = ""
    return {
        "index": index,
        "total": len(pages),
        "title": title or "(untitled)",
        "url": url or "",
    }


def _select(manager, index):
    pages = manager.pages()
    if not pages:
        raise BrowserError("No tabs are open in Himari's browser.")
    if index is None:
        current = manager.page
        if current in pages:
            return current
        return pages[0]
    try:
        number = int(index)
    except (TypeError, ValueError):
        raise BrowserError("Tab number must be a whole number.") from None
    if number < 1 or number > len(pages):
        raise BrowserError(
            f"Tab {number} does not exist; Himari's browser has {len(pages)} tab(s)."
        )
    return pages[number - 1]


def _is_blank(page):
    return str(getattr(page, "url", "") or "") in {"", "about:blank"}


def _is_search_page(page):
    url = str(getattr(page, "url", "") or "").casefold()
    if "duckduckgo.com/" in url:
        return "?q=" in url or "&q=" in url
    return "google.com/search" in url or "bing.com/search" in url


def open_page(manager, url, new_tab=True):
    """Navigate a managed tab and return its verified title and tab number."""
    created = None
    pages = manager.pages()
    reuse_blank = (
        new_tab
        and len(pages) == 1
        and pages[0] is manager.page
        and _is_blank(pages[0])
    )
    if new_tab and not reuse_blank and len(pages) >= MAX_OPEN_TABS:
        raise BrowserError(
            f"Himari's browser already has {len(pages)} tabs (the limit is "
            f"{MAX_OPEN_TABS}). Close a tab with browser_tabs first, or reuse "
            "the current tab with new_tab=false."
        )
    if new_tab and not reuse_blank:
        created = manager.new_page()
        page = created
    elif manager.page is not None and not manager.page.is_closed():
        page = manager.page
    else:
        page = manager.open()
    result = navigate(page, url, timeout_ms=DEFAULT_TIMEOUT_MS)
    if not result.get("ok"):
        if created is not None:
            try:
                created.close()
            except Exception:
                pass
        return {"ok": False, "error": result.get("error") or "The page did not load."}
    try:
        page.bring_to_front()
    except Exception:
        pass
    manager.page = page
    summary = _summary(manager, page)
    return {"ok": True, **summary}


def open_search(manager, query, engine="duckduckgo"):
    """Open search results, replacing a previous search page instead of stacking tabs."""
    target = search_url(query, engine)
    current = manager.page
    if current is not None and not current.is_closed() and (
        _is_blank(current) or _is_search_page(current)
    ):
        return open_page(manager, target, new_tab=False)
    return open_page(manager, target, new_tab=True)


def read_active(manager):
    pages = manager.pages()
    if not pages:
        raise BrowserError("No page is open in Himari's browser.")
    page = manager.page if manager.page in pages else pages[0]
    content = read_page(page)
    return {"ok": True, **content}


def manage_tabs(manager, action="list", index=None):
    action = str(action or "list").casefold()
    pages = manager.pages()

    if action == "list":
        if not pages:
            return {"ok": True, "message": "No tabs are open in Himari's browser."}
        lines = ["Tabs in Himari's browser:"]
        for position, page in enumerate(pages[:MAX_LISTED_TABS], start=1):
            info = _summary(manager, page)
            lines.append(f"{position}. {info['title']} — {info['url']}")
        return {"ok": True, "message": "\n".join(lines)}

    if action == "close_all":
        count = len(pages)
        for page in pages:
            try:
                page.close()
            except Exception:
                pass
        manager.page = None
        return {
            "ok": True,
            "message": f"Closed all {count} tab(s) in Himari's browser."
            if count
            else "No tabs were open in Himari's browser.",
        }

    if action == "close_others":
        keep = _select(manager, index)
        closed = 0
        for page in pages:
            if page is keep:
                continue
            try:
                page.close()
                closed += 1
            except Exception:
                pass
        try:
            keep.bring_to_front()
        except Exception:
            pass
        manager.page = keep
        info = _summary(manager, keep)
        return {
            "ok": True,
            "message": (
                f"Closed {closed} other tab(s). Kept tab {info['index']}: "
                f"{info['title']} — {info['url']}."
            ),
        }

    if action == "focus":
        page = _select(manager, index)
        try:
            page.bring_to_front()
        except Exception as exc:
            raise BrowserError(f"Could not focus the tab: {exc}") from exc
        manager.page = page
        info = _summary(manager, page)
        return {
            "ok": True,
            "message": (
                f"Focused tab {info['index']} of {info['total']}: "
                f"{info['title']} — {info['url']}."
            ),
        }

    if action == "close":
        page = _select(manager, index)
        info = _summary(manager, page)
        try:
            page.close()
        except Exception as exc:
            raise BrowserError(f"Could not close the tab: {exc}") from exc
        remaining = manager.pages()
        if manager.page is page:
            manager.page = remaining[0] if remaining else None
        return {
            "ok": True,
            "message": (
                f"Closed tab {info['index']} ({info['title']}). "
                f"{len(remaining)} tab(s) remain."
            ),
        }

    raise BrowserError(
        "Unsupported tab action. Choose from: list, focus, close, close_others, close_all."
    )


def close_browser(manager):
    manager.close()
    return {"ok": True, "message": "Closed Himari's browser window."}
