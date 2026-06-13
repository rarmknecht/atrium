from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/context", tags=["context"])


@router.get("/tree")
async def tree(request: Request) -> list[dict]:
    docs = await request.app.state.librarian.list_docs()
    return [d.model_dump(exclude={"body", "frontmatter"}) for d in docs]


@router.get("/doc")
async def get_doc(request: Request, path: str) -> dict:
    try:
        doc = await request.app.state.librarian.get(path, include_body=True)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return doc.model_dump()


class DocBody(BaseModel):
    path: str
    frontmatter: dict = Field(default_factory=dict)
    body: str = ""


@router.put("/doc")
async def put_doc(request: Request, payload: DocBody) -> dict:
    try:
        doc = await request.app.state.librarian.put(
            payload.path, payload.frontmatter, payload.body
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return doc.model_dump()


@router.delete("/doc", status_code=204)
async def delete_doc(request: Request, path: str) -> None:
    librarian = request.app.state.librarian
    try:
        await librarian.get(path, include_body=False)
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await librarian.delete(path)


class AskBody(BaseModel):
    query: str
    k: int = Field(default=5, ge=1, le=25)


@router.post("/ask")
async def ask(request: Request, payload: AskBody) -> list[dict]:
    hits = await request.app.state.librarian.ask(payload.query, k=payload.k)
    return [h.model_dump(exclude={"doc": {"body", "frontmatter"}}) for h in hits]


class RouteBody(BaseModel):
    task: str
    k: int = Field(default=4, ge=1, le=10)


@router.post("/route")
async def route(request: Request, payload: RouteBody) -> dict:
    bundle = await request.app.state.librarian.route(payload.task, k=payload.k)
    return bundle.model_dump()


@router.get("/graph")
async def graph(request: Request) -> dict:
    return request.app.state.indexer.graph_json()


@router.post("/reindex")
async def reindex(request: Request) -> dict:
    return await request.app.state.indexer.full_scan()
