from __future__ import annotations

import re
from typing import Any

CATEGORY_WEIGHTS = {
    "hook": 0.17,
    "curiosity": 0.14,
    "emotion": 0.11,
    "controversy": 0.13,
    "clarity": 0.11,
    "shareability": 0.12,
    "comments": 0.11,
    "retention": 0.11,
}

CURIOSITY = {"segredo", "verdade", "ninguém", "ninguem", "revelou", "descobriu", "motivo", "por que", "nunca", "agora", "isso"}
EMOTION = {"chocante", "absurdo", "inacreditável", "inacreditavel", "medo", "amor", "ódio", "odio", "surpresa", "emocionante", "revoltante"}
CONTROVERSY = {"polêmica", "polemica", "crítica", "critica", "ataque", "briga", "discussão", "discussao", "crime", "preso", "governo", "eleição", "eleicao", "denúncia", "denuncia"}
SHARE = {"compartilhe", "manda", "veja", "assista", "todo mundo", "precisa ver", "viral", "alerta", "urgente"}
COMMENT = {"você concorda", "voce concorda", "concorda", "discorda", "opinião", "opiniao", "comente", "quem", "qual", "por quê", "por que"}
HOOK = {"você não", "voce nao", "ninguém", "ninguem", "olha isso", "atenção", "atencao", "nunca", "acabou de", "isso vai", "verdade"}


def _clamp(value: float) -> int:
    return int(round(max(0.0, min(100.0, value))))


def _hits(text: str, terms: set[str]) -> int:
    return sum(1 for term in terms if term in text)


def _lexical_score(text: str, terms: set[str], *, base: float = 34, per_hit: float = 14, cap: float = 96) -> int:
    return _clamp(min(cap, base + _hits(text, terms) * per_hit))


def _clarity(text: str) -> int:
    words = re.findall(r"[\wÀ-ÿ]+", text, flags=re.UNICODE)
    if not words:
        return 40
    avg = sum(len(w) for w in words) / len(words)
    punctuation = 6 if re.search(r"[.!?]", text) else 0
    length_penalty = max(0, len(words) - 90) * 0.35
    return _clamp(82 - abs(avg - 5.2) * 4 + punctuation - length_penalty)


def _retention(duration: float, text: str) -> int:
    # Shorts around 25–60s get the strongest baseline. We intentionally do not
    # claim observed retention; this is only an editing heuristic.
    if 25 <= duration <= 60:
        base = 82
    elif 15 <= duration <= 90:
        base = 72
    elif duration <= 120:
        base = 62
    else:
        base = 50
    if len(text.split()) >= 12:
        base += 5
    return _clamp(base)


def score_clip_payload(payload: dict[str, Any]) -> dict[str, Any]:
    title = str(payload.get("title") or "")
    hook = str(payload.get("hook") or "")
    reason = str(payload.get("reason") or "")
    body = str(payload.get("text") or payload.get("transcript") or "")
    text = " ".join([title, hook, reason, body]).lower()
    duration = max(0.0, float(payload.get("duration") or 0.0))
    try:
        prior = float(payload.get("score") or 0.0)
    except Exception:
        prior = 0.0
    prior100 = prior * 10 if prior <= 10 else prior

    question_bonus = 12 if "?" in text else 0
    number_bonus = 7 if re.search(r"\b\d+[.,]?\d*\s*(%|mil|milhão|milhao|bilhão|bilhao)?", text) else 0
    breakdown = {
        "hook": _clamp(_lexical_score((title + " " + hook).lower(), HOOK, base=42, per_hit=15) + question_bonus / 2),
        "curiosity": _clamp(_lexical_score(text, CURIOSITY, base=42, per_hit=14) + question_bonus),
        "emotion": _lexical_score(text, EMOTION, base=38, per_hit=16),
        "controversy": _lexical_score(text, CONTROVERSY, base=36, per_hit=15),
        "clarity": _clarity(" ".join([title, hook, body])),
        "shareability": _clamp(_lexical_score(text, SHARE, base=42, per_hit=13) + number_bonus),
        "comments": _clamp(_lexical_score(text, COMMENT | CONTROVERSY, base=40, per_hit=11) + question_bonus),
        "retention": _retention(duration, body or title),
    }
    heuristic = sum(breakdown[key] * CATEGORY_WEIGHTS[key] for key in CATEGORY_WEIGHTS)
    score = _clamp(heuristic * 0.72 + max(0, min(100, prior100)) * 0.28)
    label = "Muito alto" if score >= 85 else "Alto" if score >= 70 else "Médio" if score >= 50 else "Baixo"
    signals = []
    if breakdown["curiosity"] >= 70: signals.append("curiosity")
    if breakdown["controversy"] >= 70: signals.append("controversy")
    if breakdown["comments"] >= 70: signals.append("comments")
    if breakdown["hook"] >= 70: signals.append("hook")
    return {"version": 2, "score": score, "label": label, "breakdown": breakdown, "signals": signals, "estimated": True}


