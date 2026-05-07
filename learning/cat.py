import math
from collections import Counter

from .parse_mini import parse_header, parse_mini


BLOOM_LABELS = {
    "L1": "Recordar",
    "L2": "Comprender",
    "L3": "Aplicar",
    "L4": "Analizar",
    "L5": "Evaluar",
    "L6": "Crear",
}


def parse_cat_params(assessment):
    meta = parse_header(assessment.header) if assessment.header else {}
    raw = meta.get("cat", "0,-3,3,0.30,10,SH").split(",")
    return {
        "theta_init": _float_at(raw, 0, 0.0),
        "theta_min": _float_at(raw, 1, -3.0),
        "theta_max": _float_at(raw, 2, 3.0),
        "se_stop": _float_at(raw, 3, 0.30),
        "max_items": int(_float_at(raw, 4, 10)),
        "exposure_control": raw[5] if len(raw) > 5 else "SH",
    }


def build_bank(mini_text):
    assessment = parse_mini(mini_text)
    params = parse_cat_params(assessment)
    return assessment.items, params


def choose_next_item(items, used_ids, theta, responses, target_count):
    candidates = [item for item in items if item.id not in used_ids]
    if not candidates:
        return None

    answered_bloom = Counter(response.item_bloom for response in responses)
    total = max(len(items), 1)
    bank_bloom = Counter(item.bloom for item in items)

    def score(item):
        information = item_information(item, theta)
        expected_share = bank_bloom[item.bloom] / total
        current_share = answered_bloom[item.bloom] / max(len(responses), 1)
        bloom_bonus = max(expected_share - current_share, 0) * 0.35
        demand_bonus = {"high": 0.08, "medium": 0.04, "low": 0.0}.get(item.demand, 0.02)
        length_penalty = len(used_ids) / max(target_count, 1) * item.exposure_cap * 0.05
        return information + bloom_bonus + demand_bonus - length_penalty

    return max(candidates, key=score)


def estimate_theta(items_by_id, responses, theta_min=-3.0, theta_max=3.0):
    if not responses:
        return 0.0, 9.99

    theta = 0.0
    for _ in range(18):
        gradient = 0.0
        information = 0.0
        for response in responses:
            item = items_by_id.get(response.item_id)
            if not item:
                continue
            p = probability_3pl(item, theta)
            q = max(1.0 - p, 1e-6)
            p = min(max(p, 1e-6), 1 - 1e-6)
            u = 1.0 if response.is_correct else 0.0
            d1 = d1_3pl(item, theta)
            gradient += (u - p) * d1 / (p * q)
            information += item_information(item, theta)
        if information <= 1e-6:
            break
        theta += gradient / information
        theta = max(theta_min, min(theta_max, theta))

    info = sum(item_information(items_by_id[r.item_id], theta) for r in responses if r.item_id in items_by_id)
    se = 1 / math.sqrt(info) if info > 1e-6 else 9.99
    return round(theta, 3), round(se, 3)


def probability_3pl(item, theta):
    a = max(item.irt_a, 0.01)
    b = item.irt_b
    c = min(max(item.irt_c, 0.0), 0.35)
    logistic = 1 / (1 + math.exp(-1.7 * a * (theta - b)))
    return c + (1 - c) * logistic


def item_information(item, theta):
    p = probability_3pl(item, theta)
    q = max(1 - p, 1e-6)
    p = min(max(p, 1e-6), 1 - 1e-6)
    d1 = d1_3pl(item, theta)
    return (d1 * d1) / (p * q)


def d1_3pl(item, theta):
    a = max(item.irt_a, 0.01)
    c = min(max(item.irt_c, 0.0), 0.35)
    p = probability_3pl(item, theta)
    return 1.7 * a * (p - c) * (1 - p) / max(1 - c, 1e-6)


def option_index(item):
    for index, option in enumerate(item.options):
        if option.get("correct"):
            return index
    return -1


def _float_at(values, index, default):
    try:
        return float(values[index])
    except (IndexError, TypeError, ValueError):
        return default
