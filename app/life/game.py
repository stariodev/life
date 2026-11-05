"""The Conway engine: one shared board and its tick. No HTTP in here.

One shared board. Commands queue between ticks; ``step()`` advances one
generation, applies the queue on top of it, and reports which cells
changed. Every painted cell stamps a plus onto a dead anchor — strokes
bloom into evolving trails and taps leave ornaments that settle into
pulsing oscillators. A live anchor falls through to the erase toggle.

Cells carry no owner. Each live cell stores its age in generations and
the view maps that to an ember ramp — newborns glow, elders go ashen.
"""

import textwrap
from bisect import bisect_right
from collections.abc import Iterable
from dataclasses import dataclass

COLS = 256
ROWS = 256
CELLS = COLS * ROWS
TICK_HZ = 5
TICK_SECONDS = 1 / TICK_HZ

# The board is served in 16x16 chunks; clients render a viewport of them.
CHUNK = 16
CHUNK_COLS = COLS // CHUNK
CHUNK_ROWS = ROWS // CHUNK
CHUNKS = CHUNK_COLS * CHUNK_ROWS
# A viewport may span at most this many chunks in each direction — bounds
# the payload a single stream can ask for.
MAX_VIEW_COLS = 15
MAX_VIEW_ROWS = 10

MAX_PENDING = 4096  # commands buffered per tick, all players together
MAX_PER_PLAYER = 96  # commands one player may queue per tick

# Live-cell count where step() switches neighbor counting from a dict to a
# flat CELLS-long list — measured crossover near 2k cells.
_DENSE_CUTOFF = 2048

# Seed cells start mid-ember so the opening board looks established.
SEED_AGE = 4


def _stamp(art: str) -> tuple[tuple[int, int], ...]:
    """ASCII art -> centered ``(dx, dy)`` offsets. ``X`` is a live cell."""
    rows = textwrap.dedent(art).strip("\n").split("\n")
    width = max(len(row) for row in rows)
    cy, cx = len(rows) // 2, width // 2
    return tuple(
        (x - cx, y - cy) for y, row in enumerate(rows) for x, ch in enumerate(row) if ch == "X"
    )


# Seed-only patterns. The demo has no stamp picker — clicks toggle.
STAMPS: dict[str, tuple[tuple[int, int], ...]] = {
    "blinker": _stamp("XXX"),
    "beacon": _stamp(
        """
        XX..
        XX..
        ..XX
        ..XX
        """
    ),
    "glider": _stamp(
        """
        .X.
        ..X
        XXX
        """
    ),
    "rpentomino": _stamp(
        """
        .XX
        XX.
        .X.
        """
    ),
    "pulsar": _stamp(
        """
        ..XXX...XXX..
        .............
        X....X.X....X
        X....X.X....X
        X....X.X....X
        ..XXX...XXX..
        .............
        ..XXX...XXX..
        X....X.X....X
        X....X.X....X
        X....X.X....X
        .............
        ..XXX...XXX..
        """
    ),
}

# The tap ornament: a five-cell plus. Alone on the board it churns about
# eight generations and settles into a twelve-cell period-2 oscillator —
# a permanent twinkle where someone poked the board.
PLUS = ((0, 0), (1, 0), (-1, 0), (0, -1), (0, 1))
STAMPABLE = {"plus": PLUS}

# Age (generations alive) -> ember band a0..a7. ~9s from spark to ash.
# The band is also the repaint unit: a chunk re-renders when any cell in it
# dies, is born, or crosses a band boundary.
_AGE_STEPS = (1, 3, 6, 11, 18, 29, 46)
_STEP_SET = frozenset(_AGE_STEPS)


def band(age: int) -> int:
    return min(bisect_right(_AGE_STEPS, age), 7)


_GOSPER_GUN = _stamp(
    """
    ........................X
    ......................X.X
    ............XX......XX............XX
    ...........X...X....XX............XX
    XX........X.....X...XX
    XX........X...X.XX....X.X
    ..........X.....X.......X
    ...........X...X
    ............XX
    """
)

# Origins are stamp anchors: stamps are centered, so the gun needs x >= 18.
_SEEDS: tuple[tuple[tuple[tuple[int, int], ...], int, int], ...] = (
    (_GOSPER_GUN, 30, 30),
    (STAMPS["glider"], 120, 25),
    (STAMPS["rpentomino"], 128, 150),
    (STAMPS["pulsar"], 190, 100),
    (STAMPS["blinker"], 70, 200),
    (STAMPS["beacon"], 220, 210),
)


