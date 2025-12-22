import React, { useState } from 'react';
import MediaImage from './MediaImage';
import { convertGDriveUrl } from '../../utils/gdrive';

function MaterialCard({ material, onDetailClick }) {
  // State to track if the main image fails to load
  const [imgError, setImgError] = useState(false);

  // 1. Try material's image, 2. Fallback to default, 3. Show placeholder on error
  const imageSrc = `https://lh3.googleusercontent.com/d/1syoH7m_FmZWfZgXyGkk5427jOFqq020o`;

  // Decide what to show
  const shouldShowImage = imageSrc;
  const shouldShowPlaceholder = !material?.image_url || imgError;

  return (
    <div className="material-card" style={{ position: 'relative' }}>
      <div className="material-image">
        {/* Show image only if we have a source and no error */}
        {material?.image_url && (
          <img
            src={convertGDriveUrl(material?.image_url)}
            alt={imageSrc || "Material image"}
            loading="lazy"
            onError={() => {
              setImgError(true); // Simple state update on error
            }}
            style={{ display: 'block' }}
          />
        )}

        {/* Show placeholder if no image source or image failed to load */}
        {shouldShowPlaceholder && (
          <div className="material-placeholder">
            🧱
          </div>
        )}
        {/* <MediaImage
          imageUrl={material.image_url}
          alt={material.material_name}
        /> */}
      </div>
      <div className="material-info">
        <h4>{material.material_name}</h4>
        <p className="material-code">🏷️ Mã SAP: <strong>{material.id_sap}</strong></p>
        <p className="material-group">📂 Nhóm: {material.material_group || 'N/A'}</p>
        {(!!material.price || !!material.total_cost) ? <div className="price-badge">
          💰 {material.total_cost?.toLocaleString('vi-VN') || material.price?.toLocaleString('vi-VN')} VNĐ {material.unit ? "/" + material.unit : ''}
        </div>
          : null}
      </div>
      <div className="material-actions" style={{ position: 'absolute', bottom: '10px', width: '90%' }}>
        <button
          className="btn-detail"
          onClick={onDetailClick}
        >
          🔍 Chi tiết
        </button>
        {material.image_url && (
          <a
            href={material.image_url}
            target="_blank"
            rel="noopener noreferrer"
            className="btn-drive"
          >
            🔗 Drive
          </a>
        )}
      </div>
    </div>
  );
}

export default MaterialCard;