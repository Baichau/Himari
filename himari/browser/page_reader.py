"""Page reading and unique element identification.

Element metadata is extracted with a fixed internal script; model-generated
JavaScript is never executed. Selectors are snapshot-based locators, so
re-enumerate after navigation or page changes.
"""

from .browser_manager import BrowserError

ELEMENT_SELECTOR = "a, button, input, textarea, select, [role=button], [role=link]"
MAX_ELEMENTS = 200
MAX_TEXT_CHARS = 8000
MAX_LABEL_CHARS = 200

_ELEMENT_SNIPPET = """el => ({
    tag: el.tagName.toLowerCase(),
    type: (el.getAttribute('type') || '').toLowerCase(),
    id: el.id || '',
    name: el.getAttribute('name') || '',
    text: (el.innerText || el.value || '').trim().slice(0, %d),
    label: (el.getAttribute('aria-label') || el.getAttribute('placeholder') || '').slice(0, %d),
    href: el.getAttribute('href') || ''
})""" % (MAX_LABEL_CHARS, MAX_LABEL_CHARS)


class ElementNotFoundError(BrowserError):
    """No element matches the description."""


class AmbiguousElementError(BrowserError):
    def __init__(self, description, candidates):
        self.description = description
        self.candidates = list(candidates)
        listing = "; ".join(self.candidates[:8])
        super().__init__(
            f"More than one element matches '{description}': {listing}. "
            "Use a unique description; Himari will not guess."
        )


def read_page(page, max_chars=MAX_TEXT_CHARS):
    try:
        raw = page.inner_text("body")
    except Exception:
        raw = ""
    text = "\n".join(line.strip() for line in raw.splitlines() if line.strip())
    return {"title": page.title(), "url": page.url, "text": text[:max_chars]}


def list_elements(page):
    try:
        handles = page.query_selector_all(ELEMENT_SELECTOR)
    except Exception as exc:
        raise BrowserError(f"Could not enumerate page elements: {exc}") from exc
    elements = []
    for index, handle in enumerate(handles[:MAX_ELEMENTS]):
        try:
            metadata = handle.evaluate(_ELEMENT_SNIPPET)
        except Exception:
            continue
        if not isinstance(metadata, dict):
            continue
        metadata = {key: str(value or "") for key, value in metadata.items()}
        metadata["index"] = index
        elements.append(metadata)
    return elements


def locate(page, description):
    """Return (locator, metadata) for exactly one matching element."""
    needle = (description or "").strip().casefold()
    if not needle:
        raise ElementNotFoundError("Describe the element to interact with.")
    elements = list_elements(page)

    def fields(element):
        return [element.get(key, "").casefold() for key in ("text", "label", "id", "name")]

    exact = [element for element in elements if needle in fields(element)]
    matches = exact or [
        element for element in elements
        if any(needle in value for value in fields(element)[:2] if value)
    ]
    if not matches:
        raise ElementNotFoundError(f"No element matches '{description}'.")
    if len(matches) > 1:
        raise AmbiguousElementError(
            description,
            [
                f"{element.get('tag')} '{element.get('text') or element.get('label') or element.get('id')}'"
                for element in matches
            ],
        )
    match = matches[0]
    locator = page.locator(ELEMENT_SELECTOR).nth(match["index"])
    return locator, match