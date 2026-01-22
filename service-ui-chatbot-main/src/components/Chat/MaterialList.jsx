import { Box, Grid } from '@mui/material';
import React, { useState } from 'react';
import MaterialCard from './MaterialCard';

function MaterialList({
  materials = [],
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
    <div>
      <div className="products-header-row">
        <h3>
          📦 Kết quả tìm kiếm sản phẩm ({materials.length})
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

      <div>
        <Grid container spacing={2}>
          {materials?.map((material, pidx) => {

            const headcode = material.headcode || 'N/A';
            const productName = (material.product_name || 'N/A').slice(0, 50);
            const originalRank =
              material.original_rank !== undefined
                ? material.original_rank
                : pidx + 1;
            const finalRank =
              material.final_rank !== undefined ? material.final_rank : pidx + 1;
            const feedbackCount = material.feedback_count || 0;
            const similarity = material.similarity || 0;
            const finalScore =
              material.final_score !== undefined
                ? material.final_score
                : similarity;
            const personalizedScore = material.personalized_score || 0;
            const baseScore = material.base_score || 0;

            const rankChange = originalRank - finalRank;
            const hasFeedback = feedbackCount > 0;

            const isSelected = selectedProducts.includes(headcode);
            const isFeedbackSelected = feedbackSelected.includes(headcode);

            return (
              <Grid key={pidx} size={{ xs: 12, md: 6 }}>
                <Box sx={{ height: '100%' }}>
                  <MaterialCard
                    material={material}
                    onDetailClick={() =>
                      onMaterialClick(material.material_name)
                    }
                    onPriceClick={() => onPriceClick?.(headcode)}
                  />
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
                </Box>
              </Grid>
            )
          })}
        </Grid>
      </div>
    </div>
  );
}

export default MaterialList;
