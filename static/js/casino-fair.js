/* Browser mirror of casino/fair.py — lets players recompute any result themselves. */
window.CasinoFair = (function () {
    const enc = new TextEncoder();
    async function floats(serverSeed, clientSeed, nonce, count) {
        const key = await crypto.subtle.importKey("raw", enc.encode(serverSeed), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
        const out = [];
        for (let cursor = 0; out.length < count; cursor++) {
            const d = new Uint8Array(await crypto.subtle.sign("HMAC", key, enc.encode(`${clientSeed}:${nonce}:${cursor}`)));
            for (let i = 0; i < 32 && out.length < count; i += 4) {
                out.push(d[i] / 256 + d[i + 1] / 256 ** 2 + d[i + 2] / 256 ** 3 + d[i + 3] / 256 ** 4);
            }
        }
        return out;
    }
    async function sha256(text) {
        const buf = await crypto.subtle.digest("SHA-256", enc.encode(text));
        return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
    }
    return { floats, sha256 };
})();
