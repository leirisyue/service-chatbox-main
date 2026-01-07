import { Grid } from '@mui/material';
import React, { useState } from 'react';
import ProductCard from './ProductCard';

function ProductListWithFeedback({
  products = [],
  onMaterialClick,
  onPriceClick,
  selectedProducts = [],
  onToggleSelected,
  feedbackSelected = [],
  onToggleFeedback,
}) {
  const [debugMode, setDebugMode] = useState(false);
  const [feedbackMode, setFeedbackMode] = useState(false);

  return (
    <div className="products-section fade-in">
      <div className="products-header-row">
        <h3>
          📦 Kết quả tìm kiếm sản phẩm ({products.length})
        </h3>
        <div className="products-toggles">
          <label>
            <input
              type="checkbox"
              checked={feedbackMode}
              onChange={(e) => setFeedbackMode(e.target.checked)}
            />
            <span> Feedback mode</span>
          </label>
          <label>
            <input
              type="checkbox"
              checked={debugMode}
              onChange={(e) => setDebugMode(e.target.checked)}
            />
            <span> Debug</span>
          </label>
        </div>
      </div>

      <div className="">
        <Grid container spacing={2}>
          {products.map((product, pidx) => {
            const headcode = product.headcode || 'N/A';
            const productName = (product.product_name || 'N/A').slice(0, 50);
            const originalRank =
              product.original_rank !== undefined
                ? product.original_rank
                : pidx + 1;
            const finalRank =
              product.final_rank !== undefined ? product.final_rank : pidx + 1;
            const feedbackCount = product.feedback_count || 0;
            const similarity = product.similarity || 0;
            const finalScore =
              product.final_score !== undefined
                ? product.final_score
                : similarity;
            const personalizedScore = product.personalized_score || 0;
            const baseScore = product.base_score || 0;

            const rankChange = originalRank - finalRank;
            const hasFeedback = feedbackCount > 0;

            const isSelected = selectedProducts.includes(headcode);
            const isFeedbackSelected = feedbackSelected.includes(headcode);

            return (
              <Grid key={pidx} size={{ xs: 12, md: 6 }}>
                <div
                  key={`${headcode}_${pidx}`}
                  className="product-card-extended"
                >
                  {/* Card chính: vẫn dùng ProductCard để giữ hành vi cũ */}
                  <ProductCard
                    product={{ ...product, product_name: productName }}
                    onMaterialClick={() => onMaterialClick?.(headcode)}
                    onPriceClick={() => onPriceClick?.(headcode)}
                  />
                  {/* Badge feedback giống Streamlit */}
                  {hasFeedback && (
                    <div className="product-feedback">
                      <span className="feedback-text">
                        ⭐ {feedbackCount} người đã chọn
                      </span>
                      {rankChange !== 0 && (
                        <span
                          className={`feedback-rank ${rankChange > 0 ? 'feedback-rank--up' : 'feedback-rank--down'
                            }`}
                        >
                          {rankChange > 0 ? `⬆️ +${rankChange}` : `⬇️ ${rankChange}`}
                        </span>
                      )}
                    </div>
                  )}
                  {/* Panel debug */}
                  {debugMode && (
                    <div className="product-debug-panel">
                      <div>
                        Rank: {originalRank} → {finalRank}
                      </div>
                      <div>
                        Base: {baseScore.toFixed(3)} | Final: {finalScore.toFixed(3)}
                      </div>
                      <div>Personalized: {personalizedScore.toFixed(3)}</div>
                      <div>Feedback: {feedbackCount} lượt</div>
                    </div>
                  )}
                  {/* Checkbox chọn / feedback giống Streamlit */}
                  <div className="product-checkbox-group">
                    <label className="product-checkbox">
                      <input
                        type="checkbox"
                        checked={isSelected}
                        onChange={() => onToggleSelected?.(headcode)}
                      />
                      <span>Chọn để xem chi tiết</span>
                    </label>
                    {feedbackMode && (
                      <label className="product-checkbox">
                        <input
                          type="checkbox"
                          checked={isFeedbackSelected}
                          onChange={() => onToggleFeedback?.(headcode)}
                        />
                        <span>Phù hợp với câu hỏi</span>
                      </label>
                    )}
                  </div>
                </div>
              </Grid>
            );
          })}
        </Grid>
      </div>
    </div>
  );
}

export default ProductListWithFeedback;
