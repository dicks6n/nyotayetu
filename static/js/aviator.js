/* ==========================================================================
   Nyota Yetu Aviator client
   The server is the source of truth (round timing, crash point, settlement).
   This script syncs with /aviator/api/state/, animates the flight locally from the
   server's take-off timestamp, and drives the two bet panels.
   ========================================================================== */
(function () {
    "use strict";
    const C = window.AVIATOR;
    const { api, toast, fmt, setBalance } = window.Luma;
    const CUR = window.LUMA.currency;
    const $ = (sel, root = document) => root.querySelector(sel);

    // ------------------------------------------------------------------ state
    let state = null;
    let offset = 0;              // serverTime - clientTime (ms)
    let offsetReady = false;
    let phase = "betting";       // betting | flying | crashed (local view)
    let lastSeq = null;
    let crashPoint = 1;
    let crashedAtLocal = 0;
    let growth = 0.075;
    let lastHistoryTop = null;
    let betTab = "all";

    const serverNow = () => Date.now() + offset;
    const flightElapsed = () => state ? (serverNow() - state.round.flight_starts_at) / 1000 : 0;
    const currentMultiplier = () => {
        if (phase === "crashed") return crashPoint;
        const t = flightElapsed();
        return t <= 0 ? 1 : Math.floor(Math.exp(growth * t) * 100) / 100;
    };

    // ------------------------------------------------------------------ DOM
    const stage = $("#gameStage");
    const overlay = $("#overlay");
    const multEl = $("#multiplier");
    const progressBar = $("#progressBar");
    const roundTag = $("#roundTag");
    const historyStrip = $("#historyStrip");
    const betsBody = $("#betsBody");

    // ------------------------------------------------------------------ sound (WebAudio, no assets)
    const Sound = (() => {
        let ctx = null;
        let enabled = true;
        try { enabled = localStorage.getItem("luma_sound") !== "off"; } catch (e) { /* ignore */ }
        const btn = $("#soundBtn");
        const paint = () => { btn.textContent = enabled ? "🔊 Sound" : "🔇 Muted"; };
        paint();
        btn.addEventListener("click", () => {
            enabled = !enabled; paint();
            try { localStorage.setItem("luma_sound", enabled ? "on" : "off"); } catch (e) { /* ignore */ }
        });
        const ensure = () => {
            if (!ctx) { try { ctx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { return null; } }
            if (ctx.state === "suspended") ctx.resume();
            return ctx;
        };
        document.addEventListener("pointerdown", ensure, { once: true });
        function tone(freq, dur, type = "sine", vol = 0.12, slideTo = null, delay = 0) {
            if (!enabled || !ctx) return;
            const t0 = ctx.currentTime + delay;
            const o = ctx.createOscillator(), g = ctx.createGain();
            o.type = type; o.frequency.setValueAtTime(freq, t0);
            if (slideTo) o.frequency.exponentialRampToValueAtTime(slideTo, t0 + dur);
            g.gain.setValueAtTime(0.0001, t0);
            g.gain.exponentialRampToValueAtTime(vol, t0 + 0.02);
            g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
            o.connect(g).connect(ctx.destination); o.start(t0); o.stop(t0 + dur + 0.05);
        }
        return {
            takeoff: () => tone(180, 1.1, "sawtooth", 0.04, 520),
            bet: () => tone(660, 0.12, "triangle", 0.08),
            cashout: () => { tone(880, 0.18, "sine", 0.12); tone(1320, 0.3, "sine", 0.1, null, 0.1); tone(1760, 0.45, "sine", 0.07, null, 0.2); },
            crash: () => { tone(300, 0.6, "sawtooth", 0.06, 60); tone(90, 0.5, "square", 0.04, 40); },
        };
    })();

    // ------------------------------------------------------------------ canvas
    const canvas = $("#gameCanvas");
    const ctx = canvas.getContext("2d");
    let W = 0, H = 0, dpr = 1;
    function resize() {
        dpr = Math.min(window.devicePixelRatio || 1, 2);
        const r = stage.getBoundingClientRect();
        W = canvas.width = Math.floor(r.width * dpr);
        H = canvas.height = Math.floor(r.height * dpr);
    }
    addEventListener("resize", resize);
    resize();

    const planeImg = new Image();
    planeImg.src = "data:image/svg+xml;charset=utf-8," + encodeURIComponent(`
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 120 60">
<defs>
 <clipPath id="body"><path d="M10 30 C20 21 70 17 97 23 C108 26 109 35 97 37 C70 43 22 40 10 30 Z"/></clipPath>
 <linearGradient id="sheen" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff" stop-opacity=".45"/><stop offset=".5" stop-color="#fff" stop-opacity="0"/><stop offset="1" stop-color="#000" stop-opacity=".35"/></linearGradient>
</defs>
<path d="M16 29 L5 7 L19 7 L33 25 Z" fill="#BB0000" stroke="#fff" stroke-width="1.4"/>
<path d="M9 12 L14 12 M8 17 L17 17" stroke="#000" stroke-width="2"/>
<path d="M6 27 L22 27 L22 33 L4 33 Z" fill="#006600" stroke="#fff" stroke-width="1"/>
<g clip-path="url(#body)">
  <rect x="0" y="15" width="120" height="8.4" fill="#000"/><rect x="0" y="23.4" width="120" height="1.6" fill="#fff"/>
  <rect x="0" y="25" width="120" height="8.4" fill="#BB0000"/><rect x="0" y="33.4" width="120" height="1.6" fill="#fff"/>
  <rect x="0" y="35" width="120" height="10" fill="#006600"/>
  <rect x="0" y="15" width="120" height="30" fill="url(#sheen)"/>
</g>
<path d="M10 30 C20 21 70 17 97 23 C108 26 109 35 97 37 C70 43 22 40 10 30 Z" fill="none" stroke="#fff" stroke-width="1.6"/>
<path d="M66 22 C71 12 84 12 89 23 Z" fill="#e8f7ff" stroke="#fff" stroke-width="1"/>
<path d="M44 32 L72 32 L60 54 L47 54 Z" fill="#006600" stroke="#fff" stroke-width="1.4"/>
<path d="M49 26 L67 25 L61 9 L53 9 Z" fill="#BB0000" stroke="#fff" stroke-width="1.2"/>
<path d="M57 13l1.3 2.8 3 .3-2.3 2 .7 3-2.7-1.6-2.7 1.6.7-3-2.3-2 3-.3z" fill="#fff"/>
<circle cx="103" cy="30" r="5.5" fill="#fff"/><circle cx="103" cy="30" r="2.3" fill="#000"/>
</svg>`);

    // particles: sparkle trail + bursts
    const particles = [];
    const COLS = ["255,255,255", "224,30,30", "0,200,83", "255,255,255", "187,0,0"];   // flag sparks
    function spawn(x, y, n, opts = {}) {
        for (let i = 0; i < n; i++) {
            const a = opts.angle !== undefined ? opts.angle + (Math.random() - 0.5) * (opts.spread || 1) : Math.random() * Math.PI * 2;
            const sp = (opts.speed || 1.2) * (0.4 + Math.random()) * dpr;
            particles.push({
                x, y, vx: Math.cos(a) * sp, vy: Math.sin(a) * sp,
                life: 1, decay: (opts.decay || 0.012) * (0.6 + Math.random() * 0.8),
                size: (opts.size || 3) * (0.5 + Math.random()) * dpr,
                col: opts.col || COLS[Math.floor(Math.random() * COLS.length)],
                spin: Math.random() * Math.PI, gravity: (opts.gravity || 0) * dpr,
            });
        }
        if (particles.length > 900) particles.splice(0, particles.length - 900);
    }
    function drawStar(x, y, r, rot) {
        ctx.save(); ctx.translate(x, y); ctx.rotate(rot);
        ctx.beginPath();
        for (let i = 0; i < 4; i++) {
            ctx.lineTo(0, -r); ctx.quadraticCurveTo(0, 0, r, 0); ctx.rotate(Math.PI / 2);
        }
        ctx.closePath(); ctx.fill(); ctx.restore();
    }
    function updateParticles() {
        ctx.save();
        ctx.globalCompositeOperation = "lighter";
        for (let i = particles.length - 1; i >= 0; i--) {
            const p = particles[i];
            p.x += p.vx; p.y += p.vy; p.vy += p.gravity; p.vx *= 0.985; p.vy *= 0.985;
            p.life -= p.decay; p.spin += 0.05;
            if (p.life <= 0) { particles.splice(i, 1); continue; }
            ctx.fillStyle = `rgba(${p.col}, ${p.life})`;
            drawStar(p.x, p.y, p.size * (0.5 + p.life * 0.7), p.spin);
        }
        ctx.restore();
    }

    // flight geometry
    let planePos = { x: 0, y: 0, angle: 0 };
    let flyAway = null;    // { x, y, vx, vy } after crash
    let rayAngle = 0;

    function geometry(t, m) {
        const L = 46 * dpr, R = 80 * dpr, T = 64 * dpr, B = 34 * dpr;
        const tMax = Math.max(8, t * 1.18);
        const mMax = Math.max(1.9, 1 + (m - 1) * 1.25);
        const px = (tt) => L + (tt / tMax) * (W - L - R);
        const py = (mm) => H - B - ((mm - 1) / (mMax - 1)) * (H - T - B);
        return { L, R, T, B, tMax, mMax, px, py };
    }

    function drawBackground(t, flying) {
        // radiating magical rays from bottom-left
        rayAngle += flying ? 0.004 : 0.0015;
        ctx.save();
        ctx.translate(0, H);
        const rays = 14;
        for (let i = 0; i < rays; i++) {
            const a = rayAngle + (i / rays) * Math.PI * 2;
            ctx.beginPath(); ctx.moveTo(0, 0);
            ctx.arc(0, 0, Math.max(W, H) * 1.6, a, a + Math.PI / rays / 1.6);
            ctx.closePath();
            ctx.fillStyle = i % 2 ? "rgba(0, 160, 70,0.045)" : "rgba(224, 30, 30,0.03)";
            ctx.fill();
        }
        ctx.restore();

        // axes with drifting dots (sense of speed)
        const g = geometry(Math.max(t, 0), 1);
        ctx.fillStyle = "rgba(230, 230, 230,0.35)";
        const shift = flying ? (t * 40 * dpr) % (40 * dpr) : 0;
        for (let x = g.L - shift; x < W; x += 40 * dpr) {
            if (x >= g.L) { ctx.beginPath(); ctx.arc(x, H - g.B + 14 * dpr, 1.6 * dpr, 0, Math.PI * 2); ctx.fill(); }
        }
        for (let y = H - g.B + (flying ? shift : 0); y > g.T - 20 * dpr; y -= 40 * dpr) {
            if (y <= H - g.B) { ctx.beginPath(); ctx.arc(g.L - 18 * dpr, y, 1.6 * dpr, 0, Math.PI * 2); ctx.fill(); }
        }
        ctx.strokeStyle = "rgba(255, 255, 255,0.25)"; ctx.lineWidth = 1 * dpr;
        ctx.beginPath(); ctx.moveTo(g.L, g.T - 20 * dpr); ctx.lineTo(g.L, H - g.B); ctx.lineTo(W - 10 * dpr, H - g.B); ctx.stroke();
    }

    function drawPlane(x, y, angle, scale = 1) {
        const pw = 104 * dpr * scale, ph = pw / 2;
        ctx.save();
        ctx.translate(x, y);
        ctx.rotate(angle);
        ctx.shadowColor = "rgba(255,255,255,0.8)"; ctx.shadowBlur = 22 * dpr;
        if (planeImg.complete) ctx.drawImage(planeImg, -pw * 0.18, -ph * 0.78, pw, ph);
        ctx.shadowBlur = 0;
        // spinning propeller blur
        const nx = -pw * 0.18 + pw * (103 / 120), ny = -ph * 0.78 + ph * 0.5;
        const spin = Math.abs(Math.sin(performance.now() / 22));
        ctx.fillStyle = "rgba(255,255,255,0.55)";
        ctx.beginPath(); ctx.ellipse(nx + 3 * dpr, ny, 2.2 * dpr, ph * 0.42 * (0.35 + spin * 0.65), 0, 0, Math.PI * 2); ctx.fill();
        ctx.restore();
        return { tailX: x - pw * 0.12 * Math.cos(angle), tailY: y - pw * 0.12 * Math.sin(angle) };
    }

    function render() {
        // local phase transition: take-off happens exactly at the server timestamp
        if (state && phase === "betting" && serverNow() >= state.round.flight_starts_at) onTakeoff();

        ctx.clearRect(0, 0, W, H);
        const flying = phase === "flying";
        const t = phase === "crashed" ? Math.log(crashPoint) / growth : Math.max(0, flightElapsed());
        const m = currentMultiplier();
        drawBackground(t, flying);

        if (phase === "betting") {
            const g = geometry(0, 1);
            const bob = Math.sin(performance.now() / 380) * 4 * dpr;
            drawPlane(g.L + 16 * dpr, H - g.B - 6 * dpr + bob, -0.05, 0.85);
            if (Math.random() < 0.3) spawn(g.L + 10 * dpr, H - g.B - 4 * dpr + bob, 1, { angle: Math.PI, spread: 0.8, speed: 0.6, decay: 0.03, size: 2 });
            // progress
            const total = (state ? state.round.betting_seconds : 7) * 1000;
            const left = state ? Math.max(0, state.round.flight_starts_at - serverNow()) : total;
            progressBar.style.transform = `scaleX(${Math.min(1, left / total)})`;
        } else {
            const g = geometry(t, Math.max(m, 1));
            // curve
            const N = 90, pts = [];
            for (let i = 0; i <= N; i++) {
                const tt = (t * i) / N;
                pts.push([g.px(tt), g.py(Math.exp(growth * tt))]);
            }
            const last = pts[pts.length - 1];
            const prev = pts[Math.max(0, pts.length - 6)];
            const angle = Math.max(-0.85, Math.atan2(last[1] - prev[1], last[0] - prev[0] || 1));

            const fill = ctx.createLinearGradient(0, g.T, 0, H - g.B);
            const crashed = phase === "crashed";
            fill.addColorStop(0, crashed ? "rgba(224, 30, 30,0.35)" : "rgba(224, 30, 30,0.45)");
            fill.addColorStop(1, "rgba(0, 160, 70,0.02)");
            ctx.beginPath(); ctx.moveTo(pts[0][0], H - g.B);
            pts.forEach(([x, y]) => ctx.lineTo(x, y));
            ctx.lineTo(last[0], H - g.B); ctx.closePath();
            ctx.fillStyle = fill; ctx.fill();

            const stroke = ctx.createLinearGradient(g.L, 0, last[0], 0);
            stroke.addColorStop(0, crashed ? "#ff4d4d" : "#006600");
            stroke.addColorStop(0.5, crashed ? "#e01e1e" : "#ffffff");
            stroke.addColorStop(1, crashed ? "#bb0000" : "#e01e1e");
            ctx.save();
            ctx.shadowColor = crashed ? "#e01e1e" : "#ffffff"; ctx.shadowBlur = 18 * dpr;
            ctx.lineWidth = 4 * dpr; ctx.lineCap = "round"; ctx.lineJoin = "round"; ctx.strokeStyle = stroke;
            ctx.beginPath(); pts.forEach(([x, y], i) => (i ? ctx.lineTo(x, y) : ctx.moveTo(x, y))); ctx.stroke();
            ctx.restore();

            if (!crashed) {
                planePos = { x: last[0], y: last[1], angle };
                const tail = drawPlane(last[0], last[1], angle);
                spawn(tail.tailX, tail.tailY, 3, { angle: angle + Math.PI, spread: 1.1, speed: 1.6, decay: 0.016, size: 3.2 });
            } else if (flyAway) {
                flyAway.vx *= 1.06; flyAway.vy *= 1.06;
                flyAway.x += flyAway.vx; flyAway.y += flyAway.vy;
                if (flyAway.x < W + 200 * dpr && flyAway.y > -200 * dpr) {
                    const tail = drawPlane(flyAway.x, flyAway.y, -0.55);
                    spawn(tail.tailX, tail.tailY, 2, { angle: Math.PI * 0.8, spread: 0.7, speed: 1, decay: 0.02, col: "224,30,30" });
                }
            }
        }
        updateParticles();

        // multiplier text & tiers
        multEl.textContent = m.toFixed(2) + "x";
        multEl.classList.toggle("tier-2", phase !== "crashed" && m >= 2 && m < 10);
        multEl.classList.toggle("tier-3", phase !== "crashed" && m >= 10);
        multEl.classList.toggle("crashed", phase === "crashed");
        panels.forEach((p) => p.paint(m));
        requestAnimationFrame(render);
    }

    // ------------------------------------------------------------------ phase events
    function setOverlay() {
        overlay.classList.toggle("is-betting", phase === "betting");
        overlay.classList.toggle("is-crashed", phase === "crashed");
    }
    function onTakeoff() {
        phase = "flying"; setOverlay(); Sound.takeoff();
        const g = geometry(0, 1);
        spawn(g.L + 10 * dpr, H - g.B, 40, { angle: -0.4, spread: 1.5, speed: 3, decay: 0.02 });
    }
    function onCrash(point) {
        phase = "crashed"; crashPoint = Number(point); crashedAtLocal = Date.now(); setOverlay(); Sound.crash();
        flyAway = { x: planePos.x, y: planePos.y, vx: 3 * dpr, vy: -2.2 * dpr };
        spawn(planePos.x, planePos.y, 70, { speed: 4, decay: 0.018, size: 3.5, gravity: 0.03, col: "224,30,30" });
        spawn(planePos.x, planePos.y, 40, { speed: 2.5, decay: 0.014, size: 3, col: "255,255,255" });
    }
    function onNewRound(seq) {
        lastSeq = seq; phase = "betting"; flyAway = null; crashPoint = 1; setOverlay();
        panels.forEach((p) => p.newRound());
        if (betTab !== "all") loadHistoryTab(betTab);
    }

    // ------------------------------------------------------------------ server sync
    function applyState(s) {
        state = s;
        growth = s.growth_rate || growth;
        const r = s.round;
        if (r.sequence !== lastSeq) onNewRound(r.sequence);
        if (r.phase === "crashed") {
            if (phase !== "crashed") onCrash(r.crash_point);
        } else if (r.phase === "flying" && phase === "betting") {
            onTakeoff();
        }
        roundTag.textContent = `🔮 Round #${r.sequence} · ${r.seed_hash.slice(0, 10)}…`;
        roundTag.title = "Seed hash: " + r.seed_hash;

        renderHistory(s.history);
        if (betTab === "all") {
            $("#playersCount").textContent = s.stats.players;
            $("#totalBet").textContent = fmt(s.stats.total);
            renderBets(s.bets);
        }
        if (s.balance !== null) setBalance(s.balance);
        panels.forEach((p) => p.sync(s));
    }

    async function poll() {
        try {
            const t0 = Date.now();
            const s = await api(C.stateUrl);
            const t1 = Date.now();
            const sample = s.now - (t0 + t1) / 2;
            offset = offsetReady ? offset * 0.7 + sample * 0.3 : sample;
            offsetReady = true;
            applyState(s);
        } catch (e) { /* network blip: keep animating */ }
        setTimeout(poll, phase === "flying" ? 350 : 700);
    }

    // ------------------------------------------------------------------ history & bets
    function pillClass(x) { return x >= 10 ? "high" : x >= 2 ? "mid" : ""; }
    function renderHistory(list) {
        if (!list.length || list[0].sequence === lastHistoryTop) return;
        const fresh = lastHistoryTop !== null;
        lastHistoryTop = list[0].sequence;
        historyStrip.innerHTML = list.map((h, i) =>
            `<span class="hpill ${pillClass(Number(h.crash_point))} ${fresh && i === 0 ? "new" : ""}">${Number(h.crash_point).toFixed(2)}x</span>`
        ).join("");
    }

    const AVATAR = ["#BB0000", "#006600", "#000000", "#3a3a3a"];
    function hueOf(name) { let h = 0; for (const c of name) h = (h * 31 + c.charCodeAt(0)) % 997; return AVATAR[h % AVATAR.length]; }
    function esc(s) { return String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])); }
    function betRow(b) {
        const won = b.status === "won";
        const h = hueOf(b.player);
        return `<tr class="bet-row ${won ? "won" : ""} ${b.mine ? "mine" : ""}">
            <td><span class="mini-avatar" style="background:${h};box-shadow:0 0 0 1px #fff">${esc(b.player[0].toUpperCase())}</span>${esc(b.player)}</td>
            <td class="num">${fmt(b.amount)}</td>
            <td class="num">${won ? `<span class="xbadge">${Number(b.cashed_out_at).toFixed(2)}x</span>` : (b.crash_point ? `<span class="muted">${Number(b.crash_point).toFixed(2)}x</span>` : "")}</td>
            <td class="num">${won ? fmt(b.payout) : (b.status === "lost" ? '<span class="text-red">0.00</span>' : "")}</td>
        </tr>`;
    }
    function renderBets(bets, emptyText = "No bets yet this round — be the first to fly ✨") {
        betsBody.innerHTML = bets.length ? bets.map(betRow).join("") : `<tr><td colspan="4" class="empty">${emptyText}</td></tr>`;
    }
    async function loadHistoryTab(tab) {
        try {
            const data = await api(C.historyUrl + "?tab=" + tab);
            if (betTab !== tab) return;
            if (tab === "previous" && data.round) {
                $("#liveSummary").innerHTML = `<span>Round #${data.round.sequence}</span><span>Crashed at <b class="text-magenta">${Number(data.round.crash_point).toFixed(2)}x</b></span>`;
            }
            renderBets(data.bets, tab === "mine" ? (window.LUMA.loggedIn ? "You haven't flown yet." : "Log in to see your bets.") : "No bets last round.");
        } catch (e) { /* ignore */ }
    }
    document.querySelectorAll("#betTabs .tab").forEach((tabEl) => {
        tabEl.addEventListener("click", () => {
            document.querySelectorAll("#betTabs .tab").forEach((t) => t.classList.remove("active"));
            tabEl.classList.add("active");
            betTab = tabEl.dataset.tab;
            if (betTab === "all") {
                $("#liveSummary").innerHTML = `<span><b id="playersCount">${state ? state.stats.players : 0}</b> players</span><span>Total <b id="totalBet">${fmt(state ? state.stats.total : 0)}</b> ${CUR}</span>`;
                if (state) renderBets(state.bets);
            } else {
                if (betTab === "mine") $("#liveSummary").innerHTML = "<span>Your recent flights</span><span></span>";
                betsBody.innerHTML = `<tr><td colspan="4" class="empty">Loading…</td></tr>`;
                loadHistoryTab(betTab);
            }
        });
    });

    // ------------------------------------------------------------------ bet panels
    function Panel(el) {
        const n = Number(el.dataset.panel);
        const amountInput = $(".amount", el);
        const action = $(".action", el);
        const label = $(".label", action);
        const sub = $(".sub", action);
        const autoBet = $(".auto-bet", el);
        const autoCash = $(".auto-cash", el);
        const autoX = $(".auto-x", el);
        const self = { n, el, bet: null, queued: false, busy: false, seen: new Set(), view: null };

        const amount = () => Math.max(C.minBet, Math.round((parseFloat(amountInput.value) || 0) * 100) / 100);
        const setAmount = (v) => { amountInput.value = Math.max(C.minBet, v).toFixed(2); };

        // Bet / Auto tabs
        el.querySelectorAll(".tabs .tab").forEach((t) => t.addEventListener("click", () => {
            el.querySelectorAll(".tabs .tab").forEach((x) => x.classList.remove("active"));
            t.classList.add("active");
            el.classList.toggle("auto-mode", t.dataset.mode === "auto");
        }));
        el.querySelectorAll("[data-step]").forEach((b) => b.addEventListener("click", () => {
            const step = amount() >= 1000 ? 100 : 10;
            setAmount(amount() + step * Number(b.dataset.step));
        }));
        el.querySelectorAll("[data-quick]").forEach((b) => b.addEventListener("click", () => {
            setAmount(self.lastQuick === b.dataset.quick ? amount() + Number(b.dataset.quick) : Number(b.dataset.quick));
            self.lastQuick = b.dataset.quick;
        }));
        amountInput.addEventListener("blur", () => setAmount(amount()));
        autoX.addEventListener("blur", () => { autoX.value = Math.max(1.01, parseFloat(autoX.value) || 2).toFixed(2); });
        autoBet.addEventListener("change", () => {
            if (autoBet.checked && !self.bet && phase !== "betting") self.queued = true;
            if (autoBet.checked && !self.bet && phase === "betting") place();
        });

        function locked(on) {
            el.querySelectorAll(".stepper button, .stepper input, .quick button, .auto-x, .auto-cash").forEach((x) => { x.disabled = on; });
        }

        async function place() {
            if (!window.LUMA.loggedIn) { toast("Log in to start flying ✨", "error"); setTimeout(() => (location.href = window.LUMA.loginUrl + "?next=/"), 900); return; }
            if (self.busy) return;
            self.busy = true;
            try {
                const res = await api(C.betUrl, {
                    amount: amount(), panel: n,
                    auto_cashout: autoCash.checked ? Math.max(1.01, parseFloat(autoX.value) || 2) : null,
                });
                self.queued = false; self.bet = res.bet; Sound.bet();
                applyState(res.state);
            } catch (e) {
                if (/closed/i.test(e.message)) self.queued = true;
                else { toast(e.message, "error"); self.queued = false; if (/balance/i.test(e.message)) autoBet.checked = false; }
            } finally { self.busy = false; }
        }

        async function cancel() {
            self.busy = true;
            try { const res = await api(C.cancelUrl, { bet_id: self.bet.id }); self.bet = null; applyState(res.state); }
            catch (e) { toast(e.message, "error"); }
            finally { self.busy = false; }
        }

        async function cashout() {
            self.busy = true;
            try { const res = await api(C.cashoutUrl, { bet_id: self.bet.id }); applyState(res.state); handleWin(res.bet); }
            catch (e) { toast(e.message, "error"); }
            finally { self.busy = false; }
        }

        function handleWin(b) {
            if (!b || b.status !== "won" || self.seen.has(b.id)) return;
            self.seen.add(b.id);
            self.bet = b;
            Sound.cashout();
            toast(`✨ Cashed out at ${Number(b.cashed_out_at).toFixed(2)}x — +${fmt(b.payout)} ${CUR}`, "win");
            const r = el.getBoundingClientRect(), s = stage.getBoundingClientRect();
            spawn(planePos.x || W / 2, planePos.y || H / 2, 60, { speed: 3.5, decay: 0.012, size: 4, col: "255,255,255" });
            spawn(((r.left + r.width / 2) - s.left) * dpr, H - 10 * dpr, 30, { angle: -Math.PI / 2, spread: 1.2, speed: 4, decay: 0.015, gravity: 0.04 });
        }

        action.addEventListener("click", () => {
            if (self.busy) return;
            switch (self.view) {
                case "idle":
                    if (phase === "betting" && state && state.round.flight_starts_at - serverNow() > 250) place();
                    else if (!window.LUMA.loggedIn) place();
                    else self.queued = true;
                    break;
                case "queued": self.queued = false; autoBet.checked = false; break;
                case "placed": autoBet.checked = false; cancel(); break;
                case "active": cashout(); break;
            }
        });

        self.newRound = () => {
            self.bet = null;
            if (autoBet.checked) self.queued = true;
        };

        self.sync = (s) => {
            const mine = s.my_bets.find((b) => b.panel === n);
            if (mine) {
                self.bet = mine;
                if (mine.status === "won") handleWin(mine);
            } else if (self.bet && self.bet.status === "active" && !self.busy) {
                self.bet = null;
            }
            if (s.round.phase === "betting" && self.queued && !self.bet && !self.busy && s.round.flight_starts_at - serverNow() > 250) place();
        };

        self.paint = (m) => {
            let view = "idle";
            if (self.bet && self.bet.status === "active" && phase !== "crashed") view = phase === "betting" ? "placed" : "active";
            else if (self.queued) view = "queued";
            el.classList.toggle("is-active", view === "active");
            el.classList.toggle("is-placed", view === "placed");
            el.classList.toggle("is-queued", view === "queued");
            action.classList.toggle("cancel", view === "queued" || view === "placed");
            action.classList.toggle("cashout", view === "active");
            action.classList.toggle("busy", self.busy);
            if (view === "active") {
                label.textContent = "Cash out";
                sub.textContent = `${fmt(Number(self.bet.amount) * m)} ${CUR}`;
            } else if (view === "placed") {
                label.textContent = "Cancel";
                sub.textContent = `${fmt(self.bet.amount)} ${CUR} placed ✓`;
            } else if (view === "queued") {
                label.textContent = "Cancel";
                sub.textContent = "Waiting for next round";
            } else {
                label.textContent = "Bet";
                sub.textContent = `${fmt(amount())} ${CUR}`;
            }
            if (view !== self.view) { locked(view !== "idle"); self.view = view; }
        };
        return self;
    }
    const panels = [...document.querySelectorAll(".bet-panel")].map(Panel);

    // ------------------------------------------------------------------ go
    setOverlay();
    poll();
    requestAnimationFrame(render);
})();
