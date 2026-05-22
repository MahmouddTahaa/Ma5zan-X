"""
Traffic intensity model — varies order likelihood by time of day
"""

_HOURLY_MULTIPLIERS = {
    0: 0.05,
    1: 0.02,
    2: 0.02,
    3: 0.02,
    4: 0.02,
    5: 0.05,
    6: 0.10,
    7: 0.30,
    8: 0.50,
    9: 0.80,
    10: 0.70,
    11: 0.75,
    12: 1.00,
    13: 1.10,
    14: 0.90,
    15: 0.80,
    16: 0.85,
    17: 1.00,
    18: 1.20,
    19: 1.40,
    20: 1.10,
    21: 0.70,
    22: 0.30,
    23: 0.10,
}


def intensity(simulated_hour: int) -> float:
    return _HOURLY_MULTIPLIERS.get(simulated_hour, 1.0)


def apply_traffic(base_prob: float, simulated_hour: int) -> float:
    return min(base_prob * intensity(simulated_hour), 0.95)
