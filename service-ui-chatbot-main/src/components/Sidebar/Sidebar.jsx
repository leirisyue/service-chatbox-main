import ChatBubbleOutlineIcon from '@mui/icons-material/ChatBubbleOutline';
import QuestionAnswerIcon from '@mui/icons-material/QuestionAnswer';
import MoreVertIcon from '@mui/icons-material/MoreVert';
import EditIcon from '@mui/icons-material/Edit';
import DeleteIcon from '@mui/icons-material/Delete';
import Button from '@mui/material/Button';
import IconButton from '@mui/material/IconButton';
import Menu from '@mui/material/Menu';
import MenuItem from '@mui/material/MenuItem';
import ListItemIcon from '@mui/material/ListItemIcon';
import ListItemText from '@mui/material/ListItemText';
import { useAtom, useAtomValue } from 'jotai/react';
import { useEffect, useState } from 'react';
import { messagesAtom, viewHistoryAtom } from '../../atom/messageAtom';
import { emailUserAtom } from '../../atom/variableAtom';
import {
  classifyMaterials, classifyProducts, generateEmbeddings,
  generateMaterialEmbeddings, getChatSessions, getDebugInfo, getMessagersHistory, importMaterials,
  importProductMaterials, importProducts, renameSession, deleteSession
} from '../../services/api';
import './Sidebar.css';

