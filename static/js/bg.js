/* ==========================================================================
   Nyota Yetu — full-page animated background (decorative only)
   Kenyan-flag take on a "live engine" backdrop:
     · flowing flag ribbons (black / white / red / white / green)
     · perspective grid rolling toward the viewer
     · streams of Aviator results scrolling as bars (real round history)
     · data rain of live scores & odds from the site's own feeds
     · a constellation ("nyota") of nodes with red/green signals firing through it
     · scan line + HUD readout
   Runs at ~30 fps, pauses when the tab is hidden, respects reduced motion.
   ========================================================================== */
(function () {
    "use strict";
    const cv = document.getElementById("ny-bg");
    if (!cv) return;
    const ctx = cv.getContext("2d");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const C = { black: "0,0,0", white: "255,255,255", red: "187,0,0", redHi: "230,40,40", green: "0,102,0", greenHi: "0,190,80" };
    const rgba = (c, a) => `rgba(${c},${a})`;

    let W = 0, H = 0, dpr = 1, small = false;
    let nodes = [], edges = [], pulses = [], rings = [], rain = [], bars = [], tokens = [], last = 0;
    const mouse = { x: -9999, y: -9999 };
    const t0 = performance.now();

    // ---------------------------------------------------------------- layout
    function resize() {
        dpr = Math.min(window.devicePixelRatio || 1, 1.5);
        W = window.innerWidth; H = window.innerHeight; small = W < 700;
        cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
        cv.style.width = W + "px"; cv.style.height = H + "px";
        ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        build();
    }
    function build() {
        nodes = []; edges = []; pulses = []; rings = [];
        const layers = small ? 4 : 6, per = small ? 4 : 6;
        for (let l = 0; l < layers; l++) {
            for (let k = 0; k < per; k++) {
                const x = W * (0.08 + 0.84 * l / (layers - 1)) + (Math.random() - 0.5) * 40;
                const y = H * (0.12 + 0.6 * (k + 0.5) / per) + (Math.random() - 0.5) * 30;
                nodes.push({ x, y, bx: x, by: y, l, ph: Math.random() * 6.28, act: 0, star: Math.random() < 0.25 });
            }
        }
        nodes.forEach((a, i) => nodes.forEach((b, j) => {
            if (b.l === a.l + 1 && Math.random() < (small ? 0.45 : 0.36)) edges.push([i, j]);
        }));
        rain = [];
        const cols = Math.floor(W / (small ? 72 : 56));
        for (let c = 0; c < cols; c++) {
            rain.push({ x: c * (W / cols) + 8, y: Math.random() * H, v: 26 + Math.random() * 55, txt: token(), a: 0.25 + Math.random() * 0.5 });
        }
    }

    // ---------------------------------------------------------------- real data → tokens & bars
    const SAMPLE_ODDS = () => (1 + Math.random() * (Math.random() < 0.8 ? 3 : 12)).toFixed(2);
    function token() {
        if (tokens.length && Math.random() < 0.6) return tokens[Math.floor(Math.random() * tokens.length)];
        const kinds = [() => SAMPLE_ODDS(), () => SAMPLE_ODDS() + "x", () => "OV2.5 " + SAMPLE_ODDS(), () => "GG " + SAMPLE_ODDS(), () => "1X2"];
        return kinds[Math.floor(Math.random() * kinds.length)]();
    }
    const short = (name) => name.replace(/[^A-Za-z ]/g, "").split(" ").filter(Boolean).map((w) => w.slice(0, 3)).join("").slice(0, 3).toUpperCase();
    let liveCount = 0, liveNames = [];
    async function feed() {
        try {
            const t = await fetch("/sports/api/ticker/", { headers: { Accept: "application/json" } }).then((r) => r.json());
            liveCount = t.live.length;
            liveNames = t.live.map((m) => `${m.home} v ${m.away}`);
            const live = t.live.map((m) => `${short(m.home)} ${m.score[0] ?? 0}-${m.score[1] ?? 0} ${short(m.away)} ${m.period === "HT" ? "HT" : m.minute + "'"}`);
            tokens = live.concat(tokens.filter((x) => x.endsWith("x")).slice(0, 20));
        } catch (e) { /* offline is fine */ }
        try {
            const a = await fetch("/aviator/api/state/", { headers: { Accept: "application/json" } }).then((r) => r.json());
            const hist = (a.history || []).map((h) => Number(h.crash_point)).reverse();
            if (hist.length) {
                bars = hist;
                tokens = tokens.filter((x) => !x.endsWith("x")).concat(hist.slice(-12).map((v) => v.toFixed(2) + "x"));
            }
        } catch (e) { /* ignore */ }
        hud();
    }

    // ---------------------------------------------------------------- layers
    function drawFlag(t) {
        // five flowing ribbons in flag order; slow, wide waves across the upper half
        const bands = [[C.black, 26, 0.55], [C.white, 6, 0.18], [C.red, 22, 0.28], [C.white, 6, 0.18], [C.green, 26, 0.3]];
        const base = H * (small ? 0.2 : 0.16), amp = H * 0.06;
        let off = 0;
        bands.forEach(([col, thick, alpha], b) => {
            const y0 = base + off;
            off += thick * (small ? 0.8 : 1.1);
            ctx.beginPath();
            for (let x = 0; x <= W + 20; x += 20) {
                const y = y0 + Math.sin(x / W * Math.PI * 2.2 + t / 2400 + b * 0.08) * amp + Math.sin(x / 210 + t / 1300) * 6;
                x ? ctx.lineTo(x, y) : ctx.moveTo(x, y);
            }
            for (let x = W + 20; x >= 0; x -= 20) {
                const y = y0 + thick + Math.sin(x / W * Math.PI * 2.2 + t / 2400 + b * 0.08 + 0.05) * amp + Math.sin(x / 210 + t / 1300) * 6;
                ctx.lineTo(x, y);
            }
            ctx.closePath();
            ctx.fillStyle = rgba(col, alpha * 0.9);
            ctx.fill();
        });
    }
    function drawGrid(t) {
        const horizon = H * 0.62, vx = W / 2;
        ctx.lineWidth = 1;
        for (let i = -14; i <= 14; i++) {
            ctx.strokeStyle = rgba(i % 2 ? C.greenHi : C.redHi, 0.12);
            ctx.beginPath(); ctx.moveTo(vx, horizon); ctx.lineTo(vx + i * W / 7, H); ctx.stroke();
        }
        const off = (t / 2200) % 1;
        for (let k = 0; k < 12; k++) {
            const z = (k + off) / 12, y = horizon + (H - horizon) * z * z;
            ctx.strokeStyle = rgba(C.greenHi, 0.05 + 0.18 * z);
            ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(W, y); ctx.stroke();
        }
    }
    function drawBars(t) {
        // Aviator results as scrolling bars: tall = big multiplier; green ≥ 2x, red < 2x
        if (bars.length < 5) return;
        const max = Math.log(Math.max(...bars, 10));
        [[H * 0.42, 54, 30, 0.22], [H * 0.86, 70, 44, 0.3]].forEach(([cy, bandH, speed, alpha], band) => {
            const bw = band ? 9 : 7, gap = 4, step = bw + gap, total = bars.length * step;
            const shift = (t / 1000 * speed) % total;
            for (let x = -shift, i = 0; x < W + step; x += step, i++) {
                const v = bars[i % bars.length], h = Math.max(3, Math.log(Math.max(v, 1.01)) / max * bandH);
                ctx.fillStyle = rgba(v >= 2 ? C.greenHi : C.redHi, alpha);
                ctx.fillRect(x, cy + bandH / 2 - h, bw, h);
                ctx.fillStyle = rgba(C.white, alpha * 0.6);
                ctx.fillRect(x, cy + bandH / 2 - h, bw, 1);
            }
        });
    }
    function drawRain(dt) {
        ctx.font = `600 ${small ? 9 : 10}px "JetBrains Mono", ui-monospace, monospace`;
        rain.forEach((r) => {
            r.y += r.v * dt / 1000;
            if (r.y > H + 60) { r.y = -40; r.txt = token(); }
            const live = /'|HT/.test(r.txt), mult = r.txt.endsWith("x");
            const col = live ? C.redHi : mult ? C.greenHi : C.white;
            ctx.fillStyle = rgba(col, (live ? 0.75 : mult ? 0.55 : 0.28) * r.a);
            ctx.save(); ctx.translate(r.x, r.y); ctx.rotate(Math.PI / 2); ctx.fillText(r.txt, 0, 0); ctx.restore();
        });
    }
    function star(x, y, r) {
        ctx.beginPath();
        for (let i = 0; i < 10; i++) {
            const rad = i % 2 ? r * 0.42 : r, a = -Math.PI / 2 + i * Math.PI / 5;
            ctx.lineTo(x + Math.cos(a) * rad, y + Math.sin(a) * rad);
        }
        ctx.closePath(); ctx.fill();
    }
    function drawNet(t, dt) {
        nodes.forEach((n) => {
            n.x = n.bx + Math.sin(t / 2600 + n.ph) * 10; n.y = n.by + Math.cos(t / 3100 + n.ph) * 8;
            const dx = n.x - mouse.x, dy = n.y - mouse.y, d = Math.hypot(dx, dy);
            if (d < 140 && d > 0) { n.x += dx / d * (140 - d) * 0.25; n.y += dy / d * (140 - d) * 0.25; n.act = Math.max(n.act, 0.6); }
            n.act *= 0.96;
        });
        ctx.lineWidth = 1;
        edges.forEach(([i, j]) => {
            const a = nodes[i], b = nodes[j];
            ctx.strokeStyle = rgba(C.white, 0.07 + 0.3 * Math.max(a.act, b.act));
            ctx.beginPath(); ctx.moveTo(a.x, a.y); ctx.lineTo(b.x, b.y); ctx.stroke();
        });
        if (!reduced && Math.random() < (small ? 0.25 : 0.5) && edges.length) {
            const e = edges[Math.floor(Math.random() * edges.length)];
            if (nodes[e[0]].l === 0 || Math.random() < 0.3) pulses.push({ e, p: 0, v: 0.6 + Math.random() * 0.8, win: Math.random() < 0.5 });
        }
        const lastLayer = nodes.length ? nodes[nodes.length - 1].l : 0;
        pulses = pulses.filter((pu) => {
            pu.p += pu.v * dt / 1000;
            const a = nodes[pu.e[0]], b = nodes[pu.e[1]];
            if (pu.p >= 1) {
                b.act = 1;
                const next = edges.filter((e) => e[0] === pu.e[1]);
                if (next.length && Math.random() < 0.7) { pu.e = next[Math.floor(Math.random() * next.length)]; pu.p = 0; return true; }
                if (b.l === lastLayer) rings.push({ x: b.x, y: b.y, r: 4, a: 0.7, win: pu.win });
                return false;
            }
            const x = a.x + (b.x - a.x) * pu.p, y = a.y + (b.y - a.y) * pu.p, col = pu.win ? C.greenHi : C.redHi;
            ctx.fillStyle = rgba(col, 0.95); ctx.beginPath(); ctx.arc(x, y, 2.2, 0, 6.28); ctx.fill();
            ctx.fillStyle = rgba(col, 0.22); ctx.beginPath(); ctx.arc(x, y, 6.5, 0, 6.28); ctx.fill();
            return true;
        });
        nodes.forEach((n) => {
            ctx.fillStyle = rgba(C.white, 0.45 + 0.55 * n.act);
            if (n.star) star(n.x, n.y, 4 + 3 * n.act);
            else { ctx.beginPath(); ctx.arc(n.x, n.y, 2.2 + 2.4 * n.act, 0, 6.28); ctx.fill(); }
            if (n.act > 0.3) {
                ctx.strokeStyle = rgba(n.l % 2 ? C.greenHi : C.redHi, 0.45 * n.act);
                ctx.beginPath(); ctx.arc(n.x, n.y, 9 * n.act + 4, 0, 6.28); ctx.stroke();
            }
        });
        rings = rings.filter((r) => {
            r.r += dt * 0.06; r.a -= dt * 0.0012;
            ctx.strokeStyle = rgba(r.win ? C.greenHi : C.redHi, Math.max(0, r.a));
            ctx.beginPath(); ctx.arc(r.x, r.y, r.r, 0, 6.28); ctx.stroke();
            return r.a > 0;
        });
        if (mouse.x > 0) nodes.forEach((n) => {
            const d = Math.hypot(n.x - mouse.x, n.y - mouse.y);
            if (d < 180) { ctx.strokeStyle = rgba(C.white, 0.22 * (1 - d / 180)); ctx.beginPath(); ctx.moveTo(n.x, n.y); ctx.lineTo(mouse.x, mouse.y); ctx.stroke(); }
        });
    }
    function drawScan(t) {
        const y = (t / 18) % (H + 200) - 100;
        const g = ctx.createLinearGradient(0, y - 60, 0, y);
        g.addColorStop(0, rgba(C.white, 0)); g.addColorStop(1, rgba(C.white, 0.06));
        ctx.fillStyle = g; ctx.fillRect(0, y - 60, W, 60);
        // the scan line itself carries the flag: red | white | green
        ctx.fillStyle = rgba(C.redHi, 0.35); ctx.fillRect(0, y, W / 3, 1);
        ctx.fillStyle = rgba(C.white, 0.35); ctx.fillRect(W / 3, y, W / 3, 1);
        ctx.fillStyle = rgba(C.greenHi, 0.35); ctx.fillRect(2 * W / 3, y, W / 3, 1);
    }

    // ---------------------------------------------------------------- HUD (real numbers only)
    const hudFeed = document.getElementById("ny-hud-feed"), hudScan = document.getElementById("ny-hud-scan");
    function hud() {
        if (hudFeed) hudFeed.firstChild.textContent =
            `feeds: ${liveCount} match${liveCount === 1 ? "" : "es"} live · ${new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
    }
    let si = 0;
    setInterval(() => {
        if (!hudScan) return;
        hudScan.firstChild.textContent = liveNames.length
            ? `pricing ${liveNames[si++ % liveNames.length]} · in-play`
            : `aviator: ${bars.length ? bars[bars.length - 1].toFixed(2) + "x last round" : "warming up"}`;
    }, 1800);

    // ---------------------------------------------------------------- loop
    function frame(now) {
        const dt = Math.min(64, now - last || 16);
        if (!reduced && now - last < 30) { requestAnimationFrame(frame); return; }   // ~30 fps is plenty
        last = now;
        const t = now - t0;
        ctx.clearRect(0, 0, W, H);
        drawFlag(reduced ? 0 : t);
        drawGrid(reduced ? 0 : t);
        drawBars(reduced ? 0 : t);
        drawRain(reduced ? 0 : dt);
        drawNet(reduced ? 0 : t, reduced ? 0 : dt);
        if (!reduced) drawScan(t);
        if (!reduced && !document.hidden) requestAnimationFrame(frame);
    }
    document.addEventListener("visibilitychange", () => { if (!document.hidden && !reduced) { last = 0; requestAnimationFrame(frame); } });
    window.addEventListener("resize", () => { resize(); if (reduced) frame(performance.now()); });
    window.addEventListener("pointermove", (e) => { mouse.x = e.clientX; mouse.y = e.clientY; }, { passive: true });
    window.addEventListener("pointerleave", () => { mouse.x = mouse.y = -9999; });

    resize();
    feed(); setInterval(() => { if (!document.hidden) feed(); }, 15000);
    requestAnimationFrame(frame);
})();
