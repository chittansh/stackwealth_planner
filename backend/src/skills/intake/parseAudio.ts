/**
 * Audio / video intake — Whisper transcription → text path.
 */
import OpenAI from 'openai';
import { parseText } from './parseText.js';
import type { IngestResult } from './index.js';

let _client: OpenAI | null = null;
function client() {
  if (!_client) _client = new OpenAI({ apiKey: process.env.OPENAI_API_KEY });
  return _client;
}

export async function parseAudio(buf: Buffer, filename: string, mime: string): Promise<IngestResult> {
  try {
    const file = new File([new Uint8Array(buf)], filename, { type: mime });
    const tx = await client().audio.transcriptions.create({ model: 'whisper-1', file });
    const text = tx.text ?? '';
    const result = await parseText({ text, source_type: 'transcript', filename });
    return { ...result, parser_used: 'audio:whisper+text+llm' };
  } catch {
    return {
      partial_state: {},
      evidence: [],
      missing: ['audio_transcription_failed'],
      parser_used: 'audio:whisper+text+llm',
    };
  }
}
