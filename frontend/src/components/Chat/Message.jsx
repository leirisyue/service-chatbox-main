import { useAtom } from 'jotai';
import { useEffect, useRef, useState } from 'react';
import { messagesAtom } from '../../atom/messageAtom';
import { batchProducts, exportBOMReport, trackReject, trackView } from '../../services/api';
import { formatTimestamp } from '../../utils/helpers';
import ProductListWithFeedback from './ProductList';

import ReactMarkdown from "react-markdown";
import rehypeRaw from "rehype-raw";
import rehypeSanitize from "rehype-sanitize";
import remarkBreaks from "remark-breaks";
import remarkGfm from "remark-gfm";
import { schemaMarkdown } from '../../utils/mardownhtml';

import TabContext from '@mui/lab/TabContext';
import TabList from '@mui/lab/TabList';
import TabPanel from '@mui/lab/TabPanel';
import Box from '@mui/material/Box';
import Tab from '@mui/material/Tab';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import * as React from 'react';
import { convertGDriveUrl } from '../../utils/gdrive';
import ProductList from './ProductList';
import MaterialList from './MaterialList';

function Message({ message, onSendMessage, typing }) {

  const isUser = message?.role === 'user';

  const [displayedText, setDisplayedText] = useState(message?.content || "");
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
    if (isUser || typeof message?.content !== 'string') {
      setDisplayedText(message?.content);
      setTypingDone(true);
      hasMountedRef.current = true;
      return;
    }

    // render lần đầu (reload / history)
    if (!hasMountedRef.current) {
      setDisplayedText(message?.content);
      setTypingDone(true);
      hasMountedRef.current = true;
      return;
    }

    // message mới → typing
    setDisplayedText("");
    setTypingDone(false);

    let index = 0;
    const text = message?.content;

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
      content: botData?.response || 'Thành thật xin lỗi, tôi không hiểu yêu cầu của bạn.',
      data: botData,
      suggested_prompts_mess: botData?.suggested_prompts_mess || [],
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

    const products = message?.data?.products || [];
    try {
      await Promise.all(
        products.slice(0, 5).map((p) =>
          p.headcode ? trackReject(sessionId, p.headcode) : Promise.resolve()
        )
      );
    } catch (error) {
      console.error('Error tracking reject:', error);
    }

    const originalQuery = message?.data?.query || '';
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
    <div className={message?.type === 'welcome' ? 'welcome-md' : ''}>
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

  const [value, setValue] = React.useState('1');

  const handleChange = (event: React.SyntheticEvent, newValue: string) => {
    setValue(newValue);
  };

  return (
    <div className={`message ${isUser ? 'user-message' : 'bot-message'}`}>
      <div className="message-avatar">
        {isUser ? '👤' : '🤖'}
      </div>

      <div className="message-content">
        <div className="message-text">
          <div>
            {formatTimestamp(message?.timestamp)}
          </div>
          {message?.imageUrl && (
            <div className="message-image">
              <img src={message?.imageUrl} alt="Uploaded" width={300} />
            </div>
          )}
          {message.imageUrl && isUser && message?.content && (
            <div className="message-text-with-image">
              {message?.content}
            </div>
          )}
          {!message?.imageUrl && renderContent()}
          {message?.imageUrl && !isUser && renderContent()}
          <div ref={bottomRef} />
          {!isUser && (!!message?.data?.materials?.length || !!message.data?.products?.length) && typingDone &&
            <Box sx={{ width: '100%', typography: 'body1' }}>
              <TabContext value={value}>
                <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
                  <TabList onChange={handleChange} aria-label="lab API tabs example">
                    <Tab label="View table" value="1" />
                    <Tab label="View List" value="2" />
                  </TabList>
                </Box>
                <TabPanel value="1">
                  {!!message.data?.materials?.length &&
                    <TableContainer >
                      <Table sx={{ minWidth: 650 }} aria-label="simple table">
                        <TableHead>
                          <TableRow>
                            <TableCell>STT</TableCell>
                            <TableCell></TableCell>
                            <TableCell>Tên vật liệu</TableCell>
                            <TableCell>Mã SAP</TableCell>
                            <TableCell>Nhóm</TableCell>
                            <TableCell>Số lượng</TableCell>
                            <TableCell>Đơn giá mới nhất (VNĐ)</TableCell>
                            <TableCell>Thành tiền (VNĐ)</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {message.data?.materials?.map((row, index) => (
                            <TableRow key={index}>
                              <TableCell>{index + 1}</TableCell>
                              <TableCell> {row?.image_url ? <img src={convertGDriveUrl(row?.image_url)} alt={row?.material_name} width={50} /> : ''}</TableCell>
                              <TableCell component="th" scope="row">{row?.material_name}</TableCell>
                              <TableCell>{row?.id_sap}</TableCell>
                              <TableCell>{row?.material_subgroup} </TableCell>
                              <TableCell>{row?.quantity}/{row?.pm_unit || row?.unit}</TableCell>
                              <TableCell>{row?.price?.toLocaleString("vi-VN") || row?.unit_price?.toLocaleString("vi-VN") || ''}</TableCell>
                              <TableCell>{row?.total_cost?.toLocaleString("vi-VN") || ''}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  }
                  {!!message.data?.products?.length &&
                    <TableContainer >
                      <Table sx={{ minWidth: 650 }} aria-label="simple table">
                        <TableHead>
                          <TableRow>
                            <TableCell>STT</TableCell>
                            <TableCell></TableCell>
                            <TableCell>Tên sản phẩm</TableCell>
                            <TableCell>Mã SAP</TableCell>
                            <TableCell>Nhóm</TableCell>
                            <TableCell>Vật liệu</TableCell>
                            <TableCell>Đơn giá mới nhất (VNĐ)</TableCell>
                            <TableCell>Dự án</TableCell>
                          </TableRow>
                        </TableHead>
                        <TableBody>
                          {message.data?.products?.map((row, index) => (
                            <TableRow key={index}>
                              <TableCell>{index + 1}</TableCell>
                              <TableCell> {row.image_url ? <img src={convertGDriveUrl(row.image_url)} alt={row.product_name} width={50} /> : ''}</TableCell>
                              <TableCell component="th" scope="row">{row.product_name}</TableCell>
                              <TableCell>{row.headcode}</TableCell>
                              <TableCell width={160}> {row.sub_category}</TableCell>
                              <TableCell width={80}>{row.material_primary}</TableCell>
                              <TableCell>{row?.total_cost?.toLocaleString("vi-VN") || ''}</TableCell>
                              <TableCell>{row.project}</TableCell>
                            </TableRow>
                          ))}
                        </TableBody>
                      </Table>
                    </TableContainer>
                  }
                </TabPanel>
                <TabPanel value="2">
                  {!isUser && typingDone && message.data?.products?.length > 0 && (
                    <>
                      <ProductList
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
                        {selectedProducts.length > 0 && (
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
                              <button
                                className="batch-btn secondary"
                                onClick={handleExportBOM}
                              >
                                📊 Xuất BOM
                              </button>
                            </div>
                          </>
                        )}
                      </div>
                    </>
                  )}
                  {!isUser && typingDone && message.data?.materials?.length > 0 && (
                    <>
                      <MaterialList
                        materials={message?.data?.materials}
                        onMaterialClick={handleMaterialDetailClick}
                      />
                    </>
                  )}
                </TabPanel>
              </TabContext>
            </Box>
          }
          {!isUser && (!!message?.data?.products_second?.length) && typingDone &&
            <>
              <div>💜 Tôi có một số <b>sản phẩm tương tự</b> với yêu cầu trên của bạn! Bạn có thể tham khảo</div>
              <Box sx={{ width: '100%', typography: 'body1' }}>
                <TabContext value={value}>
                  <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
                    <TabList onChange={handleChange} aria-label="lab API tabs example">
                      <Tab label="View table" value="1" />
                      <Tab label="View List" value="2" />
                    </TabList>
                  </Box>
                  <TabPanel value="1">
                    {!!message?.data?.products_second?.length &&
                      <TableContainer >
                        <Table sx={{ minWidth: 650 }} aria-label="simple table">
                          <TableHead>
                            <TableRow>
                              <TableCell>STT</TableCell>
                              <TableCell></TableCell>
                              <TableCell>Tên sản phẩm</TableCell>
                              <TableCell>Mã SAP</TableCell>
                              <TableCell>Nhóm</TableCell>
                              <TableCell>Vật liệu</TableCell>
                              <TableCell>Đơn giá mới nhất (VNĐ)</TableCell>
                              <TableCell>Dự án</TableCell>
                            </TableRow>
                          </TableHead>
                          <TableBody>
                            {message.data?.products_second?.map((row, index) => (
                              <TableRow key={index}>
                                <TableCell>{index + 1}</TableCell>
                                <TableCell> {row?.image_url ? <img src={convertGDriveUrl(row?.image_url)} alt={row?.product_name} width={50} /> : ''}</TableCell>
                                <TableCell component="th" scope="row">{row?.product_name}</TableCell>
                                <TableCell>{row?.headcode}</TableCell>
                                <TableCell width={160}> {row?.sub_category}</TableCell>
                                <TableCell width={80}>{row?.material_primary}</TableCell>
                                <TableCell>{row?.total_cost?.toLocaleString("vi-VN") || ''}</TableCell>
                                <TableCell>{row?.project}</TableCell>
                              </TableRow>
                            ))}
                          </TableBody>
                        </Table>
                      </TableContainer>
                    }
                  </TabPanel>
                  <TabPanel value="2">
                    {!isUser && typingDone && message?.data?.products_second?.length > 0 && (
                      <>
                        <ProductListWithFeedback
                          products={message?.data?.products_second}
                          onMaterialClick={handleMaterialClick}
                          onPriceClick={handlePriceClick}
                          selectedProducts={selectedProducts}
                          onToggleSelected={handleToggleSelected}
                          feedbackSelected={feedbackSelected}
                          onToggleFeedback={handleToggleFeedback}
                        />
                        <div className="batch-actions">
                          <hr />
                          {selectedProducts.length > 0 && (
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
                                <button
                                  className="batch-btn secondary"
                                  onClick={handleExportBOM}
                                >
                                  📊 Xuất BOM
                                </button>
                              </div>
                            </>
                          )}
                        </div>
                      </>
                    )}
                  </TabPanel>
                </TabContext>
              </Box>
            </>
          }
          {!isUser && message?.data?.success && message?.data?.suggested_prompts_mess && typingDone &&
            <>
              <div>💡 <b>Gợi ý cho bạn:</b></div>
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkBreaks]}
                rehypePlugins={[
                  rehypeRaw,
                  [rehypeSanitize, schemaMarkdown],
                ]}
              >
                {message?.data?.suggested_prompts_mess + '\n\n**Trên đây là những gợi ý phù hợp với bạn, Bạn có thể tìm kiếm thêm sản phẩm hoặc Bạn có thể hỏi tôi bất cứ điều gì khác!**'}
              </ReactMarkdown>
            </>
          }
        </div>
      </div>
    </div>
  );
}

export default Message;
