# Life

One shared Conway world, 256 by 256 cells, that ticks five times a second. Tap or drag to draw on it, and everyone watching sees it on the next tick.

**Play:** [life.stario.dev](https://life.stario.dev) · **Framework:** [stario.dev](https://stario.dev)

Life is a [Stario](https://stario.dev) app that pushes a lot of HTML to a lot of tabs: 65,536 cells, five frames a second, one shared world. It shows how a live page stays cheap when the state changes all the time. It deploys on [Yard](https://stario.dev/yard).

## How it works

```text
GET  /       the page once: the top bar and an empty board of 256 chunks
GET  /live   stays open; each tick sends this tab the cells that changed in its view
POST /drop   queues taps and strokes for the next tick; answers 204
POST /view   the tab scrolled; the chunks that came into view arrive on /live
```

1. **One tick computes the world once.** A loop calls `Game.step()` every 200 ms: it applies the queued taps and runs one generation. The frame is computed once for everyone, not once per tab.
2. **Each tab sees only its viewport.** The board is 16 by 16 chunks of 16 by 16 cells. A tab tells the server which chunks it can see (`POST /view` when it scrolls). Each tick sends a tab only the cells that changed inside its view, about 80 bytes a cell, instead of the whole board.
3. **Commands queue; the tick applies them.** `POST /drop` answers 204 at once and puts the taps in a queue. They land on the next frame, on every tab at the same moment. The tab shows a faint ghost right away, so the tap feels instant.
4. **One subject per tab.** Each stream subscribes to `life.v.<tab id>` on a `Relay`. The tick publishes each tab's own patch, and tabs with the same viewport share one built string.

## Read the code

```text
app/
  main.py                  bootstrap: the Game, the Relay, the page, and the tick loop
  life/game.py             the Conway engine: the board, the command queue, step(); no HTTP
  common/shell.py          the <html> document
  features/board/
    urls.py                the four routes
    views.py               the page, the stats bar, and one chunk as a string
    handlers.py            LifePage (stream, drop, view), broadcast(), tick_forever()
static/js/life.js          app.life: pointer to cell, batching, two-finger pan, viewport math
tests/test_board.py        the engine's rules, and the stream and commands over HTTP
```

What makes it fast, and safe, is worth copying:

- **Build hot HTML as strings.** A chunk is 256 cells. Element trees for that, five times a second, cost too much, so `views.py` joins prefixes computed once at import. A chunk's HTML is cached until its cells change.
- **Never morph the board itself.** `#board` renders once per page, so its pointer listeners bind once. The stream patches `#chunk-…` and `#cell-…` inside it by id.
- **Bound every write.** `w.write()` never blocks, so a tab that vanishes without closing its connection would buffer every frame forever. `flush()` waits for the client to take each patch and aborts the stream after 10 seconds. Without that, memory once grew to 36 GB.
- **Check every id that becomes a subject.** The tab id becomes part of a Relay subject, so dots and wildcards are refused. A bad subject would stop the tick for everyone.
- **Cap the input.** Each tab may queue 96 commands per tick, and all tabs together 4,096. A drop carries at most 256 cells.
- **Wait on shutdown, not on a timer.** `tick_forever` waits on `app.shutdown` between frames, so a deploy never waits out a tick.
- **JavaScript only where HTML cannot reach.** `static/js/life.js` turns a pointer into a cell number and batches strokes. It never builds HTML; the server sends every cell.

## Run it

You need [uv](https://docs.astral.sh/uv/) and Python 3.14.

```bash
git clone https://github.com/stariodev/life
cd life
uv sync
uv run python -m app.main
```

Open http://127.0.0.1:8000 in two windows and draw in one. With [just](https://just.systems), `just dev` reloads on every change, and `just check` formats, lints, type-checks, and runs the tests.

## Deploy it on Yard

On a host with [Yard](https://stario.dev/yard), one command deploys this repo and serves it over HTTPS:

```bash
yard app new --repo https://github.com/stariodev/life --caddy life.example.com
```

Yard sees a `pyproject.toml` that lists `stario` and a `uv.lock`, writes the container file, and starts `python -m app.main`. For your own copy, fork the repo and run `yard app new --caddy life.example.com` in your checkout. Each push then deploys.

## Good to know

- **The world lives in memory.** A restart seeds it again. If every cell dies, it reseeds itself.
- **One process holds the world.** `Relay` is in-process, and the tick runs in that process. That is the right size for this: one frame, computed once.
- **The edges are dead.** The board does not wrap, so gliders leave the world at the edge.

## License

MIT
