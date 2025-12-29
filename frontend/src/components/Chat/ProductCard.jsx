import React from 'react';

function ProductCard({ product, onMaterialClick, onPriceClick }) {
  
  return (
    <div className="product-card" style={{ position: 'relative' }}>
      <div className="product-header">
        <h4>{product.product_name?.slice(0, 50)}</h4>
        <span className="product-code">🏷️ {product.headcode}</span>
      </div>

      <div className="product-details">
        <p>📦 {product.category || ''} - {product.sub_category || ''}</p>
        <p>🪵 {product.material_primary || ''}</p>
        {!!product.project && <p style={{whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          width: '100%'}} title={`🗂️ Dự án: ${product.project}`}>🗂️ Dự án: {product.project}</p>}
      </div>
      <div className="product-actions" style={{ position: 'absolute', width: '90%', bottom: '15px' }}>
        <button
          className="btn-material"
          onClick={onMaterialClick}
        >
          📋 Vật liệu
        </button>
        <button
          className="btn-price"
          onClick={onPriceClick}
        >
          💰 Chi phí
        </button>
      </div>
    </div>
  );
}

export default ProductCard;