"""
Modelos psicometricos del motor adaptativo v2.

- EAP (Bock & Mislevy, 1982): estimacion bayesiana de la habilidad por
  cuadratura. Frente a la maxima verosimilitud, da menor error en tests cortos
  y una desviacion posterior utilizable como error estandar desde el primer item.
- Randomesque (Kingsbury & Zara, 1989): control de exposicion eligiendo al azar
  entre los k items mas informativos; rinde como Sympson-Hetter con k = 5-6 y
  no requiere simulaciones previas.
- Calibracion en linea tipo Elo (Pelanek, 2016): los parametros de dificultad
  que entrega el modelo de lenguaje son una conjetura; cada respuesta real los
  corrige con un paso decreciente en el numero de observaciones.
- Bayesian Knowledge Tracing (Corbett & Anderson, 1995): probabilidad de que el
  estudiante domine cada tema, actualizada respuesta a respuesta con parametros
  de olvido nulo, aprendizaje, desliz y acierto por azar (0.25 para 4 opciones).
- Puerta de calidad: items con exito casi total o casi nulo tras varias
  observaciones se apartan de la seleccion (probable error de clave o trivialidad).
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from .cat import probability_3pl

THETA_GRID = [round(-4.0 + i * 0.1, 2) for i in range(81)]
EPS = 1e-6


@dataclass(frozen=True)
class ItemParams:
    irt_a: float
    irt_b: float
    irt_c: float


def _clamp_p(p: float) -> float:
    return min(max(p, EPS), 1.0 - EPS)


# ---------------------------------------------------------------------------
# EAP
# ---------------------------------------------------------------------------
def eap_estimate(items_by_id, responses, prior_mean: float = 0.0, prior_sd: float = 1.0) -> tuple[float, float]:
    """
    Media y desviacion estandar posterior de theta con prior normal
    N(prior_mean, prior_sd) y verosimilitud 3PL sobre `responses`
    (objetos con .item_id y .is_correct). Sin respuestas devuelve el prior.
    """
    prior_sd = max(float(prior_sd), 0.05)
    usable = [(items_by_id.get(r.item_id), r.is_correct) for r in responses]
    usable = [(item, u) for item, u in usable if item is not None]
    if not usable:
        return round(prior_mean, 3), round(prior_sd, 3)

    log_weights = []
    for theta in THETA_GRID:
        logw = -0.5 * ((theta - prior_mean) / prior_sd) ** 2
        for item, correct in usable:
            p = _clamp_p(probability_3pl(item, theta))
            logw += math.log(p) if correct else math.log(1.0 - p)
        log_weights.append(logw)
    peak = max(log_weights)
    weights = [math.exp(w - peak) for w in log_weights]
    total = sum(weights)
    mean = sum(t * w for t, w in zip(THETA_GRID, weights)) / total
    variance = sum(((t - mean) ** 2) * w for t, w in zip(THETA_GRID, weights)) / total
    return round(mean, 3), round(math.sqrt(max(variance, 0.0)), 3)


# ---------------------------------------------------------------------------
# Randomesque
# ---------------------------------------------------------------------------
def randomesque(candidates, score, k: int = 5, rng: random.Random | None = None):
    """Elige al azar entre los k candidatos de mayor puntaje."""
    if not candidates:
        return None
    rng = rng or random
    ranked = sorted(candidates, key=score, reverse=True)
    pool = ranked[: max(1, min(k, len(ranked)))]
    return rng.choice(pool)


# ---------------------------------------------------------------------------
# Bayesian Knowledge Tracing
# ---------------------------------------------------------------------------
BKT_DEFAULTS = {"p_init": 0.25, "p_learn": 0.12, "p_slip": 0.10, "p_guess": 0.25}


def bkt_trace(outcomes, p_init=None, p_learn=None, p_slip=None, p_guess=None) -> float:
    """Probabilidad de dominio tras una secuencia cronologica de aciertos/fallos."""
    p = BKT_DEFAULTS["p_init"] if p_init is None else p_init
    t = BKT_DEFAULTS["p_learn"] if p_learn is None else p_learn
    s = BKT_DEFAULTS["p_slip"] if p_slip is None else p_slip
    g = BKT_DEFAULTS["p_guess"] if p_guess is None else p_guess
    for correct in outcomes:
        if correct:
            posterior = p * (1 - s) / max(p * (1 - s) + (1 - p) * g, EPS)
        else:
            posterior = p * s / max(p * s + (1 - p) * (1 - g), EPS)
        p = posterior + (1 - posterior) * t
    return round(min(max(p, 0.0), 1.0), 4)


# ---------------------------------------------------------------------------
# Calibracion en linea de la dificultad (Elo con paso decreciente)
# ---------------------------------------------------------------------------
ELO_K0 = 0.4
ELO_DECAY = 8.0
B_MIN, B_MAX = -3.5, 3.5


def elo_step(n_observations: int) -> float:
    """Paso de actualizacion: grande al inicio, decreciente con las observaciones."""
    return ELO_K0 / (1.0 + n_observations / ELO_DECAY)


def calibrate_difficulty(b_current: float, n_observations: int, theta: float, irt_a: float, irt_c: float, is_correct: bool) -> float:
    """
    Mueve b hacia la dificultad observada: un acierto inesperado la baja, un
    fallo inesperado la sube, proporcional a la sorpresa (u - p).
    """
    expected = probability_3pl(ItemParams(irt_a, b_current, irt_c), theta)
    observed = 1.0 if is_correct else 0.0
    b_new = b_current + elo_step(n_observations) * (expected - observed)
    return round(min(max(b_new, B_MIN), B_MAX), 3)


# ---------------------------------------------------------------------------
# Puerta de calidad de items
# ---------------------------------------------------------------------------
QUALITY_MIN_ATTEMPTS = 8
TOO_EASY_ACCURACY = 0.97
SUSPECT_ACCURACY = 0.10


def quality_flag(attempts: int, correct: int) -> str:
    """'' (ok) · 'too_easy' (casi nadie falla) · 'suspect' (casi nadie acierta: clave dudosa)."""
    if attempts < QUALITY_MIN_ATTEMPTS:
        return ""
    accuracy = correct / attempts
    if accuracy >= TOO_EASY_ACCURACY:
        return "too_easy"
    if accuracy <= SUSPECT_ACCURACY:
        return "suspect"
    return ""
