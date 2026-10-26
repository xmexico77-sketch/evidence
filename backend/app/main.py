"""FastAPI 服务层。

设计取舍：
* 解析与索引都是阻塞的 CPU 任务，直接放请求里会拖死事件循环，
  所以走 `run_in_threadpool`；
* 模型对象（向量/重排）在进程内单例缓存，避免每次请求重载；
* 问答结果连同锚点一起返回，前端据此在 PDF 上画高亮框。
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .auth import (
    COOKIE_NAME,
    TOKEN_TTL,
    auth_enabled,
    check_password,
    create_token,
    is_public,
    token_from_request,
    users,
    verify_token,
)

from .config import DATA_DIR, INDEX_DIR, PDF_DIR
from .discovery import fetch as fetch_arxiv
from .discovery.recommend import ingest as ingest_discovery
from .discovery.recommend import recommend
from .graph import (
    build_graph,
    compute_metrics,
    rank_derivative,
    rank_foundational,
    to_cytoscape,
)
from .graph.future import (
    assess_items,
    cluster_items,
    extract_future_work,
    summarize_order,
)
from .graph.review import build_area_reviews
from .indexing import HybridRetriever, Store, build_chunks
from .llm import DeepSeekClient, ExtractiveLLM, Message, has_key
from .llm.prompts import CROSS_PAPER_COMPARE, TRANSLATE_PARAGRAPH
from .parsing import parse_pdf, summary
from .rag import GroundedAnswerer
from .rag.answerer import Evidence, validate_markers
from .writing import build_chart
from .writing.framework import build_framework, to_mermaid

app = FastAPI(title="证源 Evidence API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

SAMPLE_DIR = DATA_DIR / "samples"
FIGURES_DIR = DATA_DIR / "figures"
FIGURES_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/figures", StaticFiles(directory=str(FIGURES_DIR)), name="figures")

_state: dict = {}


def get_state() -> dict:
    """进程内单例：存储、检索器、问答器。"""
    if "store" not in _state:
        store = Store()
        retriever = HybridRetriever(store)
        retriever.build_bm25()
        llm = DeepSeekClient() if has_key() else ExtractiveLLM()
        _state.update(
            {
                "store": store,
                "retriever": retriever,
                "llm": llm,
                "answerer": GroundedAnswerer(retriever, llm),
            }
        )
    return _state


def reset_state() -> None:
    """索引变更后丢弃缓存，下次请求重建。"""
    store = _state.pop("store", None)
    if store is not None:
        store.close()
    _state.clear()


class SearchHit(BaseModel):
    chunk_id: str
    text: str
    section_path: str
    score: float
    anchor: dict


class AskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    top_k: int = Field(default=5, ge=1, le=12)
    # 可选：把问题限定在某篇论文内。库大了之后同一个问题可能有多个合理答案，
    # 不限定范围就会答成另一篇论文的数值——技术上不错，但不是用户问的。
    paper_id: str | None = None


class AskResponse(BaseModel):
    question: str
    answer: str
    grounded: bool
    insufficient: bool
    repaired: bool
    invalid_markers: list[int]
    citations: list[dict]
    # 前端用它显示置信度并做"低相关度"提示，漏掉会导致页面崩溃
    confidence: float = 0.0


@app.middleware("http")
async def auth_guard(request: Request, call_next):
    """统一鉴权：AUTH_ENABLED=0 时完全放行，便于本地开发与离线演示。"""
    if not auth_enabled() or is_public(request.url.path):
        return await call_next(request)

    token = token_from_request(dict(request.headers), request.cookies)
    user = verify_token(token) if token else None
    if user is None:
        return JSONResponse({"detail": "未登录或会话已过期"}, status_code=401)

    response = await call_next(request)
    response.headers["X-Evidence-User"] = user
    return response


class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=1, max_length=128)


@app.post("/api/login")
def login(req: LoginRequest) -> JSONResponse:
    if not check_password(req.username, req.password):
        raise HTTPException(401, "账号或密码错误")
    token = create_token(req.username)
    payload = JSONResponse({"ok": True, "user": req.username, "token": token})
    payload.set_cookie(
        COOKIE_NAME,
        token,
        max_age=TOKEN_TTL,
        httponly=True,
        samesite="lax",
        path="/",
    )
    return payload


@app.post("/api/logout")
def logout() -> JSONResponse:
    payload = JSONResponse({"ok": True})
    payload.delete_cookie(COOKIE_NAME, path="/")
    return payload


@app.get("/api/me")
def me(request: Request) -> dict:
    if not auth_enabled():
        return {"user": "anonymous", "auth_enabled": False}
    token = token_from_request(dict(request.headers), request.cookies)
    return {
        "user": verify_token(token) if token else None,
        "auth_enabled": True,
        "users": sorted(users()),
    }


@app.get("/api/health")
def health() -> dict:
    state = get_state()
    return {
        "ok": True,
        "llm": "deepseek" if has_key() else "extractive-fallback",
        "chunks": len(state["retriever"].chunks),
    }


@app.get("/api/papers")
def list_papers() -> dict:
    state = get_state()
    return {"papers": state["store"].list_papers()}


@app.post("/api/papers")
async def upload_paper(file: UploadFile = File(...)) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "只接受 PDF 文件")

    dest = PDF_DIR / Path(file.filename).name
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)

    def _ingest() -> dict:
        paper = parse_pdf(dest)
        chunks = build_chunks(paper)
        store = get_state()["store"]
        store.upsert_paper(paper, chunks)
        reset_state()
        state = get_state()
        state["retriever"].build_bm25()
        embedded = state["retriever"].embed_missing()
        return {
            **summary(paper),
            "chunks": len(chunks),
            "embedded": embedded,
        }

    try:
        return await run_in_threadpool(_ingest)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"解析失败: {exc}") from exc


@app.get("/api/papers/{paper_id}/outline")
def paper_outline(paper_id: str) -> dict:
    """标题树：阅读器左侧导航。"""
    store = get_state()["store"]
    if store.get_paper(paper_id) is None:
        raise HTTPException(404, "论文不存在")
    return {"outline": store.load_outline(paper_id)}


@app.get("/api/papers/{paper_id}/references")
def paper_references(paper_id: str) -> dict:
    store = get_state()["store"]
    if store.get_paper(paper_id) is None:
        raise HTTPException(404, "论文不存在")
    return {"references": store.load_references(paper_id)}


@app.get("/api/papers/{paper_id}/blocks")
def paper_blocks(paper_id: str) -> dict:
    """按页分组的段落 bbox，供前端画定位层。"""
    store = get_state()["store"]
    if store.get_paper(paper_id) is None:
        raise HTTPException(404, "论文不存在")
    pages = store.load_pages_blocks(paper_id)
    return {"pages": {str(k): v for k, v in pages.items()}}


class ChartResponse(BaseModel):
    kind: str
    png: str
    svg: str
    script: str
    caption: str
    reason: str
    stats: dict


@app.post("/api/charts", response_model=ChartResponse)
async def make_chart(file: UploadFile = File(...)) -> ChartResponse:
    """上传 CSV，自动选图型、出学术图、给图注与可复现脚本。"""
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "只接受 CSV 文件")
    stem = Path(file.filename).stem or "chart"
    dest = SAMPLE_DIR / f"{stem}.csv"
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    with dest.open("wb") as fh:
        shutil.copyfileobj(file.file, fh)

    def _run():
        llm = get_state()["llm"] if has_key() else None
        return build_chart(dest, stem=stem, llm=llm)

    try:
        result = await run_in_threadpool(_run)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"绘图失败: {exc}") from exc

    return ChartResponse(
        kind=result.kind,
        png=result.png,
        svg=result.svg,
        script=result.script,
        caption=result.caption,
        reason=result.spec.reason,
        stats=result.stats,
    )


class FeedbackRequest(BaseModel):
    id: str
    verdict: int = Field(ge=-1, le=1)


class IngestRequest(BaseModel):
    arxiv_id: str


@app.get("/api/discover")
async def discover(
    q: str | None = None,
    category: str = "cs.CL",
    limit: int = 8,
    enrich: bool = True,
) -> dict:
    """检索或追踪论文，按相关度+可复现性+偏好排序。"""
    store = get_state()["store"]

    def _run():
        items = recommend(
            store, query=q, category=category, limit=limit, enrich=enrich
        )
        store.save_discoveries(items)
        return items

    try:
        items = await run_in_threadpool(_run)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"外部检索失败: {exc}") from exc
    return {"items": items, "mode": "search" if q else "track", "category": category}


@app.get("/api/discover/list")
def discover_list(limit: int = 20) -> dict:
    return {"items": get_state()["store"].list_discoveries(limit)}


@app.post("/api/discover/feedback")
def discover_feedback(req: FeedbackRequest) -> dict:
    store = get_state()["store"]
    store.set_feedback(req.id, req.verdict)
    return {"ok": True, "feedback": store.load_feedback()}


@app.post("/api/discover/ingest")
async def discover_ingest(req: IngestRequest) -> dict:
    """智能下钻：下载 PDF -> 解析 -> 分块 -> 入库。"""
    store = get_state()["store"]

    def _run():
        paper = fetch_arxiv(req.arxiv_id)
        if paper is None:
            raise HTTPException(404, f"arXiv 未找到 {req.arxiv_id}")
        info = ingest_discovery(store, paper, PDF_DIR, build_chunks, parse_pdf)
        reset_state()  # 索引变了，重建检索器缓存
        st = get_state()
        st["retriever"].build_bm25()
        embedded = st["retriever"].embed_missing()
        return {**info, "embedded": embedded}

    try:
        return await run_in_threadpool(_run)
    except HTTPException:
        raise
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"下钻失败: {exc}") from exc


@app.get("/api/graph")
def citation_graph() -> dict:
    """局域引用图谱：节点/边 + 基石榜 + 边缘衍生。"""
    store = get_state()["store"]
    g, works = build_graph(store)
    works = compute_metrics(g, works)
    payload = to_cytoscape(works, g)

    def node_row(w) -> dict:  # noqa: ANN001
        return {
            "key": w.key,
            "title": w.title,
            "year": w.year,
            "pagerank": round(w.pagerank, 5),
            "sustained": w.sustained,
            "foundational": round(w.foundational, 5),
            "betweenness": round(w.betweenness, 5),
            "community": w.community,
            "members": w.members,
        }

    payload["foundational"] = [node_row(w) for w in rank_foundational(works, 6)]
    payload["derivative"] = [node_row(w) for w in rank_derivative(works, 5)]
    payload["communities"] = sorted({w.community for w in works.values() if w.community >= 0})
    return payload


@app.get("/api/graph/review")
def area_reviews(refresh: bool = False, use_llm: bool = True) -> dict:
    """自动综述 + Idea 考古。

    这个计算要跑几十秒（37 条 Future Work 各做一次检索+重排），
    所以结果按"库指纹"落盘缓存，只有库变了或显式 refresh 才重算。

    有模型时（use_llm=True 且配置了 Key）综述写成叙述性文字、
    Idea 判定也交给模型；缓存的指纹里带上这个标志，
    否则先算的启发式结果会一直顶着不回。
    """
    store = get_state()["store"]
    llm = get_state()["llm"] if (use_llm and has_key()) else None
    fingerprint = json.dumps(
        {
            "papers": len(store.list_papers()),
            "chunks": len(store.load_chunks()),
            "llm": bool(llm),
        },
        sort_keys=True,
    )
    import hashlib

    key = hashlib.sha1(fingerprint.encode()).hexdigest()[:12]
    cache_path = INDEX_DIR / "review_cache.json"
    if not refresh and cache_path.exists():
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("key") == key:
                return cached["payload"]
        except Exception:  # noqa: BLE001 —— 缓存损坏就当没有
            pass

    g, works = build_graph(store)
    works = compute_metrics(g, works)
    reviews = build_area_reviews(works, store, llm=llm)

    year_by_paper: dict[str, int] = {}
    for w in works.values():
        for pid in w.members:
            year_by_paper[pid] = w.year

    retriever = get_state()["retriever"]
    items = extract_future_work(store, year_by_paper)
    cluster_items(items)
    assess_items(items, retriever, year_by_paper, llm=llm)
    open_items = summarize_order(items, 6)

    payload = {
        "reviews": [
            {
                "community": r.community,
                "theme": r.theme,
                "year_range": r.year_range,
                "members": r.members,
                "summary": r.summary,
                "method": r.method,
            }
            for r in reviews
        ],
        "open_ideas": [
            {
                "id": it.id,
                "paper_id": it.paper_id,
                "year": it.year,
                "page": it.page,
                "text": it.text,
                "status": it.status,
                "score": it.score,
                "mentions": sum(1 for x in items if x.cluster == it.cluster),
            }
            for it in open_items
        ],
        "total_ideas": len(items),
    }
    cache_path.write_text(
        json.dumps({"key": key, "payload": payload}, ensure_ascii=False), encoding="utf-8"
    )
    return payload


class WriteRequest(BaseModel):
    idea: str = Field(min_length=4, max_length=400)
    use_llm: bool = True


@app.post("/api/write")
async def write_framework(req: WriteRequest) -> dict:
    """Idea → 论文框架（章节 + 真实可核实引用 + 拓扑图）。"""
    state = get_state()
    retriever = state["retriever"]
    llm = state["llm"] if (req.use_llm and has_key()) else None

    def _run():
        fw = build_framework(req.idea, state["store"], retriever, llm=llm)
        return {**fw.to_dict(), "mermaid": to_mermaid(fw), "markdown": fw.to_markdown()}

    try:
        return await run_in_threadpool(_run)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(400, f"框架生成失败: {exc}") from exc


@app.get("/api/papers/{paper_id}/paragraphs")
def paper_paragraphs(paper_id: str) -> dict:
    """段落级正文 + 坐标，双语侧栏与联动滚动用。"""
    store = get_state()["store"]
    if store.get_paper(paper_id) is None:
        raise HTTPException(404, "论文不存在")
    return {"paragraphs": store.load_paragraphs(paper_id)}


class TranslateRequest(BaseModel):
    paper_id: str
    lang: str = "zh"
    block_ids: list[str] | None = None
    limit: int = Field(default=25, ge=1, le=60)


@app.post("/api/translate")
def translate(req: TranslateRequest) -> dict:
    """段落翻译（带缓存）。

    未配置模型时明确返回 enabled=false，前端显示提示而不是编造译文——
    伪造翻译比不给翻译更糟。
    """
    store = get_state()["store"]
    if store.get_paper(req.paper_id) is None:
        raise HTTPException(404, "论文不存在")

    if not has_key():
        return {
            "enabled": False,
            "translations": {},
            "reason": "未配置 DEEPSEEK_API_KEY，不生成译文",
        }

    paragraphs = store.load_paragraphs(req.paper_id)
    if req.block_ids:
        wanted = set(req.block_ids)
        paragraphs = [p for p in paragraphs if p["id"] in wanted]

    cached = store.load_translations(req.paper_id, req.lang)
    todo = [p for p in paragraphs if p["id"] not in cached and p["text"].strip()][: req.limit]

    client = get_state()["llm"]
    fresh: dict[str, str] = {}
    for para in todo:
        messages = [
            _msg(role, content)
            for role, content in TRANSLATE_PARAGRAPH.render(paragraph=para["text"][:1800])
        ]
        try:
            fresh[para["id"]] = client.chat(messages).strip()
        except Exception:  # noqa: BLE001 —— 单段失败不应中断整批
            continue

    store.save_translations(req.paper_id, req.lang, fresh)
    merged = {**cached, **fresh}
    return {
        "enabled": True,
        "translations": merged,
        "translated": len(fresh),
        "pending": max(0, len(paragraphs) - len(merged)),
    }


@app.get("/api/papers/{paper_id}/file")
def paper_file(paper_id: str) -> FileResponse:
    """把原始 PDF 交给前端 PDF.js 渲染。"""
    store = get_state()["store"]
    meta = store.get_paper(paper_id)
    if meta is None or not meta["filename"]:
        raise HTTPException(404, "论文不存在")
    path = PDF_DIR / Path(meta["filename"]).name
    if not path.exists():
        raise HTTPException(404, f"PDF 文件缺失: {path.name}")
    return FileResponse(path, media_type="application/pdf", filename=path.name)


@app.post("/api/search", response_model=list[SearchHit])
async def search(req: AskRequest) -> list[SearchHit]:
    state = get_state()

    def _run() -> list[SearchHit]:
        hits = state["retriever"].search(req.question, top_k=req.top_k)
        return [
            SearchHit(
                chunk_id=h["id"],
                text=h["text"][:600],
                section_path=h["section_path"],
                score=h["score"],
                anchor=h["anchor"],
            )
            for h in hits
        ]

    return await run_in_threadpool(_run)


class CompareRequest(BaseModel):
    dimension: str = Field(min_length=2, max_length=200)
    paper_ids: list[str] = Field(min_length=2, max_length=2)
    top_k: int = Field(default=4, ge=1, le=8)


@app.post("/api/compare")
async def compare_papers(req: CompareRequest) -> dict:
    """跨论文对比：两篇论文沿同一维度对齐，输出带证据的 Markdown 表格。

    赛题点名"多篇论文跨文献对比（承袭与抛弃关系、参数量演化等）"。
    这里强制每格标注来源编号，并复用问答链路的标记校验：
    引用了不存在的编号即判不可信，不把编造内容当结论返回。
    """
    state = get_state()
    if not has_key():
        raise HTTPException(400, "跨论文对比需要配置模型")

    store = state["store"]
    for pid in req.paper_ids:
        if store.get_paper(pid) is None:
            raise HTTPException(404, f"论文不存在: {pid}")

    retriever = state["retriever"]

    def _run() -> dict:
        evidence: list[Evidence] = []
        for pid in req.paper_ids:
            hits = retriever.search(req.dimension, top_k=req.top_k, paper_filter={pid})
            for h in hits:
                evidence.append(Evidence(index=len(evidence) + 1, chunk=h))
        if not evidence:
            return {
                "answer": "证据不足：两篇论文中都没有与该维度相关的内容。",
                "grounded": False,
                "citations": [],
                "invalid_markers": [],
            }

        ev_text = "\n".join(
            f"[E{e.index}] {e.chunk['paper_id']} · p{e.chunk['page_start']} · "
            f"§{e.chunk.get('section_title') or '正文'}\n{e.chunk['text'][:600]}"
            for e in evidence
        )
        messages = [
            Message(role=role, content=content)
            for role, content in CROSS_PAPER_COMPARE.render(
                dimension=req.dimension, evidence=ev_text
            )
        ]
        answer = state["llm"].chat(messages).strip()
        valid, invalid = validate_markers(answer, evidence)
        citations = [
            {
                "marker": f"[E{i}]",
                "anchor": evidence[i - 1].anchor,
                "snippet": evidence[i - 1].chunk["text"][:200],
            }
            for i in valid
        ]
        return {
            "answer": answer,
            "grounded": bool(valid),
            "citations": citations,
            "invalid_markers": invalid,
            "dimension": req.dimension,
            "paper_ids": req.paper_ids,
        }

    return await run_in_threadpool(_run)


@app.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    state = get_state()
    scope = {req.paper_id} if req.paper_id else None
    result = await run_in_threadpool(state["answerer"].ask, req.question, req.top_k, scope)
    return AskResponse(**result.to_dict())


@app.post("/api/ask/stream")
async def ask_stream(req: AskRequest) -> StreamingResponse:
    """SSE：先给答案，再给锚点，最后结束。

    说明：当前把整段答案作为一帧下发。接入真模型后改为逐 token 下发
    （DeepSeekClient.stream 已就绪），此处保留同一条事件协议，前端不用改。
    """
    state = get_state()
    scope = {req.paper_id} if req.paper_id else None

    async def gen():
        result = await run_in_threadpool(
            state["answerer"].ask, req.question, req.top_k, scope
        )
        yield _sse({"type": "answer", "delta": result.answer})
        yield _sse(
            {
                "type": "citations",
                "grounded": result.grounded,
                "insufficient": result.insufficient,
                "repaired": result.repaired,
                "invalid_markers": result.invalid_markers,
                "citations": result.citations,
            }
        )
        yield _sse({"type": "done"})

    return StreamingResponse(gen(), media_type="text/event-stream")


def _sse(payload: dict) -> str:
    import json

    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


def _msg(role: str, content: str) -> Message:
    return Message(role=role, content=content)

