"""End-to-end text-classification pipelines.

``TextClassifier`` bundles a feature extractor, one or more models and an
optional probability calibrator behind a single ``fit``/``predict`` API, and can
report held-out and cross-validated metrics so models can be compared.

Extractors/models may be passed either as ready instances or as zero-argument
factories; factories are preferred because cross-validation then rebuilds
unbiased copies that keep the configured hyper-parameters.
"""
from __future__ import annotations

import copy

from . import metrics
from .calibration import TemperatureScaler
from .features import TfidfFeatureExtractor
from .models import (
    DecisionTreeClassifier,
    KNNClassifier,
    MultinomialNB,
    SoftmaxRegression,
    VotingEnsemble,
)


def _factory(value, default):
    if value is None:
        return default
    if callable(value):
        return value
    captured = value
    return lambda: copy.deepcopy(captured)


class TextClassifier:
    """Feature extraction + model, trainable from ``(label, text)`` samples."""

    def __init__(self, extractor=None, model=None, calibrator=None, name="classifier"):
        self._extractor_factory = _factory(
            extractor, lambda: TfidfFeatureExtractor(ngram_range=(1, 2))
        )
        self._model_factory = _factory(model, lambda: MultinomialNB())
        self._calibrator_factory = (lambda: None) if calibrator is None else _factory(
            calibrator, lambda: TemperatureScaler()
        )
        self.name = name
        self.extractor = self._extractor_factory()
        self.model = self._model_factory()
        self.calibrator = self._calibrator_factory()
        self.classes_: list = []

    def _split(self, texts_or_samples, labels):
        if labels is not None:
            return list(texts_or_samples), list(labels)
        samples = list(texts_or_samples)
        return [text for _, text in samples], [label for label, _ in samples]

    def fit(self, texts_or_samples, labels=None):
        texts, ys = self._split(texts_or_samples, labels)
        if not texts:
            return self
        self.extractor = self._extractor_factory()
        self.model = self._model_factory()
        X = self.extractor.fit_transform(texts)
        self.model.fit(X, ys)
        self.classes_ = list(getattr(self.model, "classes_", sorted(set(ys))))
        if self._calibrator_factory() is not None:
            self.calibrator = self._calibrator_factory()
            samples = list(zip(ys, texts))
            train, valid = metrics.train_test_split(samples, test_size=0.25)
            if valid and train:
                self.extractor = self._extractor_factory()
                self.model = self._model_factory()
                X_train = self.extractor.fit_transform([t for _, t in train])
                self.model.fit(X_train, [y for y, _ in train])
                probabilities = self.model.predict_proba(
                    [self.extractor.transform(t) for _, t in valid]
                )
                self.calibrator.fit(probabilities, [y for y, _ in valid])
                self.extractor = self._extractor_factory()
                self.model = self._model_factory()
                X_all = self.extractor.fit_transform(texts)
                self.model.fit(X_all, ys)
        return self

    def predict_proba(self, texts):
        if isinstance(texts, str):
            texts = [texts]
        X = [self.extractor.transform(text) for text in texts]
        probabilities = self.model.predict_proba(X)
        if self.calibrator is not None:
            probabilities = [self.calibrator.calibrate(p) for p in probabilities]
        return probabilities

    def predict(self, texts):
        if isinstance(texts, str):
            return self._label(self.predict_proba([texts])[0])
        return [self._label(p) for p in self.predict_proba(texts)]

    @staticmethod
    def _label(probabilities):
        if not probabilities:
            return "unknown"
        return max(probabilities, key=probabilities.get)

    def predict_with_confidence(self, text):
        probabilities = self.predict_proba([text])[0]
        label = self._label(probabilities)
        return label, probabilities.get(label, 0.0), probabilities

    def evaluate(self, samples, n_splits=3, seed=42):
        """Cross-validated metrics computed on raw ``(label, text)`` samples."""
        samples = list(samples)

        def build():
            return TextClassifier(extractor=self._extractor_factory(),
                                  model=self._model_factory(), name=self.name)

        y_true, y_pred = metrics.cross_val_predict(
            build, samples, lambda model, text: model.predict([text])[0],
            n_splits=n_splits, seed=seed,
        )
        report = metrics.classification_report(y_true, y_pred)
        report["confusion"] = metrics.confusion_matrix(y_true, y_pred)
        return report

    def model_names(self):
        model = self.model
        if isinstance(model, VotingEnsemble):
            return [m.__class__.__name__ for m in model.models]
        return [model.__class__.__name__]


def default_intent_models():
    """Deployed intent ensemble: Naive Bayes + softmax regression + k-NN."""
    return VotingEnsemble(
        [MultinomialNB(), SoftmaxRegression(epochs=40), KNNClassifier(k=3)],
        weights=[1.0, 1.2, 0.8],
    )


def fast_intent_models():
    """Cheaper ensemble used for quick metric estimation."""
    return VotingEnsemble(
        [MultinomialNB(), DecisionTreeClassifier(max_depth=16), KNNClassifier(k=3)],
        weights=[1.0, 0.6, 0.8],
    )


def build_intent_classifier(model=None, use_char=False, calibrate=True,
                            max_features=None, tokenizer=None):
    """Convenience factory for the assistant's intent classifier.

    ``tokenizer`` overrides the default whitespace tokeniser; the assistant
    passes its stemmed/stop-worded tokeniser so inflected forms ("events" and
    "event") collapse to the same feature.
    """
    extractor_factory = lambda: TfidfFeatureExtractor(  # noqa: E731
        ngram_range=(1, 2), use_char=use_char, max_features=max_features,
        tokenizer=tokenizer,
    )
    calibrator = (lambda: TemperatureScaler()) if calibrate else None
    return TextClassifier(
        extractor=extractor_factory,
        model=model or default_intent_models,
        calibrator=calibrator,
        name="intent",
    )
