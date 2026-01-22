import React from 'react';
import './Input.css';

function SuggestedPrompts({ prompts, onSelect }) {
  return (
    <div className="suggested-prompts">
      <div style={{paddingBottom:'5px'}}>💡 Gợi ý nhanh:</div>
      <div className="prompts-grid">
        {prompts.slice(0, 4).map((prompt, index) => (
          <button
            key={index}
            className="prompt-button"
            onClick={() => onSelect(prompt)}
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}

export default SuggestedPrompts;