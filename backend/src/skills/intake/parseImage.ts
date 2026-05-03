/**
 * Image intake — single-pass structured extraction. Sends the image straight
 * to a multimodal model with the canonical schema; tries Claude first then
 * falls back to GPT-4o so screenshots of brokerage statements, salary slips,
 * Zerodha P&L, etc. all extract cleanly without an OCR-then-re-extract dance.
 *
 * HEIC (iPhone camera default) is normalised to JPEG before sending — the
 * vision providers reject HEIC bytes directly. We try `sharp` if installed;
 * otherwise we surface a clean error so the user knows to re-export.
 */
import { multimodalExtract } from './multimodalExtract.js';
import type { IngestResult } from './index.js';

const VISION_OK = new Set(['image/png', 'image/jpeg', 'image/webp', 'image/gif']);

async function normaliseForVision(
  buf: Buffer,
  mime: string,
): Promise<{ ok: true; bytes: Buffer; mime: string } | { ok: false; reason: string }> {
  if (VISION_OK.has(mime)) return { ok: true, bytes: buf, mime };

  // HEIC / HEIF / unknown image — try to transcode to JPEG via sharp if present.
  if (mime === 'image/heic' || mime === 'image/heif' || mime === 'application/octet-stream' || mime.startsWith('image/')) {
    try {
      const mod = (await (
        // @ts-expect-error sharp is an optional dependency
        import('sharp').catch(() => null)
      )) as
        | { default: (b: Buffer) => { jpeg: (o?: { quality?: number }) => { toBuffer: () => Promise<Buffer> } } }
        | null;
      if (mod) {
        const jpeg = await mod.default(buf).jpeg({ quality: 88 }).toBuffer();
        return { ok: true, bytes: jpeg, mime: 'image/jpeg' };
      }
    } catch {
      /* fall through */
    }
    return {
      ok: false,
      reason: `mime=${mime} not supported by Claude/GPT-4o vision. Re-export as JPEG, PNG, or PDF — or install \`sharp\` on the backend so HEIC/HEIF transcodes automatically.`,
    };
  }

  return { ok: false, reason: `Unsupported image mime ${mime}` };
}

export async function parseImage(buf: Buffer, filename: string, mime: string): Promise<IngestResult> {
  const norm = await normaliseForVision(buf, mime);
  if (!norm.ok) {
    return {
      partial_state: {},
      evidence: [],
      missing: [`image_unsupported:${norm.reason}`],
      parser_used: `image:unsupported(${mime})`,
    };
  }

  try {
    const result = await multimodalExtract({
      kind: 'image',
      bytes: norm.bytes,
      mime: norm.mime,
      sourceType: 'image',
      filename,
    });
    return { ...result, parser_used: `image:${result.parser_used}` };
  } catch (err) {
    return {
      partial_state: {},
      evidence: [],
      missing: [`image_extraction_failed:${(err as Error).message}`],
      parser_used: 'image:failed',
    };
  }
}
