**1. ListMaterialsBOQ:**

* desscription => tiếng Anh/tiếng Việt => thiếu Name => (...Có hình ảnh để lấy Name bằng tool)
* unit
* codeProject => thuộc dự án nào
* imageURL => f\_IDDocument => TABLE documentDMVT (...tự động chuyển URL ??) => a HÙng
* supplierSpecCDT => nhà cung cấp
* description


**2. MD\_Material\_SAP:**

* Des\_material\_Sap => material name
* Material\_Group => mãCODE 
* ID\_Material\_SAP => id\_SAP
* Base\_Unit =>
* image\_url => ??? có thì lấy


**3. materials\_qwen:** 

Các cột cần

* ID\_SAP => map materials cho Products
* material\_name
* material\_group => Danh sách phân loại theo MãCODE
* material\_subgroup => chạy code phân loại 
* material\_subprice => cần nhưng thông tin chưa có
* unit => lấy trực tiếp
* image\_url => link ggDrive


**Vấn đề:**

Cần phải chạy code xử lý material\_subgroup/material\_group(file Excel k có Table) => **bổ xung thêm cột NAME MATERIAL-GROUP**


Bảng TMP => không có liên kết với bảng vetor embedding ????

1. &nbsp;	=> **VIEW +** **materials\_qwen** có cột material\_name

=> lưu thêm Hash(material\_name)=> tương tự như password (vừa tìm được phần tử trùng nhau truy xuất dữ liệu mau)

=> name thay đổi => cột lưu hash phải thay đổi theo

=> api trigger thay đổi name => thêm

...


2. bỏ	=> tạo UUI gắn vào **VIEW +** **materials\_qwen** (mau, dễ dàng tìm kiếm, mất VIEW mất luôn UUI)

Viết service bao gồm:

* viết bảng VIEW postgres
* xử lý material\_group + material\_subgroup , desscription tách Name, thiếu Name
* start khi mất VIEW





--------------

Họp

tên vật tư => có thể dùng gemine => xem bảng gemini-lite trước

Giá chưa có => 

button xem **tổng hợp** lại các ... được chọn

show danh sách lấy lại sản phẩm đã chọn review lại trước => OK => xuất file

.

thông tin gemni + research => thông tin SAP + Ứng dụng => thông tin chung

merge 2 thông tin chung 1 bên SAP + 1 bên ứng dụng => 2 màn hình/table => VIEW 

=> giải pháp merge nêu không cho người dùng tích chọn 

=> merge lại lần đầu tiên => cờ danh mục vật tư tương ứng mã SAP nào

=> lần sau vào đã merge chung => trở thành 

.

thông tin SAP => 1 list dự án

Ứng dụng => material tương ứng dự án nào

=> so sánh trùng dự án nào???



























