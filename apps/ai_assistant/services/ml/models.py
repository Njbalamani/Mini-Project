"""Dependency-free supervised learning models.

Every classifier implements the same tiny interface::

    model.fit(X, y)            # X: list of dense float vectors, y: labels
    model.predict_proba(X)     # -> list of {label: probability} dicts
    model.predict(X)           # -> list of labels

Included algorithms
-------------------
* ``MultinomialNB``        – Naive Bayes with Laplace smoothing.
* ``SoftmaxRegression``    – multinomial logistic regression (mini-batch GD).
* ``PerceptronClassifier`` – multi-class perceptron (one-vs-rest).
* ``LinearSVM``            – linear SVM, hinge loss, SGD with L2.
* ``DecisionTreeClassifier`` – CART with Gini impurity.
* ``RegressionTree``       – CART with variance-reduction (used by boosting).
* ``RandomForestClassifier`` – bagged trees with feature subsampling.
* ``GradientBoostingClassifier`` – one-vs-rest logistic-loss boosting.
* ``MLPClassifier``        – feed-forward neural net trained with back-prop.
* ``KNNClassifier``        – k-nearest neighbours (cosine/euclidean).
* ``VotingEnsemble`` / ``StackingEnsemble`` – meta-learners.
"""
from __future__ import annotations

import copy
import math
import random
from collections import Counter


def _majority(labels):
    counts = Counter(labels)
    top = max(counts.values())
    return min(label for label, count in counts.items() if count == top)


def _softmax(scores):
    highest = max(scores.values())
    exps = {label: math.exp(value - highest) for label, value in scores.items()}
    total = sum(exps.values()) or 1.0
    return {label: value / total for label, value in exps.items()}


class BaseClassifier:
    def __init__(self):
        self.classes_: list = []

    def _encode(self, y):
        self.classes_ = sorted(set(y))

    def fit(self, X, y):
        raise NotImplementedError

    def predict_proba(self, X):
        raise NotImplementedError

    def predict(self, X):
        return [max(probs, key=probs.get) if probs else self.classes_[0]
                for probs in self.predict_proba(X)]


class MultinomialNB(BaseClassifier):
    """Naive Bayes for non-negative (count/TF-IDF) features."""

    def __init__(self, alpha=1.0):
        super().__init__()
        self.alpha = alpha
        self._log_prior: dict = {}
        self._log_likelihood: dict = {}

    def fit(self, X, y):
        self._encode(y)
        dim = len(X[0]) if X else 0
        totals = {label: [0.0] * dim for label in self.classes_}
        counts = Counter(y)
        for vector, label in zip(X, y):
            for i, value in enumerate(vector):
                totals[label][i] += value
        for label in self.classes_:
            self._log_prior[label] = math.log(counts[label] / len(y))
            denominator = sum(totals[label]) + self.alpha * dim
            self._log_likelihood[label] = [
                math.log((value + self.alpha) / denominator) for value in totals[label]
            ]
        return self

    def predict_proba(self, X):
        results = []
        for vector in X:
            scores = {}
            for label in self.classes_:
                score = self._log_prior[label]
                for i, value in enumerate(vector):
                    if value:
                        score += value * self._log_likelihood[label][i]
                scores[label] = score
            results.append(_softmax(scores))
        return results


def _linear_scores(weights, biases, vector, classes):
    scores = {}
    for label in classes:
        total = biases[label]
        weight = weights[label]
        for i, value in enumerate(vector):
            if value:
                total += weight[i] * value
        scores[label] = total
    return scores


