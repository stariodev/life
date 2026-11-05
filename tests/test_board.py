"""The Conway engine, and the page's stream and commands."""

import asyncio
import json
from urllib.parse import quote

from stario.testing import TestClient

from app.features.board.urls import DROP, HOME, LIVE, VIEW
from app.life.game import (
    _GOSPER_GUN,
    COLS,
    MAX_PENDING,
    MAX_PER_PLAYER,
    Game,
)
from app.main import bootstrap


def _i(x: int, y: int) -> int:
    return y * COLS + x


def _live_cells(game: Game) -> set[int]:
    return set(game.cells)


def test_blinker_oscillates() -> None:
    game = Game(seed=False)
    game.cells = {_i(10, 9): 0, _i(10, 10): 0, _i(10, 11): 0}
    game.step()
    assert _live_cells(game) == {_i(9, 10), _i(10, 10), _i(11, 10)}
    game.step()
    assert _live_cells(game) == {_i(10, 9), _i(10, 10), _i(10, 11)}


def test_block_is_still_life() -> None:
    game = Game(seed=False)
    block = {_i(10, 10), _i(11, 10), _i(10, 11), _i(11, 11)}
    game.cells = dict.fromkeys(block, 0)
    frame = game.step()
    assert _live_cells(game) == block
    # Still positions, but the cells aged a band — they repaint.
    assert frame.changed == block


def test_mature_cells_stop_changing() -> None:
    game = Game(seed=False)
    block = {_i(10, 10), _i(11, 10), _i(10, 11), _i(11, 11)}
    game.cells = dict.fromkeys(block, 99)  # deep in the ash band
    frame = game.step()
    assert _live_cells(game) == block
    assert frame.changed == frozenset()


def test_frame_reports_changed_chunks() -> None:
    game = Game(seed=False)
    game.join("v1")
    game.queue("v1", 1, 1)  # cell lands inside chunk 0
    frame = game.step()
    assert 0 in frame.changed_chunks


def test_command_applies_on_next_tick_only() -> None:
    game = Game(seed=False)
    game.join("v1")

    assert game.queue("v1", 5, 6)
    assert _i(5, 6) not in game.cells  # queued, not applied

    game.step()
    assert _i(5, 6) in game.cells


def test_dead_cell_click_plants_a_cell() -> None:
    game = Game(seed=False)
    game.join("v1")
    # A distant block keeps the board out of the void-reseed path.
    block = {_i(100, 100), _i(101, 100), _i(100, 101), _i(101, 101)}
    game.cells = dict.fromkeys(block, 4)
    assert game.queue("v1", 20, 20)
    frame = game.step()
    # The lone cell lands on the frame it was queued for.
    assert _live_cells(game) == block | {_i(20, 20)}
    assert frame.applied == 1
    # ...then dies of loneliness on the next one.
    game.step()
    assert _live_cells(game) == block


def test_live_cell_click_erases_it() -> None:
    game = Game(seed=False)
    game.join("v1")
    # Two distant blinkers; clearing one leaves the other oscillating.
    blinker_a = {_i(10, 9), _i(10, 10), _i(10, 11)}
    blinker_b = {_i(40, 39), _i(40, 40), _i(40, 41)}
    game.cells = dict.fromkeys(blinker_a | blinker_b, 0)

    assert game.queue("v1", 10, 10)  # cut blinker_a in the middle
    game.step()
    # Commands land on the finished frame: blinker_a still swung horizontal
    # and only its middle is erased, leaving two wings that die next tick.
    assert _live_cells(game) == {_i(9, 10), _i(11, 10), _i(39, 40), _i(40, 40), _i(41, 40)}
    game.step()
    assert _live_cells(game) == {_i(40, 39), _i(40, 40), _i(40, 41)}


def test_survivors_age_each_generation() -> None:
    game = Game(seed=False)
    block = {_i(10, 10), _i(11, 10), _i(10, 11), _i(11, 11)}
    game.cells = dict.fromkeys(block, 0)
    game.step()
    assert all(age == 1 for age in game.cells.values())
    game.step()
    assert all(age == 2 for age in game.cells.values())


