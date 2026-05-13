/**
 * PanelGrid - Grid display of multiple panel cards.
 * 
 * Purpose: Render 6 panel cards in a 3-column grid layout.
 * Optional click handler for individual panel selection.
 * 
 * Used by: StyleReferencePage, PanelImagesPage, ReviewPage
 */
import React from 'react';
import { Panel } from '../../types/wizard';
import { PanelCard } from './PanelCard';

interface PanelGridProps {
  panels: Panel[];
  jobId?: string | null;
  onPanelClick?: (index: number) => void;
}

export function PanelGrid({ panels, jobId, onPanelClick }: PanelGridProps) {
  return (
    <div className="panel-grid grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5 mb-4">
      {panels.map((panel, idx) => (
        <PanelCard
          key={idx}
          panel={panel}
          index={idx}
          jobId={jobId}
          onClick={() => onPanelClick?.(idx)}
        />
      ))}
    </div>
  );
}
