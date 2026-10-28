"""Evaluation metrics and model-selection utilities (pure Python).

Implements the standard supervised-learning toolkit without numpy/scikit-learn:
stratified train/test splitting, k-fold cross-validation, confusion matrices,
per-class precision/recall/F1 and a macro/weighted classification report.
"""
from __future__ import annotations

import random
from collections import defaultdict


def train_test_split(samples, test_size=0.25, seed=42, stratify=True):
    """Split ``samples`` (a list of ``(label, payload)`` pairs) into train/test.

    When ``stratify`` is true the class proportions are preserved in both parts,
    which matters for small, imbalanced intent datasets. Returns ``(train, test)``.
    """
    samples = list(samples)
    rng = random.Random(seed)
    if not samples:
        return [], []
    if not stratify:
        rng.shuffle(samples)
        cut = max(1, int(round(len(samples) * test_size)))
        return samples[cut:], samples[:cut]

    by_label: dict = defaultdict(list)
    for sample in samples:
        by_label[sample[0]].append(sample)

    train, test = [], []
    for group in by_label.values():
        group = list(group)
        rng.shuffle(group)
        cut = max(1, int(round(len(group) * test_size))) if len(group) > 1 else 0
        test.extend(group[:cut])
        train.extend(group[cut:])
    rng.shuffle(train)
    rng.shuffle(test)
    if not train:
        train, test = test, []
    return train, test


def stratified_folds(samples, n_splits=5, seed=42):
    """Partition ``samples`` into ``n_splits`` class-balanced folds."""
    samples = list(samples)
    rng = random.Random(seed)
    by_label: dict = defaultdict(list)
    for sample in samples:
        by_label[sample[0]].append(sample)
    folds = [[] for _ in range(max(2, n_splits))]
    for group in by_label.values():
        group = list(group)
        rng.shuffle(group)
        for index, sample in enumerate(group):
            folds[index % len(folds)].append(sample)
    return folds


def accuracy(y_true, y_pred) -> float:
    if not y_true:
        return 0.0
    return sum(1 for a, b in zip(y_true, y_pred) if a == b) / len(y_true)


def confusion_matrix(y_true, y_pred, labels=None):
    """Return ``(labels, matrix)`` where ``matrix[true][pred]`` is a count."""
    labels = list(labels) if labels is not None else sorted(set(y_true) | set(y_pred))
    index = {label: i for i, label in enumerate(labels)}
    matrix = [[0] * len(labels) for _ in labels]
    for actual, predicted in zip(y_true, y_pred):
        if actual in index and predicted in index:
            matrix[index[actual]][index[predicted]] += 1
    return labels, matrix


def precision_recall_f1(y_true, y_pred, labels=None) -> dict:
    """Per-class precision, recall, F1 and support."""
    labels = list(labels) if labels is not None else sorted(set(y_true) | set(y_pred))
    per_class = {}
    for label in labels:
        tp = sum(1 for a, b in zip(y_true, y_pred) if a == label and b == label)
        fp = sum(1 for a, b in zip(y_true, y_pred) if a != label and b == label)
        fn = sum(1 for a, b in zip(y_true, y_pred) if a == label and b != label)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = (2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": sum(1 for value in y_true if value == label),
        }
    return per_class


def classification_report(y_true, y_pred, labels=None) -> dict:
    """Full report: per-class table plus macro/weighted aggregates."""
    labels = list(labels) if labels is not None else sorted(set(y_true) | set(y_pred))
    per_class = precision_recall_f1(y_true, y_pred, labels)
    total = len(y_true) or 1
    count = len(per_class) or 1

    def aggregate(weighted: bool) -> dict:
        weights = {
            label: (metrics["support"] if weighted else 1) for label, metrics in per_class.items()
        }
        weight_sum = sum(weights.values()) or 1
        return {
            "precision": sum(per_class[l]["precision"] * weights[l] for l in per_class) / weight_sum,
            "recall": sum(per_class[l]["recall"] * weights[l] for l in per_class) / weight_sum,
            "f1": sum(per_class[l]["f1"] * weights[l] for l in per_class) / weight_sum,
        }

    return {
        "labels": per_class,
        "accuracy": accuracy(y_true, y_pred),
        "macro": aggregate(weighted=False),
        "weighted": aggregate(weighted=True),
        "support": total,
        "n_labels": count,
    }


def cross_val_predict(build_model, samples, target_fn, n_splits=5, seed=42):
    """Out-of-fold predictions for every sample via stratified k-fold.

    ``build_model`` returns an unfitted estimator with a ``fit`` method;
    ``target_fn`` turns an estimator + payload into a prediction.
    Returns ``(y_true, y_pred)``.
    """
    samples = list(samples)
    folds = stratified_folds(samples, n_splits=n_splits, seed=seed)
    y_true, y_pred = [], []
    for i in range(len(folds)):
        test = folds[i]
        train = [sample for j, fold in enumerate(folds) if j != i for sample in fold]
        if not train or not test:
            continue
        model = build_model().fit([s[1] for s in train], [s[0] for s in train])
        for label, payload in test:
            y_true.append(label)
            y_pred.append(target_fn(model, payload))
    return y_true, y_pred


def cross_val_score(build_model, samples, target_fn, n_splits=5, seed=42):
    """Per-fold accuracy scores plus mean and standard deviation."""
    samples = list(samples)
    folds = stratified_folds(samples, n_splits=n_splits, seed=seed)
    scores = []
    for i in range(len(folds)):
        test = folds[i]
        train = [sample for j, fold in enumerate(folds) if j != i for sample in fold]
        if not train or not test:
            continue
        model = build_model().fit([s[1] for s in train], [s[0] for s in train])
        correct = sum(1 for label, payload in test if target_fn(model, payload) == label)
        scores.append(correct / len(test))
    if not scores:
        return {"scores": [], "mean": 0.0, "std": 0.0}
    mean = sum(scores) / len(scores)
    variance = sum((score - mean) ** 2 for score in scores) / len(scores)
    return {"scores": scores, "mean": mean, "std": variance ** 0.5}


def roc_auc_binary(y_true, scores, positive=1) -> float:
    """Area under the ROC curve for a binary problem (rank/Mann-Whitney form)."""
    positives = [s for t, s in zip(y_true, scores) if t == positive]
    negatives = [s for t, s in zip(y_true, scores) if t != positive]
    if not positives or not negatives:
        return 0.5
    ranked = sorted(zip(scores, y_true), key=lambda pair: pair[0])
    rank_sum = 0.0
    for rank, (_, label) in enumerate(ranked, start=1):
        if label == positive:
            rank_sum += rank
    n_pos, n_neg = len(positives), len(negatives)
    return (rank_sum - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