def test_planted_cell_is_born_young() -> None:
    game = Game(seed=False)
    game.join("v1")
    game.queue("v1", 10, 10)
    game.step()
    assert all(age == 0 for age in game.cells.values())


def test_queue_rejects_bad_input() -> None:
    game = Game(seed=False)
    game.join("v1")
    # A well-formed id queues even before the stream joins — a click that
    # lands while /live connects is still a real intent.
    assert game.queue("ghost", 1, 1)
    assert not game.queue("v1", COLS, 0)  # off the board
    assert not game.queue("v1", -1, 0)
    assert not game.queue("v1", 1, 1, "pulsar")  # not a stampable shape


def test_tap_stamp_plants_a_plus() -> None:
    game = Game(seed=False)
    game.join("v1")
    game.cells = dict.fromkeys({_i(100, 100), _i(101, 100), _i(100, 101), _i(101, 101)}, 4)
    # A tap sends the cell toggle on press, then the stamp on release.
    game.queue("v1", 10, 10)
    game.queue("v1", 10, 10, "plus")
    game.step()
    plus = {_i(10, 10), _i(11, 10), _i(9, 10), _i(10, 9), _i(10, 11)}
    assert plus <= _live_cells(game)
    assert all(game.cells[i] == 0 for i in plus)


def test_stamp_cannot_plant_over_a_live_cell() -> None:
    game = Game(seed=False)
    game.join("v1")
    game.cells = {_i(10, 10): 0, _i(100, 100): 4, _i(101, 100): 4, _i(100, 101): 4, _i(101, 101): 4}
    game.queue("v1", 10, 10, "plus")
    game.step()
    assert _i(10, 10) not in game.cells  # fell through to the erase


