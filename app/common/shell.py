from stario import h
from stario.datastar import ModuleScript
from stario.markup import HtmlElement, baked

from app.assets import DATASTAR_JS, FAVICON_URL, FONTS_CSS, SCRIPTS, STYLE_CSS

DESCRIPTION = "One shared Game of Life board, computed once per tick and sent to everyone watching."


@baked
def page(title: str, body: HtmlElement, url: str, image: str) -> HtmlElement:
    """The document. `url` and `image` are absolute: the page's address and its share picture."""
    return h.HtmlDocument(
        {"lang": "en"},
        h.Head(
            h.Meta({"charset": "utf-8"}),
            h.Meta({"name": "viewport", "content": "width=device-width, initial-scale=1"}),
            h.Meta({"name": "description", "content": DESCRIPTION}),
            h.Title(title),
            # Open Graph and Twitter tags: the title, text, and picture of a shared link.
            h.Meta({"property": "og:type", "content": "website"}),
            h.Meta({"property": "og:site_name", "content": "Stario"}),
            h.Meta({"property": "og:title", "content": title}),
            h.Meta({"property": "og:description", "content": DESCRIPTION}),
            h.Meta({"property": "og:url", "content": url}),
            h.Meta({"property": "og:image", "content": image}),
            h.Meta({"property": "og:image:width", "content": "960"}),
            h.Meta({"property": "og:image:height", "content": "600"}),
            h.Meta({"name": "twitter:card", "content": "summary_large_image"}),
            h.Link({"rel": "icon", "type": "image/png", "href": FAVICON_URL}),
            h.Link({"rel": "stylesheet", "href": FONTS_CSS}),
            h.Link({"rel": "stylesheet", "href": STYLE_CSS}),
            # Classic scripts first, so app.life exists when Datastar runs data-init.
            *[h.Script({"src": src, "defer": True}) for src in SCRIPTS],
            ModuleScript(DATASTAR_JS),
        ),
        h.Body(body),
    )
