"""Probability calibration.

``TemperatureScaler`` rescales a model's predicted probabilities with a single
temperature parameter fitted on a validation set (Guo et al., 2017). It turns
over-confident softmax outputs into better-calibrated confidences, which matters
when the assistant decides whether it is sure enough to act.
"""
from __future__ import annotations

import math


class TemperatureScaler:
    def __init__(self, grid=None):
        self.temperature = 1.0
        self.grid = grid or [round(0.25 + 0.05 * i, 2) for i in range(1, 60)]

    @staticmethod
    def _apply(probabilities, temperature):
        # Convert probabilities to logits, divide by T, re-softmax.
        logits = {label: math.log(max(p, 1e-12)) for label, p in probabilities.items()}
        scaled = {label: value / temperature for label, value in logits.items()}
        highest = max(scaled.values())
        exps = {label: math.exp(value - highest) for label, value in scaled.items()}
        total = sum(exps.values()) or 1.0
        return {label: value / total for label, value in exps.items()}

    def fit(self, probability_list, labels):
        if not probability_list:
            return self
        best_temperature, best_loss = 1.0, float("inf")
        for temperature in self.grid:
            loss = 0.0
            for probabilities, label in zip(probability_list, labels):
                scaled = self._apply(probabilities, temperature)
                loss -= math.log(max(scaled.get(label, 0.0), 1e-12))
            loss /= len(probability_list)
            if loss < best_loss:
                best_loss, best_temperature = loss, temperature
        self.temperature = best_temperature
        return self

    def calibrate(self, probabilities):
        if self.temperature == 1.0:
            return probabilities
        return self._apply(probabilities, self.temperature)
