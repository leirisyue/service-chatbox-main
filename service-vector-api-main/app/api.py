from fastapi import FastAPI, BackgroundTasks, HTTPException
from typing import Optional, List, Dict, Any
from sqlalchemy import text

from .service import process_table, run_all_tables, insert_records, update_records
from .db import get_origin_tables, get_id_sap_by_material_name
from .db import target_engine as engine  # <-- use target_engine

from .schema import UpsertRequest, UpdateByKeysRequest

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


@app.post("/sync/{table_name}/update/keys")
def update_data_by_keys(
    table_name: str,
    req: UpdateByKeysRequest,
):
    """Update record(s) using required list_key.

        - list_key là danh sách object theo thứ tự ưu tiên, ví dụ:
            [
                {"id_sap": 123},
                {"material_name": "gỗ"}
            ]
    - Nếu record có `id_sap` thì dùng luôn.
    - Nếu không có `id_sap` nhưng có `material_name` / `name_material`,
      sẽ tra `id_sap` từ bảng gốc rồi update.
    """

    # Chuẩn hóa list_key: lấy ra danh sách tên key theo thứ tự ưu tiên
    raw_list_key = req.list_key
    if not raw_list_key:
        raise HTTPException(status_code=400, detail="list_key is required and cannot be empty")

    prioritized_keys: List[str] = []

    for idx, item in enumerate(raw_list_key):
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=400,
                detail=f"list_key[{idx}] must be an object, e.g. {{\"id_sap\": 123}}",
            )
        if not item:
            raise HTTPException(
                status_code=400,
                detail=f"list_key[{idx}] object cannot be empty",
            )
        if len(item) != 1:
            raise HTTPException(
                status_code=400,
                detail=f"list_key[{idx}] must contain exactly one key",
            )

        key_name = next(iter(item.keys()))
        prioritized_keys.append(str(key_name))

    records = req.data

    # Chuẩn hóa cho phép 1 object hoặc list object
    if isinstance(records, dict):
        records_list: List[Dict[str, Any]] = [records]
    else:
        records_list = records or []

    if not records_list:
        raise HTTPException(status_code=400, detail="Empty data")

    normalized_records: List[Dict[str, Any]] = []

    for idx, rec in enumerate(records_list, start=1):
        if not isinstance(rec, dict):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid record format at index {idx - 1}",
            )

        current = rec.copy()

        # Map name_material -> material_name nếu client dùng key này
        if "material_name" not in current and "name_material" in current:
            current["material_name"] = current["name_material"]

        used_key = None

        # Duyệt theo thứ tự ưu tiên trong list_key (đã chuẩn hóa)
        for key in prioritized_keys:
            # Ưu tiên id_sap nếu có sẵn trong record
            if key == "id_sap" and current.get("id_sap") is not None:
                used_key = "id_sap"
                break

            # Sử dụng material_name / name_material để truy vấn ra id_sap
            if key in ("material_name", "name_material"):
                material_name = current.get("material_name") or current.get("name_material")
                if material_name is None:
                    continue

                id_sap = get_id_sap_by_material_name(table_name, str(material_name))
                if id_sap is None:
                    raise HTTPException(
                        status_code=404,
                        detail=(
                            f"No record found in table '{table_name}' "
                            f"with material_name='{material_name}'"
                        ),
                    )

                current["id_sap"] = id_sap
                used_key = key
                break

        if used_key is None:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"Record at index {idx - 1} does not contain any "
                    f"supported key from list_key: {prioritized_keys}"
                ),
            )

        normalized_records.append(current)

    # Gọi lại logic update cũ
    update_records(table_name, normalized_records)

    return {
        "message": "Records updated successfully",
        "table": table_name,
        "count": len(normalized_records),
    }


@app.get("/db/health")
def db_health():
    try:
        with engine.connect() as conn:
            v = conn.execute(text("SELECT 1")).scalar()
        return {"db": "ok", "select_1": v}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"DB connection failed: {type(e).__name__}: {e}")
