from __future__ import annotations

import math
import re
from collections import Counter

from .llm import chat_json, enabled as llm_enabled

HOOK_TERMS = {
    "pt": [
        "ninguém", "segredo", "verdade", "polêmica", "absurdo", "chocante", "revelou",
        "confesso", "confissão", "exposed", "bomba", "não acredito", "você precisa",
        "o problema", "o pior", "o melhor", "nunca", "sempre", "descobri", "erro",
        "mentira", "prova", "bastidores", "treta", "briga", "discordo", "não concordo",
        "mudou tudo", "ninguém fala", "presta atenção", "olha isso", "escuta",
    ],
    "en": [
        "nobody", "secret", "truth", "controversial", "shocking", "revealed", "confess",
        "exposed", "you need", "the problem", "worst", "best", "never", "always",
        "discovered", "mistake", "proof", "behind the scenes", "disagree", "plot twist",
        "listen", "watch this", "here's the thing",
    ],
}

EMOTION_TERMS = [
    "amor", "odeio", "raiva", "medo", "chor", "feliz", "triste", "inacreditável", "insano",
    "surpresa", "rir", "risada", "love", "hate", "angry", "fear", "cry", "happy", "sad",
    "unbelievable", "insane", "surprise", "laugh",
]

STOP = set("a o e de da do das dos um uma para por com sem em no na nos nas que se eu você ele ela nós voces eles elas this that the and or to of in on for with is are was were be been i you he she we they it".split())


def _tokens(text: str) -> list[str]:
    return [t for t in re.findall(r"[\wÀ-ÿ']+", text.lower()) if len(t) > 2 and t not in STOP]


def _tfidf_segment_scores(segments: list[dict]) -> dict[int, float]:
    docs = {s["id"]: _tokens(s.get("text", "")) for s in segments}
    n = max(1, len(docs))
    df = Counter()
    for toks in docs.values():
        for t in set(toks):
            df[t] += 1
    raw = {}
    maxv = 0.0
    for sid, toks in docs.items():
        if not toks:
            raw[sid] = 0.0
            continue
        tf = Counter(toks)
        score = sum((c / len(toks)) * (math.log((n + 1) / (df[t] + 1)) + 1) for t, c in tf.items())
        raw[sid] = score
        maxv = max(maxv, score)
    return {k: (v / maxv if maxv else 0.0) for k, v in raw.items()}


def _make_windows(segments: list[dict], min_d: float, max_d: float) -> list[dict]:
    windows = []
    n = len(segments)
    for i in range(n):
        text_parts = []
        for j in range(i, min(n, i + 22)):
            text_parts.append(segments[j].get("text", ""))
            dur = segments[j]["end"] - segments[i]["start"]
            if dur < min_d:
                continue
            if dur > max_d:
                break
            windows.append({
                "start": segments[i]["start"],
                "end": segments[j]["end"],
                "segments": segments[i:j+1],
                "text": " ".join(text_parts).strip(),
            })
    return windows


def _score_window(w: dict, tfidf: dict[int, float], total_duration: float, custom_keywords: str = "") -> tuple[float, dict, str]:
    text = w["text"]
    low = text.lower()
    hook_hits = sum(1 for k in HOOK_TERMS["pt"] + HOOK_TERMS["en"] if k in low)
    custom_hits = sum(1 for k in [x.strip().lower() for x in custom_keywords.split(",") if x.strip()] if k in low)
    emotion_hits = sum(1 for k in EMOTION_TERMS if k in low)
    tf = sum(tfidf.get(s["id"], 0) for s in w["segments"]) / max(1, len(w["segments"]))
    punctuation = min(1.0, (text.count("?") * 0.22) + (text.count("!") * 0.16))
    contrast = min(1.0, sum(0.15 for p in ["mas ", "porém", "só que", "however", "but ", "a verdade", "the truth"] if p in low))
    position = ((w["start"] + w["end"]) / 2) / max(1.0, total_duration)
    position_bonus = 0.85 if position < 0.15 else (0.75 if 0.55 <= position <= 0.85 else 0.45)
    hook = min(1.0, hook_hits * 0.18 + custom_hits * 0.22)
    emotion = min(1.0, emotion_hits * 0.16)
    duration = w["end"] - w["start"]
    duration_fit = 1.0 if 30 <= duration <= 75 else (0.75 if 20 <= duration <= 100 else 0.45)
    total = (tf * 0.24 + hook * 0.28 + emotion * 0.12 + punctuation * 0.08 + contrast * 0.10 + position_bonus * 0.08 + duration_fit * 0.10)
    breakdown = {
        "tfidf": round(tf, 3), "hook": round(hook, 3), "emotion": round(emotion, 3),
        "punctuation": round(punctuation, 3), "contrast": round(contrast, 3),
        "position": round(position_bonus, 3), "duration_fit": round(duration_fit, 3),
    }
    reason = max(breakdown, key=breakdown.get)
    return round(total * 100, 1), breakdown, reason


