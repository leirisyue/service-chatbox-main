import ImageSearchIcon from '@mui/icons-material/ImageSearch';
import IconButton from '@mui/material/IconButton';
import { useRef } from 'react';
import './Input.css';

function ImageUpload({ onImageUpload, disabled }) {
  const fileInputRef = useRef(null);

  const handleButtonClick = () => {
    if (!disabled && fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  const handleFileSelect = (e) => {
    const file = e.target.files[0];
    if (file && !disabled) {
      onImageUpload(file);
      e.target.value = '';
    }
  };

  return (
    <>
      <input
        type="file"
        ref={fileInputRef}
        accept="image/png,image/jpeg,image/jpg"
        onChange={handleFileSelect}
        style={{ display: 'none' }}
        disabled={disabled}
      />
      <IconButton
        aria-label="upload image"
        size="large"
        onClick={handleButtonClick}
        disabled={disabled}
        title="📷 Upload ảnh để tìm sản phẩm tương tự"
        color="primary"
      >
        <ImageSearchIcon />
      </IconButton>
    </>
  );
}

export default ImageUpload;