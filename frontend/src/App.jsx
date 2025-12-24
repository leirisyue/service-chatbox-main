import Chip from '@mui/material/Chip';
import { useEffect, useState } from 'react';
import { v4 as uuidv4 } from 'uuid';
import './App.css';
import ChatContainer from './components/Chat/ChatContainer';
import ChatInput from './components/Input/ChatInput';
import SuggestedPrompts from './components/Input/SuggestedPrompts';
import MainLayout from './components/Layout/MainLayout';
import Sidebar from './components/Sidebar/SidebarOld';
import { searchByImage, sendMessage } from './services/api';

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
    "🔍 Danh sách sản phẩm",
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
        content: `👋 Xin chào! Tôi là trợ lý AI của <b>AA Corporation</b> (Phiên bản 4.0).\nTôi có thể giúp bạn: \n• 🔍 <b>Tìm kiếm sản phẩm</b> (bằng mô tả hoặc hình ảnh) \n• 🧱 <b>Tìm kiếm nguyên vật liệu</b> (gỗ, da, đá, vải...) \n• 📋 <b>Xem định mức vật liệu</b> của sản phẩm \n• 💰 <b>Tính chi phí</b> sản phẩm (NVL + Nhân công + Lợi nhuận) \n• 🔗 <b>Tra cứu</b> vật liệu được dùng ở sản phẩm/dự án nào \n• 📈 <b>Xem lịch sử giá</b> vật liệu. <b> \n• 🆕 Tính năng mới V4.0:</b> \n• 🤖 AI tự động phân loại sản phẩm/vật liệu \n• 📊 Lưu lịch sử truy vấn để học \nHãy chọn một trong các gợi ý bên dưới hoặc gõ câu hỏi của bạn!
        `,
        type: 'welcome',
        timestamp: Date.now()
      };
      setMessages([welcomeMessage]);
    }
  }, []);

  // main message handler
  const handleSendMessage = async (message) => {
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

    // Tạo preview URL từ file
    const imageUrl = URL.createObjectURL(file);

    try {
      const response = await searchByImage(file);

      // Thêm user message với ảnh
      const userMessage = {
        role: 'user',
        content: "📷 Tìm kiếm bằng hình ảnh",
        imageUrl: imageUrl,
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

  // Cleanup URLs khi component unmount
  useEffect(() => {
    return () => {
      messages.forEach(msg => {
        if (msg.imageUrl) {
          URL.revokeObjectURL(msg.imageUrl);
        }
      });
    };
  }, [messages]);

  const handleResetChat = () => {
    // Tạo session mới
    const newSessionId = uuidv4();
    setSessionId(newSessionId);
    localStorage.setItem('chat_session_id', newSessionId);
    
    setMessages([]);
    setContext({
      last_search_results: [],
      current_products: [],
      current_materials: [],
      search_params: {}
    });
    setSuggestedPrompts([
      "🔍 Danh sách sản phẩm",
      // "🧱 Tìm nguyên vật liệu",
      // "💰 Tính chi phí",
      // "📋 Danh sách nhóm vật liệu"
    ]);

    // Thêm welcome message lại
    const welcomeMessage = {
      role: 'bot',
      content: `
      👋 Xin chào! Tôi là trợ lý AI của <b>AA Corporation</b> (Phiên bản 4.0).\nTôi có thể giúp bạn:\n• 🔍 <b>Tìm kiếm sản phẩm</b> (bằng mô tả hoặc hình ảnh)\n• 🧱 <b>Tìm kiếm nguyên vật liệu</b> (gỗ, da, đá, vải...)\n• 📋 <b>Xem định mức vật liệu</b> của sản phẩm\n• 💰 <b>Tính chi phí</b> sản phẩm (NVL + Nhân công + Lợi nhuận)\n• 🔗 <b>Tra cứu</b> vật liệu được dùng ở sản phẩm/dự án nào\n• 📈 <b>Xem lịch sử giá</b> vật liệu\nHãy chọn một trong các gợi ý bên dưới hoặc gõ câu hỏi của bạn!
      `,
      timestamp: Date.now()
    };
    setMessages([welcomeMessage]);
  };

  const handleLoadSession = (loadedSessionId, history) => {
    // Chuyển đổi sang session được load
    setSessionId(loadedSessionId);
    localStorage.setItem('chat_session_id', loadedSessionId);
    
    // Convert history từ database sang format messages
    const convertedMessages = history.map(item => ({
      role: item.role,
      content: item.content,
      timestamp: new Date(item.timestamp).getTime(),
      data: item.data || null,
      imageUrl: item.image_url || null
    }));
    
    setMessages(convertedMessages);
    
    // Reset context khi load session mới
    setContext({
      last_search_results: [],
      current_products: [],
      current_materials: [],
      search_params: {}
    });
  };

  return (
    <MainLayout
      sidebar={
        <Sidebar
          sessionId={sessionId}
          onResetChat={handleResetChat}
          // onLoadSession={handleLoadSession}
        />
      }
      mainContent={
        <div className="chat-interface">
          <div className="header">
            <div className="main-title">
              <b>AA Corporation AI Assistant</b>
              {/* <span className="version-badge">V4.0</span> */}
              <Chip label="v1.0" />
            </div>
            <div className="sub-title">
              Trợ Lý AI Thông Minh - Hỗ trợ Báo giá vật tư
            </div>
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