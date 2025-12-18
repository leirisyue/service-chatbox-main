import React from 'react';
import './Input.css';

function SuggestedPrompts({ prompts, onSelect }) {
  return (
    <div className="suggested-prompts">
      <h4>💡 Gợi ý nhanh:</h4>
      <div className="prompts-grid">
        {prompts.slice(0, 4).map((prompt, index) => (
          <buttons
            key={index}
            className="prompt-button"
            onClick={() => onSelect(prompt)}
          >
            {prompt}
          </buttons>
        ))}
      </div>
    </div>
  );
}

export default SuggestedPrompts;