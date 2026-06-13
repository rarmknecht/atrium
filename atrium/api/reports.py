from fastapi import APIRouter, HTTPException, Request

router = APIRouter(prefix="/api/reports", tags=["reports"])


@router.get("")
async def list_reports(
    request: Request,
    module_id: str | None = None,
    kind: str | None = None,
    since: str | None = None,   # ISO date/datetime lower bound
    limit: int = 50,
) -> list[dict]:
    clauses, args = [], []
    if module_id:
        clauses.append("module_id = ?")
        args.append(module_id)
    if kind:
        clauses.append("kind = ?")
        args.append(kind)
    if since:
        clauses.append("created_at >= ?")
        args.append(since)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    sql = f"SELECT * FROM reports {where} ORDER BY created_at DESC LIMIT ?"
    args.append(min(max(limit, 1), 500))
    async with request.app.state.db.execute(sql, args) as cur:
        return [dict(row) for row in await cur.fetchall()]


@router.get("/{report_id}")
async def get_report(request: Request, report_id: str) -> dict:
    async with request.app.state.db.execute(
        "SELECT * FROM reports WHERE id = ?", (report_id,)
    ) as cur:
        row = await cur.fetchone()
    if row is None:
        raise HTTPException(404, f"unknown report {report_id!r}")
    return dict(row)
