/* Shared helpers for the instant casino games. */
(function () {
    "use strict";
    const { api, toast, fmt, setBalance } = window.Luma;
    const CFG = window.CASINO;
    const CUR = window.LUMA.currency;
    const $ = (s, r = document) => r.querySelector(s);

    // ------------------------------------------------------------------ bet amount
    const amountInput = $("#amount");
    const amount = () => Math.round((parseFloat(amountInput.value) || 0) * 100) / 100;
    const setAmount = (v) => {
        amountInput.value = Math.min(CFG.maxBet, Math.max(CFG.minBet, v)).toFixed(2);
        amountInput.dispatchEvent(new Event("input"));
    };
    amountInput.addEventListener("blur", () => setAmount(amount()));
    document.querySelectorAll("[data-amt]").forEach((b) => b.addEventListener("click", () => {
        const op = b.dataset.amt;
        setAmount(op === "half" ? amount() / 2 : op === "double" ? amount() * 2 : Number(op));
    }));

    // ------------------------------------------------------------------ segmented buttons
    function segmented(el, onChange) {
        el.querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
            if (b.disabled) return;
            el.querySelectorAll("button").forEach((x) => x.classList.remove("active"));
            b.classList.add("active");
            onChange && onChange(b.dataset.v);
        }));
        return () => el.querySelector("button.active").dataset.v;
    }

    // ------------------------------------------------------------------ sound
    let actx = null, soundOn = true;
    try { soundOn = localStorage.getItem("luma_sound") !== "off"; } catch (e) { /* ignore */ }
    document.addEventListener("pointerdown", () => {
        if (!actx) { try { actx = new (window.AudioContext || window.webkitAudioContext)(); } catch (e) { /* ignore */ } }
    }, { once: true });
    function tone(freq, dur = 0.12, type = "sine", vol = 0.08, delay = 0, slide = null) {
        if (!soundOn || !actx) return;
        const t = actx.currentTime + delay, o = actx.createOscillator(), g = actx.createGain();
        o.type = type; o.frequency.setValueAtTime(freq, t);
        if (slide) o.frequency.exponentialRampToValueAtTime(slide, t + dur);
        g.gain.setValueAtTime(0.0001, t); g.gain.exponentialRampToValueAtTime(vol, t + 0.01);
        g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
        o.connect(g).connect(actx.destination); o.start(t); o.stop(t + dur + 0.05);
    }
    const sound = {
        tick: () => tone(1200 + Math.random() * 400, 0.03, "triangle", 0.03),
        click: () => tone(520, 0.08, "triangle", 0.06),
        win: () => { tone(880, 0.15); tone(1320, 0.25, "sine", 0.07, 0.08); tone(1760, 0.4, "sine", 0.05, 0.16); },
        lose: () => tone(220, 0.35, "sawtooth", 0.04, 0, 90),
        gem: () => { tone(1500, 0.12, "sine", 0.06); tone(2200, 0.2, "sine", 0.04, 0.05); },
        boom: () => { tone(120, 0.6, "sawtooth", 0.08, 0, 40); tone(60, 0.5, "square", 0.05); },
    };

    // ------------------------------------------------------------------ sparkle burst (DOM, no canvas needed)
    function burst(x, y, n = 26, cols = ["#ffffff", "#e01e1e", "#00c853", "#ffffff", "#BB0000"]) {
        for (let i = 0; i < n; i++) {
            const s = document.createElement("span");
            const a = Math.random() * Math.PI * 2, d = 40 + Math.random() * 110;
            s.textContent = "✦";
            s.style.cssText = `position:fixed;left:${x}px;top:${y}px;z-index:4000;pointer-events:none;font-size:${8 + Math.random() * 14}px;` +
                `color:${cols[i % cols.length]};text-shadow:0 0 10px currentColor, 1px 1px 0 #000;transition:transform .9s cubic-bezier(.1,.8,.3,1),opacity .9s;`;
            document.body.appendChild(s);
            requestAnimationFrame(() => {
                s.style.transform = `translate(${Math.cos(a) * d}px, ${Math.sin(a) * d}px) rotate(${Math.random() * 360}deg)`;
                s.style.opacity = "0";
            });
            setTimeout(() => s.remove(), 950);
        }
    }
    function burstAt(el, n) { const r = el.getBoundingClientRect(); burst(r.left + r.width / 2, r.top + r.height / 2, n); }

    // ------------------------------------------------------------------ play
    async function play(url, body) {
        if (!window.LUMA.loggedIn) {
            toast("Log in to play ✨", "error");
            setTimeout(() => (location.href = window.LUMA.loginUrl + "?next=" + encodeURIComponent(location.pathname)), 900);
            throw new Error("login");
        }
        return api(url, body);
    }

    // multiplier -> colour tier (t0..t4), shared with CSS
    const tier = (m) => (m <= 0 ? "t0" : m < 1.5 ? "t1" : m < 3 ? "t2" : m < 10 ? "t3" : "t4");
    const xfmt = (m) => {
        const v = Number(m);
        return (v >= 100 ? v.toFixed(0) : v >= 10 ? +v.toFixed(1) : +v.toFixed(2)) + "x";
    };

    // ------------------------------------------------------------------ live feed
    const feedBody = $("#feedBody");
    let feedTab = "all", feedData = { all: [], mine: [] };
    const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
    function renderFeed() {
        const rows = feedData[feedTab] || [];
        feedBody.innerHTML = rows.length ? rows.map((b) => `
            <tr class="bet-row ${b.status === "won" ? "won" : ""} ${b.mine ? "mine" : ""}">
                <td>${esc(b.player)}</td>
                <td class="muted">${new Date(b.created_at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</td>
                <td class="num">${fmt(b.amount)}</td>
                <td class="num"><span class="xbadge">${Number(b.multiplier).toFixed(2)}x</span></td>
                <td class="num ${Number(b.payout) > Number(b.amount) ? "text-green" : "muted"}">${fmt(b.payout)}</td>
            </tr>`).join("") : `<tr><td colspan="5" class="empty">${feedTab === "mine" ? "Your bets will appear here." : "No bets yet — be the first ✨"}</td></tr>`;
    }
    async function refreshFeed() {
        if (!feedBody) return;
        try { feedData = await api(CFG.feedUrl + "?game=" + CFG.game); renderFeed(); } catch (e) { /* ignore */ }
    }
    document.querySelectorAll("#feedTabs .tab").forEach((t) => t.addEventListener("click", () => {
        document.querySelectorAll("#feedTabs .tab").forEach((x) => x.classList.remove("active"));
        t.classList.add("active"); feedTab = t.dataset.tab; renderFeed();
    }));
    refreshFeed();
    setInterval(refreshFeed, 8000);

    // recent results pills on the stage
    const pills = $("#recentPills");
    function pushRecent(mult) {
        if (!pills) return;
        const m = Number(mult);
        const el = document.createElement("span");
        el.className = `hpill new ${m >= 10 ? "high" : m >= 2 ? "mid" : m >= 1 ? "" : "lose"}`;
        el.textContent = m.toFixed(2) + "x";
        pills.prepend(el);
        while (pills.children.length > 10) pills.lastChild.remove();
    }

    function settle(bet, balance, anchorEl) {
        setBalance(balance);
        pushRecent(bet.multiplier);
        const m = Number(bet.multiplier);
        if (Number(bet.payout) > Number(bet.amount)) {
            sound.win();
            if (anchorEl) burstAt(anchorEl, m >= 10 ? 60 : 30);
            if (m >= 5) toast(`✨ ${m.toFixed(2)}x — won ${fmt(bet.payout)} ${CUR}!`, "win");
        } else {
            sound.lose();
        }
        setTimeout(refreshFeed, 400);
    }

    window.Casino = { amount, setAmount, segmented, sound, burst, burstAt, play, tier, xfmt, settle, pushRecent, refreshFeed, $, fmt, CUR };
})();

/* Playing-card helpers shared by Blackjack & Baccarat. A card is 0..51: rank = c % 13, suit = c / 13. */
window.Cards = (function () {
    const SUITS = ["♠", "♥", "♦", "♣"], RANKS = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"];
    function html(c, delay = 0) {
        if (c === null || c === undefined) return `<div class="pcard back" style="animation-delay:${delay}ms"></div>`;
        const r = RANKS[c % 13], s = SUITS[Math.floor(c / 13)], red = s === "♥" || s === "♦";
        return `<div class="pcard ${red ? "red" : ""}" style="animation-delay:${delay}ms">
            <span class="c1">${r}<br>${s}</span><span class="mid">${s}</span><span class="c2">${r}<br>${s}</span></div>`;
    }
    return { html };
})();
