import React, { useState, useEffect } from 'react';
import { v4 as uuidv4 } from 'uuid';
import Sidebar from './components/Sidebar/Sidebar';
import ChatContainer from './components/Chat/ChatContainer';
import ChatInput from './components/Input/ChatInput';
import SuggestedPrompts from './components/Input/SuggestedPrompts';
import ImageUpload from './components/Input/ImageUpload';
import MainLayout from './components/Layout/MainLayout';
import { sendMessage, searchByImage, queryChat } from './services/api';
import './App.css';

function App() {
  const [sessionId, setSessionId] = useState('');
  const [messages, setMessages] = useState([]);
  const [context, setContext] = useState({
    last_search_results: [],
    current_products: [],
    current_materials: [],
    search_params: {}
  });
  const [suggestedPrompts, setSuggestedPrompts] = useState([
    "🔍 Tìm sản phẩm",
    "🧱 Tìm nguyên vật liệu",
    "💰 Tính chi phí",
    "📋 Danh sách nhóm vật liệu"
  ]);
  const [isLoading, setIsLoading] = useState(false);

  // Khởi tạo session
  useEffect(() => {
    const storedSessionId = localStorage.getItem('chat_session_id') || uuidv4();
    setSessionId(storedSessionId);
    localStorage.setItem('chat_session_id', storedSessionId);

    // Thêm welcome message
    if (messages.length === 0) {
      const welcomeMessage = {
        role: 'bot',
        content: `
        👋 Xin chào! Tôi là trợ lý AI của **AA Corporation** (Phiên bản 4.0).\n\n
        Tôi có thể giúp bạn:
        • 🔍 **Tìm kiếm sản phẩm** (bằng mô tả hoặc hình ảnh)
        • 🧱 **Tìm kiếm nguyên vật liệu** (gỗ, da, đá, vải...)
        • 📋 **Xem định mức vật liệu** của sản phẩm
        • 💰 **Tính chi phí** sản phẩm (NVL + Nhân công + Lợi nhuận)
        • 🔗 **Tra cứu** vật liệu được dùng ở sản phẩm/dự án nào
        • 📈 **Xem lịch sử giá** vật liệu\n\n
        **🆕 Tính năng mới V4.0:**
        • 🤖 AI tự động phân loại sản phẩm/vật liệu
        • 📊 Lưu lịch sử truy vấn để học
        • ⚡ Import CSV dễ dàng hơn\n\n
        Hãy chọn một trong các gợi ý bên dưới hoặc gõ câu hỏi của bạn!
      `,
        timestamp: Date.now()
      };
      setMessages([welcomeMessage]);
    }
  }, []);

  // main message handler
  const handleSendMessage = async (message) => {
    console.log("🚀 ~ handleSendMessage ~ message:", message);
    // Thêm message của user
    const userMessage = {
      role: 'user',
      content: message,
      timestamp: Date.now()
    };
    setMessages(prev => [...prev, userMessage]);
    setIsLoading(true);

    try {
      const response = await sendMessage(sessionId, message, context);
      // const min_score = 0.5; // example value
      // const text = message;
      // const top_k = 5; // example value
      // const response = await queryChat(min_score, text, top_k);

      // Cập nhật context nếu có
      if (response.context) {
        setContext(prev => ({ ...prev, ...response.context }));
      }

      if (response.products) {
        setContext(prev => ({
          ...prev,
          current_products: response.products,
          last_search_results: response.products.map(p => p.headcode)
        }));
      }

      if (response.materials) {
        setContext(prev => ({
          ...prev,
          current_materials: response.materials
        }));
      }

      // Thêm message của bot
      const botMessage = {
        role: 'bot',
        content: response.response || "Xin lỗi, tôi không hiểu.",
        data: response,
        timestamp: Date.now()
      };

      setMessages(prev => [...prev, botMessage]);

      // Cập nhật suggested prompts
      if (response.suggested_prompts) {
        setSuggestedPrompts(response.suggested_prompts);
      }
    } catch (error) {
      console.error('Error sending message:', error);
      const errorMessage = {
        role: 'bot',
        content: "⚠️ Lỗi kết nối đến server. Vui lòng thử lại.",
        timestamp: Date.now()
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleImageSearch = async (file) => {
    setIsLoading(true);

    try {
      const response = await searchByImage(file);

      // Thêm user message
      const userMessage = {
        role: 'user',
        content: "📷 [Đã upload ảnh]",
        timestamp: Date.now()
      };
      setMessages(prev => [...prev, userMessage]);

      // Thêm bot message
      const botMessage = {
        role: 'bot',
        content: response.response || "Đã phân tích ảnh",
        data: response,
        timestamp: Date.now()
      };

      setMessages(prev => [...prev, botMessage]);

      // Cập nhật context
      if (response.products) {
        setContext(prev => ({
          ...prev,
          current_products: response.products,
          last_search_results: response.products.map(p => p.headcode)
        }));
      }

      // Cập nhật suggested prompts
      if (response.products && response.products.length > 0) {
        const firstHeadcode = response.products[0].headcode;
        setSuggestedPrompts([
          `💰 Xem chi phí ${firstHeadcode}`,
          `📋 Phân tích vật liệu ${firstHeadcode}`,
          "🔍 Tìm sản phẩm khác"
        ]);
      }
    } catch (error) {
      console.error('Error processing image:', error);
      const errorMessage = {
        role: 'bot',
        content: "⚠️ Lỗi xử lý ảnh. Vui lòng thử lại.",
        timestamp: Date.now()
      };
      setMessages(prev => [...prev, errorMessage]);
    } finally {
      setIsLoading(false);
    }
  };

  const handleResetChat = () => {
    setMessages([]);
    setContext({
      last_search_results: [],
      current_products: [],
      current_materials: [],
      search_params: {}
    });
    setSuggestedPrompts([
      "🔍 Tìm sản phẩm",
      "🧱 Tìm nguyên vật liệu",
      "💰 Tính chi phí",
      "📋 Danh sách nhóm vật liệu"
    ]);

    // Thêm welcome message lại
    const welcomeMessage = {
      role: 'bot',
      content: `👋 Xin chào! Tôi là trợ lý AI của **AA Corporation** (Phiên bản 4.0).\n\n
Tôi có thể giúp bạn:
• 🔍 **Tìm kiếm sản phẩm** (bằng mô tả hoặc hình ảnh)
• 🧱 **Tìm kiếm nguyên vật liệu** (gỗ, da, đá, vải...)
• 📋 **Xem định mức vật liệu** của sản phẩm
• 💰 **Tính chi phí** sản phẩm (NVL + Nhân công + Lợi nhuận)
• 🔗 **Tra cứu** vật liệu được dùng ở sản phẩm/dự án nào
• 📈 **Xem lịch sử giá** vật liệu\n\n
Hãy chọn một trong các gợi ý bên dưới hoặc gõ câu hỏi của bạn!`,
      timestamp: Date.now()
    };
    setMessages([welcomeMessage]);
  };

  return (
    <MainLayout
      sidebar={
        <Sidebar
          sessionId={sessionId}
          onResetChat={handleResetChat}
        />
      }
      mainContent={
        <div className="chat-interface">
          <div className="header">
            <h1 className="main-title">
              🏢 AA Corporation AI Assistant
              <span className="version-badge">V4.0</span>
            </h1>
            <p className="sub-title">
              Trợ Lý AI Thông Minh - Hỗ trợ Báo giá vật tư
            </p>
          </div>

          <ChatContainer
            messages={messages}
            isLoading={isLoading}
            onSendMessage={handleSendMessage}
          />

          <div className="input-section">
            <SuggestedPrompts
              prompts={suggestedPrompts}
              onSelect={handleSendMessage}
            />

            <div className="input-row">
              <ChatInput
                onSendMessage={handleSendMessage}
                onImageUpload={handleImageSearch}
                disabled={isLoading}
              />
            </div>
          </div>
        </div>
      }
    />
  );
}

export default App;