class SoftmaxRegression(BaseClassifier):
    """Multinomial logistic regression with L2 regularisation."""

    def __init__(self, epochs=300, learning_rate=0.35, l2=0.001, batch_size=16, seed=42):
        super().__init__()
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.l2 = l2
        self.batch_size = batch_size
        self.seed = seed
        self.weights: dict = {}
        self.biases: dict = {}

    def fit(self, X, y):
        self._encode(y)
        dim = len(X[0]) if X else 0
        rng = random.Random(self.seed)
        self.weights = {label: [0.0] * dim for label in self.classes_}
        self.biases = {label: 0.0 for label in self.classes_}
        data = list(zip(X, y))
        for _ in range(self.epochs):
            rng.shuffle(data)
            for start in range(0, len(data), self.batch_size):
                batch = data[start:start + self.batch_size]
                grad_b = {label: 0.0 for label in self.classes_}
                grad_w = {label: {} for label in self.classes_}
                for vector, label in batch:
                    probabilities = _softmax(_linear_scores(self.weights, self.biases, vector, self.classes_))
                    for candidate in self.classes_:
                        error = (1.0 if candidate == label else 0.0) - probabilities[candidate]
                        grad_b[candidate] += error
                        accumulate = grad_w[candidate]
                        for i, value in enumerate(vector):
                            if value:
                                accumulate[i] = accumulate.get(i, 0.0) + error * value
                scale = self.learning_rate / max(1, len(batch))
                for candidate in self.classes_:
                    self.biases[candidate] += scale * grad_b[candidate]
                    weight = self.weights[candidate]
                    for i, value in grad_w[candidate].items():
                        weight[i] += scale * (value - self.l2 * weight[i])
        return self

    def predict_proba(self, X):
        return [_softmax(_linear_scores(self.weights, self.biases, vector, self.classes_))
                for vector in X]


class PerceptronClassifier(BaseClassifier):
    """Multi-class perceptron trained with the classic mistake-driven update."""

    def __init__(self, epochs=50, learning_rate=1.0, seed=42):
        super().__init__()
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.seed = seed
        self.weights: dict = {}
        self.biases: dict = {}

    def fit(self, X, y):
        self._encode(y)
        dim = len(X[0]) if X else 0
        rng = random.Random(self.seed)
        self.weights = {label: [0.0] * dim for label in self.classes_}
        self.biases = {label: 0.0 for label in self.classes_}
        data = list(zip(X, y))
        for _ in range(self.epochs):
            rng.shuffle(data)
            for vector, label in data:
                scores = _linear_scores(self.weights, self.biases, vector, self.classes_)
                predicted = max(scores, key=scores.get)
                if predicted != label:
                    for target, sign in ((label, 1.0), (predicted, -1.0)):
                        weight = self.weights[target]
                        for i, value in enumerate(vector):
                            weight[i] += sign * self.learning_rate * value
                        self.biases[target] += sign * self.learning_rate
        return self

    def predict_proba(self, X):
        return [_softmax(_linear_scores(self.weights, self.biases, vector, self.classes_))
                for vector in X]


class LinearSVM(BaseClassifier):
    """One-vs-rest linear SVM with hinge loss, optimised by SGD."""

    def __init__(self, epochs=40, learning_rate=0.05, l2=0.01, seed=42):
        super().__init__()
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.l2 = l2
        self.seed = seed
        self.weights: dict = {}
        self.biases: dict = {}

    def fit(self, X, y):
        self._encode(y)
        dim = len(X[0]) if X else 0
        rng = random.Random(self.seed)
        self.weights = {}
        self.biases = {}
        for label in self.classes_:
            weight = [0.0] * dim
            bias = 0.0
            data = [(vector, 1.0 if target == label else -1.0) for vector, target in zip(X, y)]
            for _ in range(self.epochs):
                rng.shuffle(data)
                for vector, polarity in data:
                    margin = polarity * (bias + sum(w * v for w, v in zip(weight, vector)))
                    if margin < 1.0:
                        for i, value in enumerate(vector):
                            weight[i] += self.learning_rate * (polarity * value - self.l2 * weight[i])
                        bias += self.learning_rate * polarity
                    else:
                        for i in range(dim):
                            weight[i] -= self.learning_rate * self.l2 * weight[i]
            self.weights[label] = weight
            self.biases[label] = bias
        return self

    def predict_proba(self, X):
        return [_softmax(_linear_scores(self.weights, self.biases, vector, self.classes_))
                for vector in X]


def _gini(counts, total):
    if total == 0:
        return 0.0
    return 1.0 - sum((count / total) ** 2 for count in counts.values())


