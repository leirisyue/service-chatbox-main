import React from 'react';
import ProductCard from './ProductCard';
import MaterialCard from './MaterialCard';

function Message({ message }) {
  const isUser = message.role === 'user';
  
  const renderContent = () => {
    if (typeof message.content === 'string') {
      return message.content.split('\n').map((line, i) => (
        <React.Fragment key={i}>
          {line}
          {i < message.content.split('\n').length - 1 && <br />}
        </React.Fragment>
      ));
    }
    return message.content;
  };

  return (
    <div className={`message ${isUser ? 'user-message' : 'bot-message'}`}>
      <div className="message-avatar">
        {isUser ? '👤' : '🤖'}
      </div>
      <div className="message-content">
        <div className="message-text">
          {renderContent()}
        </div>
        
        {/* Hiển thị sản phẩm */}
        {!isUser && message.data?.products && (
          <div className="products-section">
            <h3>📦 Kết quả tìm kiếm sản phẩm ({message.data.products.length} sản phẩm)</h3>
            <div className="products-grid">
              {message.data.products.slice(0, 9).map((product, index) => (
                <ProductCard
                  key={index}
                  product={product}
                  onMaterialClick={() => {/* Handle click */}}
                  onPriceClick={() => {/* Handle click */}}
                />
              ))}
            </div>
          </div>
        )}
        
        {/* Hiển thị vật liệu */}
        {!isUser && message.data?.materials && (
          <div className="materials-section">
            <h3>🧱 Kết quả tìm kiếm nguyên vật liệu ({message.data.materials.length} vật liệu)</h3>
            <div className="materials-grid">
              {message.data.materials.slice(0, 9).map((material, index) => (
                <MaterialCard
                  key={index}
                  material={material}
                  onDetailClick={() => {/* Handle click */}}
                />
              ))}
            </div>
          </div>
        )}
        
        {/* Hiển thị chi tiết vật liệu */}
        {!isUser && message.data?.material_detail && (
          <div className="material-detail-section">
            <h3>🧱 Chi tiết nguyên vật liệu</h3>
            {/* Thêm chi tiết vật liệu ở đây */}
          </div>
        )}
      </div>
    </div>
  );
}

export default Message;