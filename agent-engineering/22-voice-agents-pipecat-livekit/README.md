# 22 · Voice Agents: Pipecat and LiveKit

> **Short answer:** A voice agent is an agent loop inside a real-time audio pipeline. It must detect when the user has finished speaking, answer within about a second, and stop mid-word when interrupted. **Pipecat** (Python, frame-based pipelines, now past 1.0) gives you full control of each stage. **LiveKit Agents** (1.8.x) gives you WebRTC rooms, telephony and an `AgentSession` that runs either a speech-to-text → LLM → text-to-speech cascade or a speech-to-speech realtime model. In Oct 2026 the main design choice is cascade (text-level control) versus realtime (`gpt-realtime-2.1`, Gemini 3.8 Live), with cheap decision models handling the small, latency-critical choices.

**Type:** Learn · **Languages:** Python (stdlib) · **Time:** ~60 min

---

## 1. The problem

A text agent can think for 20 seconds and nobody minds. A voice agent that takes more than about 1.5 seconds sounds broken, and one that talks over the user sounds rude. Voice adds four problems that text never had:

1. **Turn-taking.** Silence is not the end of a turn ("I want to move my appointment and... um..."). Ending the turn too early interrupts the user. Ending it too late leaves dead air.
2. **Barge-in.** The user interrupts. Audio that is already queued must stop, and the conversation history must record only what was actually spoken.
3. **Noisy input.** Speech-to-text errors look like confident text. "Cancel the whole account" at 40% confidence should never trigger a cancellation.
4. **Latency stacking.** Every stage adds 30–300 ms. The total is what users hear.

## 2. The concept

### The canonical pipeline

```
DOWNSTREAM (data)  ─────────────────────────────────────────────────────►
 mic ─► transport ─► VAD ─► turn detector ─► STT ─► LLM ─► TTS ─► transport ─► speaker
 ◄──────────────────────────────────────────────────────────────────────
UPSTREAM (control)   CancelFrame on barge-in · metrics · errors
```

**Pipecat** models everything as typed `Frame`s flowing through `FrameProcessor`s. Audio, transcripts and LLM tokens flow downstream. Control frames (cancel, interruption, metrics) flow upstream. A `PipelineTask` owns the lifecycle and observers. Transports include Daily, LiveKit, SmallWebRTC, WebSockets and telephony providers. Pipecat Flows adds state-machine conversations, and Pipecat Cloud is the managed runtime.

**LiveKit Agents** starts from the room. Your agent joins a WebRTC room (or a SIP call) as a participant. `AgentSession` wires up voice activity detection (VAD), turn detection, STT, LLM and TTS, or a single realtime model, and exposes tools, handoffs between agents and MCP servers.

### Cascade vs speech-to-speech

| | Cascade (STT → LLM → TTS) | Speech-to-speech realtime |
|---|---|---|
| Examples | Any STT + any LLM + any TTS | `gpt-realtime-2.1` / `-mini`, Gemini 3.8 Live |
| Latency | More stages, more latency | Lowest; one model hop |
| Control | Full transcript, text guardrails, any LLM | Less visibility; guardrails run on side transcripts |
| Voice quality | Choose the best TTS voice | Prosody and emotion carried through |
| Cost | Mix and match | Usually higher per minute |

### Latency budget (illustrative targets)

| Stage | Typical |
|---|---|
| Transport in + VAD | 50–100 ms |
| Turn detection | 20–60 ms |
| STT final | 100–250 ms |
| LLM first token | 150–400 ms |
| TTS first audio | 100–200 ms |
| Transport out | 30–80 ms |

About 600 ms voice-to-voice feels premium. 800–1200 ms is common. Above 1500 ms feels broken. Stream every stage: the LLM should start before the transcript is polished, and TTS should start on the first sentence, not the full reply.

## 3. What changed by Oct 2026

- **Pipecat 1.12** (2026-09-25) is well past 1.0. Coverage reports that its default realtime integration targets `gpt-realtime-2.1`.
- **LiveKit Agents 1.8.x** is current. The 1.x line consolidated the old `MultimodalAgent` / `VoicePipelineAgent` split into a single `AgentSession` that accepts either style. Check the changelog for newer features before you rely on them.
- **OpenAI `gpt-realtime-2.1` and `-mini`** (Jul 2026) brought reasoning into the Realtime API. Coverage reports p95 latency down 25% or more versus the previous generation. `gpt-live-transcribe` handles streaming transcription.
- **Gemini 3.8 Live is GA** (Sep 2026). ADK added Live avatars.
- **Decision models entered the voice hot path.** Cloudflare's **Clef-omni** (2026-10-09) accepts audio directly (WAV/MP3) as well as text, images and video. It answers typed questions in well under 100 ms for audio. That fits the small decisions in a voice loop: "Is the user done?", "Is this an interruption or a backchannel ('mm-hm')?", "Which intent: billing, tech or human?", "Is the caller distressed enough to escalate?". It returns probabilities, and your code owns the thresholds (Lessons 55–57).

## 4. Build it

`code/main.py` is a frame pipeline with a simulated clock:

