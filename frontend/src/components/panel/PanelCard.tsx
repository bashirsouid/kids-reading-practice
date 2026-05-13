/**
 * PanelCard - Single panel display card component.
 * 
 * Purpose: Display a comic panel with number badge, optional image, and caption.
 * Shows dashed border for placeholder panels.
 * 
 * Used by: PanelGrid
 */
import React from 'react';
import { Panel } from '../../../types/wizard';

interface PanelCardProps {
  panel: Panel;
  index: number;
  onClick?: () => void;
}

export function PanelCard({ panel, index, onClick }: PanelCardProps) {
  const hasImage = panel.has_image || !!panel.image;
  const isPlaceholder = panel.is_placeholder || (panel.caption && panel.caption.startsWith('[Placeholder'));

  return (
    <div
      className={`panel-card relative aspect-[3/4] bg-surface2 border-2 rounded-xl overflow-hidden flex flex-col cursor-${hasImage ? 'pointer' : 'default'} ${
        isPlaceholder ? 'border-dashed border-accent opacity-80' : 'border-white/8'
      }`}
      onClick={onClick}
    >
      <div className="panel-num absolute top-1 left-1 bg-accent text-white w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold">
        {index + 1}
      </div>
      {hasImage && (
        <img src={`/api/panel-image/placeholder/${index}`} alt={`Panel ${index + 1}`} className="w-full h-1/2 object-cover" />
      )}
      <div className="panel-caption flex-1 p-1.5 text-xs line-clamp-3 overflow-y-auto border-t border-white/8">
        {panel.caption || '(no caption)'}
      </div>
    </div>
  );
}