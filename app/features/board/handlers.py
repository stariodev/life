"""The page, its stream, two commands, and the tick loop that drives every stream.

One shared 256x256 board, one 5 Hz tick. The board renders as 16x16 chunks. Each
tick computes one frame and publishes to every viewer only the cells that changed
inside their own viewport, so a tab paints a screenful of the world, not the board.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass

from stario import App, Context, Relay, Writer
from stario.datastar import SSE, read_signals
from stario.exceptions import StarioError
from stario.markup import render as render_html

from app.features.board.urls import DROP, HOME, LIVE, VIEW
from app.features.board.views import (
    CELL_ALIVE,
    CELL_DEAD,
    CELL_PRE,
    DIV_CLOSE,
    chunk_html,
    render,
    stats_view,
)
from app.life.game import CELLS, COLS, TICK_SECONDS, Game, band, chunk_of

# Each stream subscribes to its own subject. The tick loop publishes one combined
# patch (stats, catch-up chunks, and changed cells in view) per viewer.
V_PREFIX = "life.v."

# `w.write()` never blocks. A client that vanishes without closing TCP keeps every
# tick's patch buffered in the transport, and memory grows until the health check
# fails: that took stario.dev down once, at 36 GB. `drain()` waits until the client
# took the bytes. A stream that cannot drain in this window is dead for a 5 Hz
# board, so it is aborted, and `live` then drops its player and viewport.
DRAIN_TIMEOUT_S = 10.0


async def flush(sse: SSE, w: Writer, html: str) -> bool:
    """Patch the client, bounded. False: the stream is dead, and the caller returns."""
    sse.patch_elements(html)
    try:
        await asyncio.wait_for(w.drain(), DRAIN_TIMEOUT_S)
    except TimeoutError, ConnectionError:
        w.abort()
        return False
    return not w.closing


def visitor_id(signals: dict) -> str | None:
    """The tab's id, or None when the signal is forged.

    The id becomes one Relay subject segment in ``life.v.<id>``, so dots and
    wildcards are refused: a bad publish would stop the tick loop for every viewer.
    """
    v = signals.get("life_id")
    if not isinstance(v, str) or not 1 <= len(v) <= 64:
        return None
    return v if "." not in v and "*" not in v else None


def viewport(signals: dict) -> tuple[int, int, int, int] | None:
    """The chunk range ``(cx0, cy0, cx1, cy1)`` from the signals; `Game.view` clamps it."""
    try:
        return (
            int(signals.get("vx0", 0)),
            int(signals.get("vy0", 0)),
            int(signals.get("vx1", 7)),
            int(signals.get("vy1", 5)),
        )
    except TypeError, ValueError:
        return None


@dataclass(frozen=True, slots=True)
class LifePage:
    """The board page: one stream, a drop command, and a view command."""

    game: Game
    relay: Relay[str]

    def register(self, app: App) -> None:
        app.add(HOME, self.home)
        app.add(LIVE, self.live)
        app.add(DROP, self.drop)
        app.add(VIEW, self.view)

    async def home(self, c: Context, w: Writer) -> None:
        w.html(render(uuid.uuid7().hex, self.game))

    async def live(self, c: Context, w: Writer) -> None:
        signals = await read_signals(c.req)
        visitor = visitor_id(signals)
        vp = viewport(signals)
        if visitor is None or vp is None:
            # A Datastar GET: navigate reloads the page, which gives the tab a new id.
            SSE(w).navigate(HOME.href())
            return
        c.span.attr("life_id", visitor)

        # leave() runs even when a write fails; otherwise the player, viewport, and
        # catch-up entries of a dead stream would linger.
        try:
            async with self.relay.subscribe(V_PREFIX + visitor) as sub:
                sse = SSE(w)
                self.game.join(visitor)
                # Catch-up: paint the stats and every chunk in view now, so the gap
                # between the GET and this subscription is not stale. Chunks that a
                # /view buffered before this stream subscribed paint too.
                needed = self.game.view(visitor, *vp) | self.game.catchup.pop(visitor, set())
                catch_up = render_html(stats_view(self.game)) + "".join(
                    chunk_html(self.game, ch) for ch in sorted(needed)
                )
                if not await flush(sse, w, catch_up):
                    return
                async for _subject, html in c.alive(sub):
                    if not await flush(sse, w, html):
                        return
        finally:
            self.game.leave(visitor)

    async def drop(self, c: Context, w: Writer) -> None:
        visitor = visitor_id(await read_signals(c.req))
        if visitor is None:
            SSE(w).navigate(HOME.href())
            return

        # Strokes arrive as one comma list per ~90 ms window; a lone click may use
        # `cell`. Either way each id is checked.
        raw = c.req.query.get("cells") or c.req.query.get("cell") or ""
        try:
            cells = [int(n) for n in raw.split(",")][:256]
        except ValueError:
            cells = []
        if not cells or any(not 0 <= cell < CELLS for cell in cells):
            w.text("cells must be board cell numbers, separated by commas", status=400)
            return
        stamp = c.req.query.get("stamp")
        if stamp is not None and stamp != "plus":
            w.text("stamp must be plus", status=400)
            return

        # Reply, then queue. The taps land on the next tick and arrive on every stream.
        w.empty()
        for cell in cells:
            self.game.queue(visitor, cell % COLS, cell // COLS, stamp)

    async def view(self, c: Context, w: Writer) -> None:
        signals = await read_signals(c.req)
        visitor = visitor_id(signals)
        if visitor is None:
            SSE(w).navigate(HOME.href())
            return
        vp = viewport(signals)
        if vp is None:
            w.text("vx0, vy0, vx1, and vy1 must be numbers", status=400)
            return
        if visitor not in self.game.players:
            # The stream is not subscribed yet, or is reconnecting. Its join paints the
            # viewport from the live GET's own signals, so there is nothing to do.
            w.empty()
            return

        needed = self.game.view(visitor, *vp)
        if needed:
            self.relay.publish(
                V_PREFIX + visitor, "".join(chunk_html(self.game, ch) for ch in sorted(needed))
            )
            # The publish covered these chunks; view() also buffered them for a stream
            # that had not subscribed yet. Drop that copy, or the next tick sends them again.
            buffered = self.game.catchup.get(visitor)
            if buffered is not None:
                buffered -= needed
        w.empty()


def broadcast(game: Game, relay: Relay[str], state: dict) -> None:
    """One tick: step the game, then send each viewer the part they can see.

    The stats render only when the counts change. Whole chunks render only for
    catch-up; steady updates are cell morphs, about 80 bytes per changed cell
    against about 14 KB per chunk. Viewers with the same viewport share one payload.
    """
    frame = game.step()
    stats_key = (len(game.players), len(game.cells))
    fresh_stats = state.get("stats_key") != stats_key
    if fresh_stats:
        state["stats_key"] = stats_key
        state["stats"] = render_html(stats_view(game))
    stats: str = state["stats"]

    # Changed cells grouped by chunk, so a viewport's share is cheap to find.
    by_chunk: dict[int, list[int]] = {}
    for i in frame.changed:
        by_chunk.setdefault(chunk_of(i), []).append(i)

    # One string per changed chunk, built once and joined into every viewport that sees it.
    cell_blob: dict[int, str] = {}
    catchup_html: dict[int, str] = {}
    get_age = game.cells.get

    def blob(c: int) -> str:
        html = cell_blob.get(c)
        if html is None:
            html = cell_blob[c] = "".join(
                CELL_PRE[i]
                + (CELL_DEAD if (a := get_age(i)) is None else CELL_ALIVE[band(a)])
                + DIV_CLOSE
                for i in by_chunk[c]
            )
        return html

    groups: dict[frozenset[int], list[str]] = {}
    for vid, visible in list(game.rendered.items()):
        groups.setdefault(visible, []).append(vid)

    for visible, vids in groups.items():
        base = "".join(blob(c) for c in visible if c in by_chunk)
        for vid in vids:
            catchup = game.catchup.pop(vid, set())
            parts = [stats] if fresh_stats else []
            for c in sorted(catchup):
                html = catchup_html.get(c)
                if html is None:
                    html = catchup_html[c] = chunk_html(game, c)
                parts.append(html)
            if base:
                parts.append(base)
            if parts:
                try:
                    relay.publish(V_PREFIX + vid, "".join(parts))
                except StarioError:
                    # A bad subject must not stop the loop for everyone. Drop the
                    # viewer; their next action reloads the page.
                    game.leave(vid)


async def tick_forever(app: App, game: Game, relay: Relay[str]) -> None:
    """The metronome: one frame every TICK_SECONDS, sent to every viewer.

    Each pass waits on `app.shutdown`, never `asyncio.sleep`, so a deploy does not
    wait out a tick.
    """
    state: dict = {}
    shutdown = app.shutdown  # read once; each read is a new shield
    while not app.shutting_down:
        started = time.monotonic()
        broadcast(game, relay, state)
        await asyncio.wait(
            {shutdown}, timeout=max(0.01, TICK_SECONDS - (time.monotonic() - started))
        )
