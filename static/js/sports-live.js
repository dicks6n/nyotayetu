/* Live sportsbook updates: scores, match clock, goal flashes and odds that move in real time. */
(function () {
    "use strict";
    const CFG = window.SPORTS || {};
    const { api } = window.Luma;
    const containers = () => [...document.querySelectorAll("[data-match]")];
    const ids = () => [...new Set(containers().map((el) => el.dataset.match))];
    const last = {};   // matchId -> previous state

    function setOdds(btn, price) {
        const pv = btn.querySelector(".pv") || btn;
        const old = btn.dataset.price;
        if (!price) {
            btn.disabled = true; btn.classList.add("locked");
            if (pv === btn) btn.textContent = ""; else pv.textContent = "";
            btn.dataset.price = "";
            return;
        }
        btn.disabled = false; btn.classList.remove("locked");
        if (old && old !== price) {
            btn.classList.remove("up", "down"); void btn.offsetWidth;   // restart the flash
            btn.classList.add(Number(price) > Number(old) ? "up" : "down");
        }
        btn.dataset.price = price;
        pv.textContent = price;
    }

    function apply(id, st) {
        const prev = last[id];
        const scored = prev && (prev.score[0] !== st.score[0] || prev.score[1] !== st.score[1]);
        containers().filter((el) => el.dataset.match === String(id)).forEach((el) => {
            el.classList.toggle("suspended", st.suspended && el.classList.contains("mrow"));
            if (el.classList.contains("mrow")) el.classList.toggle("done", st.status === "finished" || st.status === "cancelled");
            if (scored && el.classList.contains("mrow")) { el.classList.remove("goal"); void el.offsetWidth; el.classList.add("goal"); }
            const live = st.status === "live", done = st.status === "finished";
            const q = (r) => el.querySelector(`[data-role="${r}"]`);
            if (el.classList.contains("mrow") && (live || done)) {
                const when = q("when");
                when.innerHTML = done ? '<span class="fs-ft">FT</span>'
                    : `<span class="fs-live">${st.period === "HT" ? "HT" : st.minute + "<i>'</i>"}</span>`;
                el.querySelectorAll(".teams a").forEach((a, i) => {
                    let b = a.querySelector("b");
                    if (!b) { b = document.createElement("b"); a.appendChild(b); }
                    b.textContent = st.score[i] ?? 0;
                    b.classList.toggle("lv", live);
                });
            }
            if (el.id === "board") {
                if (live || done) { q("sh").textContent = st.score[0] ?? 0; q("sa").textContent = st.score[1] ?? 0; }
                const clock = q("clock");
                clock.classList.toggle("pre", !live);
                if (live) clock.textContent = st.period === "HT" ? "HALF TIME" : st.minute + "'";
                if (done) clock.textContent = "FULL TIME";
                q("fill").style.width = Math.min(100, st.minute / 90 * 100) + "%";
                q("events").innerHTML = st.events.map((e) =>
                    `<span class="ev" style="left:${Math.min(100, e.minute / 90 * 100)}%" title="${e.minute}' goal">${e.team === "home" ? "⚽" : "🥅"}</span>`).join("");
                if (st.ht[0] !== null) q("ht").textContent = `HT ${st.ht[0]}-${st.ht[1]}`;
                q("status").textContent = st.suspended ? "⛔ Suspended — goal!" : live ? "🔴 In play · odds update live" : done ? "Full time — bets settled" : `${st.markets} markets`;
                if (scored) { Luma.toast(`⚽ GOAL! ${el.dataset.home} ${st.score[0]} - ${st.score[1]} ${el.dataset.away}`, "win"); }
            }
            el.querySelectorAll(".ob[data-market]").forEach((btn) => {
                const m = st.odds[btn.dataset.market];
                // the list only receives main markets; leave others untouched there
                if (!m && el.classList.contains("mrow") && !["1x2", "ou_2.5", "btts"].includes(btn.dataset.market)) return;
                setOdds(btn, done || st.suspended ? null : m && m[btn.dataset.pick]);
            });
        });
        document.dispatchEvent(new CustomEvent("nyota:odds", { detail: { id: String(id), state: st } }));
        last[id] = st;
    }

    async function poll() {
        const list = ids();
        if (list.length) {
            try {
                const d = await api(`${CFG.liveUrl}?ids=${list.join(",")}${CFG.full ? "&full=" + CFG.full : ""}`);
                Object.entries(d.matches).forEach(([id, st]) => apply(id, st));
                const c = document.querySelector('[data-count="live"]');
                if (c && d.counts) c.textContent = d.counts.live;
            } catch (e) { /* network blip */ }
        }
        const anyLive = Object.values(last).some((s) => s.status === "live");
        setTimeout(poll, anyLive ? 2500 : 8000);
    }
    // remember the server-rendered prices so the first poll can show movement
    document.querySelectorAll(".ob[data-market]").forEach((b) => {
        const t = (b.querySelector(".pv") || b).textContent.trim();
        b.dataset.price = /^\d/.test(t) ? t : "";
        if (!b.dataset.price) { b.disabled = true; b.classList.add("locked"); if (!b.querySelector(".pv")) b.textContent = ""; }
    });
    poll();
})();
