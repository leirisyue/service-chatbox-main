import React, { useRef, useState } from 'react';
import './Input.css';

function ImageUpload({ onImageUpload, disabled }) {
  const fileInputRef = useRef(null);
  const [previewUrl, setPreviewUrl] = useState(null);

  const handleFileSelect = (e) => {
    const file = e.target.files[0];
    if (file) {
      const reader = new FileReader();
      reader.onloadend = () => {
        setPreviewUrl(reader.result);
      };
      reader.readAsDataURL(file);
    }
  };

  const handleUpload = () => {
    if (fileInputRef.current?.files[0] && !disabled) {
      onImageUpload(fileInputRef.current.files[0]);
      setPreviewUrl(null);
      fileInputRef.current.value = '';
    }
  };

  const handleCancel = () => {
    setPreviewUrl(null);
    if (fileInputRef.current) {
      fileInputRef.current.value = '';
    }
  };

  return (
    <div className="image-upload">
      <input
        type="file"
        ref={fileInputRef}
        accept="image/*"
        onChange={handleFileSelect}
        className="file-input"
        disabled={disabled}
      />
      
      {previewUrl ? (
        <div className="image-preview">
          <img src={previewUrl} alt="Preview" />
          <div className="preview-actions">
            <button 
              type="button" 
              onClick={handleUpload}
              className="btn-upload"
              disabled={disabled}
            >
              🔍 Tìm sản phẩm tương tự
            </button>
            <button 
              type="button" 
              onClick={handleCancel}
              className="btn-cancel"
            >
              ✕
            </button>
          </div>
        </div>
      ) : (
        <div className="upload-placeholder">
          <span>📷 Hoặc upload ảnh sản phẩm để tìm kiếm</span>
        </div>
      )}
    </div>
  );
}

export default ImageUpload;