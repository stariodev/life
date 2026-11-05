import asyncio

from stario import App, Relay, Span, serve
from stario.http import same_origin, security_headers

from app.assets import ASSETS
from app.features.board.handlers import LifePage, tick_forever
from app.life.game import COLS, ROWS, TICK_HZ, Game


async def bootstrap(app: App, span: Span):
    """Build the one Game and the one Relay, register the page, and start the tick.

    Everything the app shares lives here and is handed to the page. No module globals.
    """
    app.use("/", same_origin(), security_headers())
    span.attrs(await ASSETS.attach(app))

    game = Game()
    relay: Relay[str] = Relay()  # in-process: one subject per open stream
    span.attrs({"life.cols": COLS, "life.rows": ROWS, "life.tick_hz": TICK_HZ})

    # pages
    LifePage(game, relay).register(app)

    app.create_task(tick_forever(app, game, relay), name="life.tick")
    yield


if __name__ == "__main__":
    asyncio.run(serve(bootstrap))
