# 📋 Chat History System - Deployment Checklist

## Pre-Deployment

### 1. Database Setup
- [ ] Connect to PostgreSQL database
  ```bash
  psql -U postgres -d db_vector
  ```
- [ ] Run migration script
  ```bash
  \i create_chat_histories_table.sql
  ```
- [ ] Verify table creation
  ```sql
  \dt chat_histories
  \d chat_histories
  ```
- [ ] Check indexes were created
  ```sql
  \di chat_histories*
  ```

### 2. Code Verification
- [ ] Check [chatbot_api.py](chatbot_api.py) has no syntax errors
- [ ] Verify `email` field added to `ChatMessage` model
- [ ] Confirm new helper functions exist:
  - [ ] `get_time_block()`
  - [ ] `save_chat_to_history()`
  - [ ] `get_session_chat_history()`
- [ ] Verify new endpoints registered:
  - [ ] `GET /chat-history/{email}/{session_id}`
  - [ ] `GET /chat-history/{email}`

### 3. Dependencies
- [ ] All required packages installed (see [requirements.txt](requirements.txt))
- [ ] psycopg2 working correctly
- [ ] Database connection string correct in `DB_CONFIG`

## Testing

### 4. Local Testing
- [ ] Start API server
  ```bash
  uvicorn chatbot_api:app --reload
  ```
- [ ] API responds at http://localhost:8000
- [ ] Check API version shows 4.2
  ```bash
  curl http://localhost:8000/
  ```
- [ ] Run test script
  ```bash
  python test_chat_history.py
  ```

### 5. Manual API Tests

#### Test 1: Send Chat with Email
```bash
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "email": "test@example.com",
    "session_id": "test_session",
    "message": "Hello",
    "context": {}
  }'
```
- [ ] Returns valid response
- [ ] No error in logs

#### Test 2: Check Database
```sql
SELECT * FROM chat_histories ORDER BY created_at DESC LIMIT 1;
```
- [ ] Record exists
- [ ] `email` matches
- [ ] `time_block` is 1 or 2
- [ ] `history` is valid JSONB

#### Test 3: Get History
```bash
curl http://localhost:8000/chat-history/test@example.com/test_session
```
- [ ] Returns chat history
- [ ] `total_chats` > 0
- [ ] Chats array not empty

#### Test 4: Get All Sessions
```bash
curl http://localhost:8000/chat-history/test@example.com
```
- [ ] Returns sessions list
- [ ] Shows correct session info

### 6. Time Block Testing
- [ ] Send message in morning (before 12:00)
  - [ ] Check `time_block = 1` in database
- [ ] Send another message in morning
  - [ ] Same record updated (not created)
- [ ] Send message in afternoon (after 12:00)
  - [ ] New record created with `time_block = 2`

### 7. Multi-Day Testing
- [ ] Create chat on Day 1
- [ ] Check database record for Day 1
- [ ] Simulate Day 2 (or wait for next day)
- [ ] Create chat on Day 2
- [ ] Check database has separate records for each day
- [ ] Retrieve full history shows both days

## Production Readiness

### 8. Performance Checks
- [ ] Database queries execute quickly (< 100ms)
- [ ] JSONB updates are fast
- [ ] Indexes are being used (check with EXPLAIN)
  ```sql
  EXPLAIN ANALYZE 
  SELECT * FROM chat_histories 
  WHERE email = 'test@example.com' AND session_id = 'test';
  ```

### 9. Error Handling
- [ ] Missing email in request → returns error
- [ ] Invalid session_id → handles gracefully
- [ ] Database connection failure → catches exception
- [ ] JSONB parsing error → handles gracefully

### 10. Security
- [ ] No SQL injection vulnerabilities (using parameterized queries ✓)
- [ ] Email validation (add if needed)
- [ ] Session ID validation (add if needed)
- [ ] Rate limiting configured (if needed)

### 11. Monitoring
- [ ] Log messages show chat history saves
  ```
  💾 CREATED chat history: email | session | date | Block X
  💾 UPDATED chat history: email | session | date | Block X
  ```
- [ ] Error logs working
- [ ] Database connection pool status

### 12. Documentation
- [ ] [QUICK_START.md](QUICK_START.md) reviewed
- [ ] [CHAT_HISTORY_GUIDE.md](CHAT_HISTORY_GUIDE.md) reviewed
- [ ] [IMPLEMENTATION_SUMMARY.md](IMPLEMENTATION_SUMMARY.md) reviewed
- [ ] [VISUAL_FLOW.md](VISUAL_FLOW.md) reviewed
- [ ] Team informed of changes
- [ ] Frontend team knows about `email` field requirement

## Post-Deployment

### 13. Monitoring (First 24 Hours)
- [ ] Check chat_histories table is receiving data
- [ ] Verify time blocks are correct
- [ ] Monitor database size growth
- [ ] Check API response times
- [ ] Review error logs

### 14. Data Validation
- [ ] Random sample of chats stored correctly
- [ ] JSONB structure is valid
- [ ] Timestamps are accurate
- [ ] Time blocks match actual time
- [ ] No duplicate records (UNIQUE constraint working)

### 15. Backup
- [ ] Database backup schedule includes new table
- [ ] Test restore procedure
- [ ] Document recovery process

## Rollback Plan (If Needed)

### 16. Emergency Rollback
If issues occur:
1. [ ] Revert code changes to previous version
2. [ ] API will continue using old `chat_history` table
3. [ ] New `chat_histories` table can remain (won't be used)
4. [ ] No data loss (dual writing to both tables)

Steps:
```bash
# 1. Stop API server
Ctrl+C

# 2. Restore previous version
git checkout <previous-commit>

# 3. Restart API
uvicorn chatbot_api:app --reload
```

## Success Criteria

### All Checks Must Pass:
- ✅ Database table created and accessible
- ✅ API accepts email field in chat requests
- ✅ Chats saved to chat_histories table
- ✅ Time blocks work correctly (1 for morning, 2 for afternoon)
- ✅ Same time block updates existing record
- ✅ Different time block creates new record
- ✅ History retrieval works for session
- ✅ Session list works for user
- ✅ No errors in logs
- ✅ Performance acceptable (< 200ms response time)
- ✅ Frontend can send email field

## Notes

- Old `chat_history` table is still active (backward compatibility)
- Both systems run in parallel
- No disruption to existing functionality
- Easy to rollback if needed

## Support Contacts

| Issue Type | Contact |
|------------|---------|
| Database | DBA Team |
| API | Backend Team |
| Frontend Integration | Frontend Team |
| Testing | QA Team |

## Useful Commands

### Check table size:
```sql
SELECT pg_size_pretty(pg_total_relation_size('chat_histories'));
```

### Count records:
```sql
SELECT COUNT(*) FROM chat_histories;
```

### Recent chats:
```sql
SELECT 
  email, 
  session_id, 
  chat_date, 
  time_block,
  jsonb_array_length(history) as num_messages
FROM chat_histories 
ORDER BY updated_at DESC 
LIMIT 10;
```

### Debug specific user:
```sql
SELECT * FROM chat_histories 
WHERE email = 'user@example.com' 
ORDER BY chat_date, time_block;
```

---

**Deployment Date**: _____________  
**Deployed By**: _____________  
**Verification By**: _____________  
**Status**: ⬜ PENDING / ✅ COMPLETE / ❌ FAILED