class DecisionTreeClassifier(BaseClassifier):
    """CART decision tree using Gini impurity."""

    def __init__(self, max_depth=12, min_samples_split=2, min_samples_leaf=1,
                 n_features=None, seed=42):
        super().__init__()
        self.max_depth = max_depth
        self.min_samples_split = min_samples_split
        self.min_samples_leaf = min_samples_leaf
        self.n_features = n_features
        self.seed = seed
        self.tree = None
        self._rng = random.Random(seed)

    def _best_split(self, X, y):
        n_samples = len(X)
        dim = len(X[0])
        if self.n_features and self.n_features < dim:
            feature_indices = self._rng.sample(range(dim), self.n_features)
        else:
            feature_indices = range(dim)
        best = None
        parent = _gini(Counter(y), n_samples)
        for feature in feature_indices:
            values = sorted({row[feature] for row in X})
            if len(values) <= 1:
                continue
            if len(values) > 24:
                step = len(values) // 24
                values = values[::step]
            for i in range(len(values) - 1):
                threshold = (values[i] + values[i + 1]) / 2
                left = [label for row, label in zip(X, y) if row[feature] <= threshold]
                if len(left) < self.min_samples_leaf or (n_samples - len(left)) < self.min_samples_leaf:
                    continue
                right = [label for row, label in zip(X, y) if row[feature] > threshold]
                weighted = (len(left) / n_samples) * _gini(Counter(left), len(left)) \
                    + (len(right) / n_samples) * _gini(Counter(right), len(right))
                gain = parent - weighted
                if best is None or gain > best["gain"]:
                    best = {"feature": feature, "threshold": threshold, "gain": gain}
        return best

    def _build(self, X, y, depth):
        counts = Counter(y)
        node = {"prediction": _majority(y), "distribution": counts, "n": len(y)}
        if (depth >= self.max_depth or len(y) < self.min_samples_split
                or len(counts) == 1 or not X):
            return node
        split = self._best_split(X, y)
        if not split or split["gain"] <= 0:
            return node
        feature, threshold = split["feature"], split["threshold"]
        left_idx = [i for i, row in enumerate(X) if row[feature] <= threshold]
        right_idx = [i for i, row in enumerate(X) if row[feature] > threshold]
        if not left_idx or not right_idx:
            return node
        node["feature"] = feature
        node["threshold"] = threshold
        node["left"] = self._build([X[i] for i in left_idx], [y[i] for i in left_idx], depth + 1)
        node["right"] = self._build([X[i] for i in right_idx], [y[i] for i in right_idx], depth + 1)
        return node

    def fit(self, X, y):
        self._encode(y)
        self.tree = self._build(X, y, 0)
        return self

    def _leaf(self, node, vector):
        while "feature" in node:
            node = node["left"] if vector[node["feature"]] <= node["threshold"] else node["right"]
        return node

    def predict_proba(self, X):
        results = []
        for vector in X:
            leaf = self._leaf(self.tree, vector)
            total = leaf["n"] or 1
            probabilities = {label: leaf["distribution"].get(label, 0) / total
                             for label in self.classes_}
            results.append(probabilities)
        return results


