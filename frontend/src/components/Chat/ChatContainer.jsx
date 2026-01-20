import { useAtomValue } from 'jotai';
import { useEffect, useRef, useState } from 'react';
import { messagesAtom } from '../../atom/messageAtom';
import './Chat.css';
import Message from './Message';

function ChatContainer({ isLoading, onSendMessage }) {

  const messages = useAtomValue(messagesAtom);
  const [showThinkingText, setShowThinkingText] = useState('');
  const messagesEndRef = useRef(null);

  const scrollToBottom = () => {
    messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
  };

  useEffect(() => {
    scrollToBottom();
  }, [messages]);

  useEffect(() => {
    let timer1, timer2, timer3;
    if (isLoading) {
      setShowThinkingText('');
      timer1 = setTimeout(() => {
        setShowThinkingText('đang phân tích...');
      }, 5000);
      timer2 = setTimeout(() => {
        setShowThinkingText('đang suy nghĩ...');
      }, 4000);
      timer3 = setTimeout(() => {
        setShowThinkingText('vui lòng chờ...');
      }, 3000);
    } else {
      setShowThinkingText('');
    }
    
    return () => {
      if (timer1) clearTimeout(timer1);
      if (timer2) clearTimeout(timer2);
      if (timer3) clearTimeout(timer3);
    };
  }, [isLoading]);

  return (
    <div className="chat-container">
      <div className="messages-wrapper">
        {messages?.map((message, index) => (
          <Message key={index} message={message} onSendMessage={onSendMessage} typing={index === messages.length - 1 && index !== 0 && !message.view_history} />
        ))}
        {isLoading && (
          <div className="loading-indicator">
            <div className="typing-dots">
              <div className="dot"></div>
              <div className="dot"></div>
              <div className="dot"></div>
            </div>
            {showThinkingText && (
              <span className="thinking-text">{showThinkingText}</span>
            )}
          </div>
        )}
        <div ref={messagesEndRef} />
      </div>
    </div>  
  );
}

export default ChatContainer;