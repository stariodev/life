from stario import Route

HOME = Route("GET /")  # the page, once: the top bar and an empty board of 256 chunks
LIVE = Route("GET /live")  # stays open; each tick sends this viewer the cells that changed in view
DROP = Route("POST /drop")  # queues taps and strokes for the next tick; answers 204
VIEW = Route("POST /view")  # the viewer scrolled; newly visible chunks arrive on LIVE
