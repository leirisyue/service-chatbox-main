# 🚀 Chat History Quick Start

## 1️⃣ Setup Database (One-time)
```bash
psql -U postgres -d db_vector -f create_chat_histories_table.sql
```

## 2️⃣ Send Chat (with email)
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "email": "user@example.com",
    "session_id": "session123",
    "message": "Tìm bàn gỗ"
  }'
```

## 3️⃣ Get Chat History
```bash
# Get full history for a session
curl http://localhost:8000/chat-history/user@example.com/session123

# Get all sessions for a user
curl http://localhost:8000/chat-history/user@example.com
```

## 4️⃣ Test Everything
```bash
python test_chat_history.py
```

## ⏰ Time Blocks
- **Block 1**: 0:00 - 11:59 (Morning)
- **Block 2**: 12:00 - 23:59 (Afternoon/Evening)

## 📝 Key Changes
✅ Added `email` field to ChatMessage  
✅ Chats grouped by date and time block  
✅ Auto-update same time block, create new for different block  
✅ JSONB storage for flexible queries  
✅ New endpoints for retrieving history  

## 🔗 Endpoints
- `POST /chat` - Send message (requires email now)
- `GET /chat-history/{email}/{session_id}` - Get session history
- `GET /chat-history/{email}` - Get all sessions

## 📚 Full Documentation
- `CHAT_HISTORY_GUIDE.md` - Complete guide
- `IMPLEMENTATION_SUMMARY.md` - Detailed summary
- `create_chat_histories_table.sql` - Database schema
