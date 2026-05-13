/**
 * PanelGrid - Grid display of multiple panel cards.
 * 
 * Purpose: Render 6 panel cards in a 3-column grid layout.
 * Optional click handler for individual panel selection.
 * 
 * Used by: StyleReferencePage, PanelImagesPage, ReviewPage
 */
import React from 'react';
import { Panel } from '../../../types/wizard';
import { PanelCard } from './PanelCard';

interface PanelGridProps {
  panels: Panel[];
  onPanelClick?: (index: number) => void;
}

export function PanelGrid({ panels, onPanelClick }: PanelGridProps) {
  return (
    <div className="panel-grid grid grid-cols-3 gap-2.5 mb-4">
      {panels.map((panel, idx) => (
        <PanelCard
          key={idx}
          panel={panel}
          index={idx}
          onClick={() => onPanelClick?.(idx)}
        />
      ))}
    </div>
  );
}