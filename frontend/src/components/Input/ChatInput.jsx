import React, { useState } from 'react';
import './Input.css';
import ImageUpload from './ImageUpload';

function ChatInput({ onSendMessage, onImageUpload, disabled }) {
  const [inputValue, setInputValue] = useState('');

  const handleSubmit = (e) => {
    e.preventDefault();
    if (inputValue.trim() && !disabled) {
      onSendMessage(inputValue);
      setInputValue('');
    }
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <form className="chat-input-form" onSubmit={handleSubmit}>
      <ImageUpload onImageUpload={onImageUpload} disabled={disabled} />
      <input
        type="text"
        value={inputValue}
        onChange={(e) => setInputValue(e.target.value)}
        onKeyPress={handleKeyPress}
        placeholder="Nhập câu hỏi của bạn... (VD: Tìm bàn tròn gỗ sồi, hoặc Tìm gỗ làm bàn...)"
        disabled={disabled}
        className="chat-input"
      />
      <button
        type="submit"
        disabled={!inputValue.trim() || disabled}
        className="send-button"
      >
        📤 Gửi
      </button>
    </form>
  );
}

export default ChatInput;