"""FastAPI 服务层。

设计取舍：
* 解析与索引都是阻塞的 CPU 任务，直接放请求里会拖死事件循环，
  所以走 `run_in_threadpool`；
* 模型对象（向量/重排）在进程内单例缓存，避免每次请求重载；
* 问答结果连同锚点一起返回，前端据此在 PDF 上画高亮框。
"""
from __future__ import annotations

import shutil
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from .config import PDF_DIR
from .indexing import HybridRetriever, Store, build_chunks
from .llm import DeepSeekClient, ExtractiveLLM, has_key
from .parsing import parse_pdf, summary
from .rag import GroundedAnswerer

app = FastAPI(title="证源 Evidence API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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


class AskResponse(BaseModel):
    question: str
    answer: str
    grounded: bool
    insufficient: bool
    repaired: bool
    invalid_markers: list[int]
    citations: list[dict]


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


@app.post("/api/ask", response_model=AskResponse)
async def ask(req: AskRequest) -> AskResponse:
    state = get_state()
    result = await run_in_threadpool(state["answerer"].ask, req.question, req.top_k)
    return AskResponse(**result.to_dict())


@app.post("/api/ask/stream")
async def ask_stream(req: AskRequest) -> StreamingResponse:
    """SSE：先给答案，再给锚点，最后结束。

    说明：当前把整段答案作为一帧下发。接入真模型后改为逐 token 下发
    （DeepSeekClient.stream 已就绪），此处保留同一条事件协议，前端不用改。
    """
    state = get_state()

    async def gen():
        result = await run_in_threadpool(state["answerer"].ask, req.question, req.top_k)
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

