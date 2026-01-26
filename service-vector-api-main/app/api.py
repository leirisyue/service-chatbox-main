from fastapi import FastAPI, BackgroundTasks, HTTPException
from typing import Optional

from .service import process_table, run_all_tables, insert_records,update_records
from .db import get_origin_tables

from .schema import UpsertRequest

app = FastAPI(title="RAG Vector Build API")   

@app.get("/health")
def health():
    return {"status": "ok"}

@app.get("/tables")
def tables():
    return {"tables": get_origin_tables()}

@app.post("/build/all")
def build_all(background_tasks: BackgroundTasks):
    background_tasks.add_task(run_all_tables)
    return {"message": "Build all started"}

# theo từng page
@app.post("/build/table/{table_name}")
def build_table(
    table_name: str,
    background_tasks: BackgroundTasks,
    limit: Optional[int] = None,
    batch_size: int = 50,
):
    background_tasks.add_task(process_table, table_name, limit, batch_size)
    return {"message": "Build table started", "table": table_name}


@app.post("/sync/{table_name}/insert")
def sync_data(table_name: str, req: UpsertRequest):
    records = req.data
    if isinstance(records, dict):
        records = [records]
    if not records:
        raise HTTPException(status_code=400, detail="Empty data")
    insert_records(table_name, records)
    return {
        "message": "Data synced successfully",
        "table": table_name,
        "count": len(records),
    }


@app.post("/sync/{table_name}/update")
def update_data(table_name: str, req: UpsertRequest):
    record = req.data
    # Cho phép client gửi 1 object hoặc list chứa đúng 1 object
    if isinstance(record, list):
        if not record:
            raise HTTPException(status_code=400, detail="Empty data")
        if len(record) != 1:
            raise HTTPException(
                status_code=400,
                detail="Only one record is allowed for update",
            )
        record = record[0]

    if not record or not isinstance(record, dict):
        raise HTTPException(status_code=400, detail="Invalid record format")

    update_records(table_name, [record])
    return {
        "message": "Record updated successfully",
        "table": table_name,
        "count": 1,
    }
