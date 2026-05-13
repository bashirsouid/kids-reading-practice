/**
 * ProgressBar - Visual progress indicator component.
 * 
 * Purpose: Display generation progress with a gradient fill animation.
 * The percent value is clamped between 0-100.
 * 
 * Used by: Wizard pages for generation progress
 */
import React from 'react';

interface ProgressBarProps {
  percent: number;
  label?: string;
  className?: string;
}

export function ProgressBar({ percent, label, className = '' }: ProgressBarProps) {
  return (
    <div className={`w-full ${className}`}>
      <div className="w-full h-1 bg-surface2 rounded-full overflow-hidden">
        <div 
          className="h-full bg-gradient-to-r from-accent to-gold rounded-full transition-all duration-400"
          style={{ width: `${Math.min(100, Math.max(0, percent))}%` }}
        />
      </div>
      {label && (
        <div className="text-xs text-text-dim mt-1">{label}</div>
      )}
    </div>
  );
}