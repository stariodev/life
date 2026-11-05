from stario import h
from stario.datastar import ModuleScript
from stario.markup import HtmlElement, baked

from app.assets import DATASTAR_JS, FAVICON_URL, FONTS_CSS, SCRIPTS, STYLE_CSS

DESCRIPTION = "One shared Game of Life board, computed once per tick and sent to everyone watching."


@baked
def page(title: str, body: HtmlElement) -> HtmlElement:
    return h.HtmlDocument(
        {"lang": "en"},
        h.Head(
            h.Meta({"charset": "utf-8"}),
            h.Meta({"name": "viewport", "content": "width=device-width, initial-scale=1"}),
            h.Meta({"name": "description", "content": DESCRIPTION}),
            h.Title(title),
            h.Link({"rel": "icon", "type": "image/png", "href": FAVICON_URL}),
            h.Link({"rel": "stylesheet", "href": FONTS_CSS}),
            h.Link({"rel": "stylesheet", "href": STYLE_CSS}),
            # Classic scripts first, so app.life exists when Datastar runs data-init.
            *[h.Script({"src": src, "defer": True}) for src in SCRIPTS],
            ModuleScript(DATASTAR_JS),
        ),
        h.Body(body),
    )
