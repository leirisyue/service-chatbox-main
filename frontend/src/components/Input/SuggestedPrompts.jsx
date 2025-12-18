import React from 'react';
import './Input.css';

function SuggestedPrompts({ prompts, onSelect }) {
  return (
    <div className="suggested-prompts">
      <h4>💡 Gợi ý nhanh:</h4>
      <div className="prompts-grid">
        {prompts.slice(0, 4).map((prompt, index) => (
          <button
            key={index}
            className="prompt-button"
            onClick={() => onSelect(prompt.includes(" ") ? prompt.split(" ", 1)[1] : prompt)}
          >
            {prompt}
          </button>
        ))}
      </div>
    </div>
  );
}

export default SuggestedPrompts;