def _dedupe(candidates: list[dict], max_clips: int) -> list[dict]:
    ordered = sorted(candidates, key=lambda x: x["score"], reverse=True)
    kept = []
    for c in ordered:
        bad = False
        for k in kept:
            overlap = max(0.0, min(c["end"], k["end"]) - max(c["start"], k["start"]))
            smaller = min(c["end"] - c["start"], k["end"] - k["start"])
            if smaller > 0 and overlap / smaller > 0.45:
                bad = True
                break
        if not bad:
            kept.append(c)
        if len(kept) >= max_clips:
            break
    return kept


def _llm_candidates(transcript: dict, num_clips: int, min_d: float, max_d: float) -> list[dict]:
    if not llm_enabled():
        return []
    segments = transcript.get("segments", [])
    # Chunk to control context size. Each chunk keeps timestamps so outputs remain absolute.
    chunks, current, chars = [], [], 0
    for s in segments:
        line = f"[{s['start']:.1f}-{s['end']:.1f}] {s['text']}"
        if current and chars + len(line) > 14000:
            chunks.append(current)
            current, chars = [], 0
        current.append(line)
        chars += len(line)
    if current:
        chunks.append(current)

    system = f"""Você é um editor especialista em TikTok, Reels e Shorts. Selecione momentos autossuficientes com alto potencial de retenção e comentários. Priorize hook imediato, revelações, opiniões fortes, emoção, conflito, histórias com payoff e dicas práticas. Não corte no meio de uma ideia. Duração entre {min_d:.0f} e {max_d:.0f} segundos. Retorne SOMENTE JSON no formato {{\"highlights\":[{{\"title\":\"...\",\"start\":0.0,\"end\":45.0,\"score\":90,\"hook\":\"...\",\"reason\":\"...\"}}]}}."""
    out = []
    for lines in chunks:
        data = chat_json(system, "TRANSCRIÇÃO:\n" + "\n".join(lines) + f"\nGere até {max(3, num_clips)} candidatos.")
        if not data:
            continue
        for h in data.get("highlights", []):
            try:
                start, end = float(h["start"]), float(h["end"])
                if end <= start or end - start < min_d * 0.7 or end - start > max_d * 1.25:
                    continue
                out.append({
                    "start": start, "end": end, "score": float(h.get("score", 75)),
                    "title": str(h.get("title", "Corte viral")), "hook": str(h.get("hook", "")),
                    "reason": str(h.get("reason", "LLM")), "breakdown": {"llm": 1.0},
                })
            except Exception:
                pass
    return out


def find_highlights(transcript: dict, num_clips: int = 5, min_duration: float = 20, max_duration: float = 90, custom_keywords: str = "", use_llm: bool = True) -> list[dict]:
    segments = transcript.get("segments", [])
    if not segments:
        return []
    total = float(transcript.get("duration") or segments[-1]["end"])
    tfidf = _tfidf_segment_scores(segments)
    windows = _make_windows(segments, min_duration, max_duration)
    heuristic = []
    for w in windows:
        score, breakdown, reason = _score_window(w, tfidf, total, custom_keywords)
        if score < 28:
            continue
        first_sentence = re.split(r"(?<=[.!?])\s+", w["text"])[0][:180]
        heuristic.append({
            "start": w["start"], "end": w["end"], "score": score,
            "title": first_sentence[:70] or "Corte viral", "hook": first_sentence,
            "reason": reason, "breakdown": breakdown,
        })
    candidates = heuristic
    if use_llm:
        candidates += _llm_candidates(transcript, num_clips, min_duration, max_duration)
    return _dedupe(candidates, num_clips)


def sequential_highlights(transcript: dict, target_duration: float = 60, overlap: float = 1.5) -> list[dict]:
    segments = transcript.get("segments", [])
    if not segments:
        return []
    out, start_idx, idx = [], 0, 1
    while start_idx < len(segments):
        start = segments[start_idx]["start"]
        end_idx = start_idx
        while end_idx + 1 < len(segments) and segments[end_idx + 1]["end"] - start <= target_duration:
            end_idx += 1
        end = segments[end_idx]["end"]
        text = " ".join(s["text"] for s in segments[start_idx:end_idx+1])
        out.append({"start": start, "end": end, "score": 50, "title": f"Parte {idx}", "hook": text[:160], "reason": "sequential"})
        idx += 1
        if end_idx >= len(segments) - 1:
            break
        next_start = end - overlap
        start_idx = end_idx + 1
        for k in range(max(0, end_idx - 2), end_idx + 2):
            if k < len(segments) and segments[k]["start"] >= next_start:
                start_idx = k
                break
    return out
