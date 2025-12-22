import React from 'react';
import ProductCard from './ProductCard';
import MaterialCard from './MaterialCard';
import Grid from '@mui/material/Grid';
import Box from '@mui/material/Box';
import { formatTimestamp } from '../../utils/helpers';
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkBreaks from "remark-breaks";
import { schemaMarkdown } from '../../utils/mardownhtml';


function Message({ message, onSendMessage }) {
  const isUser = message.role === 'user';

  // Handle click for material button
  const handleMaterialClick = (headcode) => {
    if (onSendMessage) {
      onSendMessage(`Phân tích nguyên vật liệu sản phẩm ${headcode}`);
    }
  };

  // Handle click for price button
  const handlePriceClick = (headcode) => {
    if (onSendMessage) {
      onSendMessage(`Tính chi phí sản phẩm ${headcode}`);
    }
  };

  // Handle click for material detail button
  const handleMaterialDetailClick = (materialName) => {
    if (onSendMessage) {
      onSendMessage(`Chi tiết vật liệu ${materialName}`);
    }
  };

  const renderContent = () => {
    // if (typeof message.content === 'string') {
    //   return message.content.split('\n').map((line, i) => (
    //     <React.Fragment key={i}>
    //       {line}
    //       {i < message.content.split('\n').length - 1 && <br />}
    //     </React.Fragment>
    //   ));
    // }
    // return message.content;

    return (
      <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkBreaks]}
      rehypePlugins={[
        rehypeRaw,
        [rehypeSanitize, schemaMarkdown],
      ]}
    >
        {message.content}
      </ReactMarkdown>
    );
  };

  return (
    <div className={`message ${isUser ? 'user-message' : 'bot-message'}`}>
      <div className="message-avatar">
        {isUser ? '👤' : '🤖'}
      </div>
      <div className="message-content">
        <div className="message-text">
          {formatTimestamp(message?.timestamp)}
          <br />
          <br />
          {renderContent()}
        </div>

        {/* Hiển thị sản phẩm */}
        {!isUser && message.data?.products && (
          <div className="products-section">
            <h3>📦 Kết quả tìm kiếm sản phẩm ({message?.data?.products?.length} sản phẩm)</h3>
            <Grid container spacing={2}>
              {/* <div className="products-grid"> */}
              {message.data.products.slice(0, 9).map((product, index) => (
                <Grid size={{ xs: 12, md: 6 }}>
                  <Box sx={{ height: '100%' }}>
                    <ProductCard
                      key={index}
                      product={product}
                      onMaterialClick={() => handleMaterialClick(product.headcode)}
                      onPriceClick={() => handlePriceClick(product.headcode)}
                    />
                  </Box>
                </Grid>
              ))}
              {/* </div> */}
            </Grid>
          </div>
        )}

        {/* Hiển thị vật liệu */}
        {!isUser && message.data?.materials && (
          <div className="materials-section">
            <h3>🧱 Kết quả tìm kiếm nguyên vật liệu ({message.data.materials.length} vật liệu)</h3>
            <Grid container spacing={2}>
              {message.data.materials.slice(0, 9).map((material, index) => (
                <Grid size={{ xs: 12, md: 6, lg: 4 }}>
                  <Box sx={{ height: '100%' }}>
                    <MaterialCard
                      key={index}
                      material={material}
                      onDetailClick={() => handleMaterialDetailClick(material.material_name)}
                    />
                  </Box>
                </Grid>
              ))}
            </Grid>
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