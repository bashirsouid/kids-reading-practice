/**
 * ErrorMessage - Display an error message with optional dismiss button.
 * 
 * Purpose: Show API or other errors in a consistent, user-friendly way.
 * 
 * Used by: All pages that make API calls
 */
import React from 'react';

interface ErrorMessageProps {
  message: string;
  onDismiss?: () => void;
}

export function ErrorMessage({ message, onDismiss }: ErrorMessageProps) {
  return (
    <div className="bg-red-900/50 border border-red-500 text-red-200 p-3 rounded-md mb-3 text-sm">
      <strong>Error:</strong> {message}
      {onDismiss && (
        <button 
          onClick={onDismiss}
          className="ml-2 text-red-400 hover:text-red-200 font-bold float-right"
          aria-label="Dismiss error"
        >
          ×
        </button>
      )}
    </div>
  );
}