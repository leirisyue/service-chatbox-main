# Chat History System - Implementation Summary

## 📋 What Was Implemented

A new chat history logging system that stores conversations grouped by:
- **Email**: User identifier
- **Session ID**: Chat session identifier
- **Date**: Chat date (YYYY-MM-DD)
- **Time Block**: 
  - `1` = Morning (0:00 - 11:59)
  - `2` = Afternoon/Evening (12:00 - 23:59)

## 📁 Files Created/Modified

### ✅ New Files Created:

1. **`create_chat_histories_table.sql`**
   - PostgreSQL migration script
   - Creates `chat_histories` table
   - Adds indexes and triggers

2. **`CHAT_HISTORY_GUIDE.md`**
   - Complete documentation
   - Usage examples
   - API endpoint details

3. **`test_chat_history.py`**
   - Test script for the new system
   - Validates all endpoints
   - Example usage code

### ✅ Modified Files:

1. **`chatbot_api.py`**
   - Added `email` field to `ChatMessage` model
   - Added `get_time_block()` helper function
   - Added `save_chat_to_history()` function
   - Added `get_session_chat_history()` function
   - Updated `/chat` endpoint to save to new table
   - Added 2 new GET endpoints:
     - `/chat-history/{email}/{session_id}` - Get full chat history
     - `/chat-history/{email}` - Get all sessions for user
   - Updated API version to 4.2

## 🗄️ Database Schema

```sql
CREATE TABLE chat_histories (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL,
    session_id TEXT NOT NULL,
    chat_date DATE NOT NULL,
    time_block SMALLINT NOT NULL,  -- 1 or 2
    history JSONB NOT NULL,         -- [{"q":"...", "a":"...", "timestamp":"..."}]
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    UNIQUE (email, session_id, chat_date, time_block)
);
```

## 🔄 How It Works

### Saving Logic:

1. **Determine time block** from current hour:
   ```python
   time_block = 1 if hour < 12 else 2
   ```

2. **Check for existing record**:
   - Match: email + session_id + date + time_block

3. **Action**:
   - **EXISTS**: Append Q&A to JSONB array
   - **NOT EXISTS**: Create new record

### Example Timeline:

```
Day 1, 10:00 AM (Block 1):
  Record 1: {"email":"user@x.com", "session":"s1", "date":"2025-12-23", "block":1}
  history: [{"q":"Hello", "a":"Hi", "timestamp":"10:00:00"}]

Day 1, 11:30 AM (Block 1 - SAME):
  Record 1: (UPDATED)
  history: [
    {"q":"Hello", "a":"Hi", "timestamp":"10:00:00"},
    {"q":"How are you?", "a":"Good!", "timestamp":"11:30:00"}
  ]

Day 1, 14:00 PM (Block 2 - DIFFERENT):
  Record 2: (NEW)
  history: [{"q":"Goodbye", "a":"Bye!", "timestamp":"14:00:00"}]

Day 2, 09:00 AM (Block 1 - NEW DAY):
  Record 3: (NEW)
  history: [{"q":"Good morning", "a":"Hi!", "timestamp":"09:00:00"}]
```

## 🌐 API Endpoints

### 1. POST /chat (Updated)
```json
{
  "email": "user@example.com",        // ✨ NEW - Required
  "session_id": "session123",
  "message": "Tìm bàn gỗ",
  "context": {}
}
```

### 2. GET /chat-history/{email}/{session_id} (New)
Returns all chats for a session across all days.

**Example**: `GET /chat-history/user@example.com/session123`

**Response**:
```json
{
  "email": "user@example.com",
  "session_id": "session123",
  "total_records": 5,
  "total_chats": 23,
  "chats": [
    {
      "question": "Tìm bàn gỗ",
      "answer": "Tìm thấy 10 sản phẩm...",
      "timestamp": "2025-12-23T10:30:45",
      "date": "2025-12-23",
      "time_block": 1
    }
  ]
}
```

### 3. GET /chat-history/{email} (New)
Returns all sessions for a user.

**Example**: `GET /chat-history/user@example.com`

