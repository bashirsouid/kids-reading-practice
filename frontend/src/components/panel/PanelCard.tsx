/**
 * PanelCard - Single panel display card component.
 * 
 * Purpose: Display a comic panel with number badge, optional image, and caption.
 * Shows dashed border for placeholder panels.
 * When generating, shows a progress overlay instead of the old image.
 * 
 * Used by: PanelGrid
 */
import React from 'react';
import { Panel } from '../../types/wizard';
import { getPanelImageUrl } from '../../services/api';

export interface PanelGenerationProgress {
  step: number;
  totalSteps: number;
}

interface PanelCardProps {
  panel: Panel;
  index: number;
  jobId?: string | null;
  onClick?: () => void;
  onRegenerate?: (index: number) => void;
  /** True when this panel is currently being generated/regenerated. */
  isGenerating?: boolean;
  /** Step-level progress data during generation. */
  generationProgress?: PanelGenerationProgress | null;
}

export function PanelCard({ panel, index, jobId, onClick, onRegenerate, isGenerating, generationProgress }: PanelCardProps) {
  const hasImage = !isGenerating && (panel.has_image || !!panel.image);
  const isPlaceholder = panel.is_placeholder || (panel.caption && panel.caption.startsWith('[Placeholder'));
  const imageUrl = panel.image || (jobId && hasImage ? getPanelImageUrl(jobId, index) : null);

  // Calculate progress percentage for the ring
  const progressPercent = generationProgress
    ? (generationProgress.step / generationProgress.totalSteps) * 100
    : 0;

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

      {/* Regenerate icon button - blue, top right corner */}
      {hasImage && onRegenerate && !isGenerating && (
        <button
          className="regen-icon-btn absolute top-2 right-2 z-20 flex items-center justify-center w-7 h-7 rounded-full bg-blue-600/80 hover:bg-blue-500 text-white shadow-lg border border-blue-400/50 transition-all duration-150"
          onClick={(e) => {
            e.stopPropagation();
            onRegenerate(index);
          }}
          title="Regenerate this panel"
        >
          <svg xmlns="http://www.w3.org/2000/svg" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
            <path d="M21 12a9 9 0 1 1-6.22-8.56"/>
            <path d="M22 3v5h-5"/>
          </svg>
        </button>
      )}

      <div className="relative aspect-[3/2] w-full bg-white">
        {isGenerating ? (
          <div className="gen-overlay">
            <div className="gen-progress-ring-container">
              <svg className="gen-progress-ring" viewBox="0 0 60 60">
                <circle
                  className="gen-progress-ring-track"
                  cx="30" cy="30" r="25"
                  fill="none"
                  strokeWidth="4"
                />
                <circle
                  className="gen-progress-ring-fill"
                  cx="30" cy="30" r="25"
                  fill="none"
                  strokeWidth="4"
                  strokeDasharray={`${2 * Math.PI * 25}`}
                  strokeDashoffset={`${2 * Math.PI * 25 * (1 - progressPercent / 100)}`}
                  strokeLinecap="round"
                />
              </svg>
              <div className="gen-progress-text">
                {generationProgress
                  ? `${generationProgress.step}/${generationProgress.totalSteps}`
                  : '...'}
              </div>
            </div>
            <div className="gen-label">Generating</div>
          </div>
        ) : imageUrl ? (
          <img
            src={imageUrl}
            alt={`Panel ${index + 1}`}
            className="h-full w-full object-cover"
          />
        ) : null}
      </div>
      {hasImage && (
        <div className="px-2 pt-1 text-[10px] font-semibold uppercase tracking-wide text-green-300">
          Image ready
        </div>
      )}
      {isGenerating && (
        <div className="px-2 pt-1 text-[10px] font-semibold uppercase tracking-wide text-accent animate-pulse">
          Generating...
        </div>
      )}
      <div className="panel-caption min-h-[4.25rem] p-2 text-xs leading-snug overflow-y-auto border-t border-white/8">
        {panel.caption || '(no caption)'}
      </div>
    </div>
  );
}
