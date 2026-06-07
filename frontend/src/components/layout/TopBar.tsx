/**
 * TopBar - Top navigation bar with home link and model status.
 * 
 * Purpose: Display navigation header with home link, current page path, and model status indicator.
 * Shows loading spinner when model status is loading.
 * Home link supports right-click "Open in New Tab" via native browser context menu.
 * 
 * Used by: AppLayout
 */
import React from 'react';

interface TopBarProps {
  modelStatus: 'loading' | 'ready' | 'error';
  onHomeClick: () => void;
  headerPath: string;
}

export function TopBar({ modelStatus, onHomeClick, headerPath }: TopBarProps) {
  const statusConfig = {
    loading: { label: 'Loading', className: 'status-badge loading' },
    ready: { label: '✅ Ready', className: 'status-badge ready' },
    error: { label: '❌ Failed', className: 'status-badge error' },
  };

  const status = statusConfig[modelStatus];

  const handleHomeClick = (e: React.MouseEvent) => {
    // Allow default behavior for middle-click, Ctrl+click, Cmd+click (opens in new tab)
    // and right-click (shows context menu)
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.shiftKey) return;
    
    // For left-click without modifiers, prevent default and use SPA navigation
    e.preventDefault();
    onHomeClick();
  };

  return (
    <div className="topbar">
      <div className="topbar-left">
        <a 
          href="/"
          onClick={handleHomeClick}
          className="text-accent hover:text-gold font-semibold text-sm"
        >
          🏠 Home
        </a>
        {headerPath && (
          <span className="text-text-dim text-xs" style={{ marginLeft: '8px' }}>
            {headerPath}
          </span>
        )}
      </div>
      <div className="topbar-right">
        <span className={status.className}>
          {modelStatus === 'loading' && <span className="spinner-sm" style={{ marginRight: '4px' }} />}
          {status.label}
        </span>
      </div>
    </div>
  );
}