# Index offsets of the 8 neighbors — valid for non-edge cells.
_NEIGHBOR_OFFS = (-COLS - 1, -COLS, -COLS + 1, -1, 1, COLS - 1, COLS, COLS + 1)


def _idx(x: int, y: int) -> int | None:
    """Board index for ``(x, y)``; ``None`` off the board. Edges are dead."""
    if 0 <= x < COLS and 0 <= y < ROWS:
        return y * COLS + x
    return None


def chunk_of(i: int) -> int:
    """Chunk id for a board cell index."""
    return (i // COLS // CHUNK) * CHUNK_COLS + (i % COLS) // CHUNK


@dataclass(frozen=True, slots=True)
class Frame:
    """One computed tick: what the broadcast has to repaint."""

    generation: int
    changed: frozenset[int]
    changed_chunks: frozenset[int]
    applied: int


class Game:
    """The one shared board. Mutated only by ``join``, ``leave``, ``queue``,
    and ``step`` — all on the app loop.

    ``cells`` maps board index -> age in generations. ``players`` is the
    set of visitor ids holding an open stream; it only feeds the count.
    ``viewports``/``rendered`` track which 16x16 chunks each stream sees.
    """

    def __init__(self, *, seed: bool = True) -> None:
        self.cells: dict[int, int] = {}
        self.players: set[str] = set()
        self.viewports: dict[str, tuple[int, int, int, int]] = {}
        self.rendered: dict[str, frozenset[int]] = {}
        self.catchup: dict[str, set[int]] = {}
        # chunk_rev bumps per changed chunk each step; chunk_cache/chunk_seen
        # make chunk_html content-addressed — it renders only stale chunks.
        self.chunk_rev = [0] * CHUNKS
        self.chunk_seen = [-1] * CHUNKS
        self.chunk_cache: list[str | None] = [None] * CHUNKS
        self.pending: list[tuple[str, int, int, str | None]] = []
        self.generation = 0
        self.last_applied = 0
        self._quota: dict[str, int] = {}
        if seed:
            self._seed()

    def _seed(self) -> None:
        for pattern, ox, oy in _SEEDS:
            for dx, dy in pattern:
                i = _idx(ox + dx, oy + dy)
                if i is not None:
                    self.cells[i] = SEED_AGE

    # -- players ------------------------------------------------------

    def join(self, visitor: str) -> None:
        self.players.add(visitor)

    def leave(self, visitor: str) -> None:
        self.players.discard(visitor)
        self.viewports.pop(visitor, None)
        self.rendered.pop(visitor, None)
        self.catchup.pop(visitor, None)

    def view(self, visitor: str, cx0: int, cy0: int, cx1: int, cy1: int) -> frozenset[int]:
        """Record a visitor's chunk viewport; return chunks needing a paint.

        Chunks that leave the viewport drop out of ``rendered`` — they go
        stale off-screen and repaint in full if the visitor scrolls back.
        """
        cx0 = max(0, min(cx0, CHUNK_COLS - 1))
        cy0 = max(0, min(cy0, CHUNK_ROWS - 1))
        cx1 = max(cx0, min(cx1, min(CHUNK_COLS - 1, cx0 + MAX_VIEW_COLS - 1)))
        cy1 = max(cy0, min(cy1, min(CHUNK_ROWS - 1, cy0 + MAX_VIEW_ROWS - 1)))
        viewport = frozenset(
            cy * CHUNK_COLS + cx for cy in range(cy0, cy1 + 1) for cx in range(cx0, cx1 + 1)
        )
        needed = viewport - self.rendered.get(visitor, frozenset())
        self.viewports[visitor] = (cx0, cy0, cx1, cy1)
        self.rendered[visitor] = viewport
        # Keep needed buffered as well: a /view publish can land before the
        # visitor's stream subscribes, so the join (or next tick) drains it.
        if needed:
            self.catchup.setdefault(visitor, set()).update(needed)
        return needed

    # -- commands -----------------------------------------------------

    def queue(self, visitor: str, x: int, y: int, stamp: str | None = None) -> bool:
        """Buffer a command for the next tick. ``False`` = dropped.

        ``stamp`` names a shape planted on a dead cell (a tap upgrade);
        no stamp toggles the cell the clicker saw. Player membership is
        not required — a click that lands before the stream connects is
        still a real intent, and the caps below bound abuse either way.
        """
        if _idx(x, y) is None:
            return False
        if stamp is not None and stamp not in STAMPABLE:
            return False
        if len(self.pending) >= MAX_PENDING:
            return False
        used = self._quota.get(visitor, 0)
        if used >= MAX_PER_PLAYER:
            return False
        self._quota[visitor] = used + 1
        self.pending.append((visitor, x, y, stamp))
        return True

    # -- tick ---------------------------------------------------------

    def step(self) -> Frame:
        """Apply queued commands, run one Conway generation, report the diff."""
        prev = self.cells
        self.last_applied = len(self.pending)
        pending, self.pending = self.pending, []
        self._quota.clear()

        # Neighbor counting — two containers, picked by density. A flat
        # list wins on dense boards (indexed adds beat dict get/set); a
        # dict wins on sparse boards (the survival pass skips dead cells).
        # Interior cells take the offset fast path either way. The flat
        # pass must not rescan the whole board for nonzero cells — a full
        # enumerate costs more than the counting itself at 5 Hz, so
        # ``touched`` records each index the first time it gets a count.
        counted: Iterable[tuple[int, int]]
        if len(prev) > _DENSE_CUTOFF:
            flat = [0] * CELLS
            touched: list[int] = []
            tpush = touched.append
            for i in prev:
                x, y = i % COLS, i // COLS
                if 0 < x < COLS - 1 and 0 < y < ROWS - 1:
                    for o in _NEIGHBOR_OFFS:
                        j = i + o
                        v = flat[j] + 1
                        flat[j] = v
                        if v == 1:
                            tpush(j)
                else:
                    for ny in (y - 1, y, y + 1):
                        for nx in (x - 1, x, x + 1):
                            if (nx != x or ny != y) and 0 <= nx < COLS and 0 <= ny < ROWS:
                                j = ny * COLS + nx
                                v = flat[j] + 1
                                flat[j] = v
                                if v == 1:
                                    tpush(j)
            counted = ((i, flat[i]) for i in touched)
        else:
            counts: dict[int, int] = {}
            cget = counts.get
            for i in prev:
                x, y = i % COLS, i // COLS
                if 0 < x < COLS - 1 and 0 < y < ROWS - 1:
                    for o in _NEIGHBOR_OFFS:
                        j = i + o
                        counts[j] = cget(j, 0) + 1
                else:
                    for ny in (y - 1, y, y + 1):
                        for nx in (x - 1, x, x + 1):
                            if (nx != x or ny != y) and 0 <= nx < COLS and 0 <= ny < ROWS:
                                j = ny * COLS + nx
                                counts[j] = cget(j, 0) + 1
            counted = counts.items()

        nxt: dict[int, int] = {}
        changed: set[int] = set()
        pget = prev.get
        for i, n in counted:
            a = pget(i)
            if a is None:
                if n == 3:
                    nxt[i] = 0
                    changed.add(i)
            elif n == 2 or n == 3:
                nxt[i] = a + 1
                # Repaint a survivor only when it crosses a band boundary.
                if a + 1 in _STEP_SET:
                    changed.add(i)

        # Commands land on the finished frame, toggled by what the clicker
        # saw (``prev``): a live cell is erased, a dead cell is born. This
        # keeps a lone placement visible for the frame it lands on — run
        # before Conway, it would die of loneliness before ever rendering.
        # A stamp plants its shape only on a dead cell, so a tap on a live
        # cell can never resurrect it. Erasures fall out of the death diff.
        for _visitor, x, y, stamp in pending:
            i = y * COLS + x
            if stamp and i not in prev:
                for dx, dy in STAMPABLE[stamp]:
                    j = _idx(x + dx, y + dy)
                    if j is not None:
                        nxt[j] = 0
                        changed.add(j)
            elif i in prev:
                nxt.pop(i, None)
            else:
                nxt[i] = 0
                changed.add(i)

        if not nxt:
            # Never leave a dead void on screen — reseed the demo.
            self._seed()
            nxt = dict(self.cells)

        # Deaths and erasures fall out of the diff; reseeded cells count too.
        changed |= (prev.keys() - nxt.keys()) | (nxt.keys() - prev.keys())
        self.cells = nxt
        self.generation += 1
        changed_chunks = frozenset(chunk_of(i) for i in changed)
        for c in changed_chunks:
            self.chunk_rev[c] += 1
        return Frame(self.generation, frozenset(changed), changed_chunks, self.last_applied)
