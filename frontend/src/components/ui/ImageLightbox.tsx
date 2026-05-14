/**
 * ImageLightbox - Full-screen image modal.
 *
 * Purpose: Display a panel image at near-full-screen size.
 * Clicking anywhere on the overlay dismisses it.
 * Pressing Escape also dismisses the modal.
 *
 * Used by: PanelImagesPage, ReviewPage
 */
import React, { useEffect, useCallback } from 'react';

interface ImageLightboxProps {
  src: string;
  onClose: () => void;
}

export function ImageLightbox({ src, onClose }: ImageLightboxProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    },
    [onClose],
  );

  useEffect(() => {
    document.addEventListener('keydown', handleKeyDown);
    // Prevent body scroll while lightbox is open
    document.body.style.overflow = 'hidden';
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [handleKeyDown]);

  return (
    <div className="lightbox-overlay" onClick={onClose}>
      <img
        src={src}
        alt="Panel preview"
        className="lightbox-image"
        onClick={(e) => e.stopPropagation()}
      />
      <div className="lightbox-hint">Click anywhere to close</div>
    </div>
  );
}
