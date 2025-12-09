# RAG Chatbot Service — Bản sửa lỗi chọn bảng theo schema

## Sửa lỗi pgvector
- Thêm ép kiểu `%s::vector` trong câu lệnh SQL để toán tử `<=>` hoạt động với kiểu `vector` thay vì `double precision[]`.
- Rollback transaction khi câu lệnh lỗi để tránh `current transaction is aborted`.

## Chọn đúng 1 bảng bằng mô tả schema
- Module `app/table_selector.py` cho phép mô tả từng bảng bằng `description`. Service sẽ nhúng mô tả này và chọn bảng có cosine similarity cao nhất với câu hỏi.
- Sau khi chọn bảng, service chỉ truy vấn bảng đó, giảm thời gian so với việc truy vấn tất cả các bảng.

### Cấu hình mô tả bảng
- Qua biến môi trường `APP_TABLE_SCHEMAS_JSON` (JSON array).
- Hoặc chỉnh sửa danh sách mặc định trong `table_selector.py`.

Ví dụ `.env`:
```
APP_TABLE_SCHEMAS_JSON=[{"schema":"public","table":"customers","description":"Thông tin khách hàng, hồ sơ, liên hệ, lịch sử tương tác."},{"schema":"public","table":"products","description":"Thông tin sản phẩm, mô tả, tính năng, giá, tồn kho."},{"schema":"public","table":"orders","description":"Đơn hàng, trạng thái, chi tiết mua, thanh toán, vận chuyển."}]
```

## API không đổi
- `POST /query`: nhận `text` + `files[]` (ảnh). Service sẽ OCR ảnh, hợp nhất text, chọn bảng theo schema, sau đó similarity search trong bảng đó.
- `GET /health`
- `GET /documents/count`

## Ghi chú
- Đảm bảo Postgres đã cài `pgvector` và cột `embedding` là kiểu `vector`.
- Nếu chiều vector khác, cần đảm bảo `nomic-embed-text:latest` tương thích hoặc chuyển đổi cùng chiều khi lưu vào DB.