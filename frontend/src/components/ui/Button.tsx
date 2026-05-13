/**
 * Button - Reusable button component with multiple variants.
 * 
 * Purpose: Provide consistent button styling across the application.
 * Variants: primary (gradient), secondary (outline), gold (accent)
 * 
 * Used by: HomePage, ComicInfoPage, StyleReferencePage, etc.
 */
import React from 'react';

interface ButtonProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: 'primary' | 'secondary' | 'gold';
  size?: 'sm' | 'default';
}

export function Button({ 
  variant = 'primary', 
  size = 'default', 
  className = '', 
  children, 
  ...props 
}: ButtonProps) {
  const baseClasses = 'inline-flex items-center gap-2 font-semibold rounded-lg cursor-pointer transition-all duration-150 disabled:opacity-50 disabled:cursor-not-allowed';
  
  const variantClasses = {
    primary: 'bg-gradient-to-r from-accent to-red-800 text-white hover:-translate-y-0.5 hover:shadow-lg hover:shadow-accent/30',
    secondary: 'bg-surface2 text-text border border-white/10 hover:bg-white/8',
    gold: 'bg-gradient-to-r from-gold to-yellow-600 text-gray-900 hover:-translate-y-0.5 hover:shadow-lg hover:shadow-gold/30',
  };
  
  const sizeClasses = {
    sm: 'px-3 py-1.5 text-xs',
    default: 'px-5 py-2.5 text-sm',
  };

  return (
    <button
      className={`${baseClasses} ${variantClasses[variant]} ${sizeClasses[size]} ${className}`}
      {...props}
    >
      {children}
    </button>
  );
}