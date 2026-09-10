"""Post-processing for synthesized speech.

ElevenLabs exposes no pitch control - stability/similarity/style change
delivery, not vocal register - so depth has to be added after synthesis.
This uses libavfilter through PyAV, which is already a faster-whisper
dependency, so it needs no ffmpeg binary on PATH.
"""
import io
from fractions import Fraction

import av
from av.filter import Graph

from src.security.audit import audit


def _build_graph(sample_rate: int, layout: str, fmt: str, factor: float) -> tuple[Graph, object]:
    """
    asetrate lowers pitch by resampling (which also slows playback), then
    atempo speeds it back up by the inverse, leaving pitch down and duration
    unchanged. This is the standard libavfilter pitch-shift chain.
    """
    graph = Graph()
    src = graph.add_abuffer(
        sample_rate=sample_rate,
        format=fmt,
        layout=layout,
        time_base=Fraction(1, sample_rate),
    )
    nodes = [
        graph.add("asetrate", str(int(sample_rate * factor))),
        graph.add("aresample", str(sample_rate)),
        graph.add("atempo", f"{1 / factor:.6f}"),
        graph.add("aformat", f"sample_fmts=fltp:sample_rates={sample_rate}:channel_layouts={layout}"),
        graph.add("abuffersink"),
    ]
    prev = src
    for node in nodes:
        prev.link_to(node)
        prev = node
    graph.configure()
    return graph, src


def deepen(mp3_bytes: bytes, factor: float) -> bytes:
    """
    Lower the pitch of MP3 audio without changing its duration.

    factor is a pitch multiplier: 1.0 is unchanged, 0.92 is about 1.5
    semitones down, 0.85 is about 2.8 semitones down. Below roughly 0.80 the
    formants smear and it starts sounding like a slowed tape rather than a
    deeper voice.

    Returns the original bytes unchanged if anything goes wrong - a failed
    effect must never cost the user their audio.
    """
    if not mp3_bytes or factor >= 0.999:
        return mp3_bytes

    try:
        in_container = av.open(io.BytesIO(mp3_bytes), "r")
        in_stream = in_container.streams.audio[0]
        ctx = in_stream.codec_context
        sample_rate = ctx.sample_rate

        graph, src = _build_graph(sample_rate, ctx.layout.name, ctx.format.name, factor)

        out_buffer = io.BytesIO()
        out_container = av.open(out_buffer, "w", format="mp3")
        out_stream = out_container.add_stream("mp3", rate=sample_rate)

        def drain():
            while True:
                try:
                    frame = graph.pull()
                except (av.BlockingIOError, av.EOFError):
                    return
                frame.pts = None
                for packet in out_stream.encode(frame):
                    out_container.mux(packet)

        for frame in in_container.decode(in_stream):
            frame.pts = None
            src.push(frame)
            drain()

        src.push(None)   # flush the graph
        drain()

        for packet in out_stream.encode(None):
            out_container.mux(packet)

        out_container.close()
        in_container.close()
        return out_buffer.getvalue()

    except Exception as e:
        audit.log_event("audio_fx.error", {"error": str(e), "factor": factor})
        return mp3_bytes
