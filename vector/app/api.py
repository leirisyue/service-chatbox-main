from fastapi import FastAPI, BackgroundTasks, Query
from typing import Optional, List

from .db import get_origin_tables
from .main import process_table
from .logger import setup_logger

logger = setup_logger(__name__)

app = FastAPI(
    title="RAG Vector Builder API",
    version="1.0.0"
)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/tables", response_model=List[str])
def list_tables():
    """
    Lấy danh sách bảng trong origin DB
    """
    return get_origin_tables()


@app.post("/process/table/{table_name}")
def process_single_table(
    table_name: str,
    background_tasks: BackgroundTasks,
    limit: Optional[int] = Query(None),
    batch_size: int = Query(50)
):
    """
    Xử lý embedding cho 1 table
    """
    logger.info("API request: process table %s", table_name)

    background_tasks.add_task(
        process_table,
        table_name,
        limit,
        batch_size
    )

    return {
        "status": "accepted",
        "table": table_name,
        "limit": limit,
        "batch_size": batch_size
    }


@app.post("/process/all")
def process_all_tables(
    background_tasks: BackgroundTasks,
    limit: Optional[int] = Query(None)
):
    """
    Xử lý toàn bộ tables
    """
    tables = get_origin_tables()
    for tbl in tables:
        background_tasks.add_task(process_table, tbl, limit)

    return {
        "status": "accepted",
        "tables": tables,
        "limit": limit
    }
  