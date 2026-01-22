import { useState } from 'react';
import { convertGDriveUrl } from '../../utils/gdrive';

function MaterialCard({ material, onDetailClick }) {
  const [imgError, setImgError] = useState(false);
  const imageSrc = `https://lh3.googleusercontent.com/d/1syoH7m_FmZWfZgXyGkk5427jOFqq020o`;
  const shouldShowPlaceholder = !material?.image_url || imgError;

  return (
    <div className="material-card" style={{ position: 'relative' }}>
      <div className="material-image">
        {material?.image_url && (
          <img
            src={convertGDriveUrl(material?.image_url)}
            alt={imageSrc || "Material image"}
            loading="lazy"
            onError={() => {
              setImgError(true);
            }}
            style={{ display: 'block' }}
          />
        )}
        {shouldShowPlaceholder && (
          <div className="material-placeholder">
            🧱
          </div>
        )}
      </div>
      <div className="material-info">
        <h4 title={material.material_name} className="ellipsis" >
          {material.material_name}
        </h4>
        <p className="material-code" title={`Mã SAP: ${material.id_sap}`}>
          🏷️ Mã SAP: <strong>{material.id_sap}</strong>
        </p>
        <p className="material-group" title={`Nhóm: ${material.material_group || ''}`}>
          📂 Nhóm: {material.material_group || ''}
        </p>
        {(!!material.price || !!material.total_cost) ?
          <div className="price-badge" title={`Giá: ${material.total_cost?.toLocaleString('vi-VN')+' VNĐ' || material.price?.toLocaleString('vi-VN')+' VNĐ' || ''} `}>
            💰 {material.total_cost?.toLocaleString('vi-VN') || material.price?.toLocaleString('vi-VN')} VNĐ {material.unit ? "/" + material.unit : '' || ''}
          </div>
          : <div className="price-badge no-price" title="Chưa có giá">❓Liên hệ</div>}
      </div>
      <div className="material-actions" style={{ position: 'absolute', bottom: '10px', width: '94%' }}>
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