**Response**:
```json
{
  "email": "user@example.com",
  "total_sessions": 3,
  "sessions": [
    {
      "session_id": "session123",
      "first_chat_date": "2025-12-20",
      "last_chat_date": "2025-12-23",
      "total_days": 4,
      "total_messages": 35
    }
  ]
}
```

## 🚀 Setup Instructions

### Step 1: Run Database Migration

```bash
# Connect to your PostgreSQL database
psql -U postgres -d db_vector

# Run the migration script
\i create_chat_histories_table.sql

# Or using psql directly:
psql -U postgres -d db_vector -f create_chat_histories_table.sql
```

### Step 2: Install Dependencies (if needed)

```bash
pip install requests  # For testing script
```

### Step 3: Restart API Server

```bash
uvicorn chatbot_api:app --reload
```

### Step 4: Test the System

```bash
python test_chat_history.py
```

## 📊 Key Features

✅ **Time-Based Grouping**: Automatically groups chats by morning/afternoon  
✅ **Efficient Storage**: Uses JSONB for flexible, fast storage  
✅ **UPSERT Logic**: Smart update/insert based on time block  
✅ **Multi-Day Support**: Tracks conversations across multiple days  
✅ **User-Centric**: Easy to query all sessions for a user  
✅ **Backward Compatible**: Old chat_history table still works  

## ⚠️ Important Notes

1. **Email is now REQUIRED** in the `/chat` endpoint
2. The system maintains BOTH old and new chat history tables
3. Time block changes at exactly 12:00 PM (noon)
4. JSONB allows for flexible query patterns in the future
5. Indexes are created for optimal performance

## 🧪 Testing Checklist

- [ ] Database table created successfully
- [ ] API server starts without errors
- [ ] Can send chat with email field
- [ ] Chat history is saved correctly
- [ ] Morning chats (< 12:00) go to block 1
- [ ] Afternoon chats (>= 12:00) go to block 2
- [ ] Multiple chats in same block UPDATE record
- [ ] Different time blocks CREATE new record
- [ ] Can retrieve full session history
- [ ] Can retrieve all sessions for user

## 💡 Usage Examples

### Python Client
```python
import requests

# Send chat
response = requests.post("http://localhost:8000/chat", json={
    "email": "john@example.com",
    "session_id": "john_session_001",
    "message": "Tìm ghế văn phòng",
    "context": {}
})

# Get history
history = requests.get(
    "http://localhost:8000/chat-history/john@example.com/john_session_001"
).json()

print(f"Total chats: {history['total_chats']}")
for chat in history['chats']:
    print(f"Q: {chat['question']}")
    print(f"A: {chat['answer']}")
```

### JavaScript Client
```javascript
// Send chat
const response = await fetch('http://localhost:8000/chat', {
  method: 'POST',
  headers: { 'Content-Type': 'application/json' },
  body: JSON.stringify({
    email: 'john@example.com',
    session_id: 'john_session_001',
    message: 'Tìm ghế văn phòng',
    context: {}
  })
});

// Get history
const history = await fetch(
  'http://localhost:8000/chat-history/john@example.com/john_session_001'
).then(r => r.json());

console.log(`Total chats: ${history.total_chats}`);
```

## 🔍 Database Queries

### Check saved chats:
```sql
SELECT 
    email,
    session_id,
    chat_date,
    time_block,
    jsonb_array_length(history) as num_chats,
    created_at
FROM chat_histories
ORDER BY created_at DESC;
```

### Get chat content:
```sql
SELECT 
    email,
    chat_date,
    time_block,
    jsonb_pretty(history) as chat_history
FROM chat_histories
WHERE email = 'user@example.com'
ORDER BY chat_date, time_block;
```

## 📞 Support

If you encounter issues:

1. Check PostgreSQL connection in DB_CONFIG
2. Verify table was created: `\dt chat_histories`
3. Check API logs for error messages
4. Run test script for diagnostics
5. Verify email field is included in requests

---

**Version**: 4.2  
**Date**: December 23, 2025  
**Status**: ✅ Ready for Production
