"""Tests for the dependency-free ML toolkit (apps.ai_assistant.services.ml)."""
import math

import pytest

from apps.ai_assistant.services import ml
from apps.ai_assistant.services.ml import metrics as m

# A tiny, linearly separable 2-D problem used across the model tests.
X = [[1.0, 0.0], [0.9, 0.1], [1.0, 0.2], [0.0, 1.0], [0.1, 0.9], [0.2, 1.0]]
Y = ["a", "a", "a", "b", "b", "b"]


# --------------------------------------------------------------------------- #
# Metrics
# --------------------------------------------------------------------------- #
def test_accuracy_and_confusion_matrix():
    labels, matrix = m.confusion_matrix(["a", "a", "b"], ["a", "b", "b"])
    assert labels == ["a", "b"]
    assert matrix == [[1, 1], [0, 1]]
    assert m.accuracy(["a", "b"], ["a", "b"]) == 1.0
    assert m.accuracy([], []) == 0.0


def test_precision_recall_f1_and_report():
    y_true = ["a", "a", "a", "b"]
    y_pred = ["a", "a", "b", "b"]
    per_class = m.precision_recall_f1(y_true, y_pred)
    assert per_class["a"]["precision"] == 1.0
    assert per_class["a"]["recall"] == pytest.approx(2 / 3)
    report = m.classification_report(y_true, y_pred)
    assert report["accuracy"] == pytest.approx(0.75)
    assert report["labels"]["a"]["f1"] == pytest.approx(0.8)
    assert report["macro"]["f1"] == pytest.approx(0.7333, abs=1e-3)
    assert report["n_labels"] == 2
    assert set(report["labels"]) == {"a", "b"}


def test_train_test_split_is_stratified():
    samples = [("a", i) for i in range(4)] + [("b", i) for i in range(8)]
    train, test = m.train_test_split(samples, test_size=0.25, seed=0)
    assert len(train) + len(test) == len(samples)
    # every class must survive the split
    assert {label for label, _ in train} == {"a", "b"}
    assert {label for label, _ in test} == {"a", "b"}


def test_stratified_folds_cover_all_samples():
    samples = [("a", i) for i in range(6)] + [("b", i) for i in range(3)]
    folds = m.stratified_folds(samples, n_splits=3)
    assert len(folds) == 3
    flat = [sample for fold in folds for sample in fold]
    assert sorted(flat) == sorted(samples)


def test_cross_val_predict_and_score():
    samples = [(label, vector) for label, vector in zip(Y, X)]

    def build():
        return ml.MultinomialNB()

    y_true, y_pred = m.cross_val_predict(build, samples, lambda model, v: model.predict([v])[0], n_splits=3)
    assert len(y_true) == len(samples)
    score = m.cross_val_score(build, samples, lambda model, v: model.predict([v])[0], n_splits=3)
    assert 0.0 <= score["mean"] <= 1.0
    assert len(score["scores"]) == 3


def test_roc_auc_binary():
    assert m.roc_auc_binary([0, 0, 1, 1], [0.1, 0.2, 0.8, 0.9]) == 1.0
    assert m.roc_auc_binary([1, 1, 0, 0], [0.1, 0.2, 0.8, 0.9]) == 0.0
    assert m.roc_auc_binary([1], [0.5]) == 0.5


# --------------------------------------------------------------------------- #
# Features
# --------------------------------------------------------------------------- #
def test_tokenisation_and_ngrams():
    assert ml.word_tokens("Add a TASK, now!") == ["add", "a", "task", "now"]
    assert ml.word_ngrams(["a", "b", "c"], 2) == ["a b", "b c"]
    assert "ab" in "".join(ml.char_ngrams("ab", 2))


def test_tfidf_vectors_are_normalised_with_expected_dim():
    extractor = ml.TfidfFeatureExtractor(ngram_range=(1, 2))
    Xv = extractor.fit_transform(["add a task", "schedule a meeting", "add a task now"])
    assert len(Xv[0]) == extractor.dim
    for vector in Xv:
        assert math.isclose(math.sqrt(sum(v * v for v in vector)), 1.0, rel_tol=1e-6)


