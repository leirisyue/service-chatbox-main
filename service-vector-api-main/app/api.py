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
    # Validate list_key
    raw_list_key = req.list_key
    if not raw_list_key or not isinstance(raw_list_key, list):
        raise HTTPException(status_code=400, detail="list_key is required and must be a list")

    # Lưu cả key name và value
    prioritized_keys: List[Dict[str, Any]] = []

    for idx, item in enumerate(raw_list_key):
        if not isinstance(item, dict):
            raise HTTPException(
                status_code=400,
                detail=f"list_key[{idx}] must be an object, e.g. {{\"id_sap\": \"123\"}}",
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
        key_value = item[key_name]
        prioritized_keys.append({"name": str(key_name), "value": key_value})

    records = req.data

    # Chuẩn hóa cho phép 1 object hoặc list object
    if isinstance(records, dict):
        records_list: List[Dict[str, Any]] = [records]
    else:
        records_list = records or []

    if not records_list:
        raise HTTPException(status_code=400, detail="Empty data")

    normalized_records: List[Dict[str, Any]] = []

    for idx, rec in enumerate(records_list):
        if not isinstance(rec, dict):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid record format at index {idx}",
            )

        current = rec.copy()
        resolved_id_sap = None
        # Case 1: Record đã có sẵn id_sap → dùng luôn
        if "id_sap" in current and current["id_sap"] is not None:
            resolved_id_sap = current["id_sap"]
        
        # Case 2: Không có id_sap → dùng list_key để tìm
        else:
            # Duyệt theo thứ tự ưu tiên trong list_key
            for key_info in prioritized_keys:
                key_name = key_info["name"]
                key_value = key_info["value"]
                # Bỏ qua nếu value null/empty
                if key_value is None or str(key_value).strip() == "":
                    continue
                # Xử lý key id_sap
                if key_name == "id_sap":
                    resolved_id_sap = key_value
                    break
                # Xử lý key material_name / name_material
                elif key_name in ("material_name", "name_material"):
                    material_name = str(key_value)
                    
                    # Tra id_sap từ bảng gốc bằng material_name
                    resolved_id_sap = get_id_sap_by_material_name(
                        table_name,
                        material_name
                    )
                    if resolved_id_sap is not None:
                        # Tìm thấy → dừng lại
                        break
                    # Không tìm thấy → thử key tiếp theo
                # Key khác (có thể mở rộng)
                else:
                    # TODO: Implement logic cho key khác nếu cần
                    continue
        # Kiểm tra đã resolve được id_sap chưa
        if resolved_id_sap is None:
            # Tạo thông báo chi tiết
            tried_keys = [f"{k['name']}={k['value']}" for k in prioritized_keys]
            raise HTTPException(
                status_code=404,
                detail=(
                    f"Record {idx}: Could not find matching record in table '{table_name}' "
                    f"using list_key: {tried_keys}"
                ),
            )

        # Gán id_sap vào record để update
        current["id_sap"] = resolved_id_sap

        normalized_records.append(current)

    # Gọi logic update
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
