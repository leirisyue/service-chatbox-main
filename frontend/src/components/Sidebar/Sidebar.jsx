import React, { useState, useEffect } from 'react';
import './Sidebar.css';
import {
  importProducts,
  importMaterials,
  importProductMaterials,
  classifyProducts,
  classifyMaterials,
  generateEmbeddings,
  generateMaterialEmbeddings,
  getDebugInfo,
  getChatSessions,
  getSessionHistory,
  getChatSessionId
} from '../../services/api';
import QuestionAnswerIcon from '@mui/icons-material/QuestionAnswer';
import Button from '@mui/material/Button';
import { emailUserAtom } from '../../atom/variableAtom';
import { useAtomValue } from 'jotai/react';
import ChatBubbleOutlineIcon from '@mui/icons-material/ChatBubbleOutline';

function Sidebar({ sessionId, onResetChat, onLoadSession }) {

  const [importResults, setImportResults] = useState({});
  const [isProcessing, setIsProcessing] = useState(false);
  const [debugInfo, setDebugInfo] = useState(null);
  const [chatSessions, setChatSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState(null);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const emailUser = useAtomValue(emailUserAtom);

  // Load danh sách sessions khi component mount
  useEffect(() => {
    loadChatSessions();
  }, []);

  const loadChatSessions = async () => {
    setIsLoadingSessions(true);
    try {
      const sessions = await getChatSessions(emailUser);
      console.log("🚀 ~ loadChatSessions ~ sessions:", sessions);
      setChatSessions(sessions);
    } catch (error) {
      console.error('Error loading sessions:', error);
    } finally {
      setIsLoadingSessions(false);
    }
  };

  useEffect(() => {
    setSelectedSession(sessionId);
  }, [sessionId]);

  useEffect(() => {
    loadChatSessions();
  }, [emailUser]);

  const handleSessionClick = async (session) => {
    try {
      setSelectedSession(session.session_id);
      const history = await getChatSessionId(session.session_id);

      // Gọi callback để load lịch sử vào App
      if (onLoadSession) {
        onLoadSession(session.session_id, history);
      }
    } catch (error) {
      console.error('Error loading session history:', error);
      alert('Lỗi tải lịch sử: ' + error.message);
    }
  };

  const formatDate = (dateString) => {
    const date = new Date(dateString);
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    if (date.toDateString() === today.toDateString()) {
      return 'Hôm nay ' + date.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
    } else if (date.toDateString() === yesterday.toDateString()) {
      return 'Hôm qua ' + date.toLocaleTimeString('vi-VN', { hour: '2-digit', minute: '2-digit' });
    } else {
      return date.toLocaleDateString('vi-VN', {
        day: '2-digit',
        month: '2-digit',
        year: 'numeric',
        hour: '2-digit',
        minute: '2-digit'
      });
    }
  };

  const getSessionPreview = (history) => {
    console.log("🚀 ~ getSessionPreview ~ history:", history);
    if (!history || history.length === 0) return 'Không có tin nhắn';

    // Lấy tin nhắn đầu tiên của user
    const firstUserMessage = history?.find(h => h.role === 'user');
    if (firstUserMessage && firstUserMessage.content) {
      return firstUserMessage.content.substring(0, 50) + (firstUserMessage.content.length > 50 ? '...' : '');
    }

    return 'Session mới';
  };

  const handleFileUpload = async (endpoint, file, type) => {
    if (!file) {
      alert('Vui lòng chọn file');
      return;
    }

    setIsProcessing(true);
    try {
      let response;
      switch (endpoint) {
        case 'products':
          response = await importProducts(file);
          break;
        case 'materials':
          response = await importMaterials(file);
          break;
        case 'product-materials':
          response = await importProductMaterials(file);
          break;
        default:
          return;
      }

      setImportResults(prev => ({
        ...prev,
        [type]: response
      }));

      if (response.message) {
        alert(response.message);
      }
    } catch (error) {
      console.error('Import error:', error);
      alert('Lỗi import: ' + error.message);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleClassification = async (type) => {
    setIsProcessing(true);
    try {
      let response;
      if (type === 'products') {
        response = await classifyProducts();
      } else {
        response = await classifyMaterials();
      }

      if (response.message) {
        alert(response.message);
      }
    } catch (error) {
      console.error('Classification error:', error);
      alert('Lỗi phân loại: ' + error.message);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleGenerateEmbeddings = async (type) => {
    setIsProcessing(true);
    try {
      let response;
      if (type === 'products') {
        response = await generateEmbeddings();
      } else {
        response = await generateMaterialEmbeddings();
      }

      if (response.message) {
        alert(response.message);
      }
    } catch (error) {
      console.error('Embeddings error:', error);
      alert('Lỗi tạo embeddings: ' + error.message);
    } finally {
      setIsProcessing(false);
    }
  };

  const handleDebugInfo = async () => {
    try {
      const info = await getDebugInfo();
      setDebugInfo(info);
    } catch (error) {
      console.error('Debug error:', error);
      alert('Lỗi lấy thông tin debug');
    }
  };

  return (
    <div className="sidebar">
      <div className="sidebar-header">
        <Button
          className="btn-new-chat"
          onClick={onResetChat}
          disabled={isProcessing}
          startIcon={<QuestionAnswerIcon />}
          variant="contained"
          color="primary"
        >
          Mở Chat Mới
        </Button>
      </div>

      <div className="sessions-container">
        {isLoadingSessions ? (
          <div className="loading-sessions">
            <p>Đang tải...</p>
          </div>
        ) : chatSessions?.sessions?.length === 0 ? (
          <div className="empty-sessions">
            <p>Chưa có lịch sử trò chuyện</p>
          </div>
        ) : (
          <div className="sessions-list">
            {chatSessions?.sessions?.map((session) => (
              <div
                key={session?.session_id}
                className={`session-item ${selectedSession === session?.session_id ? 'active' : ''}`}
                onClick={() => handleSessionClick(session)}
              >
                <div className="session-header">
                  <span className="session-icon" style={{paddingLeft:'10px'}}>
                    <ChatBubbleOutlineIcon sx={{ fontSize: 15 }} />
                  </span>
                  <div className="session-info">
                    <div className="session-preview">
                      {/* {getSessionPreview(session?.session_name)} */}
                      {session?.session_name}
                    </div>
                    <div className="session-date">
                      {formatDate(session.last_updated || session.created_at)}
                    </div>
                  </div>
                </div>
                {/* {session.history && session.history.length > 0 && (
                  <div className="session-count">
                    {session.history.length} tin nhắn
                  </div>
                )} */}
              </div>
            ))}
            
          </div>
        )}
      </div>
      <div className="sidebar-footer">
        {emailUser ? `${emailUser}` : 'Chưa có Email người dùng'}
      </div>
    </div >
  );
}

export default Sidebar;