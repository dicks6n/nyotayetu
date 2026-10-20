/* Shared site behaviour: starfield, drawer, toasts, CSRF-aware fetch, cashback timer. */
(function () {
    "use strict";

    // ---------------------------------------------------------------- helpers
    const fmt = (n) => Number(n || 0).toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    function getCookie(name) {
        const m = document.cookie.match("(^|;)\\s*" + name + "\\s*=\\s*([^;]+)");
        return m ? decodeURIComponent(m.pop()) : "";
    }

    async function api(url, body) {
        const opts = body === undefined
            ? { headers: { Accept: "application/json" }, credentials: "same-origin" }
            : {
                method: "POST", credentials: "same-origin",
                headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken"), Accept: "application/json" },
                body: JSON.stringify(body),
            };
        const res = await fetch(url, opts);
        let data = {};
        try { data = await res.json(); } catch (e) { /* ignore */ }
        if (!res.ok) {
            if (data.login) {
                toast("Please log in to play ✨", "error");
                setTimeout(() => { location.href = window.LUMA.loginUrl + "?next=" + encodeURIComponent(location.pathname); }, 900);
            }
            const err = new Error(data.error || "Something went wrong");
            err.data = data;
            throw err;
        }
        return data;
    }

    function toast(message, type = "", ms = 3800) {
        const box = document.getElementById("messages");
        if (!box) return;
        const el = document.createElement("div");
        el.className = "toast " + type;
        el.textContent = message;
        box.appendChild(el);
        setTimeout(() => { el.classList.add("leaving"); setTimeout(() => el.remove(), 300); }, ms);
    }

    let lastBalance = null;
    function setBalance(value) {
        const el = document.getElementById("balanceAmount");
        if (!el || value == null) return;
        const v = Number(value);
        if (lastBalance !== null && v > lastBalance + 0.001) {
            el.classList.add("bump");
            setTimeout(() => el.classList.remove("bump"), 900);
        }
        lastBalance = v;
        el.textContent = fmt(v);
    }

    window.Luma = { api, toast, fmt, setBalance };

    // ---------------------------------------------------------------- waving Kenyan flag (canvas.waving-flag)
    function drawFlag(c, W, H, align) {
        const st = [["#000", .3], ["#fff", .05], ["#BB0000", .3], ["#fff", .05], ["#006600", .3]];
        let y = 0;
        for (const [col, f] of st) { c.fillStyle = col; c.fillRect(0, y, W, H * f + 1); y += H * f; }
        // the nyota (star) — centred like the flag's emblem, or to the right on wide hero banners
        const sh = Math.min(H * 0.6, W * 0.4);
        const cx = align === "right" ? W - Math.max(sh * 0.9, W * 0.16) : W / 2, cy = H / 2;
        c.save();
        c.beginPath(); c.arc(cx, cy, sh * 0.55, 0, Math.PI * 2);
        c.fillStyle = "rgba(0,0,0,.35)"; c.fill();
        c.lineWidth = Math.max(2, H * 0.012); c.strokeStyle = "#fff"; c.stroke();
        c.fillStyle = "#fff"; c.shadowColor = "#fff"; c.shadowBlur = H * 0.08; c.beginPath();
        for (let i = 0; i < 10; i++) {
            const r = i % 2 ? sh * 0.15 : sh * 0.36, a = -Math.PI / 2 + i * Math.PI / 5;
            c.lineTo(cx + Math.cos(a) * r, cy + Math.sin(a) * r);
        }
        c.closePath(); c.fill(); c.restore();
    }
    document.querySelectorAll("canvas.waving-flag").forEach((cv) => {
        const ctx = cv.getContext("2d"), src = document.createElement("canvas");
        let W = 0, H = 0, dpr = 1;
        const size = () => {
            dpr = Math.min(devicePixelRatio || 1, 2);
            W = cv.width = cv.clientWidth * dpr; H = cv.height = cv.clientHeight * dpr;
            // flag drawn at 3:2 then stretched across the hero so the shield stays in proportion
            src.width = W; src.height = H; drawFlag(src.getContext("2d"), W, H, cv.dataset.shield);
        };
        size(); addEventListener("resize", size);
        const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
        const frame = (t) => {
            const slice = Math.max(2, Math.round(4 * dpr)), amp = H * 0.045;
            ctx.clearRect(0, 0, W, H);
            for (let x = 0; x < W; x += slice) {
                const ph = x / W * Math.PI * 3 - t / 380;
                const dy = Math.sin(ph) * amp * (0.3 + x / W);
                ctx.drawImage(src, x, 0, slice, H, x, dy - amp, slice, H + amp * 2);
                const shade = Math.cos(ph) * 0.22;   // light & shadow in the folds
                ctx.fillStyle = shade > 0 ? `rgba(255,255,255,${shade * 0.5})` : `rgba(0,0,0,${-shade})`;
                ctx.fillRect(x, 0, slice, H);
            }
            if (!still) requestAnimationFrame(frame);
        };
        requestAnimationFrame(frame);
    });

    // ---------------------------------------------------------------- live scores ticker
    const ticker = document.getElementById("ticker");
    if (ticker) {
        const track = document.getElementById("tickerTrack");
        const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
        let sig = "";
        const load = async () => {
            try {
                const d = await api(ticker.dataset.url);
                ticker.classList.toggle("show", d.live.length > 0);
                const html = d.live.map((m) => `<a href="/sports/match/${m.id}/">${m.virtual ? "⚡ " : ""}${esc(m.home)}
                    <span class="sc">${m.score[0] ?? 0} - ${m.score[1] ?? 0}</span>${esc(m.away)}
                    <span class="mn">${m.period === "HT" ? "HT" : m.minute + "'"}</span></a>`).join("");
                if (html !== sig) { sig = html; track.innerHTML = html; }
            } catch (e) { /* ignore */ }
        };
        load(); setInterval(load, 10000);
    }

    // auto-dismiss server messages
    document.querySelectorAll("#messages .toast").forEach((el, i) => {
        setTimeout(() => { el.classList.add("leaving"); setTimeout(() => el.remove(), 300); }, 4200 + i * 400);
    });
    const balEl = document.getElementById("balanceAmount");
    if (balEl) lastBalance = Number(balEl.dataset.balance);

    // ---------------------------------------------------------------- drawer
    const drawer = document.getElementById("drawer");
    const backdrop = document.getElementById("drawerBackdrop");
    const openDrawer = (open) => { drawer.classList.toggle("open", open); backdrop.classList.toggle("open", open); };
    document.getElementById("menuBtn")?.addEventListener("click", () => openDrawer(true));
    document.getElementById("closeBtn")?.addEventListener("click", () => openDrawer(false));
    backdrop?.addEventListener("click", () => openDrawer(false));
    document.addEventListener("keydown", (e) => { if (e.key === "Escape") openDrawer(false); });

    // ---------------------------------------------------------------- cashback timer
    const timer = document.getElementById("cashbackTimer");
    if (timer) {
        const at = Number(timer.dataset.at);
        const tick = () => {
            let s = Math.max(0, Math.floor((at - Date.now()) / 1000));
            const d = Math.floor(s / 86400); s %= 86400;
            const h = String(Math.floor(s / 3600)).padStart(2, "0"); s %= 3600;
            const m = String(Math.floor(s / 60)).padStart(2, "0");
            const sec = String(s % 60).padStart(2, "0");
            timer.textContent = `${d}d ${h}:${m}:${sec}`;
        };
        tick(); setInterval(tick, 1000);
    }

    // ---------------------------------------------------------------- starfield
    const canvas = document.getElementById("starfield");
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (canvas) {
        const ctx = canvas.getContext("2d");
        let stars = [], w, h, dpr;
        const resize = () => {
            dpr = Math.min(window.devicePixelRatio || 1, 2);
            w = canvas.width = innerWidth * dpr; h = canvas.height = innerHeight * dpr;
            canvas.style.width = innerWidth + "px"; canvas.style.height = innerHeight + "px";
            const count = Math.min(220, Math.floor((innerWidth * innerHeight) / 7000));
            stars = Array.from({ length: count }, () => ({
                x: Math.random() * w, y: Math.random() * h, r: (Math.random() * 1.3 + 0.2) * dpr,
                t: Math.random() * Math.PI * 2, s: 0.005 + Math.random() * 0.02, vy: (0.02 + Math.random() * 0.08) * dpr,
                col: ["255,255,255", "255,255,255", "224,30,30", "0,200,83"][Math.floor(Math.random() * 4)],
            }));
        };
        const draw = () => {
            ctx.clearRect(0, 0, w, h);
            for (const st of stars) {
                st.t += st.s; st.y -= st.vy;
                if (st.y < 0) { st.y = h; st.x = Math.random() * w; }
                const a = 0.35 + Math.sin(st.t) * 0.35;
                ctx.beginPath();
                ctx.fillStyle = `rgba(${st.col}, ${a})`;
                ctx.arc(st.x, st.y, st.r, 0, Math.PI * 2);
                ctx.fill();
            }
            if (!reduced) requestAnimationFrame(draw);
        };
        resize(); draw();
        addEventListener("resize", resize);
    }
})();
