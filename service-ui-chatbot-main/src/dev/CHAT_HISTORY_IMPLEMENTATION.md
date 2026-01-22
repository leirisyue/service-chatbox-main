# Tích hợp Lịch sử Trò chuyện vào Sidebar

## 📋 Tổng quan
Đã cập nhật Sidebar để hiển thị lịch sử trò chuyện từ bảng `chat_histories` trong database.

## ✅ Các thay đổi đã thực hiện

### 1. **API Service** (`src/services/api.js`)
Đã thêm 2 API endpoints mới:

```javascript
// Lấy danh sách tất cả sessions của user
export const getChatSessions = async () => {
  const response = await api.get('/chat-history/sessions');
  return response.data;
};

// Lấy lịch sử chat của một session cụ thể
export const getSessionHistory = async (sessionId) => {
  const response = await api.get(`/chat-history/session/${sessionId}`);
  return response.data;
};
```

### 2. **Sidebar Component** (`src/components/Sidebar/Sidebar.jsx`)

#### Tính năng mới:
- ✅ Tự động load danh sách sessions khi component mount
- ✅ Hiển thị danh sách sessions với preview tin nhắn đầu tiên
- ✅ Format ngày giờ theo kiểu "Hôm nay", "Hôm qua", hoặc ngày cụ thể
- ✅ Click vào session để load toàn bộ lịch sử
- ✅ Highlight session đang active
- ✅ Hiển thị số lượng tin nhắn trong mỗi session
- ✅ Nút "Chat Mới" để tạo session mới
- ✅ Nút "Làm mới" để refresh danh sách sessions

#### Các hàm quan trọng:
- `loadChatSessions()` - Load danh sách tất cả sessions
- `handleSessionClick(session)` - Xử lý khi click vào một session
- `formatDate(dateString)` - Format ngày giờ theo ngữ cảnh
- `getSessionPreview(history)` - Lấy preview tin nhắn đầu tiên

### 3. **Sidebar CSS** (`src/components/Sidebar/Sidebar.css`)

#### Thêm styles mới:
- `.btn-new-chat` - Nút tạo chat mới
- `.sessions-container` - Container chứa danh sách sessions
- `.sessions-list` - List các sessions
- `.session-item` - Item đại diện cho mỗi session
- `.session-item.active` - Style cho session đang active
- `.session-preview` - Preview nội dung tin nhắn
- `.session-date` - Ngày giờ của session
- `.session-count` - Số lượng tin nhắn
- `.btn-refresh` - Nút làm mới

### 4. **App Component** (`src/App.jsx`)

#### Thay đổi:
- Cập nhật `handleResetChat()` để tạo session mới khi reset
- Thêm `handleLoadSession(sessionId, history)` để load lịch sử session
- Truyền callback `onLoadSession` vào Sidebar component
- Convert lịch sử từ database sang format messages của app

## 🔧 Yêu cầu Backend API

Backend cần implement 2 endpoints sau:

### 1. GET `/chat-history/sessions`
Lấy danh sách tất cả sessions của user (hoặc tất cả sessions nếu không có user system)

**Response format:**
```json
[
  {
    "session_id": "uuid-string",
    "created_at": "2024-12-24T10:30:00Z",
    "updated_at": "2024-12-24T11:45:00Z",
    "history": [
      {
        "role": "user",
        "content": "Tìm sản phẩm ghế sofa",
        "timestamp": "2024-12-24T10:30:00Z"
      },
      {
        "role": "bot",
        "content": "Đây là kết quả...",
        "timestamp": "2024-12-24T10:30:05Z"
      }
    ]
  }
]
```

**Lưu ý:**
- Sắp xếp sessions theo `updated_at` DESC (mới nhất trên cùng)
- Mỗi session nên có ít nhất 1-2 tin nhắn đầu tiên trong `history` để hiển thị preview
- Có thể limit số lượng tin nhắn trong `history` ở đây (ví dụ: 2-3 tin đầu)

### 2. GET `/chat-history/session/:sessionId`
Lấy toàn bộ lịch sử chat của một session cụ thể

**Response format:**
```json
[
  {
    "role": "user",
    "content": "Tìm sản phẩm ghế sofa",
    "timestamp": "2024-12-24T10:30:00Z",
    "data": null,
    "image_url": null
  },
  {
    "role": "bot",
    "content": "Đây là kết quả tìm kiếm...",
    "timestamp": "2024-12-24T10:30:05Z",
    "data": {
      "products": [...],
      "context": {...}
    },
    "image_url": null
  }
]
```

**Lưu ý:**
- Trả về toàn bộ lịch sử theo thứ tự thời gian
- Bao gồm cả tin nhắn user và bot
- Bao gồm `data` nếu có (products, materials, context...)
- Bao gồm `image_url` nếu user upload ảnh

## 📊 Database Schema
Bảng `chat_histories` cần có cấu trúc tương tự:

```sql
CREATE TABLE chat_histories (
    id INT PRIMARY KEY AUTO_INCREMENT,
    session_id VARCHAR(255) NOT NULL,
    role VARCHAR(10) NOT NULL,  -- 'user' or 'bot'
    content TEXT,
    timestamp DATETIME NOT NULL,
    data JSON,  -- Dữ liệu bổ sung (products, materials, context...)
    image_url VARCHAR(500),
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX idx_session_id (session_id),
    INDEX idx_timestamp (timestamp)
);
```

## 🎨 UI/UX Features

1. **Session Preview**: Hiển thị tin nhắn đầu tiên của user làm preview (tối đa 50 ký tự)
2. **Smart Date Formatting**: 
   - "Hôm nay HH:mm"
   - "Hôm qua HH:mm"
   - "DD/MM/YYYY HH:mm"
3. **Active Session Highlight**: Session đang active có background và border khác màu
4. **Message Count**: Hiển thị số lượng tin nhắn trong mỗi session
5. **Smooth Transitions**: Hover effects và animations mượt mà
6. **Responsive**: Sidebar scroll được khi có nhiều sessions

## 🚀 Cách sử dụng

1. Mở ứng dụng → Sidebar tự động load danh sách sessions
2. Click vào session bất kỳ → Load toàn bộ lịch sử trò chuyện
3. Click "➕ Chat Mới" → Tạo session mới và reset chat
4. Click "🔄 Làm mới" → Refresh danh sách sessions

## 🔍 Testing Checklist

- [ ] Sidebar load danh sách sessions khi mở app
- [ ] Click vào session load đúng lịch sử
- [ ] Session đang active được highlight
- [ ] Ngày giờ hiển thị đúng format
- [ ] Preview tin nhắn hiển thị chính xác
- [ ] Nút "Chat Mới" tạo session mới
- [ ] Nút "Làm mới" refresh danh sách
- [ ] Scroll hoạt động khi có nhiều sessions
- [ ] Loading states hiển thị đúng
- [ ] Error handling khi API lỗi

## 📝 Notes

- Frontend đã sẵn sàng, chỉ cần backend implement 2 endpoints trên
- Format response từ backend phải match với format đã mô tả
- Timestamps cần phải là ISO 8601 format hoặc có thể parse được bởi `new Date()`
- Có thể thêm user_id vào API nếu có hệ thống authentication
