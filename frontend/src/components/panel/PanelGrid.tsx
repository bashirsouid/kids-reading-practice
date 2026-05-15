/**
 * PanelGrid - Grid display of multiple panel cards.
 * 
 * Purpose: Render 6 panel cards in a 3-column grid layout.
 * Optional click handler for individual panel selection.
 * Supports per-panel generation progress display.
 * 
 * Used by: StyleReferencePage, PanelImagesPage, ReviewPage
 */
import React from 'react';
import { Panel } from '../../types/wizard';
import { PanelCard, PanelGenerationProgress } from './PanelCard';

interface PanelGridProps {
  panels: Panel[];
  jobId?: string | null;
  onPanelClick?: (index: number) => void;
  onRegenerate?: (index: number) => void;
  /** Map of panel index → generation progress (or true if generating without step data yet). */
  generatingPanels?: Record<number, PanelGenerationProgress | true>;
}

export function PanelGrid({ panels, jobId, onPanelClick, onRegenerate, generatingPanels }: PanelGridProps) {
  return (
    <div className="panel-grid grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-2.5 mb-4">
      {panels.map((panel, idx) => {
        const genState = generatingPanels?.[idx];
        const isGenerating = genState !== undefined;
        const progress: PanelGenerationProgress | null =
          genState && genState !== true ? genState : null;

        return (
          <PanelCard
            key={idx}
            panel={panel}
            index={idx}
            jobId={jobId}
            onClick={() => onPanelClick?.(idx)}
            onRegenerate={onRegenerate}
            isGenerating={isGenerating}
            generationProgress={progress}
          />
        );
      })}
    </div>
  );
}
