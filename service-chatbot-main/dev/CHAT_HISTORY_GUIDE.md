# Chat History Implementation Guide

## Overview
This implementation adds a new chat history system that stores conversations grouped by:
- **Email**: User identifier
- **Session ID**: Chat session
- **Date**: Chat date (YYYY-MM-DD)
- **Time Block**: 
  - `1` = 0-12h (morning)
  - `2` = 12-24h (afternoon/evening)

## Database Setup

1. **Run the migration script** to create the `chat_histories` table:
   ```bash
   psql -U postgres -d db_vector -f create_chat_histories_table.sql
   ```

   This will create:
   - Main table `chat_histories`
   - Indexes for performance
   - Triggers for automatic timestamp updates

## Table Structure

```sql
chat_histories (
    id UUID PRIMARY KEY,
    email TEXT NOT NULL,
    session_id TEXT NOT NULL,
    chat_date DATE NOT NULL,
    time_block SMALLINT NOT NULL,  -- 1 or 2
    history JSONB NOT NULL,         -- Array of Q&A
    created_at TIMESTAMP,
    updated_at TIMESTAMP,
    UNIQUE (email, session_id, chat_date, time_block)
)
```

## How It Works

### Saving Chat History

When a user sends a message:

1. **Determine time block** based on current hour:
   - If hour < 12 → time_block = 1
   - If hour >= 12 → time_block = 2

2. **Check if record exists** for:
   - Same email
   - Same session_id
   - Same date
   - Same time_block

3. **Update or Insert**:
   - **EXISTS**: Append new Q&A to existing `history` JSONB array
   - **NOT EXISTS**: Create new record with first Q&A

### History Format

The `history` column stores JSONB array:
```json
[
  {
    "q": "user question",
    "a": "bot answer",
    "timestamp": "2025-12-23T10:30:45.123456"
  },
  {
    "q": "another question",
    "a": "another answer",
    "timestamp": "2025-12-23T10:32:15.789012"
  }
]
```

## API Endpoints

### 1. Send Chat Message (Updated)
```http
POST /chat
Content-Type: application/json

{
  "session_id": "user123_session1",
  "email": "user@example.com",
  "message": "Tìm bàn gỗ",
  "context": {}
}
```

**Changes**: 
- Added required `email` field
- Automatically saves to both old and new chat history tables

### 2. Get Chat History for Session
```http
GET /chat-history/{email}/{session_id}
```

**Example**:
```http
GET /chat-history/user@example.com/user123_session1
```

**Response**:
```json
{
  "email": "user@example.com",
  "session_id": "user123_session1",
  "total_records": 3,
  "total_chats": 15,
  "chats": [
    {
      "question": "Tìm bàn gỗ",
      "answer": "Tìm thấy 5 sản phẩm...",
      "timestamp": "2025-12-23T10:30:45",
      "date": "2025-12-23",
      "time_block": 1
    },
    {
      "question": "Giá bao nhiêu?",
      "answer": "Giá từ 5 triệu...",
      "timestamp": "2025-12-23T15:20:10",
      "date": "2025-12-23",
      "time_block": 2
    }
  ]
}
```

### 3. Get All Sessions for User
```http
GET /chat-history/{email}
```

**Example**:
```http
GET /chat-history/user@example.com
```

**Response**:
```json
{
  "email": "user@example.com",
  "total_sessions": 2,
  "sessions": [
    {
      "session_id": "user123_session1",
      "first_chat_date": "2025-12-20",
      "last_chat_date": "2025-12-23",
      "total_days": 4,
      "total_messages": 25
    },
    {
      "session_id": "user123_session2",
      "first_chat_date": "2025-12-15",
      "last_chat_date": "2025-12-15",
      "total_days": 1,
      "total_messages": 8
    }
  ]
}
```

## Code Changes

### 1. Added to `chatbot_api.py`:

- **`get_time_block(hour)`**: Determines time block (1 or 2)
- **`save_chat_to_history()`**: Main function to save/update chat
- **`get_session_chat_history()`**: Retrieve all chats for a session
- Updated `ChatMessage` model to include `email` field
- Updated `/chat` endpoint to call new save function
- Added 2 new GET endpoints for retrieving history

### 2. Files Created:

- **`create_chat_histories_table.sql`**: Database migration script
- **`CHAT_HISTORY_GUIDE.md`**: This documentation

## Example Usage Flow

### Day 1 Morning (10:30 AM)
```python
# First message at 10:30 AM
POST /chat
{
  "email": "john@example.com",
  "session_id": "john_session1",
  "message": "Tìm ghế"
}
# Creates record: (john@example.com, john_session1, 2025-12-23, 1)
# history = [{"q": "Tìm ghế", "a": "...", "timestamp": "10:30:00"}]
```

### Day 1 Morning (11:45 AM)
```python
# Second message at 11:45 AM (still morning)
POST /chat
{
  "email": "john@example.com",
  "session_id": "john_session1",
  "message": "Giá bao nhiêu?"
}
# UPDATES same record: (john@example.com, john_session1, 2025-12-23, 1)
# history = [
#   {"q": "Tìm ghế", "a": "...", "timestamp": "10:30:00"},
#   {"q": "Giá bao nhiêu?", "a": "...", "timestamp": "11:45:00"}
# ]
```

### Day 1 Afternoon (14:30 PM)
```python
# Third message at 14:30 PM (afternoon)
POST /chat
{
  "email": "john@example.com",
  "session_id": "john_session1",
  "message": "Còn loại khác không?"
}
# CREATES new record: (john@example.com, john_session1, 2025-12-23, 2)
# history = [{"q": "Còn loại khác không?", "a": "...", "timestamp": "14:30:00"}]
```

### Day 2 Morning (09:00 AM)
```python
# Message on next day
POST /chat
{
  "email": "john@example.com",
  "session_id": "john_session1",
  "message": "Tôi quay lại"
}
# CREATES new record: (john@example.com, john_session1, 2025-12-24, 1)
# history = [{"q": "Tôi quay lại", "a": "...", "timestamp": "09:00:00"}]
```

### Retrieve Full History
```python
GET /chat-history/john@example.com/john_session1

# Returns ALL chats from all days and time blocks, sorted chronologically
# Total: 3 records (Day1-Morning, Day1-Afternoon, Day2-Morning)
# With all 4 messages in order
```

## Benefits

✅ **Efficient Storage**: Groups chats by time blocks instead of individual messages  
✅ **Easy Retrieval**: Simple queries to get full conversation history  
✅ **Scalable**: JSONB storage is fast and flexible  
✅ **Time Context**: Separates morning/afternoon conversations naturally  
✅ **User-Centric**: Track conversations by email and session  

## Testing

Test the endpoints with curl or Postman:

```bash
# 1. Send a chat (morning)
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "session_id": "test_session",
    "message": "Hello"
  }'

# 2. Get chat history
curl http://localhost:8000/chat-history/test@example.com/test_session

# 3. Get all sessions for user
curl http://localhost:8000/chat-history/test@example.com
```

## Notes

- The old `chat_history` table is still being used for backward compatibility
- Both systems run in parallel
- The new system is designed for better scalability and user-centric queries
- JSONB queries in PostgreSQL are highly optimized