- `STAGE_LATENCY_MS` is the per-stage budget. `budget_report()` totals it and classifies cascade against speech-to-speech.
- `turn_complete_probability()` is a toy semantic turn detector. It combines punctuation, filler words ("and", "um") and trailing silence into P(done), the role a model like Clef-omni plays in production.
- `downstream_user_turn()` runs VAD and turn detection per chunk, and finalizes STT only once P(done) crosses the threshold.
- `respond()` streams TTS sentence by sentence. `upstream_cancel()` is the barge-in `CancelFrame`.
- Case 1: a mid-sentence pause does not end the turn. Case 2: barge-in cuts TTS after one sentence. Case 3: a low-confidence transcript triggers "say that again" instead of a cancellation.

```bash
python3 code/main.py
```

What to look for: the timestamps on the turn detector lines, the `UPSTREAM CancelFrame` line, and the cascade (715 ms) versus speech-to-speech budget at the bottom.

## 5. Use it in production

- **Pipecat:** you want custom processors, unusual providers, research on turn-taking, or a Python-native stack.
- **LiveKit Agents:** WebRTC-first apps, SIP telephony, multi-participant rooms, LiveKit Cloud scaling and its inference gateway.
- **Managed platforms (Vapi, Retell and similar):** when you need a phone agent next week and have no real-time media team.
- **Realtime models:** `gpt-realtime-2.1` / `-mini` and Gemini 3.8 Live for the lowest latency. Keep a side transcript for guardrails and logging.
- **Decision layer:** Clef-omni on raw audio, or Clef-flash / Jev on transcripts, for end-of-turn, intent routing and escalation. A gate before any irreversible tool call ("cancel account", "send payment") still needs explicit confirmation by voice.
- **Observability:** trace per-stage latency as OTel spans (Lesson 23). Most platforms now offer voice tracing (for example LangSmith).

## 6. Architect's lens

1. **Measure p95 voice-to-voice, not the mean.** One slow STT call per minute ruins the experience. Budget each stage and alert on the stage, not just the total.
2. **Interruptions corrupt context.** On barge-in, truncate the assistant's last turn to what was actually played. Otherwise the model "remembers" saying things the user never heard.
3. **Confidence is a first-class signal.** Carry STT confidence and turn-detector probability through the pipeline. Destructive intents require both high confidence and spoken confirmation.
4. **Split fast decisions from slow reasoning.** End-of-turn, routing and escalation are classification tasks with a 50 ms budget. Give them to a decision model and keep the LLM for the answer. That one change often saves more latency than switching LLMs.
5. **Telephony is its own failure domain.** 8 kHz audio, DTMF, voicemail detection and carrier jitter. Test on real phone lines, not only on browser WebRTC.

## 7. Exercises

1. Add a backchannel detector: "mm-hm" and "right" during TTS should *not* trigger a cancel. What features distinguish them from a real interruption?
2. Make `respond()` truncate a `history` list to the sentences actually spoken before the cancel.
3. Add jitter: draw each stage latency from a seeded distribution and report p50 and p95 over 1,000 turns.
4. Add a destructive-intent gate: "cancel account" needs P(intent) ≥ 0.9, STT confidence ≥ 0.8 and a spoken "yes" on a follow-up turn.
5. Sketch the same pipeline as a LiveKit `AgentSession` and as a Pipecat `Pipeline`. Which stages are configuration and which are your code?

## 8. Key terms

| Term | Meaning |
|---|---|
| Frame | Typed unit flowing through a Pipecat pipeline (audio, text, control) |
| Downstream / upstream | Data direction (source to sink) vs control direction (cancel, metrics) |
| VAD | Voice activity detection: is someone speaking right now? |
| Semantic turn detection | A model decides whether the user has finished, not just whether there was silence |
| Barge-in | User speaks while the agent is talking; playback must stop |
| Cascade | STT → LLM → TTS chain with text in the middle |
| Speech-to-speech | One realtime model hears audio and produces audio |
| Voice-to-voice latency | End of user speech to first agent audio |

## 9. Quick check

<details><summary>1. Why not end the turn after 500 ms of silence?</summary>People pause mid-thought. A fixed silence rule either interrupts them or adds dead air. Semantic turn detection uses the words and prosody, not just silence, to estimate P(done).</details>
<details><summary>2. What must happen on barge-in besides stopping audio?</summary>Flush queued TTS, cancel in-flight LLM generation, and truncate the assistant turn in history to what was actually heard.</details>
<details><summary>3. When would you pick a cascade over a realtime model?</summary>When you need a specific LLM, text-level guardrails and audit logs, a specific TTS voice, or lower cost, and can accept a few hundred extra milliseconds.</details>

## References

- Pipecat docs: https://docs.pipecat.ai/ · repo: https://github.com/pipecat-ai/pipecat
- LiveKit Agents docs: https://docs.livekit.io/agents/ · repo: https://github.com/livekit/agents
- OpenAI changelog (realtime, transcription): https://developers.openai.com/api/docs/changelog
- gpt-realtime-2.1 coverage: https://www.marktechpost.com/2026/07/06/openai-gpt-realtime-2-1-mini-reasoning-realtime-api/
- Gemini models (3.8 Live): https://ai.google.dev/gemini-api/docs/models
- Cloudflare Clef launch: https://developers.cloudflare.com/changelog/post/2026-10-01-clef-workers-ai/
