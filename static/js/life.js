window.app ??= {};
app.life = {
    g() {
        if (!this._g) {
            const d = document.getElementById("board").dataset;
            this._g = {
                cells: +d.cells,
                cols: +d.cols,
                chunk: +d.chunk,
                chunkCols: +d.chunkCols,
                chunkRows: +d.chunkRows,
                chunkPx: +d.chunkPx,
                cellSpan: +d.cellSpan,
                boardLast: +d.boardLast,
                ghostMs: +d.ghostMs,
            };
        }
        return this._g;
    },
    hit(el, cx, cy) {
        const g = this.g();
        const r = el.getBoundingClientRect();
        const bx = Math.max(0, Math.min(g.boardLast, cx - r.left - 1));
        const by = Math.max(0, Math.min(g.boardLast, cy - r.top - 1));
        return (
            (Math.min(g.chunkRows - 1, Math.floor(by / g.chunkPx)) * g.chunk +
                Math.min(g.chunk - 1, Math.floor((by % g.chunkPx) / g.cellSpan))) *
                g.cols +
            Math.min(g.chunkCols - 1, Math.floor(bx / g.chunkPx)) * g.chunk +
            Math.min(g.chunk - 1, Math.floor((bx % g.chunkPx) / g.cellSpan))
        );
    },
    mark(el, id) {
        if (el._hov === id) return;
        document.getElementById("cell-" + el._hov)?.classList.remove("sel");
        document.getElementById("cell-" + id)?.classList.add("sel");
        el._hov = id;
    },
    paint(el, id) {
        const g = this.g();
        const cell = document.getElementById("cell-" + id);
        const col = id % g.cols;
        const targets = [id];
        if (col > 0) targets.push(id - 1);
        if (col < g.cols - 1) targets.push(id + 1);
        if (id >= g.cols) targets.push(id - g.cols);
        if (id < g.cells - g.cols) targets.push(id + g.cols);
        if (cell && cell.classList.contains("alive")) {
            cell.classList.add("ghost-erase");
            setTimeout(() => cell.classList.remove("ghost-erase"), g.ghostMs);
        } else {
            for (const n of targets) {
                const t = document.getElementById("cell-" + n);
                if (t && !t.classList.contains("alive")) {
                    t.classList.add("ghost");
                    setTimeout(() => t.classList.remove("ghost"), g.ghostMs);
                }
            }
        }
        (el._q ??= {})[id] = 1;
    },
    due(el, ts) {
        if (el._qt && ts - el._qt <= 90) return "";
        el._qt = ts;
        const c = Object.keys(el._q).join(",");
        el._q = {};
        return c;
    },
    down(el, evt) {
        if (evt.button !== 0) return "";
        const pos = (el._pos ??= {});
        pos[evt.pointerId] = [evt.clientX, evt.clientY];
        if (Object.keys(pos).length >= 2) {
            el._pan = 1;
            return "";
        }
        const id = this.hit(el, evt.clientX, evt.clientY);
        if (id === el._last) return "";
        el._last = id;
        this.paint(el, id);
        return this.due(el, evt.timeStamp);
    },
    drag(el, evt) {
        let id = this.hit(el, evt.clientX, evt.clientY);
        this.mark(el, id);
        if (!(evt.buttons & 1)) return "";
        const pos = el._pos;
        if (!pos) return "";
        const ids = Object.keys(pos);
        const prev = pos[evt.pointerId];
        pos[evt.pointerId] = [evt.clientX, evt.clientY];
        if (ids.length >= 2) {
            el._pan = 1;
            if (!prev) return "";
            let ox = 0, oy = 0, nx = 0, ny = 0;
            for (const k of ids) {
                const q = k === String(evt.pointerId) ? prev : pos[k];
                ox += q[0];
                oy += q[1];
                nx += pos[k][0];
                ny += pos[k][1];
            }
            const st = el.closest(".stage");
            st.scrollLeft -= (nx - ox) / ids.length;
            st.scrollTop -= (ny - oy) / ids.length;
            return "";
        }
        if (el._pan) return "";
        let pts = evt.getCoalescedEvents ? evt.getCoalescedEvents() : [];
        if (!pts.length) pts = [evt];
        for (const p of pts) {
            id = this.hit(el, p.clientX, p.clientY);
            if (id === el._last) continue;
            el._last = id;
            this.paint(el, id);
        }
        return this.due(el, evt.timeStamp);
    },
    reset(el, evt) {
        const pos = el._pos;
        if (pos) {
            delete pos[evt.pointerId];
            if (!Object.keys(pos).length) el._pan = 0;
        }
        el._last = -1;
        if (el._hov >= 0 && (evt.pointerType === "touch" || evt.type !== "pointerup")) {
            document.getElementById("cell-" + el._hov)?.classList.remove("sel");
            el._hov = -1;
        }
        if (el._q && Object.keys(el._q).length) {
            const c = Object.keys(el._q).join(",");
            el._q = {};
            el._qt = 0;
            return c;
        }
        return "";
    },
    view(el) {
        const g = this.g();
        return [
            Math.max(0, Math.floor(el.scrollLeft / g.chunkPx)),
            Math.max(0, Math.floor(el.scrollTop / g.chunkPx)),
            Math.min(g.chunkCols - 1, Math.floor((el.scrollLeft + el.clientWidth) / g.chunkPx) + 1),
            Math.min(g.chunkRows - 1, Math.floor((el.scrollTop + el.clientHeight) / g.chunkPx) + 1),
        ];
    },
    size() {
        const g = this.g();
        return [
            Math.ceil(innerWidth / g.chunkPx) + 1,
            Math.ceil((innerHeight - 48) / g.chunkPx) + 1,
        ];
    },
    fit(x0, y0) {
        const g = this.g();
        return [
            Math.min(g.chunkCols - 1, x0 + Math.ceil(innerWidth / g.chunkPx) + 1),
            Math.min(g.chunkRows - 1, y0 + Math.ceil((innerHeight - 48) / g.chunkPx) + 1),
        ];
    },
};
