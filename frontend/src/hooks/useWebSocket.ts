/**
 * useWebSocket - Hook for real-time WebSocket communication.
 * 
 * Purpose: Establish WebSocket connection to receive real-time progress updates
 * for story generation, reference generation, and panel image generation.
 * 
 * Used by: StyleReferencePage, PanelImagesPage, PanelBreakdownPage, StoryContentPage
 */
import { useEffect, useRef, useCallback } from 'react';

interface WebSocketMessage {
  job_id?: string;
  slug?: string;
  status?: string;
  stage?: string;
  mode?: string;
  synopsis?: string;
  progress_current?: number;
  progress_total?: number;
  error?: string;
  has_reference?: boolean;
  type?: 'progress' | 'complete' | 'error';
  message?: string;
  reference_ready?: boolean;
  story?: {
    title?: string;
    synopsis?: string;
    art_style?: string;
    character_bible?: string;
    characters?: Array<{ name: string; description: string }>;
    panels?: Array<{
      index: number;
      caption: string;
      image_prompt: string;
      characters: string[];
      has_image: boolean;
      is_placeholder: boolean;
    }>;
  };
  wait_for_user?: boolean;
}

interface UseWebSocketOptions {
  jobId: string;
  onProgress?: (progress: number, total: number) => void;
  onError?: (error: string) => void;
  onReferenceReady?: () => void;
  onStoryUpdate?: (story: WebSocketMessage['story']) => void;
  onStageChange?: (stage: string) => void;
}

export function useWebSocket({
   jobId,
   onProgress,
   onError,
   onReferenceReady,
   onStoryUpdate,
   onStageChange,
  }: UseWebSocketOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<number | null>(null);

  const connect = useCallback(() => {
    if (!jobId) return;

    const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
    const wsUrl = `${protocol}//${window.location.host}/ws/${jobId}`;

    wsRef.current = new WebSocket(wsUrl);

    wsRef.current.onopen = () => {
      console.log('WebSocket connected');
    };

    wsRef.current.onmessage = (event) => {
      try {
        const data: WebSocketMessage = JSON.parse(event.data);

        // Handle legacy format with explicit type field
        if (data.type) {
          switch (data.type) {
            case 'progress':
              if (data.progress !== undefined && data.total !== undefined) {
                onProgress?.(data.progress, data.total);
              }
              break;
            case 'complete':
              if (data.reference_ready && onReferenceReady) {
                onReferenceReady();
              }
              break;
            case 'error':
              onError?.(data.message || 'Unknown error');
              break;
          }
          return;
        }

        // Handle server format (from comic-server broadcast_job_update)
        // Check for error first
        if (data.error) {
          onError?.(data.error);
          return;
        }

        // Check for reference ready
        if (data.has_reference && onReferenceReady) {
          onReferenceReady();
        }

        // Handle progress updates
        if (data.progress_current !== undefined && data.progress_total !== undefined) {
          onProgress?.(data.progress_current, data.progress_total);
        }

        // Handle stage changes
        if (data.stage && onStageChange) {
          onStageChange(data.stage);
        }

        // Handle story updates (when panels are generated)
        if (data.story && onStoryUpdate) {
          onStoryUpdate(data.story);
        }

        // Handle stage changes for completion detection
        if (data.stage === 'panel_breakdown' && onReferenceReady) {
          // Reference has been generated, moving to panel breakdown
          onReferenceReady();
        }
        
        // Panel generation complete (stage moved to complete)
        if (data.stage === 'complete' && onReferenceReady) {
          onReferenceReady();
        }
      } catch (e) {
        console.error('Failed to parse WebSocket message:', e);
      }
    };

    wsRef.current.onerror = () => {
      onError?.('WebSocket connection error');
    };

    wsRef.current.onclose = () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      reconnectTimeoutRef.current = window.setTimeout(() => {
        connect();
      }, 3000);
    };
  }, [jobId, onProgress, onError, onReferenceReady, onStoryUpdate, onStageChange]);

  useEffect(() => {
    connect();

    return () => {
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
      if (wsRef.current) {
        wsRef.current.close();
      }
    };
  }, [connect]);

  return {
    reconnect: connect,
  };
}