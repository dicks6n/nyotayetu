/* Betslip: any market, live or pre-match, kept in localStorage. Odds follow live prices. */
(function () {
    "use strict";
    const { api, toast, fmt, setBalance } = window.Luma;
    const CUR = window.LUMA.currency;
    const KEY = "nyota_betslip_v2";
    const slipEl = document.getElementById("betslip");
    const esc = (v) => String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

    let picks = [];
    try { picks = JSON.parse(localStorage.getItem(KEY) || "[]"); } catch (e) { picks = []; }
    const save = () => { try { localStorage.setItem(KEY, JSON.stringify(picks)); } catch (e) { /* ignore */ } };
    let accept = false;
    try { accept = localStorage.getItem("nyota_accept_odds") === "1"; } catch (e) { /* ignore */ }

    const SHORT = {
        "1x2": { 1: (h) => h, X: () => "Draw", 2: (h, a) => a },
        "ou_2.5": { over: () => "Over 2.5", under: () => "Under 2.5" },
        btts: { yes: () => "GG — both score", no: () => "NG — not both" },
    };
    function pickLabel(btn, home, away) {
        if (btn.dataset.plabel) return btn.dataset.plabel;
        const f = (SHORT[btn.dataset.market] || {})[btn.dataset.pick];
        return f ? f(home, away) : btn.dataset.pick;
    }
    const totalOdds = () => picks.reduce((acc, p) => acc * Number(p.odds), 1);

    function paintButtons() {
        document.querySelectorAll("[data-match]").forEach((box) => {
            const sel = picks.find((p) => String(p.match_id) === box.dataset.match);
            box.querySelectorAll(".ob[data-market]").forEach((b) =>
                b.classList.toggle("selected", !!sel && sel.market === b.dataset.market && sel.pick === b.dataset.pick));
        });
        const fab = document.getElementById("slipFab");
        if (fab) { fab.classList.toggle("show", picks.length > 0); document.getElementById("slipFabCount").textContent = picks.length; }
        const tog = document.getElementById("slipToggleCount");
        if (tog) tog.textContent = picks.length;
    }

    function notice(msg) {
        const n = document.getElementById("slipNotice");
        if (!n) return;
        n.textContent = msg || ""; n.classList.toggle("show", !!msg);
    }

    function render() {
        paintButtons();
        if (!slipEl) return;
        const list = slipEl.querySelector(".slip-items");
        const stake = Number(slipEl.querySelector("#stake").value) || 0;
        slipEl.querySelector("#slipCount").textContent = picks.length;
        list.innerHTML = picks.length ? picks.map((p, i) => `
            <div class="slip-item ${p.changed ? "changed" : ""}">
                <div class="pick"><span>${esc(p.plabel)}${p.live ? '<span class="live-tag">LIVE</span>' : ""}</span><b>${Number(p.odds).toFixed(2)}${p.changed ? (p.changed > 0 ? " ▲" : " ▼") : ""}</b></div>
                <div class="mk">${esc(p.mlabel)}</div>
                <div class="teams">${esc(p.home)} vs ${esc(p.away)}</div>
                <button class="remove" data-i="${i}" aria-label="Remove">&times;</button>
            </div>`).join("") : `<div class="empty">🇰🇪 Tap any odds to add a pick</div>`;
        const odds = picks.length ? totalOdds() : 0;
        slipEl.querySelector("#totalOdds").textContent = odds ? odds.toFixed(2) : "—";
        slipEl.querySelector("#potentialWin").textContent = `${fmt(stake * odds)} ${CUR}`;
        slipEl.querySelector("#placeBtn").disabled = !picks.length;
        slipEl.querySelector("#acceptChanges").checked = accept;
    }

    document.addEventListener("click", (e) => {
        const btn = e.target.closest(".ob[data-market]");
        if (btn && !btn.disabled) {
            const box = btn.closest("[data-match]");
            const id = Number(box.dataset.match);
            const i = picks.findIndex((p) => p.match_id === id);
            if (i >= 0 && picks[i].market === btn.dataset.market && picks[i].pick === btn.dataset.pick) {
                picks.splice(i, 1);
            } else {
                const p = { match_id: id, market: btn.dataset.market, pick: btn.dataset.pick, odds: btn.dataset.price,
                            mlabel: btn.dataset.mlabel, plabel: pickLabel(btn, box.dataset.home, box.dataset.away),
                            home: box.dataset.home, away: box.dataset.away, live: box.dataset.live === "1" };
                if (i >= 0) picks[i] = p; else picks.push(p);
            }
            save(); render();
            return;
        }
        const rm = e.target.closest(".slip-item .remove");
        if (rm) { picks.splice(Number(rm.dataset.i), 1); save(); render(); }
    });

    // live price moves from sports-live.js
    document.addEventListener("nyota:odds", (e) => {
        const { id, state } = e.detail;
        let touched = false;
        picks.forEach((p) => {
            if (String(p.match_id) !== id) return;
            p.live = state.status === "live";
            const now = (state.odds[p.market] || {})[p.pick];
            if (now && now !== p.odds && (state.odds[p.market])) {
                p.changed = Number(now) > Number(p.odds) ? 1 : -1;
                p.odds = now; touched = true;
            }
        });
        if (touched) { save(); render(); notice(accept ? "" : "Some odds have changed — the slip shows the new prices."); }
    });

    if (slipEl) {
        slipEl.querySelector("#stake").addEventListener("input", render);
        slipEl.querySelectorAll("[data-stake]").forEach((b) => b.addEventListener("click", () => {
            slipEl.querySelector("#stake").value = b.dataset.stake; render();
        }));
        slipEl.querySelector("#acceptChanges").addEventListener("change", (e) => {
            accept = e.target.checked;
            try { localStorage.setItem("nyota_accept_odds", accept ? "1" : "0"); } catch (err) { /* ignore */ }
        });
        slipEl.querySelector("#clearSlip").addEventListener("click", () => { picks = []; save(); notice(""); render(); });
        slipEl.querySelector("#placeBtn").addEventListener("click", async (e) => {
            const btn = e.currentTarget;
            btn.disabled = true;
            try {
                const res = await api(slipEl.dataset.url, {
                    stake: slipEl.querySelector("#stake").value, accept_changes: accept,
                    selections: picks.map(({ match_id, market, pick, odds }) => ({ match_id, market, pick, odds })),
                });
                toast(`🎫 Bet ${res.code} placed! Potential win ${fmt(res.potential_win)} ${CUR} 🇰🇪`, "win", 5000);
                setBalance(res.balance);
                picks = []; save(); notice("");
            } catch (err) {
                const changed = err.data && err.data.odds_changed;
                if (changed) {
                    picks.forEach((p) => {
                        const c = changed[String(p.match_id)];
                        if (c) { p.changed = Number(c.odds) > Number(p.odds) ? 1 : -1; p.odds = c.odds; }
                    });
                    save(); notice("Odds changed — check the new prices and press Place bet again.");
                } else {
                    toast(err.message, "error");
                }
            } finally { render(); }
        });
        document.getElementById("slipToggle")?.addEventListener("click", () => slipEl.classList.toggle("open"));
        slipEl.querySelector("#slipClose")?.addEventListener("click", () => slipEl.classList.remove("open"));
    }
    render();
})();
