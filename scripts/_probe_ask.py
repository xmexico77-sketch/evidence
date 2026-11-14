import json
import time
import urllib.request

BASE = "http://1.12.228.44:3000"
USER = "reviewer"
PWD = "49caf89ea6d6"

cj = urllib.request.HTTPCookieProcessor()
op = urllib.request.build_opener(cj)

def post(path, payload, timeout):
    data = json.dumps(payload).encode()
    req = urllib.request.Request(BASE + path, data=data,
                                 headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.time()
    with op.open(req, timeout=timeout) as r:
        body = r.read().decode()
    return time.time() - t0, body

el, body = post("/api/login", {"username": USER, "password": PWD}, 30)
print(f"登录 {el:.1f}s  {body[:80]}")
time.sleep(1)

for i in (1, 2):
    try:
        el, body = post("/api/ask", {"question": "Transformer 为什么比 RNN 更容易并行？", "top_k": 5}, 240)
        d = json.loads(body)
        marks = d.get("answer", "").count("[E")
        print(f"第{i}次问答 {el:.1f}s  回答长度 {len(d.get('answer',''))}  锚点数 {marks}  证据 {len(d.get('evidence') or [])} 条")
        print("   开头:", (d.get("answer") or "")[:120].replace("\n", " "))
    except Exception as e:
        print(f"第{i}次问答失败: {type(e).__name__}: {e}")
