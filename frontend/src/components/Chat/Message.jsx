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

import * as React from 'react';
import Box from '@mui/material/Box';
import Tab from '@mui/material/Tab';
import TabContext from '@mui/lab/TabContext';
import TabList from '@mui/lab/TabList';
import TabPanel from '@mui/lab/TabPanel';
import Table from '@mui/material/Table';
import TableBody from '@mui/material/TableBody';
import TableCell from '@mui/material/TableCell';
import TableContainer from '@mui/material/TableContainer';
import TableHead from '@mui/material/TableHead';
import TableRow from '@mui/material/TableRow';
import { Grid } from '@mui/system';
import MaterialCard from './MaterialCard';

function Message({ message, onSendMessage, typing }) {

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

  const [value, setValue] = React.useState('1');

  const handleChange = (event: React.SyntheticEvent, newValue: string) => {
    setValue(newValue);
  };

  const columns: GridColDef[] = [
    { field: 'id', headerName: 'STT', width: 70, valueGetter: (params) => params.api.getRowIndex(params.row.headcode) + 1 },
    { field: 'product_name', headerName: 'Tên vật liệu' },
    { field: 'headcode', headerName: 'Mã SAP' },
    { field: 'category', headerName: 'Nhóm' },
    { field: 'final_rank', headerName: 'Số lượng' },
    { field: 'similarity', headerName: 'Đơn giá mới nhất (VNĐ)' },
    { field: 'total_cost', headerName: 'Thành tiền (VNĐ)' },
  ];

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
          {/* Hiển thị ảnh nếu có */}
          {message.imageUrl && (
            <div className="message-image">
              <img src={message.imageUrl} alt="Uploaded" width={300}/>
            </div>
          )}
          {renderContent()}
          <div ref={bottomRef} />

          {message.data?.materials?.length > 0 && <Box sx={{ width: '100%', typography: 'body1' }}>
            <TabContext value={value}>
              <Box sx={{ borderBottom: 1, borderColor: 'divider' }}>
                <TabList onChange={handleChange} aria-label="lab API tabs example">
                  <Tab label="View table" value="1" />
                  <Tab label="View List" value="2" />
                </TabList>
              </Box>
              <TabPanel value="1">
                <TableContainer >
                  <Table sx={{ minWidth: 650 }} aria-label="simple table">
                    <TableHead>
                      <TableRow>
                        <TableCell>Tên vật liệu</TableCell>
                        <TableCell>Mã SAP</TableCell>
                        <TableCell>Nhóm</TableCell>
                        <TableCell>Số lượng</TableCell>
                        <TableCell>Đơn giá mới nhất (VNĐ)</TableCell>
                        <TableCell>Thành tiền (VNĐ)</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {message.data?.materials?.map((row) => (
                        <TableRow
                          key={row.material_name}
                          // sx={{ '&:last-child td, &:last-child th': { border: 0 } }}
                        >
                          <TableCell component="th" scope="row">
                            {row.material_name}
                          </TableCell>
                          <TableCell>{row.id_sap}</TableCell>
                          <TableCell>{row.material_group} - {row.material_subgroup}</TableCell>
                          <TableCell>{row.quantity}/{row.pm_unit}</TableCell>
                          <TableCell>{row.price}</TableCell>
                          <TableCell>{row.total_cost}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
              </TabPanel>
              <TabPanel value="2">
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
                            <button
                              className="batch-btn secondary"
                              onClick={handleExportBOM}
                            >
                              📊 Xuất BOM
                            </button>
                          </div>
                        </>
                      ) : (
                        <></>
                      )}
                    </div>
                  </>
                )}
                {/* MATERIALS */}
                {!isUser && typingDone && message.data?.materials?.length > 0 && (
                  <div className="">
                    {/* <h3>
                      📦 Kết quả tìm kiếm vật liệu ({message.data.materials.length})
                    </h3> */}
                    <Grid container spacing={2}>
                      {message.data.materials.map((material, index) => (
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
                )}
              </TabPanel>
            </TabContext>
          </Box>}

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
                  <></>
                )}
              </div>
            </>
          )}
          {/* <div>{message?.data?.suggested_prompts_mess || ''}</div> */}
          {!isUser && message.data?.success &&
            <>
              <div>💡 <b>Gợi ý cho bạn:</b></div>
              <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkBreaks]}
                rehypePlugins={[
                  rehypeRaw,
                  [rehypeSanitize, schemaMarkdown],
                ]}
              >
                {message.data?.suggested_prompts_mess}
              </ReactMarkdown>
            </>
          }
        </div>
      </div>

    </div>
  );
}

export default Message;
