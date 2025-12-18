import React from 'react';

function ProductCard({ product, onMaterialClick, onPriceClick }) {
  return (
    <div className="product-card">
      <div className="product-header">
        <h4>{product.product_name?.slice(0, 50)}...</h4>
        <span className="product-code">🏷️ {product.headcode}</span>
      </div>
      
      <div className="product-details">
        <p>📦 {product.category || 'N/A'} - {product.sub_category || 'N/A'}</p>
        <p>🪵 {product.material_primary || 'N/A'}</p>
        {product.project && <p>🗝️ Dự án: {product.project}</p>}
      </div>
      
      <div className="product-actions">
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