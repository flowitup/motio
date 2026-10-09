/** A rough cost of the videos about to be made (USD), from numbers the app already has: the voice price per 1,000
 * characters (Stats), the picture price of the image provider and the AI clip price per second (Settings). Not a bill. */
export const CHARS_PER_SEC = 15; // French narration: an 80 s video is about 1,200 characters
export const CLIP_SECONDS = 5; // every AI clip lasts 5 s

export type Estimate = { total: number; voice: number; chars: number; pictures: number; clips: number; videos: number };

export function estimate(o: {
  seconds: number; // length of one video
  videos: number;
  pricePer1k: number; // ElevenLabs, USD per 1,000 characters
  pictures?: number; // USD for the pictures of one AI video
  clips?: number; // AI clips in one video
  clipPerSec?: number; // USD per second of AI clip
}): Estimate {
  const chars = Math.round(o.seconds * CHARS_PER_SEC);
  const voice = (chars / 1000) * o.pricePer1k * o.videos;
  const pictures = (o.pictures ?? 0) * o.videos;
  const clips = (o.clips ?? 0) * CLIP_SECONDS * (o.clipPerSec ?? 0) * o.videos;
  return { total: voice + pictures + clips, voice, chars: chars * o.videos, pictures, clips, videos: o.videos };
}
