from __future__ import annotations

from dataclasses import dataclass, field

STAGE_LATENCY_MS = {
    "transport_in": 40,
    "vad": 30,
    "turn_detector": 25,
    "stt_final": 160,
    "llm_first_token": 280,
    "tts_first_audio": 140,
    "transport_out": 40,
}


@dataclass
class Frame:
    kind: str
    payload: str = ""
    confidence: float = 1.0
    t_ms: int = 0


@dataclass
class Clock:
    now_ms: int = 0

    def advance(self, ms: int) -> int:
        self.now_ms += ms
        return self.now_ms


@dataclass
class Log:
    lines: list[str] = field(default_factory=list)

    def emit(self, clock: Clock, stage: str, text: str) -> None:
        self.lines.append(f"  t={clock.now_ms:5d}ms  {stage:<14} {text}")


def turn_complete_probability(partial: str, trailing_silence_ms: int) -> float:
    text = partial.strip().lower()
    score = 0.15
    if text.endswith("?") or text.endswith("."):
        score += 0.45
    if text.split()[-1:] in (["and"], ["um"], ["so"], ["but"]):
        score -= 0.35
    score += min(trailing_silence_ms, 800) / 800 * 0.4
    return max(0.0, min(1.0, score))


class Pipeline:
    def __init__(self, stt_confidence_floor: float = 0.6, end_of_turn_threshold: float = 0.7) -> None:
        self.clock = Clock()
        self.log = Log()
        self.stt_floor = stt_confidence_floor
        self.eot_threshold = end_of_turn_threshold
        self.speaking = False
        self.cancelled = False
        self.speech_end_ms = 0

    def downstream_user_turn(self, chunks: list[tuple[str, float, int]]) -> Frame | None:
        transcript = ""
        for text, confidence, silence_ms in chunks:
            self.speech_end_ms = self.clock.now_ms
            self.clock.advance(STAGE_LATENCY_MS["transport_in"] + STAGE_LATENCY_MS["vad"])
            transcript = (transcript + " " + text).strip()
            self.clock.advance(STAGE_LATENCY_MS["turn_detector"])
            p_done = turn_complete_probability(transcript, silence_ms)
            self.log.emit(self.clock, "turn_detector", f"P(done)={p_done:.2f} after {text!r}")
            if p_done >= self.eot_threshold:
                self.clock.advance(STAGE_LATENCY_MS["stt_final"])
                frame = Frame("transcript", transcript, confidence, self.clock.now_ms)
                self.log.emit(self.clock, "stt", f"final {transcript!r} conf={confidence:.2f}")
                return frame
        return None

    def respond(self, transcript: Frame, reply_sentences: list[str], barge_in_after: int | None = None) -> int:
        start = self.speech_end_ms
        if transcript.confidence < self.stt_floor:
            reply_sentences = ["Sorry, could you say that again?"]
            self.log.emit(self.clock, "llm", "low STT confidence, asking to repeat")
        self.clock.advance(STAGE_LATENCY_MS["llm_first_token"])
        self.log.emit(self.clock, "llm", "first token")
        self.clock.advance(STAGE_LATENCY_MS["tts_first_audio"] + STAGE_LATENCY_MS["transport_out"])
        first_audio = self.clock.now_ms - start
        self.log.emit(self.clock, "transport_out", f"first audio, voice-to-voice {first_audio} ms")
        self.speaking = True
        for index, sentence in enumerate(reply_sentences):
            if self.cancelled:
                break
            self.clock.advance(400)
            self.log.emit(self.clock, "tts", f"speak {sentence!r}")
            if barge_in_after is not None and index == barge_in_after:
                self.upstream_cancel("user started speaking")
        self.speaking = False
        return first_audio

    def upstream_cancel(self, reason: str) -> None:
        self.clock.advance(STAGE_LATENCY_MS["vad"])
        self.cancelled = True
        self.log.emit(self.clock, "UPSTREAM", f"CancelFrame: {reason}; flush TTS, truncate context")


def classify(total_ms: int) -> str:
    if total_ms <= 600:
        return "premium (<= 600 ms)"
    if total_ms <= 1200:
        return "common (600-1200 ms)"
    if total_ms <= 1500:
        return "sluggish (1200-1500 ms)"
    return "feels broken (> 1500 ms)"


def budget_report() -> None:
    cascade = sum(STAGE_LATENCY_MS.values())
    speech_to_speech = STAGE_LATENCY_MS["transport_in"] + STAGE_LATENCY_MS["vad"] + STAGE_LATENCY_MS["turn_detector"] + 300 + STAGE_LATENCY_MS["transport_out"]
    print("\nlatency budget (illustrative stage targets, ms):")
    for stage, ms in STAGE_LATENCY_MS.items():
        bar = "#" * (ms // 20)
        print(f"  {stage:<16} {ms:>4}  {bar}")
    print(f"  {'cascade total':<16} {cascade:>4}")
    print(f"  {'speech-to-speech':<16} {speech_to_speech:>4}  (realtime model replaces stt+llm+tts)")
    for name, total in (("cascade", cascade), ("speech-to-speech", speech_to_speech)):
        print(f"  {name}: {classify(total)}")


def main() -> None:
    print("=" * 74)
    print("VOICE AGENT PIPELINE: frames, turn detection, barge-in (Oct 2026 edition)")
    print("=" * 74)

    print("\ncase 1: user pauses mid-sentence, then finishes the question")
    p = Pipeline()
    t = p.downstream_user_turn([
        ("I want to move my appointment and", 0.92, 350),
        ("um", 0.92, 500),
        ("can you do Thursday?", 0.93, 600),
    ])
    assert t is not None
    v2v = p.respond(t, ["Sure, Thursday works.", "I have 10 or 2.", "Which do you prefer?"])
    print("\n".join(p.log.lines))
    print(f"  -> voice-to-voice latency {v2v} ms")

    print("\ncase 2: user barges in after the first sentence")
    p = Pipeline()
    t = p.downstream_user_turn([("What's my balance?", 0.95, 700)])
    assert t is not None
    p.respond(t, ["Your balance is 420 dollars.", "Your last payment was", "on the third."], barge_in_after=0)
    print("\n".join(p.log.lines))

    print("\ncase 3: noisy line, low STT confidence")
    p = Pipeline()
    t = p.downstream_user_turn([("cancel the whole account.", 0.41, 700)])
    assert t is not None
    p.respond(t, ["Account cancelled."])
    print("\n".join(p.log.lines))

    budget_report()


if __name__ == "__main__":
    main()