def test_tfidf_max_features_caps_vocabulary():
    extractor = ml.TfidfFeatureExtractor(ngram_range=(1, 2), max_features=3)
    extractor.fit(["alpha beta gamma delta epsilon zeta"])
    assert extractor.dim <= 3


def test_char_ngram_and_hashing_and_union():
    char = ml.CharNGramVectorizer()
    char.fit(["hello", "yellow"])
    assert char.dim > 0
    hashing = ml.HashingFeatureExtractor(n_features=32)
    hashing.fit(["anything"])
    assert len(hashing.transform("anything")) == 32
    union = ml.FeatureUnion([ml.TfidfFeatureExtractor(), ml.CharNGramVectorizer()])
    union.fit(["hello world", "goodbye world"])
    assert len(union.transform("hello world")) == union.dim


# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("model", [
    ml.MultinomialNB(),
    ml.DecisionTreeClassifier(max_depth=8),
    ml.KNNClassifier(k=3),
    ml.VotingEnsemble([ml.MultinomialNB(), ml.KNNClassifier(k=3)], [1.0, 1.0]),
])
def test_deterministic_classifiers_learn_separable_data(model):
    model.fit(X, Y)
    assert model.predict(X) == Y
    for probs in model.predict_proba(X):
        assert math.isclose(sum(probs.values()), 1.0, rel_tol=1e-6)


@pytest.mark.parametrize("model", [
    ml.SoftmaxRegression(epochs=200, learning_rate=0.5),
    ml.PerceptronClassifier(epochs=40),
    ml.LinearSVM(epochs=40),
    ml.RandomForestClassifier(n_estimators=8),
    ml.GradientBoostingClassifier(n_estimators=10),
    ml.MLPClassifier(hidden=16, epochs=300),
])
def test_stochastic_classifiers_are_reasonable(model):
    model.fit(X, Y)
    accuracy = sum(1 for a, b in zip(Y, model.predict(X)) if a == b) / len(Y)
    assert accuracy >= 0.75


def test_stacking_ensemble_trains_and_predicts():
    model = ml.StackingEnsemble(
        [ml.MultinomialNB(), ml.KNNClassifier(k=3)], meta_epochs=50
    )
    model.fit(X, Y)
    probs = model.predict_proba(X)
    assert len(probs) == len(X)
    assert math.isclose(sum(probs[0].values()), 1.0, rel_tol=1e-6)


def test_regression_tree_fits_targets():
    tree = ml.RegressionTree(max_depth=4).fit([[0.0], [1.0], [2.0], [3.0]], [1.0, 1.0, 5.0, 5.0])
    assert tree.predict([[0.0]])[0] < 3.0
    assert tree.predict([[3.0]])[0] > 3.0


# --------------------------------------------------------------------------- #
# Pipeline
# --------------------------------------------------------------------------- #
def test_text_classifier_fit_predict_and_evaluate():
    samples = [(label, " ".join(f"w{i}" for i in range(3)) + f" {label}") for label in "abc" for _ in range(4)]
    classifier = ml.TextClassifier(
        extractor=lambda: ml.TfidfFeatureExtractor(ngram_range=(1, 2)),
        model=lambda: ml.MultinomialNB(),
    )
    classifier.fit(samples)
    label, confidence, probs = classifier.predict_with_confidence("w0 w1 w2 a")
    assert label == "a"
    assert 0.0 <= confidence <= 1.0
    report = classifier.evaluate(samples, n_splits=3)
    assert 0.0 <= report["accuracy"] <= 1.0
    assert classifier.model_names() == ["MultinomialNB"]


def test_factories_preserve_hyperparameters():
    classifier = ml.TextClassifier(model=lambda: ml.SoftmaxRegression(epochs=7))
    assert classifier.model.epochs == 7
    classifier.fit([("a", "x"), ("b", "y")])
    assert classifier.model.epochs == 7


def test_build_intent_classifier_defaults():
    classifier = ml.build_intent_classifier(calibrate=False)
    assert isinstance(classifier.model, ml.VotingEnsemble)
    assert classifier.model_names() == ["MultinomialNB", "SoftmaxRegression", "KNNClassifier"]
    assert isinstance(ml.default_intent_models(), ml.VotingEnsemble)
    assert isinstance(ml.fast_intent_models(), ml.VotingEnsemble)


