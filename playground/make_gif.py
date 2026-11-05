"""Record the playground's replay of Nano runs into docs/assets/playground.gif.

    python playground/build_static.py && python playground/make_gif.py

Serves _site, drives headless Chrome over CDP, captures the diagram card, builds a GIF with PIL.
"""
import asyncio, base64, functools, io, json, subprocess, sys, tempfile, threading, time, urllib.request
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import websockets
from PIL import Image

REPO = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[1]
OUT = REPO / "docs/assets/playground.gif"
SCENES = [("Indirect injection (tool)", 6), ("PII in the message", 6), ("Injection (AR)", 3)]
FPS, WIDTH = 10, 900

srv = ThreadingHTTPServer(("127.0.0.1", 8011), functools.partial(SimpleHTTPRequestHandler, directory=str(REPO / "_site")))
srv.RequestHandlerClass.log_message = lambda *a: None
threading.Thread(target=srv.serve_forever, daemon=True).start()

prof = tempfile.mkdtemp()
chrome = subprocess.Popen(["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--headless=new", "--remote-debugging-port=9333",
                           f"--user-data-dir={prof}", "--window-size=1300,1000", "--hide-scrollbars", "--force-device-scale-factor=2",
                           "about:blank"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


async def main():
    for _ in range(50):
        try:
            tabs = json.load(urllib.request.urlopen("http://127.0.0.1:9333/json"))
            ws_url = next(t["webSocketDebuggerUrl"] for t in tabs if t["type"] == "page"); break
        except Exception:
            await asyncio.sleep(0.2)
    async with websockets.connect(ws_url, max_size=2**28) as ws:
        n = 0
        async def cdp(method, **params):
            nonlocal n; n += 1; my = n
            await ws.send(json.dumps({"id": my, "method": method, "params": params}))
            while True:
                m = json.loads(await ws.recv())
                if m.get("id") == my:
                    if "error" in m: raise RuntimeError(m["error"])
                    return m.get("result", {})
        async def js(expr):
            r = await cdp("Runtime.evaluate", expression=expr, awaitPromise=True, returnByValue=True)
            return r.get("result", {}).get("value")
        await cdp("Emulation.setDeviceMetricsOverride", width=1300, height=1000, deviceScaleFactor=2, mobile=False)
        await cdp("Page.navigate", url="http://127.0.0.1:8011/")
        await asyncio.sleep(2.5)
        await js("""(async()=>{const w=t=>new Promise(r=>setTimeout(r,t)); const B=s=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim().startsWith(s));
            const f=document.querySelector('#framework'); f.value='langgraph'; f.dispatchEvent(new Event('change')); await w(300);
            B('ProofAgent Nano').click(); B('Hybrid').click(); const sp=document.querySelector('#vSpeed'); [...sp.options].forEach(o=>{if(o.text==='fast')sp.value=o.value}); sp.dispatchEvent(new Event('change')); await w(300); return 1})()""")
        frames = []
        for label, secs in SCENES:
            await js(f"""(async()=>{{const w=t=>new Promise(r=>setTimeout(r,t)); const B=s=>[...document.querySelectorAll('button')].find(b=>b.textContent.trim().startsWith(s));
                B({json.dumps(label)}).click(); await w(200); document.querySelector('#go').click(); await w(200);
                while(document.querySelector('#go').disabled) await w(100);
                const card=[...document.querySelectorAll('svg')].sort((a,b)=>b.getBoundingClientRect().width-a.getBoundingClientRect().width)[0];
                card.scrollIntoView({{block:'start'}}); window.scrollBy(0,-8); return 1}})()""")
            box = await js("""(()=>{const s=[...document.querySelectorAll('svg')].sort((a,b)=>b.getBoundingClientRect().width-a.getBoundingClientRect().width)[0]; const v=document.querySelector('#verdict');
                const a=v.getBoundingClientRect(), b=document.querySelector('.legend2').getBoundingClientRect();
                return {x:Math.min(a.left,s.getBoundingClientRect().left)-12+scrollX, y:a.top-12+scrollY, w:s.getBoundingClientRect().width+24, h:b.bottom-a.top+20}})()""")
            end = time.time() + 25
            while time.time() < end:
                if await js("VIEW && VIEW.idx >= VIEW.steps.length - 1"):
                    await asyncio.sleep(0.6); end = 0
                t = time.time()
                shot = await cdp("Page.captureScreenshot", format="png", clip={**{k: box[k[0]] for k in ("x", "y")}, "width": box["w"], "height": box["h"], "scale": 1})
                frames.append(Image.open(io.BytesIO(base64.b64decode(shot["data"]))).convert("RGB"))
                await asyncio.sleep(max(0, 1 / FPS - (time.time() - t)))
            frames += [frames[-1]] * (FPS * 2)          # hold the result for 2 s
    return frames


try:
    frames = asyncio.run(main())
finally:
    chrome.terminate(); srv.shutdown()

h = round(frames[0].height * WIDTH / frames[0].width)
small = [f.resize((WIDTH, h), Image.LANCZOS) for f in frames]
pal = small[len(small) // 2].quantize(colors=128, method=Image.Quantize.MEDIANCUT)
q = [f.quantize(palette=pal, dither=Image.Dither.NONE) for f in small]
q[0].save(OUT, save_all=True, append_images=q[1:], duration=int(1000 / FPS), loop=0, optimize=True)
print(f"{OUT} · {len(q)} frames · {WIDTH}x{h} · {OUT.stat().st_size // 1024} KB")
