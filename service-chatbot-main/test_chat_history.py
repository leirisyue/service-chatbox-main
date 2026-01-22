"""
Test script for chat history system
Run this after setting up the database and starting the API server
"""

import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000"

def test_chat_history():
    """Test the chat history endpoints"""
    
    email = "test@example.com"
    session_id = "test_session_123"
    
    print("=" * 60)
    print("CHAT HISTORY SYSTEM TEST")
    print("=" * 60)
    
    # Test 1: Send morning messages
    print("\n1️⃣ Sending morning messages (before 12:00)...")
    current_hour = datetime.now().hour
    print(f"   Current hour: {current_hour}")
    print(f"   Time block: {1 if current_hour < 12 else 2}")
    
    messages = [
        "Tìm bàn gỗ",
        "Giá bao nhiêu?",
        "Còn màu nào khác?"
    ]
    
    for msg in messages:
        response = requests.post(
            f"{BASE_URL}/chat",
            json={
                "email": email,
                "session_id": session_id,
                "message": msg,
                "context": {}
            }
        )
        
        if response.status_code == 200:
            print(f"   ✅ Sent: {msg}")
        else:
            print(f"   ❌ Failed: {msg}")
            print(f"      Error: {response.text}")
    
    # Test 2: Get chat history for session
    print("\n2️⃣ Retrieving chat history...")
    response = requests.get(f"{BASE_URL}/chat-history/{email}/{session_id}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ Retrieved successfully")
        print(f"   📊 Total records: {data['total_records']}")
        print(f"   💬 Total chats: {data['total_chats']}")
        print(f"\n   Chat History:")
        for i, chat in enumerate(data['chats'], 1):
            print(f"   {i}. [{chat['date']} - Block {chat['time_block']}]")
            print(f"      Q: {chat['question']}")
            print(f"      A: {chat['answer'][:100]}...")
            print()
    else:
        print(f"   ❌ Failed to retrieve")
        print(f"      Error: {response.text}")
    
    # Test 3: Get all sessions for user
    print("\n3️⃣ Getting all sessions for user...")
    response = requests.get(f"{BASE_URL}/chat-history/{email}")
    
    if response.status_code == 200:
        data = response.json()
        print(f"   ✅ Retrieved successfully")
        print(f"   📊 Total sessions: {data['total_sessions']}")
        print(f"\n   Sessions:")
        for session in data['sessions']:
            print(f"   • {session['session_id']}")
            print(f"     First chat: {session['first_chat_date']}")
            print(f"     Last chat: {session['last_chat_date']}")
            print(f"     Total days: {session['total_days']}")
            print(f"     Total messages: {session['total_messages']}")
            print()
    else:
        print(f"   ❌ Failed to retrieve")
        print(f"      Error: {response.text}")
    
    print("=" * 60)
    print("TEST COMPLETED")
    print("=" * 60)

def test_api_status():
    """Check if API is running"""
    try:
        response = requests.get(f"{BASE_URL}/")
        if response.status_code == 200:
            data = response.json()
            print(f"✅ API is running - Version {data['version']}")
            return True
        else:
            print(f"❌ API returned status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Cannot connect to API: {e}")
        print(f"   Make sure the server is running at {BASE_URL}")
        return False

if __name__ == "__main__":
    print("\n🚀 Starting tests...\n")
    
    if test_api_status():
        print()
        test_chat_history()
    else:
        print("\n⚠️  Please start the API server first:")
        print("   uvicorn chatbot_api:app --reload")
