import React from 'react';
import './MainLayout.css';

function MainLayout({ sidebar, mainContent }) {
  return (
    <div className="main-layout">
      <aside className="sidebar-container">
        {sidebar}
      </aside>
      <main className="main-container">
        {mainContent}
      </main>
    </div>
  );
}

export default MainLayout;