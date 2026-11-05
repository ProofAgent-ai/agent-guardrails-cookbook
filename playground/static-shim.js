// Static mode for GitHub Pages: answers the playground's /api/* calls from recorded runs
// (data/site.json, built by build_static.py), so the page works with no server.
(() => {
  const DATA = fetch("data/site.json").then(r => r.json());
  const realFetch = window.fetch.bind(window);
  const json = body => new Response(JSON.stringify(body), { headers: { "Content-Type": "application/json" } });

  async function handle(url, init) {
    const d = await DATA, u = new URL(url, location.href), q = u.searchParams;
    const body = init && init.body ? JSON.parse(init.body) : {};
    switch (u.pathname.replace(/^.*\/api\//, "")) {
      case "frameworks": return json({ frameworks: d.frameworks, planned: d.planned });
      case "scenarios":  return json({ scenarios: d.scenarios });
      case "files":      return json({ files: d.files, code: d.code });
      case "file":
      case "source":     return json(q.get("path") in d.contents ? { path: q.get("path"), content: d.contents[q.get("path")] }
                                                                 : { error: "not in this demo" });
      case "models":     return json({ error: "model choice needs the live playground" });
      case "test/nano":
      case "test/llm":   return json({ checks: [{ name: "Replay demo", ok: null, ms: 0,
                           detail: "Connection tests need the live playground: use “Run it live”." }] });
      case "run": {
        const rec = d.recordings[body.guard] || d.recordings.local;
        const run = rec && rec.runs.find(r => r.message.trim() === String(body.message || "").trim());
        if (!run) return json({ error: "This demo replays recorded runs. Pick one of the scenarios above, "
                                     + "or type your own message in the live playground: " + d.codespaces });
        const results = body.mode === "compare" ? run.results : run.results.filter(r => r.mode === body.mode);
        return json({ results });
      }
    }
    return json({ error: "not available in the demo" });
  }
  window.fetch = (url, init) => String(url).includes("/api/") ? handle(String(url), init) : realFetch(url, init);

  // Banner, and hide controls that only make sense with a live server.
  document.addEventListener("DOMContentLoaded", async () => {
    const d = await DATA;
    const css = document.createElement("style");
    css.textContent = `#nanoFields,#llmFields,#testLlm,#llmChecks,label[for=provider],#provider,#recordBtn{display:none!important}
      .demo-bar{display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin:0 0 16px;padding:12px 16px;border-radius:12px;
        background:linear-gradient(135deg,color-mix(in srgb,var(--accent) 14%,var(--panel)),var(--panel));border:1px solid color-mix(in srgb,var(--accent) 35%,var(--line))}
      .demo-bar b{font-size:14px} .demo-bar span{color:var(--muted);font-size:12.5px}
      .demo-bar a{margin-left:auto;background:var(--accent);color:var(--accent-ink);text-decoration:none;font-weight:650;padding:8px 14px;border-radius:8px;font-size:13px}
      .demo-note{font-size:12px;color:var(--muted);margin-top:4px}`;
    document.head.appendChild(css);
    const guards = Object.entries(d.recordings).map(([k, r]) => `${k === "nano" ? "ProofAgent Nano" : "local rules"} + ${r.meta.llm}`).join(" · ");
    const bar = document.createElement("div");
    bar.className = "demo-bar";
    bar.innerHTML = `<b>▶ Replay demo</b><span>Real runs recorded on ${Object.values(d.recordings)[0].meta.recorded} (${guards}). Pick a scenario and press Run.</span>
      <a href="${d.codespaces}" target="_blank" rel="noopener">Run it live with your own key →</a>`;
    document.querySelector("#tab-play").prepend(bar);
    const llm = document.querySelector("#llmDot")?.closest(".card");
    if (llm) llm.insertAdjacentHTML("beforeend", `<div class="demo-note">Recorded with: ${Object.values(d.recordings).map(r => r.meta.llm).join(", ")}. Pick any LLM in the live playground.</div>`);
    if (!d.recordings.nano) {
      const g = document.querySelector('#guard [data-v="nano"]');
      if (g) { g.disabled = true; g.title = "Nano recordings not published yet"; }
      document.querySelector('#guard [data-v="local"]')?.click();
    }
  });
})();
