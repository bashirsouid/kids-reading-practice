/**
 * ModeCard - Individual story mode selection card.
 * 
 * Purpose: Display a single mode option with emoji, label, and description.
 * Highlights when active with accent border and background color.
 * 
 * Used by: ModeSelector
 */
import React from 'react';

interface ModeCardProps {
  mode: string;
  label: string;
  description: string;
  emoji: string;
  isActive: boolean;
  onClick: () => void;
}

export function ModeCard({ mode, label, description, emoji, isActive, onClick }: ModeCardProps) {
  return (
    <div
      className={`mode-card bg-surface2 border-2 rounded-xl p-3.5 text-center cursor-pointer transition-all duration-150 ${
        isActive 
          ? 'border-accent bg-accent/10' 
          : 'border-transparent hover:border-accent/30 hover:bg-accent/5'
      }`}
      data-mode={mode}
      onClick={onClick}
    >
      <span className="emoji block text-xl mb-1">{emoji}</span>
      <div className="label font-semibold text-sm">{label}</div>
      <div className="desc text-xs text-text-dim mt-1">{description}</div>
    </div>
  );
}