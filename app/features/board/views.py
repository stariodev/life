"""Views: the page, the stats bar, and one 16x16 chunk of the board.

The board has 65,536 cells, too many for element trees, so a chunk is built as a
string from prefixes computed once at import. `#board` renders once per page and
is never morphed, so its listeners bind once. The stream patches chunks and cells
inside it by id.
"""

from stario import h
from stario.datastar import at, data
from stario.markup import HtmlElement, SafeString

from app.assets import LOGO_URL
from app.common.shell import page
from app.features.board.urls import DROP, LIVE, VIEW
from app.life.game import (
    CELLS,
    CHUNK,
    CHUNK_COLS,
    CHUNK_ROWS,
    CHUNKS,
    COLS,
    TICK_HZ,
    TICK_SECONDS,
    Game,
    band,
)

STARIO_URL = "https://stario.dev"

CELL_PX = 11
# 16 cells of 11 px plus the 1 px gridlines around them -> 192 px pitch.
CHUNK_PX = CHUNK * (CELL_PX + 1)
CELL_SPAN = CELL_PX + 1
# Last valid board-content pixel: 16 chunks of 191 px plus 15 gaps.
BOARD_LAST = CHUNK_COLS * CHUNK_PX - 2

TIP_TEXT = (
    "One shared Conway board. Click or drag stamps a plus — dead cells "
    "bloom into evolving ornaments, live cells are erased. On touch "
    "screens one finger paints, two fingers pan the board. Moves land "
    "on the next tick: one frame every 200 ms, computed once, sent to "
    "every viewer. Cells glow hot when born and cool to ash with age."
)

# Board gestures live in static/js/life.js (app.life). One delegated listener set
# on the board: a pointer position maps to a cell by arithmetic, not hit-testing,
# so every board pixel resolves to its nearest cell. The handlers return the queued
# cell ids to post, or "" while the 90 ms batch window is open; the expression
# posts only a non-empty string. One finger paints, two fingers pan.
_DROP_POST = f"@post(`{DROP.href()}?cells=${{c}}&stamp=plus`)"
_DOWN_EXPR = f"const c = app.life.down(el, evt); c && {_DROP_POST}"
_DRAG_EXPR = f"const c = app.life.drag(el, evt); c && {_DROP_POST}"
_RESET_EXPR = f"const c = app.life.reset(el, evt); c && {_DROP_POST}"

# Scrolling moves the viewport. The new chunk range goes to the server, which
# sends the chunks that came into view on the stream.
_SCROLL_EXPR = f"[$vx0,$vy0,$vx1,$vy1] = app.life.view(el), @post(`{VIEW.href()}`)"
_RESIZE_EXPR = f"[$vx1,$vy1] = app.life.fit($vx0, $vy0), @post(`{VIEW.href()}`)"

_BOARD_ATTRS = (
    data.on("pointerdown", _DOWN_EXPR).rendered
    + data.on("pointermove", _DRAG_EXPR, throttle="15ms").rendered
    + data.on("pointerup", _RESET_EXPR, target="window").rendered
    + data.on("pointerleave", _RESET_EXPR).rendered
    + data.on("pointercancel", _RESET_EXPR).rendered
    + data.on("contextmenu", "evt.preventDefault()").rendered
)
# Board geometry for app.life, as data attributes: the server owns the numbers.
_BOARD_OPEN = (
    f'<div id="board" class="board"{_BOARD_ATTRS}'
    f' data-cells="{CELLS}" data-cols="{COLS}" data-chunk="{CHUNK}"'
    f' data-chunk-cols="{CHUNK_COLS}" data-chunk-rows="{CHUNK_ROWS}"'
    f' data-chunk-px="{CHUNK_PX}" data-cell-span="{CELL_SPAN}"'
    f' data-board-last="{BOARD_LAST}" data-ghost-ms="{int(TICK_SECONDS * 3000)}">'
)
CHUNK_PRE = tuple(f'<div id="chunk-{c}" class="chunk">' for c in range(CHUNKS))
CELL_PRE = tuple(f'<div id="cell-{i}" class="cell' for i in range(CELLS))
CELL_DEAD = '"></div>'
CELL_ALIVE = tuple(f' alive a{k}"></div>' for k in range(8))
DIV_CLOSE = "</div>"

