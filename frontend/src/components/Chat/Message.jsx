import React, { useEffect, useRef, useState } from 'react';
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

function Message({ message, onSendMessage, typing }) {
  const isUser = message.role === 'user';

  const [displayedText, setDisplayedText] = useState(message.content || "");
  const [typingDone, setTypingDone] = useState(true);

  const hasMountedRef = useRef(false);
  const bottomRef = useRef(null);

  /* =========================
      TYPING EFFECT
  ========================= */
  useEffect(() => {
    if (!typing) return;
    if (isUser || typeof message.content !== 'string') {
      setDisplayedText(message.content);
      setTypingDone(true);
      hasMountedRef.current = true;
      return;
    }

    // render lần đầu (reload / history)
    if (!hasMountedRef.current) {
      setDisplayedText(message.content);
      setTypingDone(true);
      hasMountedRef.current = true;
      return;
    }

    // message mới → typing
    setDisplayedText("");
    setTypingDone(false);

    let index = 0;
    const text = message.content;

    const interval = setInterval(() => {
      setDisplayedText((prev) => prev + text.charAt(index));
      index++;

      if (index >= text.length) {
        clearInterval(interval);
        setTypingDone(true);
      }
    }, 15);

    return () => clearInterval(interval);

  }, [typing]);

  /* =========================
      AUTO SCROLL THEO TYPING
  ========================= */
  useEffect(() => {
    if (!bottomRef.current) return;

    bottomRef.current.scrollIntoView({
      behavior: 'smooth',
      block: 'end',
    });
  }, [displayedText]);

  /* =========================
      ACTION HANDLERS
  ========================= */
  const handleMaterialClick = (headcode) => {
    onSendMessage?.(`Phân tích nguyên vật liệu sản phẩm ${headcode}`);
  };

  const handlePriceClick = (headcode) => {
    onSendMessage?.(`Tính chi phí sản phẩm ${headcode}`);
  };

  const handleMaterialDetailClick = (materialName) => {
    onSendMessage?.(`Chi tiết vật liệu ${materialName}`);
  };

  const renderContent = () => (
    <div className={message.type === 'welcome' ? 'welcome-md' : ''}>
      <ReactMarkdown
        remarkPlugins={[remarkGfm, remarkBreaks]}
        rehypePlugins={[
          rehypeRaw,
          [rehypeSanitize, schemaMarkdown],
        ]}
      >
        {displayedText}
      </ReactMarkdown>
    </div>
  );

  return (
    <div className={`message ${isUser ? 'user-message' : 'bot-message'}`}>
      <div className="message-avatar">
        {isUser ? '👤' : '🤖'}
      </div>

      <div className="message-content">
        <div className="message-text">
          <div style={{ paddingBottom: '15px' }}>
            {formatTimestamp(message?.timestamp)}
          </div>
          {renderContent()}
          <div ref={bottomRef} />
        </div>

        {/* PRODUCTS */}
        {!isUser && typingDone && message.data?.products && (
          <div className="products-section fade-in">
            <h3>
              📦 Kết quả tìm kiếm sản phẩm ({message.data.products.length})
            </h3>
            <Grid container spacing={2}>
              {message.data.products.slice(0, 9).map((product, index) => (
                <Grid key={index} size={{ xs: 12, md: 6 }}>
                  <Box sx={{ height: '100%' }}>
                    <ProductCard
                      product={product}
                      onMaterialClick={() => handleMaterialClick(product.headcode)}
                      onPriceClick={() => handlePriceClick(product.headcode)}
                    />
                  </Box>
                </Grid>
              ))}
            </Grid>
          </div>
        )}

        {/* MATERIALS */}
        {!isUser && typingDone && message.data?.materials && (
          <div className="materials-section fade-in">
            <Grid container spacing={2}>
              {message.data.materials.slice(0, 9).map((material, index) => (
                <Grid key={index} size={{ xs: 12, md: 6, lg: 4 }}>
                  <Box sx={{ height: '100%' }}>
                    <MaterialCard
                      material={material}
                      onDetailClick={() =>
                        handleMaterialDetailClick(material.material_name)
                      }
                    />
                  </Box>
                </Grid>
              ))}
            </Grid>
          </div>
        )}
      </div>
    </div>
  );
}

export default Message;
