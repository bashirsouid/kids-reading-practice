/**
 * Card - Reusable card container component.
 * 
 * Purpose: Provide a consistent container style with backdrop blur effect.
 * Can be made clickable by providing an onClick handler.
 * 
 * Used by: HomePage, all wizard pages for content sections
 */
import React from 'react';

interface CardProps {
  className?: string;
  children: React.ReactNode;
  onClick?: () => void;
}

export function Card({ className = '', children, onClick }: CardProps) {
  return (
    <div 
      className={`bg-surface border border-glass rounded-xl p-5 mb-4 backdrop-blur-md ${onClick ? 'cursor-pointer' : ''} ${className}`}
      onClick={onClick}
    >
      {children}
    </div>
  );
}