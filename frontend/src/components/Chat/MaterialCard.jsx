import React, { useState, useEffect } from 'react';

function MaterialCard({ material, onDetailClick }) {
  const [imageUrl, setImageUrl] = useState(null);

  useEffect(() => {
    const convertGDriveUrl = (url) => {
      if (!url || !url.includes('drive.google.com')) return url;
      
      try {
        let fileId;
        if (url.includes('/file/d/')) {
          fileId = url.split('/file/d/')[1].split('/')[0];
        } else if (url.includes('id=')) {
          fileId = url.split('id=')[1].split('&')[0];
        } else {
          return url;
        }
        
        return `https://drive.google.com/uc?export=view&id=${fileId}`;
      } catch {
        return url;
      }
    };

    if (material.image_url) {
      setImageUrl(convertGDriveUrl(material.image_url));
    }
  }, [material.image_url]);

  return (
    <div className="material-card">
      <div className="material-image">
        {imageUrl ? (
          <img 
            src={imageUrl} 
            alt={material.material_name} 
            onError={() => setImageUrl(null)}
          />
        ) : (
          <div className="material-placeholder">
            🧱
          </div>
        )}
      </div>
      
      <div className="material-info">
        <h4>{material.material_name?.slice(0, 40)}...</h4>
        <p className="material-code">🏷️ Mã SAP: <strong>{material.id_sap}</strong></p>
        <p className="material-group">📂 Nhóm: {material.material_group || 'N/A'}</p>
        
        <div className="price-badge">
          💰 {material.price?.toLocaleString('vi-VN') || '0'} VNĐ/{material.unit || ''}
        </div>
      </div>
      
      <div className="material-actions">
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