def test_queue_caps_a_player_per_tick() -> None:
    game = Game(seed=False)
    game.join("v1")
    for n in range(MAX_PER_PLAYER):
        assert game.queue("v1", n % COLS, n // COLS)
    assert not game.queue("v1", 0, 1)
    game.step()
    assert game.queue("v1", 0, 1)  # quota resets each tick


def test_global_queue_cap() -> None:
    game = Game(seed=False)
    game.join("v1")
    game.pending = [("v1", 0, 0, None)] * MAX_PENDING
    assert not game.queue("v1", 1, 1)


def test_empty_board_reseeds() -> None:
    game = Game(seed=False)
    game.step()
    assert len(game.cells) > 30  # the seed patterns came back


def test_gosper_gun_fires_gliders() -> None:
    game = Game(seed=False)
    for dx, dy in _GOSPER_GUN:  # centered anchor, same as the seed
        x, y = 30 + dx, 30 + dy
        game.cells[y * COLS + x] = 0
    for _ in range(60):
        game.step()
    # A working gun still stands (36 cells) and has emitted gliders.
    assert len(game.cells) > 36


async def test_life_page_serves_the_board(client) -> None:
    r = await client.get(HOME.href())
    assert r.status_code == 200
    assert 'id="board"' in r.text
    assert 'id="chunk-0"' in r.text
    assert 'id="chunk-255"' in r.text
    assert 'id="life-stats"' in r.text


async def test_drop_before_join_queues(client) -> None:
    """A click that lands while the stream connects must not reload the
    page — the command queues and the client keeps its state."""
    r = await client.post(
        DROP.href(query={"cell": "42"}),
        content=json.dumps({"life_id": "nobody"}),
        follow_redirects=False,
    )
    assert r.status_code == 204
    assert "window.location" not in r.text


async def test_view_before_join_is_a_quiet_204(client) -> None:
    """A viewport post while the stream reconnects does nothing — join's
    catch-up paints the viewport from the live GET's own signals."""
    r = await client.post(
        VIEW.href(),
        content=json.dumps({"life_id": "nobody", "vx0": 0, "vy0": 0, "vx1": 3, "vy1": 3}),
        follow_redirects=False,
    )
    assert r.status_code == 204
    assert "window.location" not in r.text


async def test_forged_visitor_id_navigates(client) -> None:
    """A life_id that is not a safe Relay segment must never reach join()."""
    for bad in ("a*b", "a..b", "a.b", "x" * 65):
        r = await client.post(
            DROP.href(query={"cell": "42"}),
            content=json.dumps({"life_id": bad}),
            follow_redirects=False,
        )
        assert r.status_code == 200
        assert "window.location" in r.text


async def test_live_stream_broadcasts_frames_and_drops(client) -> None:
    await client.get(HOME.href())
    signals = {"life_id": "tester", "vx0": 0, "vy0": 0, "vx1": 1, "vy1": 1}
    query = quote(json.dumps(signals))
    async with client.stream("GET", f"{LIVE.href()}?datastar={query}") as stream:
        assert "text/event-stream" in stream.headers.get("content-type", "")
        events = stream.iter_events()

        first = await asyncio.wait_for(anext(events), timeout=5)
        assert first["event"] == "datastar-patch-elements"
        # Catch-up paints the viewport chunks (2x2 -> chunks 0,1,16,17).
        assert 'id="chunk-0"' in first["data"]
        assert 'id="chunk-17"' in first["data"]

        # A joined player can queue a click; the block lands in a frame.
        r = await client.post(
            DROP.href(query={"cell": "257"}),
            content=json.dumps({"life_id": "tester"}),
        )
        assert r.status_code == 204

        # Chunk patches carry the alive variant of the planted cell.
        needle = 'id="cell-257" class="cell alive'
        deadline = asyncio.get_running_loop().time() + 5
        seen = ""
        while needle not in seen:
            assert asyncio.get_running_loop().time() < deadline
            event = await asyncio.wait_for(anext(events), timeout=5)
            if event["event"] == "datastar-patch-elements":
                seen += event["data"]


async def test_view_pushes_newly_visible_chunks(client) -> None:
    signals = {"life_id": "scroller", "vx0": 0, "vy0": 0, "vx1": 0, "vy1": 0}
    query = quote(json.dumps(signals))
    async with client.stream("GET", f"{LIVE.href()}?datastar={query}") as stream:
        events = stream.iter_events()
        await asyncio.wait_for(anext(events), timeout=5)  # catch-up paint

        # Viewport moves to the right edge: chunks 15..47 column.
        # /view always answers 204 — the chunks arrive on the stream.
        move = {"life_id": "scroller", "vx0": 15, "vy0": 0, "vx1": 15, "vy1": 2}
        r = await client.post(VIEW.href(), content=json.dumps(move))
        assert r.status_code == 204

        deadline = asyncio.get_running_loop().time() + 5
        patches: list[str] = []
        while not any('id="chunk-15"' in p and 'id="chunk-47"' in p for p in patches):
            assert asyncio.get_running_loop().time() < deadline
            event = await asyncio.wait_for(anext(events), timeout=5)
            if event["event"] == "datastar-patch-elements":
                patches.append(event["data"])
        moved = next(p for p in patches if 'id="chunk-15"' in p)
        assert 'id="chunk-0"' not in moved  # outside the new viewport


async def test_the_page_has_a_share_preview(client) -> None:
    r = await client.get(HOME.href())
    assert '<meta property="og:title" content="Life — Stario"/>' in r.text
    assert '<meta property="og:url" content="https://life.stario.dev"/>' in r.text
    assert (
        '<meta property="og:image" content="https://life.stario.dev/static/images/share.' in r.text
    )
    assert '<meta name="twitter:card" content="summary_large_image"/>' in r.text


async def test_public_url_sets_the_preview_links(monkeypatch) -> None:
    monkeypatch.setenv("PUBLIC_URL", "https://life.example.com/")
    async with TestClient(bootstrap, request_timeout=5) as client:
        r = await client.get(HOME.href())
    assert '<meta property="og:url" content="https://life.example.com"/>' in r.text