# --------------------------------------------------------------------------- #
# Embeddings
# --------------------------------------------------------------------------- #
def test_word_vectors_learn_embeddings():
    corpus = [
        "the cat sat on the mat",
        "the dog sat on the log",
        "cats and dogs are pets",
        "the cat chased the dog",
    ]
    vectors = ml.WordVectors(dimensions=5, window=3, max_vocab=60, n_iter=4).fit(corpus)
    assert vectors.vector("cat")
    assert math.isclose(vectors.similarity("cat", "cat"), 1.0, rel_tol=1e-6)
    assert len(vectors.doc_vector("the cat")) == 5
    assert vectors.most_similar("cat")
    assert vectors.vector("nonexistent") == []


def test_random_projection_lsh_retrieves_neighbours():
    index = ml.RandomProjectionLSH(dim=4, n_bits=8)
    index.add([1.0, 0.0, 0.0, 0.0], "east")
    index.add([0.0, 1.0, 0.0, 0.0], "north")
    results = index.query([0.95, 0.05, 0.0, 0.0])
    assert results
    assert results[0][1] == "east"


# --------------------------------------------------------------------------- #
# Sequence labelling
# --------------------------------------------------------------------------- #
def test_pos_tagger_tags_sentence():
    tagged = ml.POSTagger().tag("add a task to call mom")
    assert len(tagged) == 6
    tags = dict(tagged)
    assert tags["add"] == "VERB"
    assert tags["task"] == "NOUN"


def test_ner_tagger_extracts_entities():
    entities = ml.NERTagger().entities("email john@example.com today in Paris")
    labels = {label for _, label in entities}
    assert "EMAIL" in labels
    assert "DATE" in labels
    assert ("Paris", "GPE") in entities


def test_spell_corrector_fixes_typos():
    corrector = ml.SpellCorrector(vocabulary="task meeting today tomorrow the".split())
    assert corrector.correct("tsak") == "task"
    assert corrector.correct("today") == "today"


def test_language_detector_identifies_english():
    language, confidence = ml.LanguageDetector().detect("the quick brown fox jumps over the lazy dog")
    assert language == "english"
    assert 0.0 <= confidence <= 1.0


# --------------------------------------------------------------------------- #
# Knowledge base & maths
# --------------------------------------------------------------------------- #
def test_evaluate_math_handles_expressions():
    assert ml.evaluate_math("12 * 7") == 84
    assert ml.evaluate_math("what is 2 to the power of 10") == 1024
    assert ml.evaluate_math("what is the square root of 144") == 12
    assert ml.evaluate_math("10 divided by 4") == 2.5
    assert ml.evaluate_math("hello world") is None
    assert ml.evaluate_math("__import__('os')") is None


def test_knowledge_base_answers_known_and_rejects_unknown():
    kb = ml.KnowledgeBase()
    assert len(ml.FACTS) > 20
    hit = kb.answer("what is the capital of peru")
    assert hit is not None and hit["score"] >= kb.threshold
    assert "lima" in hit["answer"].lower()
    assert kb.answer("qwerty zxcvbn asdfgh") is None


# --------------------------------------------------------------------------- #
# Calibration & persistence
# --------------------------------------------------------------------------- #
def test_temperature_scaler_calibrates_probabilities():
    scaler = ml.TemperatureScaler()
    scaler.fit([{"a": 0.9, "b": 0.1}, {"a": 0.2, "b": 0.8}], ["a", "b"])
    assert scaler.temperature in scaler.grid
    calibrated = scaler.calibrate({"a": 0.7, "b": 0.3})
    assert math.isclose(sum(calibrated.values()), 1.0, rel_tol=1e-6)


def test_model_registry_round_trip(tmp_path):
    model = ml.MultinomialNB().fit(X, Y)
    path = tmp_path / "nb.pkl"
    ml.save_model(model, str(path), metadata={"purpose": "test"})
    assert path.exists()
    loaded, metadata = ml.load_model(str(path))
    assert metadata["purpose"] == "test"
    assert loaded.predict(X) == Y
