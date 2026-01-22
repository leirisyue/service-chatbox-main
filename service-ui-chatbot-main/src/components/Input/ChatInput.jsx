import React, { useState } from 'react';
import './Input.css';
import ImageUpload from './ImageUpload';
import SendIcon from '@mui/icons-material/Send';
import Button from '@mui/material/Button';

function ChatInput({ onSendMessage, onImageUpload, onImageWithTextUpload, disabled, lastMessage }) {
  const [inputValue, setInputValue] = useState('');
  const [selectedImage, setSelectedImage] = useState(null);
  const [imagePreview, setImagePreview] = useState(null);

  const checkNumberInText = (text, kt) => {
    const numbers = text.match(/\d+/g)?.map(Number) || [];
    return numbers.includes(kt);
  };

  const handleSubmit = (e) => {
    e.preventDefault();
    
    // Trường hợp có cả ảnh và text
    if (selectedImage && inputValue.trim() && !disabled) {
      onImageWithTextUpload(selectedImage, inputValue.trim());
      setSelectedImage(null);
      setImagePreview(null);
      setInputValue('');
      return;
    }
    
    // Trường hợp chỉ có ảnh
    if (selectedImage && !disabled) {
      onImageUpload(selectedImage);
      setSelectedImage(null);
      setImagePreview(null);
      setInputValue('');
      return;
    }

    if (!!inputValue && inputValue.trim() && !disabled) {

      if (!!lastMessage && lastMessage?.data?.suggested_prompts_mess && lastMessage?.data?.success) {

        const list = lastMessage?.data?.suggested_prompts_mess
          .split("•")
          .map(item => item.trim())
          .filter(item => item.length > 0);

        let text = ""
        if (checkNumberInText(inputValue, 1)) {
          text = list[0];
        }
        if (checkNumberInText(inputValue, 2)) {
          text = text + (text ? " " : "") + list[1];
        }
        if (checkNumberInText(inputValue, 3)) {
          text = text + (text ? " " : "") + list[2];
        }

        if (text) {
          onSendMessage(text);
          setInputValue('');
          return;
        }
      }
      
      onSendMessage(inputValue);
      setInputValue('');
    }
  };

  const handleImageSelect = (file) => {
    if (file) {
      setSelectedImage(file);
      const reader = new FileReader();
      reader.onloadend = () => {
        setImagePreview(reader.result);
      };
      reader.readAsDataURL(file);
    }
  };

  const handleRemoveImage = () => {
    setSelectedImage(null);
    setImagePreview(null);
  };

  const handleKeyPress = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  return (
    <div style={{ width: '100%' }}>
      {imagePreview && (
        <div className="image-preview-container">
          <div className="image-preview-wrapper">
            <img src={imagePreview} alt="Preview" className="image-preview" />
            <button
              type="button"
              onClick={handleRemoveImage}
              className="remove-image-button"
              title="Xóa ảnh"
            >
              ✕
            </button>
          </div>
          <div className="image-preview-hint">📷 Bạn có thể thêm mô tả hoặc nhấn "Gửi" để tìm kiếm</div>
        </div>
      )}

      <form className="chat-input-form" onSubmit={handleSubmit}>
        <ImageUpload onImageUpload={handleImageSelect} disabled={disabled} />
        <input
          type="text"
          value={inputValue}
          onChange={(e) => setInputValue(e.target.value)}
          onKeyPress={handleKeyPress}
          placeholder="Nhập câu hỏi của bạn... (VD: Tìm bàn tròn gỗ sồi, hoặc Tìm gỗ làm bàn...)"
          disabled={disabled}
          className="chat-input"
        />
        <Button
          type="submit"
          disabled={(!inputValue.trim() && !selectedImage) || disabled}
          className="send-button"
          endIcon={<SendIcon />}
          variant="contained"
          color="primary"
        > Gửi
        </Button>
      </form>
    </div>
  );
}

export default ChatInput;