function Sidebar({ sessionId, onResetChat, onLoadSession }) {

  const [importResults, setImportResults] = useState({});
  const [isProcessing, setIsProcessing] = useState(false);
  const [debugInfo, setDebugInfo] = useState(null);
  const [chatSessions, setChatSessions] = useState([]);
  const [selectedSession, setSelectedSession] = useState(null);
  const [isLoadingSessions, setIsLoadingSessions] = useState(false);
  const emailUser = useAtomValue(emailUserAtom);
  const [, setMessages] = useAtom(messagesAtom);
  const [, setViewHistory] = useAtom(viewHistoryAtom);
  const [contextMenu, setContextMenu] = useState(null);
  const [menuSession, setMenuSession] = useState(null);
  const [isRenaming, setIsRenaming] = useState(false);
  const [renamingSessionId, setRenamingSessionId] = useState(null);
  const [newSessionName, setNewSessionName] = useState('');

  // Load danh sách sessions khi component mount
  useEffect(() => {
    loadChatSessions();
  }, []);

  const loadChatSessions = async () => {
    setIsLoadingSessions(true);
    try {
      const sessions = await getChatSessions(emailUser);
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
      await setMessages([]);
      setSelectedSession(session.session_id);
      const history = await getMessagersHistory(session.session_id);
      if (history.length > 0) {
        setViewHistory(true);
        setMessages(history);
      }
    } catch (error) {
      console.error('Error loading session history:', error);
      alert('Lỗi tải lịch sử: ' + error.message);
    }
  };

  const handleContextMenu = (event, session) => {
    event.preventDefault();
    event.stopPropagation();
    setContextMenu({
      mouseX: event.clientX - 2,
      mouseY: event.clientY - 4,
    });
    setMenuSession(session);
  };

  const handleCloseContextMenu = () => {
    setContextMenu(null);
    setMenuSession(null);
  };

  const handleRenameClick = () => {
    if (menuSession) {
      setRenamingSessionId(menuSession.session_id);
      setNewSessionName(menuSession.session_name);
      setIsRenaming(true);
    }
    handleCloseContextMenu();
  };

  const handleRenameSubmit = async (sessionId) => {
    if (!newSessionName.trim()) {
      alert('Tên session không được để trống');
      return;
    }

    try {
      // Gọi API để đổi tên session
      await renameSession(sessionId, newSessionName.trim());

      // Cập nhật local state
      setChatSessions(prev => ({
        ...prev,
        sessions: prev.sessions.map(s =>
          s.session_id === sessionId
            ? { ...s, session_name: newSessionName.trim() }
            : s
        )
      }));

      setIsRenaming(false);
      setRenamingSessionId(null);
      setNewSessionName('');
    } catch (error) {
      console.error('Error renaming session:', error);
      alert('Lỗi đổi tên: ' + error.message);
    }
  };

  const handleRenameCancel = () => {
    setIsRenaming(false);
    setRenamingSessionId(null);
    setNewSessionName('');
  };

  const handleDeleteClick = async () => {
    if (!menuSession) return;

    const confirmDelete = window.confirm(
      `Bạn có chắc chắn muốn xóa session "${menuSession.session_name}"?`
    );

    if (confirmDelete) {
      try {
        // Gọi API để xóa session
        await deleteSession(menuSession.session_id);

        // Cập nhật local state
        setChatSessions(prev => ({
          ...prev,
          sessions: prev.sessions.filter(s => s.session_id !== menuSession.session_id)
        }));

        // Nếu đang xem session bị xóa thì reset
        if (selectedSession === menuSession.session_id) {
          onResetChat();
          setViewHistory(false);
        }

        alert('Đã xóa session thành công');
      } catch (error) {
        console.error('Error deleting session:', error);
        alert('Lỗi xóa session: ' + error.message);
      }
    }

    handleCloseContextMenu();
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
    if (firstUserMessage && firstUserMessage?.content) {
      return firstUserMessage?.content.substring(0, 50) + (firstUserMessage?.content.length > 50 ? '...' : '');
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
          onClick={() => { onResetChat(); setViewHistory(false) }}
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
          <>
            <div className="sessions-list">
              {chatSessions?.sessions?.map((session) => (
                <div
                  key={session?.session_id}
                  className={`session-item ${selectedSession === session?.session_id ? 'active' : ''}`}
                  onClick={() => { handleSessionClick(session) }}
                >
                  <div className="session-header">
                    <span className="session-icon" style={{ paddingLeft: '10px' }}>
                      <ChatBubbleOutlineIcon sx={{ fontSize: 15 }} />
                    </span>
                    <div className="session-info">
                      {isRenaming && renamingSessionId === session.session_id ? (
                        <div className="session-rename" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="text"
                            className="rename-input"
                            value={newSessionName}
                            onChange={(e) => setNewSessionName(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                handleRenameSubmit(session.session_id);
                              } else if (e.key === 'Escape') {
                                handleRenameCancel();
                              }
                            }}
                            autoFocus
                          />
                          <div className="rename-actions">
                            <button
                              className="btn-rename-save"
                              onClick={() => handleRenameSubmit(session.session_id)}
                            >
                              ✓
                            </button>
                            <button
                              className="btn-rename-cancel"
                              onClick={handleRenameCancel}
                            >
                              ✕
                            </button>
                          </div>
                        </div>
                      ) : (
                        <>
                          <div className="session-preview">
                            {session?.session_name}
                          </div>
                          <div className="session-date">
                            {formatDate(session.last_updated || session.created_at)}
                          </div>
                        </>
                      )}
                    </div>
                    <IconButton
                      size="small"
                      className="session-menu-btn"
                      onClick={(e) => handleContextMenu(e, session)}
                    >
                      <MoreVertIcon sx={{ fontSize: 18 }} />
                    </IconButton>
                  </div>
                </div>
              ))}
            </div>
            <Menu
              open={contextMenu !== null}
              onClose={handleCloseContextMenu}
              anchorReference="anchorPosition"
              anchorPosition={
                contextMenu !== null
                  ? { top: contextMenu.mouseY, left: contextMenu.mouseX }
                  : undefined
              }
            >
              <MenuItem onClick={handleRenameClick}>
                <ListItemIcon>
                  <EditIcon fontSize="small" />
                </ListItemIcon>
                <ListItemText>Đổi tên</ListItemText>
              </MenuItem>
              <MenuItem onClick={handleDeleteClick}>
                <ListItemIcon>
                  <DeleteIcon fontSize="small" color="error" />
                </ListItemIcon>
                <ListItemText>Xóa</ListItemText>
              </MenuItem>
            </Menu>
          </>
        )}
      </div>
      <div className="sidebar-footer">
        {emailUser ? `${emailUser}` : 'Chưa có Email người dùng'}
      </div>
    </div >
  );
}

export default Sidebar;