def score_clip_payload_v3(payload: dict[str, Any], *, creator_calibration: dict[str, Any] | None = None) -> dict[str, Any]:
    """ViralScore 3.0: deterministic multimodal-ready score.

    It remains honest: audio/video fields are only used when callers provide real
    measurements. Missing modalities never get fabricated values.
    """
    base = score_clip_payload(payload)
    text = " ".join(str(payload.get(k) or "") for k in ("title", "hook", "reason", "text", "transcript"))
    duration = max(0.0, float(payload.get("duration") or 0.0))
    words = re.findall(r"[\wÀ-ÿ]+", text, flags=re.UNICODE)
    wps = len(words) / max(1.0, duration)
    structure = {
        "pace": _clamp(88 - abs(wps - 2.6) * 22) if words else 45,
        "open_loop": _clamp(45 + (18 if "?" in text else 0) + _hits(text.lower(), CURIOSITY) * 9),
        "payoff": _clamp(52 + (12 if re.search(r"\b(porque|por isso|resultado|então|entao|descobriu|revelou)\b", text.lower()) else 0)),
    }
    audio = payload.get("audio_signals") if isinstance(payload.get("audio_signals"), dict) else None
    video = payload.get("video_signals") if isinstance(payload.get("video_signals"), dict) else None
    modality_scores: dict[str, int] = {}
    if audio:
        energy = float(audio.get("energy") or 0.0); silence = float(audio.get("silence_ratio") or 0.0); variation = float(audio.get("energy_variation") or 0.0)
        modality_scores["audio_energy"] = _clamp(45 + energy * 35 + variation * 25 - silence * 35)
    if video:
        motion = float(video.get("motion") or 0.0); cuts = float(video.get("scene_changes_per_min") or 0.0); faces = float(video.get("face_coverage") or 0.0)
        modality_scores["visual_dynamics"] = _clamp(40 + motion * 30 + min(25, cuts * 2.5) + faces * 20)
    structural = sum(structure.values()) / len(structure)
    score = float(base["score"]) * 0.82 + structural * 0.18
    if modality_scores:
        modal = sum(modality_scores.values()) / len(modality_scores)
        score = score * 0.86 + modal * 0.14
    calibration = creator_calibration or {}
    if calibration.get("score") is not None:
        calibrated = float(calibration["score"])
        confidence = max(0.0, min(1.0, float(calibration.get("confidence") or 0)))
        score = score * (1 - 0.35 * confidence) + calibrated * (0.35 * confidence)
    score_i = _clamp(score)
    strengths = sorted(base["breakdown"].items(), key=lambda kv: kv[1], reverse=True)[:3]
    risks = sorted(base["breakdown"].items(), key=lambda kv: kv[1])[:2]
    return {
        **base,
        "version": 3,
        "score": score_i,
        "label": "Muito alto" if score_i >= 85 else "Alto" if score_i >= 70 else "Médio" if score_i >= 50 else "Baixo",
        "structure": structure,
        "modalities": modality_scores,
        "creator_calibration": calibration or None,
        "explanation": {
            "strengths": [{"signal": k, "score": v} for k, v in strengths],
            "risks": [{"signal": k, "score": v} for k, v in risks],
            "measured_modalities": sorted(modality_scores),
        },
        "estimated": True,
    }
