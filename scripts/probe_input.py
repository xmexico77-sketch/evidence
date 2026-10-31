"""临时探针：检查页面里有没有 file input（调试用，可删）。

用法：.venv\\Scripts\\python.exe scripts/probe_input.py http://127.0.0.1:3001/write
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ui_shot import Session, find_browser, page_target, wait_devtools  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
PORT = 9556


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:3001/write"
    browser = find_browser()
    proc = subprocess.Popen(
        [browser, "--headless=new", "--disable-gpu", "--no-sandbox", "--no-first-run",
         "--hide-scrollbars", "--window-size=1600,1000",
         f"--user-data-dir={ROOT / '.cache' / 'edge-probe'}",
         f"--remote-debugging-port={PORT}", "about:blank"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_devtools(PORT)
        s = Session(page_target(PORT))
        s.send("Page.enable")
        s.send("Runtime.enable")
        s.send("Page.navigate", {"url": url})
        time.sleep(7)
        js1 = (
            "(()=>{const i=document.querySelector('input[type=file]');"
            "return i?('FOUND '+i.outerHTML.slice(0,120)):'NONE';})()"
        )
        js2 = (
            "(()=>{const a=[...document.querySelectorAll('input')];"
            "return a.length+' inputs: '+a.map(x=>x.type).join(',');})()"
        )
        js3 = "document.body.innerText.slice(0,200)"
        for js in (js1, js2, js3):
            r = s.evaluate(js)
            print("→", r.get("result", {}).get("value"))
        s.close()
    finally:
        proc.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
