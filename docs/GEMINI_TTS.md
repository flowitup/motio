# Gemini TTS (voice provider)

Added on the owner's ask of 2026-10-23: "Ghép voice sử dụng cho tôi Gemini TTS". Gemini is a second voice provider next
to ElevenLabs, with the owner's own Google AI Studio key (`GEMINI_API_KEY`, secret, Settings → Voice).

## How it works (`motio/tts.py`)

- `tts.provider()`: `TTS_PROVIDER` (`elevenlabs` / `gemini`) when set, and then only that provider (no key → no voice and
  a clear error, never a silent switch to the other paid service); empty → ElevenLabs if its key is set, else Gemini,
  else the macOS `say` voice (dev only).
- One request per script line: `POST https://generativelanguage.googleapis.com/v1beta/models/<GEMINI_TTS_MODEL>:generateContent`
  with `x-goog-api-key`, `responseModalities: ["AUDIO"]` and `speechConfig.voiceConfig.prebuiltVoiceConfig.voiceName`.
  The answer is base64 16-bit mono PCM (24 kHz). Gemini gives no per-word timing, so each line is measured on its own
  (leading and trailing silence trimmed), lines are joined with 0.18 s of silence into `narration.wav`, and the
  character alignment is `None` — the same shape as the macOS voice, so captions split a line's time by characters and
  the dub places lines by their measured spans.
- 429 and 5xx answers are retried after 3, 10, 25 and 60 s (Gemini's limits are per minute; its TTS models also answer
  500 now and then when they return text instead of audio). A 4xx other than 429 is shown as `Gemini <code>: <message>`.
- Voices: the 30 prebuilt voices (`tts.GEMINI_VOICES`, with the gender and style Google lists), default `Charon`
  (`GEMINI_VOICE` in Settings). A voice saved on a channel belongs to one provider; a voice of the other provider is
  ignored and the Settings voice is used. `GET /api/voices[?provider=gemini|elevenlabs]` lists voices of the provider in
  use or the one named (Settings shows both before saving).
- Cost: every call is a `usage` row (kind `tts`, characters sent, USD = audio seconds × `GEMINI_TTS_USD_PER_MIN` / 60).
  Default 0.03 $/min = 25 audio tokens/s × 20 $/1M tokens (price list of 2026-10 for the preview models; the 3.8 Flash
  TTS models list 9 $/1M until 31 Dec 2026, then 18). The text-in price is small and not counted.

## Not verified

Written in a sandbox without a Gemini key: tests fake Google's answers (`tts._transport`). Google's docs now describe an
Interactions API (`/v1beta/interactions`, model `gemini-3.8-flash-tts`) next to `generateContent`, which the same docs call
legacy but "fully supported". If `GEMINI_TTS_MODEL` is retired or a newer model refuses `generateContent`, the error shows
Google's message; change the model in Settings, or move `_gemini_once` to the Interactions API (the rest stays).
