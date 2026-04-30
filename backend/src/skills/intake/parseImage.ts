/**
 * Image intake — Claude Sonnet 4.6 vision call.
 * Returns canonical-shape JSON with per-field confidence.
 */
import Anthropic from '@anthropic-ai/sdk';
import { llmExtract } from './llmExtract.js';
import type { IngestResult } from './index.js';

let _client: Anthropic | null = null;
function client() {
  if (!_client) _client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });
  return _client;
}

export async function parseImage(buf: Buffer, filename: string, mime: string): Promise<IngestResult> {
  // Day 2 path: ask the model to OCR + describe → reuse llmExtract on the text.
  // Future: switch to a single multimodal extraction pass with structured response.
  try {
    const resp = await client().messages.create({
      model: 'claude-sonnet-4-6',
      max_tokens: 2000,
      messages: [
        {
          role: 'user',
          content: [
            {
              type: 'image',
              source: { type: 'base64', media_type: mime as 'image/png', data: buf.toString('base64') },
            },
            {
              type: 'text',
              text: 'Transcribe every figure, table, label, and number in this image. Preserve column structure and units.',
            },
          ],
        },
      ],
    });
    const text = resp.content
      .filter((b) => b.type === 'text')
      .map((b) => (b as { type: 'text'; text: string }).text)
      .join('\n');
    const result = await llmExtract({ text, source_type: 'image', filename });
    return { ...result, parser_used: 'image:vision+llm' };
  } catch {
    return {
      partial_state: {},
      evidence: [],
      missing: ['image_extraction_failed'],
      parser_used: 'image:vision+llm',
    };
  }
}
