/**
 * Spinner - Loading spinner component.
 * 
 * Purpose: Provide a consistent loading indicator with rotation animation.
 * Two sizes available: sm (12px) and default (16px).
 * 
 * Used by: StyleReferencePage, PanelImagesPage, etc.
 */
import React from 'react';

interface SpinnerProps {
  size?: 'sm' | 'default';
  className?: string;
}

export function Spinner({ size = 'default', className = '' }: SpinnerProps) {
  const sizeClasses = {
    sm: 'w-3 h-3',
    default: 'w-4 h-4',
  };

  return (
    <div className={`animate-spin rounded-full border-2 border-text-dim border-t-accent ${sizeClasses[size]} ${className}`} />
  );
}