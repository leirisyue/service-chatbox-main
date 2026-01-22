import React, { useState } from 'react';
import './MainLayout.css';

function MainLayout({ sidebar, mainContent }) {
  const [isSidebarVisible, setIsSidebarVisible] = useState(false);

  const toggleSidebar = () => {
    setIsSidebarVisible(!isSidebarVisible);
  };

  return (
    <div className="main-layout">
      <aside className={`sidebar-container ${!isSidebarVisible ? 'hidden' : ''}`}>
        {sidebar}
      </aside>
      <main className="main-container">
        <button 
          className="toggle-sidebar-btn" 
          onClick={toggleSidebar}
          aria-label={isSidebarVisible ? 'Ẩn sidebar' : 'Hiện sidebar'}
        >
          {isSidebarVisible ? '<' : '>'}
        </button>
        {mainContent}
      </main>
    </div>
  );
}

export default MainLayout;