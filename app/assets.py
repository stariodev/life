from pathlib import Path

from stario import Assets

ASSETS = Assets(Path(__file__).resolve().parents[1] / "static", url_prefix="/static")
STYLE_CSS = ASSETS.href("css/style.css")
DATASTAR_JS = ASSETS.href("js/datastar.js")
LOGO_URL = ASSETS.href("images/logo-stario.webp")
# The picture a chat or a social site shows for a shared link: 960x600, from the demo clip.
SHARE_IMAGE = ASSETS.href("images/share.jpg")
FAVICON_URL = ASSETS.href("images/favicon-32.png")
# Client behaviour lives in static/js/<name>.js — each file defines app.<name>.
SCRIPTS: tuple[str, ...] = (ASSETS.href("js/life.js"),)

# The type of stario.dev. display=swap paints text before the files arrive.
FONTS_CSS = (
    "https://fonts.bunny.net/css?family="
    "atkinson-hyperlegible:400,700|ibm-plex-mono:400,500|newsreader:400,600"
    "&display=swap"
)