class RegressionTree:
    """CART regression tree minimising squared error (used by boosting)."""

    def __init__(self, max_depth=3, min_samples_leaf=2):
        self.max_depth = max_depth
        self.min_samples_leaf = min_samples_leaf
        self.tree = None

    def fit(self, X, y):
        self.tree = self._build(X, y, 0)
        return self

    def _build(self, X, y, depth):
        node = {"value": sum(y) / len(y) if y else 0.0}
        if depth >= self.max_depth or len(y) < 2 * self.min_samples_leaf:
            return node
        dim = len(X[0])
        best = None
        for feature in range(dim):
            values = sorted({row[feature] for row in X})
            if len(values) <= 1:
                continue
            if len(values) > 20:
                values = values[::max(1, len(values) // 20)]
            for i in range(len(values) - 1):
                threshold = (values[i] + values[i + 1]) / 2
                left = [target for row, target in zip(X, y) if row[feature] <= threshold]
                right = [target for row, target in zip(X, y) if row[feature] > threshold]
                if len(left) < self.min_samples_leaf or not right:
                    continue
                error = sum((v - sum(left) / len(left)) ** 2 for v in left) \
                    + sum((v - sum(right) / len(right)) ** 2 for v in right)
                if best is None or error < best["error"]:
                    best = {"feature": feature, "threshold": threshold, "error": error,
                            "left": left, "right": right}
        if best is None:
            return node
        feature, threshold = best["feature"], best["threshold"]
        left_idx = [i for i, row in enumerate(X) if row[feature] <= threshold]
        right_idx = [i for i, row in enumerate(X) if row[feature] > threshold]
        node["feature"] = feature
        node["threshold"] = threshold
        node["left"] = self._build([X[i] for i in left_idx], [y[i] for i in left_idx], depth + 1)
        node["right"] = self._build([X[i] for i in right_idx], [y[i] for i in right_idx], depth + 1)
        return node

    def predict_one(self, vector):
        node = self.tree
        while "feature" in node:
            node = node["left"] if vector[node["feature"]] <= node["threshold"] else node["right"]
        return node["value"]

    def predict(self, X):
        return [self.predict_one(vector) for vector in X]


class RandomForestClassifier(BaseClassifier):
    """Bagged decision trees with per-split feature subsampling."""

    def __init__(self, n_estimators=12, max_depth=10, max_features="sqrt", seed=42):
        super().__init__()
        self.n_estimators = n_estimators
        self.max_depth = max_depth
        self.max_features = max_features
        self.seed = seed
        self.trees: list = []

    def fit(self, X, y):
        self._encode(y)
        rng = random.Random(self.seed)
        dim = len(X[0]) if X else 0
        if self.max_features == "sqrt":
            n_features = max(1, int(round(math.sqrt(dim))))
        elif self.max_features == "log2":
            n_features = max(1, int(round(math.log2(dim)))) if dim > 1 else 1
        elif isinstance(self.max_features, int):
            n_features = min(self.max_features, dim)
        else:
            n_features = dim
        self.trees = []
        for _ in range(self.n_estimators):
            sample_idx = [rng.randrange(len(X)) for _ in range(len(X))]
            tree = DecisionTreeClassifier(max_depth=self.max_depth,
                                          n_features=n_features, seed=rng.randrange(1 << 30))
            tree.fit([X[i] for i in sample_idx], [y[i] for i in sample_idx])
            self.trees.append(tree)
        return self

    def predict_proba(self, X):
        results = []
        for vector in X:
            totals = {label: 0.0 for label in self.classes_}
            for tree in self.trees:
                probabilities = tree.predict_proba([vector])[0]
                for label, value in probabilities.items():
                    totals[label] += value
            scale = len(self.trees) or 1
            results.append({label: value / scale for label, value in totals.items()})
        return results


class GradientBoostingClassifier(BaseClassifier):
    """One-vs-rest gradient boosting with logistic loss and regression trees."""

    def __init__(self, n_estimators=25, learning_rate=0.2, max_depth=2, seed=42):
        super().__init__()
        self.n_estimators = n_estimators
        self.learning_rate = learning_rate
        self.max_depth = max_depth
        self.seed = seed
        self.models: dict = {}
        self._priors: dict = {}

    def fit(self, X, y):
        self._encode(y)
        self.models = {}
        for label in self.classes_:
            binary = [1.0 if target == label else 0.0 for target in y]
            prior = sum(binary) / len(binary)
            logit = math.log(prior / (1 - prior)) if 0 < prior < 1 else (-4.0 if prior == 0 else 4.0)
            self._priors[label] = logit
            predictions = [logit] * len(X)
            trees = []
            for _ in range(self.n_estimators):
                residual = [b - 1.0 / (1.0 + math.exp(-p)) for b, p in zip(binary, predictions)]
                tree = RegressionTree(max_depth=self.max_depth, min_samples_leaf=2).fit(X, residual)
                updates = [self.learning_rate * value for value in tree.predict(X)]
                predictions = [p + u for p, u in zip(predictions, updates)]
                trees.append(tree)
            self.models[label] = trees
        return self

    def predict_proba(self, X):
        results = []
        for vector in X:
            scores = {}
            for label in self.classes_:
                score = self._priors[label]
                for tree in self.models[label]:
                    score += self.learning_rate * tree.predict_one(vector)
                scores[label] = score
            results.append(_softmax(scores))
        return results


class MLPClassifier(BaseClassifier):
    """Feed-forward neural network (one ReLU hidden layer + softmax output)."""

    def __init__(self, hidden=64, epochs=200, learning_rate=0.08, l2=1e-4,
                 batch_size=16, seed=42):
        super().__init__()
        self.hidden = hidden
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.l2 = l2
        self.batch_size = batch_size
        self.seed = seed
        self.W1 = self.b1 = self.W2 = self.b2 = None

    def _init(self, dim, classes, rng):
        limit1 = math.sqrt(6.0 / (dim + self.hidden))
        limit2 = math.sqrt(6.0 / (self.hidden + classes))
        self.W1 = [[rng.uniform(-limit1, limit1) for _ in range(dim)] for _ in range(self.hidden)]
        self.b1 = [0.0] * self.hidden
        self.W2 = [[rng.uniform(-limit2, limit2) for _ in range(self.hidden)] for _ in range(classes)]
        self.b2 = [0.0] * classes

    def _forward(self, vector):
        hidden_raw = [self.b1[h] + sum(w * v for w, v in zip(self.W1[h], vector))
                      for h in range(self.hidden)]
        hidden = [value if value > 0 else 0.0 for value in hidden_raw]
        output_raw = [self.b2[k] + sum(w * h for w, h in zip(self.W2[k], hidden))
                      for k in range(len(self.classes_))]
        return hidden, _softmax({k: output_raw[k] for k in range(len(self.classes_))})

    def fit(self, X, y):
        self._encode(y)
        rng = random.Random(self.seed)
        dim = len(X[0]) if X else 0
        classes = len(self.classes_)
        class_index = {label: i for i, label in enumerate(self.classes_)}
        self._init(dim, classes, rng)
        data = list(zip(X, y))
        for _ in range(self.epochs):
            rng.shuffle(data)
            for start in range(0, len(data), self.batch_size):
                batch = data[start:start + self.batch_size]
                gradW1 = [[0.0] * dim for _ in range(self.hidden)]
                gradb1 = [0.0] * self.hidden
                gradW2 = [[0.0] * self.hidden for _ in range(classes)]
                gradb2 = [0.0] * classes
                for vector, label in batch:
                    hidden, probabilities = self._forward(vector)
                    target = class_index[label]
                    delta2 = [probabilities[k] - (1.0 if k == target else 0.0)
                              for k in range(classes)]
                    for k in range(classes):
                        gradb2[k] += delta2[k]
                        for h in range(self.hidden):
                            gradW2[k][h] += delta2[k] * hidden[h]
                    for h in range(self.hidden):
                        if hidden[h] <= 0:
                            continue
                        back = sum(self.W2[k][h] * delta2[k] for k in range(classes))
                        gradb1[h] += back
                        for i, value in enumerate(vector):
                            if value:
                                gradW1[h][i] += back * value
                scale = self.learning_rate / max(1, len(batch))
                for k in range(classes):
                    self.b2[k] -= scale * gradb2[k]
                    for h in range(self.hidden):
                        self.W2[k][h] -= scale * (gradW2[k][h] + self.l2 * self.W2[k][h])
                for h in range(self.hidden):
                    self.b1[h] -= scale * gradb1[h]
                    for i in range(dim):
                        self.W1[h][i] -= scale * (gradW1[h][i] + self.l2 * self.W1[h][i])
        return self

    def predict_proba(self, X):
        results = []
        for vector in X:
            _, probabilities = self._forward(vector)
            results.append({self.classes_[k]: probabilities[k] for k in range(len(self.classes_))})
        return results


class KNNClassifier(BaseClassifier):
    """k-nearest neighbours with distance-weighted voting."""

    def __init__(self, k=5, metric="cosine"):
        super().__init__()
        self.k = k
        self.metric = metric
        self._X: list = []
        self._y: list = []

    def _distance(self, a, b):
        if self.metric == "cosine":
            dot = sum(x * y for x, y in zip(a, b))
            norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
            norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
            return 1.0 - dot / (norm_a * norm_b)
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    def fit(self, X, y):
        self._encode(y)
        self._X = list(X)
        self._y = list(y)
        return self

    def predict_proba(self, X):
        results = []
        for vector in X:
            distances = sorted(
                ((self._distance(vector, row), label) for row, label in zip(self._X, self._y)),
                key=lambda pair: pair[0],
            )[:self.k]
            totals = {label: 0.0 for label in self.classes_}
            for distance, label in distances:
                totals[label] += 1.0 / (distance + 1e-6)
            total = sum(totals.values()) or 1.0
            results.append({label: value / total for label, value in totals.items()})
        return results


class VotingEnsemble(BaseClassifier):
    """Weighted soft-voting ensemble over fitted classifiers."""

    def __init__(self, models, weights=None):
        super().__init__()
        self.models = list(models)
        self.weights = list(weights) if weights else [1.0] * len(self.models)

    def fit(self, X, y):
        for model in self.models:
            model.fit(X, y)
        self._encode(y)
        return self

    def predict_proba(self, X):
        all_probs = [model.predict_proba(X) for model in self.models]
        results = []
        for i in range(len(X)):
            totals: dict = {}
            weight_sum = 0.0
            for model_probs, weight in zip(all_probs, self.weights):
                weight_sum += weight
                for label, value in model_probs[i].items():
                    totals[label] = totals.get(label, 0.0) + weight * value
            weight_sum = weight_sum or 1.0
            results.append({label: value / weight_sum for label, value in totals.items()})
        return results


class StackingEnsemble(BaseClassifier):
    """Stacking: out-of-fold base probabilities feed a meta (softmax) learner."""

    def __init__(self, models, meta_epochs=200, seed=42):
        super().__init__()
        self.models = list(models)
        self.meta_epochs = meta_epochs
        self.seed = seed
        self.meta: SoftmaxRegression = None

    @staticmethod
    def _features(probs_listes, classes):
        rows = []
        for probs in probs_listes:
            rows.append([probs.get(label, 0.0) for label in classes])
        return rows

    def fit(self, X, y):
        from .metrics import stratified_folds

        self._encode(y)
        folds = stratified_folds(list(zip(y, X)), n_splits=min(4, max(2, len(set(y))) ), seed=self.seed)
        meta_X = [[] for _ in X]
        index_lookup = {id(row): i for i, row in enumerate(X)}
        for i, test_fold in enumerate(folds):
            train = [pair for j, fold in enumerate(folds) if j != i for pair in fold]
            if not train:
                continue
            X_train = [pair[1] for pair in train]
            y_train = [pair[0] for pair in train]
            for model in self.models:
                clone = copy.deepcopy(model)
                clone.fit(X_train, y_train)
                probs = clone.predict_proba([pair[1] for pair in test_fold])
                for (label, row), prob in zip(test_fold, probs):
                    meta_X[index_lookup[id(row)]].extend(
                        prob.get(c, 0.0) for c in self.classes_
                    )
        for model in self.models:
            model.fit(X, y)
        meta_features = meta_X if meta_X and meta_X[0] else []
        if not meta_features:
            meta_features = self._features(
                self.models[0].predict_proba(X), self.classes_
            )
        self.meta = SoftmaxRegression(epochs=self.meta_epochs, seed=self.seed)
        self.meta.fit(meta_features, y)
        return self

    def predict_proba(self, X):
        features = []
        base_probs = [model.predict_proba(X) for model in self.models]
        for i in range(len(X)):
            row = []
            for probs in base_probs:
                row.extend(probs[i].get(label, 0.0) for label in self.classes_)
            features.append(row)
        return self.meta.predict_proba(features)
