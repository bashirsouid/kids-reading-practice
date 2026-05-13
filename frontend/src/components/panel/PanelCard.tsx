/**
 * PanelCard - Single panel display card component.
 * 
 * Purpose: Display a comic panel with number badge, optional image, and caption.
 * Shows dashed border for placeholder panels.
 * 
 * Used by: PanelGrid
 */
import React from 'react';
import { Panel } from '../../types/wizard';
import { getPanelImageUrl } from '../../services/api';

interface PanelCardProps {
  panel: Panel;
  index: number;
  jobId?: string | null;
  onClick?: () => void;
}

export function PanelCard({ panel, index, jobId, onClick }: PanelCardProps) {
  const hasImage = panel.has_image || !!panel.image;
  const isPlaceholder = panel.is_placeholder || (panel.caption && panel.caption.startsWith('[Placeholder'));
  const imageUrl = panel.image || (jobId && hasImage ? getPanelImageUrl(jobId, index) : null);

  return (
    <div
      className={`panel-card relative bg-surface2 border-2 rounded-xl overflow-hidden flex flex-col ${
        hasImage ? 'cursor-pointer' : 'cursor-default'
      } ${
        isPlaceholder ? 'border-dashed border-accent' : 'border-white/8'
      }`}
      onClick={onClick}
    >
      <div className="panel-num absolute top-2 left-2 z-10 bg-accent text-white w-6 h-6 rounded-full flex items-center justify-center text-xs font-bold shadow">
        {index + 1}
      </div>
      <div className="relative aspect-[3/2] w-full bg-white">
        {imageUrl && (
          <img
            src={imageUrl}
            alt={`Panel ${index + 1}`}
            className="h-full w-full object-cover"
          />
        )}
      </div>
      {hasImage && (
        <div className="px-2 pt-1 text-[10px] font-semibold uppercase tracking-wide text-green-300">
          Image ready
        </div>
      )}
      <div className="panel-caption min-h-[4.25rem] p-2 text-xs leading-snug overflow-y-auto border-t border-white/8">
        {panel.caption || '(no caption)'}
      </div>
    </div>
  );
}
