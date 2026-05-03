'use client';

/**
 * Fire a chat prompt from anywhere in the app — the ChatPanel listens for
 * this event and dispatches it as the next user turn. Keeps the chat panel
 * decoupled from the rest of the UI.
 */
export function firePrompt(prompt: string) {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent('sw:chat-prompt', { detail: { prompt } }));
}
