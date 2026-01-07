import { useAtom } from 'jotai';
import { useEffect, useRef, useState } from 'react';
import { messagesAtom } from '../../atom/messageAtom';
import { batchProducts, exportBOMReport, trackReject, trackView } from '../../services/api';
import { formatTimestamp } from '../../utils/helpers';
import ProductListWithFeedback from './ProductListWithFeedback';

import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { schemaMarkdown } from '../../utils/mardownhtml';

function Message({ message, onSendMessage, typing }) {
  // console.log("🚀 ~ Message ~ message:", message);
  const isUser = message.role === 'user';

  const [displayedText, setDisplayedText] = useState(message.content || "");
  const [typingDone, setTypingDone] = useState(true);
  const [selectedProducts, setSelectedProducts] = useState([]);
  const [feedbackSelected, setFeedbackSelected] = useState([]);

  const [, setMessages] = useAtom(messagesAtom);

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

  const handleToggleSelected = (headcode) => {
    setSelectedProducts((prev) =>
      prev.includes(headcode)
        ? prev.filter((h) => h !== headcode)
        : [...prev, headcode]
    );
  };

  const handleToggleFeedback = (headcode) => {
    setFeedbackSelected((prev) =>
      prev.includes(headcode)
        ? prev.filter((h) => h !== headcode)
        : [...prev, headcode]
    );
  };

  const sessionId = typeof window !== 'undefined'
    ? window.localStorage.getItem('chat_session_id')
    : null;

  const appendBotExchange = (userText, botData) => {
    const userMessage = {
      role: 'user',
      content: userText,
      timestamp: Date.now(),
    };

    const botMessage = {
      role: 'bot',
      content: botData?.response || 'Xin lỗi, tôi không hiểu.',
      data: botData,
      suggested_prompts_message: botData?.suggested_prompts_message || [],
      timestamp: Date.now(),
    };

    setMessages((prev) => [...prev, userMessage, botMessage]);
  };

  const handleBatchOperation = async (operation) => {
    if (!sessionId || selectedProducts.length === 0) return;

    try {
      if (operation === 'detail') {
        // Track view cho từng sản phẩm được chọn
        await Promise.all(
          selectedProducts.map((hc) => trackView(sessionId, hc))
        );
      }

      const result = await batchProducts(sessionId, selectedProducts, operation);

      let userTextPrefix = '';
      if (operation === 'detail') userTextPrefix = '📋 Xem chi tiết';
      else if (operation === 'materials') userTextPrefix = '🧱 Xem định mức';
      else if (operation === 'cost') userTextPrefix = '💰 Xem chi phí';

      const userText = `${userTextPrefix} ${selectedProducts.length} sản phẩm`;
      appendBotExchange(userText, result);
    } catch (error) {
      console.error('Batch operation error:', error);
      appendBotExchange(
        '⚠️ Lỗi khi thực hiện thao tác hàng loạt',
        { response: '⚠️ Lỗi khi thực hiện thao tác hàng loạt. Vui lòng thử lại.' }
      );
    }
  };

  const handleReject = async () => {
    if (!sessionId) return;

    const products = message.data?.products || [];
    try {
      await Promise.all(
        products.slice(0, 5).map((p) =>
          p.headcode ? trackReject(sessionId, p.headcode) : Promise.resolve()
        )
      );
    } catch (error) {
      console.error('Error tracking reject:', error);
    }

    const originalQuery = message.data?.query || '';
    onSendMessage?.(
      `Tìm thêm sản phẩm tương tự nhưng khác với kết quả vừa rồi: ${originalQuery}`
    );
  };

  const handleExportBOM = async () => {
    if (!sessionId || selectedProducts.length === 0) return;

    try {
      const blob = await exportBOMReport(sessionId, selectedProducts);
      const url = window.URL.createObjectURL(blob);
      const a = document.createElement('a');
      a.href = url;
      a.download = `BOM_${selectedProducts.length}SP.xlsx`;
      document.body.appendChild(a);
      a.click();
      a.remove();
      window.URL.revokeObjectURL(url);
    } catch (error) {
      console.error('Export BOM error:', error);
      appendBotExchange(
        '📊 Xuất BOM',
        { response: '❌ Lỗi khi tạo báo cáo BOM. Vui lòng thử lại.' }
      );
    }
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


          {/* MATERIALS */}
          {/* {!isUser && typingDone && message.data?.materials?.length > 0 && (
          <div className="materials-section fade-in">
            <h3>
              📦 Kết quả tìm kiếm vật liệu ({message.data.materials.length})
            </h3>
            <Grid container spacing={2}>
              {message.data.materials.slice(0, 9).map((material, index) => (
                <Grid key={index} size={{ xs: 12, md: 6 }}>
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
        )} */}

          {/* PRODUCTS – giao diện mới với feedback & debug */}
          {!isUser && typingDone && message.data?.products?.length > 0 && (
            <>
              <ProductListWithFeedback
                products={message.data.products}
                onMaterialClick={handleMaterialClick}
                onPriceClick={handlePriceClick}
                selectedProducts={selectedProducts}
                onToggleSelected={handleToggleSelected}
                feedbackSelected={feedbackSelected}
                onToggleFeedback={handleToggleFeedback}
              />
              <div className="batch-actions">
                <hr />
                {selectedProducts.length > 0 ? (
                  <>
                    <div className="batch-actions-row">
                      <button
                        className="batch-btn primary"
                        onClick={() => handleBatchOperation('detail')}
                      >
                        📋 Chi tiết SP
                      </button>
                      <button
                        className="batch-btn primary"
                        onClick={() => handleBatchOperation('materials')}
                      >
                        🧱 Định mức VL
                      </button>
                      <button
                        className="batch-btn primary"
                        onClick={() => handleBatchOperation('cost')}
                      >
                        💰 Chi phí
                      </button>
                    </div>
                    <div className="batch-actions-row">
                      {/* <button
                        className="batch-btn secondary"
                        onClick={handleReject}
                      >
                        🔄 Xem cái khác
                      </button> */}
                      <button
                        className="batch-btn secondary"
                        onClick={handleExportBOM}
                      >
                        📊 Xuất BOM
                      </button>
                    </div>
                  </>
                ) : (
                  <div className="batch-hint">
                    💡 Tích chọn sản phẩm để xem chi tiết, định mức, hoặc xuất báo cáo
                  </div>
                )}
              </div>
            </>
          )}
                    {/* <div>{message?.data?.suggested_prompts_mess || ''}</div> */}
          {!!message?.data?.suggested_prompts_mess ?? <div className="welcome-md">
            <b>💡 Gợi ý cho bạn:</b>
            <ReactMarkdown
              remarkPlugins={[remarkGfm, remarkBreaks]}
              rehypePlugins={[
                rehypeRaw,
                [rehypeSanitize, schemaMarkdown],
              ]}
            >
              {message.data.suggested_prompts_mess}
            </ReactMarkdown>
            "Trên đây là gợi ý dành riêng cho bạn. Bạn có thể hỏi thêm bất cứ điều gì khác nhé! Tôi sẵn sàng hỗ trợ."
          </div>}
        </div>
      </div>

    </div>
  );
}

export default Message;