# The empty board: 256 chunk slots. Each fills when it first comes into view.
_BOARD_SHELL = _BOARD_OPEN + "".join(p + DIV_CLOSE for p in CHUNK_PRE) + DIV_CLOSE


def chunk_html(game: Game, c: int) -> str:
    """One 16x16 chunk as an outer-morph payload for ``#chunk-{c}``.

    Cached by content revision: ``game.chunk_rev[c]`` bumps only when the chunk's
    cells change, so catch-up paints over still territory reuse the cached HTML
    instead of rendering 256 cells again.
    """
    if game.chunk_seen[c] == game.chunk_rev[c]:
        html = game.chunk_cache[c]
        if html is not None:
            return html
    cx0, cy0 = (c % CHUNK_COLS) * CHUNK, (c // CHUNK_COLS) * CHUNK
    get = game.cells.get
    parts = [CHUNK_PRE[c]]
    append = parts.append
    for y in range(cy0, cy0 + CHUNK):
        base = y * COLS
        for x in range(cx0, cx0 + CHUNK):
            i = base + x
            age = get(i)
            append(CELL_PRE[i])
            append(CELL_DEAD if age is None else CELL_ALIVE[band(age)])
    parts.append(DIV_CLOSE)
    html = "".join(parts)
    game.chunk_cache[c] = html
    game.chunk_seen[c] = game.chunk_rev[c]
    return html


def stats_view(game: Game) -> HtmlElement:
    """``#life-stats``, re-rendered and morphed when the counts change.

    The connection dot binds to ``$live``, which ``data-indicator`` sets while the
    stream request is open, so the shared payload still shows each tab its own
    connection.
    """
    return h.Div(
        {"id": "life-stats", "class": "stats"},
        h.Span({"class": "conn", "title": "stream connection"}, data.class_("on", "$live")),
        h.Span({"class": "stat"}, h.B(str(len(game.players))), " playing"),
        h.Span({"class": "sep", "aria-hidden": "true"}, "·"),
        h.Span({"class": "stat"}, h.B(str(len(game.cells))), " alive"),
        h.Span({"class": "sep", "aria-hidden": "true"}, "·"),
        h.Span({"class": "stat muted"}, f"{TICK_HZ} Hz"),
        h.Span({"class": "sep", "aria-hidden": "true"}, "·"),
        h.Span({"class": "tip", "title": TIP_TEXT}, "?"),
    )


def topbar_view(game: Game) -> HtmlElement:
    return h.Header(
        {"class": "topbar"},
        h.A(
            {"href": STARIO_URL, "class": "brand", "aria-label": "Stario"},
            h.Img({"src": LOGO_URL, "alt": "", "width": "20", "height": "20", "decoding": "async"}),
            h.Span({"class": "brand-name"}, "Stario"),
        ),
        h.Span({"class": "crumb", "aria-hidden": "true"}, "/"),
        h.Span({"class": "app-name"}, "Life"),
        stats_view(game),
    )


def render(visitor: str, game: Game) -> HtmlElement:
    return page(
        "Life — Stario",
        h.Div(
            {"id": "life"},
            # The tab's id and its viewport in chunks. The viewport starts as a guess;
            # data-init measures the window before it opens the stream.
            data.signals(
                {"life_id": visitor, "vx0": 0, "vy0": 0, "vx1": 7, "vy1": 5}, if_missing=True
            ),
            data.indicator("live"),
            data.init("[$vx1,$vy1] = app.life.size(), " + at.get(LIVE.href(), retry="always")),
            topbar_view(game),
            h.Main(
                {"class": "stage"},
                data.on("scroll", _SCROLL_EXPR, throttle="120ms"),
                data.on("resize", _RESIZE_EXPR, target="window", throttle="200ms"),
                SafeString(_BOARD_SHELL),
            ),
        ),
    )
