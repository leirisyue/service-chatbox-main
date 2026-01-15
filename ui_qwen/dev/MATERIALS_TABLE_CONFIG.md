# Cấu hình tên bảng Materials

## Tổng quan
Tên bảng `materials_qwen` đã được chuyển thành biến cấu hình trong file `config.py` để dễ dàng thay đổi tên bảng mà không ảnh hưởng đến toàn bộ project.

## Cách sử dụng

### 1. Thay đổi tên bảng
Để thay đổi tên bảng materials, chỉ cần cập nhật giá trị trong file [config.py](config.py):

```python
class Settings(BaseSettings):
    # ...
    
    # Table names
    MATERIALS_TABLE: str = "materials_qwen"  # Thay đổi giá trị này
```

Ví dụ, để đổi tên bảng thành `materials_v2`:
```python
MATERIALS_TABLE: str = "materials_v2"
```

### 2. Sử dụng biến môi trường
Bạn cũng có thể cấu hình qua file `.env`:

```env
MATERIALS_TABLE=materials_v2
```

### 3. Các file đã được cập nhật
Các file sau đã được cập nhật để sử dụng biến cấu hình `settings.MATERIALS_TABLE`:

- [chatapi/textapi_qwen.py](chatapi/textapi_qwen.py)
- [chatapi/textfunc.py](chatapi/textfunc.py)
- [chatapi/importapi.py](chatapi/importapi.py)
- [chatapi/embeddingapi.py](chatapi/embeddingapi.py)
- [chatapi/debugapi.py](chatapi/debugapi.py)
- [chatapi/classifyapi.py](chatapi/classifyapi.py)

## Lưu ý quan trọng

1. **Sau khi thay đổi tên bảng**, đảm bảo rằng:
   - Bảng mới đã tồn tại trong database
   - Cấu trúc bảng giống với bảng cũ
   - Dữ liệu đã được migrate (nếu cần)

2. **Khởi động lại ứng dụng** sau khi thay đổi cấu hình để các thay đổi có hiệu lực.

3. **File backup không được cập nhật** - các file trong thư mục `backup/` vẫn sử dụng tên bảng cố định `materials_qwen`.

## Ví dụ migrate dữ liệu

Nếu bạn muốn đổi tên bảng trong PostgreSQL:

```sql
-- Cách 1: Rename bảng
ALTER TABLE materials_qwen RENAME TO materials_v2;

-- Cách 2: Tạo bảng mới và copy dữ liệu
CREATE TABLE materials_v2 AS SELECT * FROM materials_qwen;
```
