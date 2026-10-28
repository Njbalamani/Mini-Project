"""Offline NLP/ML engine for the NexaMind assistant.

This module implements a small, dependency-free natural-language pipeline so the
assistant can answer intelligently without any external API key. It is a pure
Python library (no Django imports) which makes it fast and unit-testable.

Algorithms used
---------------
* Tokenisation, stop-word removal and a light suffix-stripping stemmer.
* TF-IDF vectorisation with L2 normalisation and cosine-similarity retrieval.
* Multinomial Naive Bayes text classification with Laplace smoothing for
  intent recognition.
* Levenshtein edit distance for fuzzy matching / spelling tolerance.
* Rule-based entity extraction (relative dates, weekdays, clock times, priority).
* Template-based natural-language generation with slot filling.
"""
from __future__ import annotations

import math
import random
import re
import threading
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, time, timedelta

from .ml import KnowledgeBase, build_intent_classifier, evaluate_math

STOPWORDS = {
    "a", "an", "the", "to", "of", "in", "on", "at", "for", "and", "or", "is",
    "are", "am", "be", "with", "my", "me", "i", "you", "please", "can", "could",
    "would", "should", "do", "does", "it", "this", "that", "as", "by", "from",
    "we", "us", "will", "just", "about", "into", "up", "out", "any", "some",
}


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s:]", " ", (text or "").lower())


def stem(word: str) -> str:
    """Very light English suffix stripper (Porter-style, rules only)."""
    w = word
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 4 and w.endswith("sses"):
        return w[:-2]
    if len(w) > 5 and w.endswith("ing"):
        return w[:-3]
    if len(w) > 4 and w.endswith("ed"):
        return w[:-2]
    if len(w) > 4 and w.endswith("es"):
        return w[:-2]
    if len(w) > 4 and w.endswith("ly"):
        return w[:-2]
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
        return w[:-1]
    return w


def tokenize(text: str):
    """Return stemmed content tokens (stop-words removed)."""
    tokens = []
    for raw in normalize(text).split():
        if raw in STOPWORDS or len(raw) < 2:
            continue
        tokens.append(stem(raw))
    return tokens


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance between two strings."""
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (ca != cb)
            current.append(min(insert, delete, replace))
        previous = current
    return previous[-1]


def _l2_norm(vector: dict) -> dict:
    norm = math.sqrt(sum(v * v for v in vector.values()))
    if norm == 0:
        return {}
    return {k: v / norm for k, v in vector.items()}


def cosine_similarity(a: dict, b: dict) -> float:
    if not a or not b:
        return 0.0
    if len(a) > len(b):
        a, b = b, a
    return sum(weight * b.get(term, 0.0) for term, weight in a.items())


def cosine_dense(a, b) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a)) or 1.0
    norm_b = math.sqrt(sum(y * y for y in b)) or 1.0
    return dot / (norm_a * norm_b)


class TfidfVectorizer:
    """Tiny bag-of-words TF-IDF vectoriser (fit/transform, L2-normalised)."""

    def __init__(self):
        self.idf: dict = {}
        self.vocabulary: set = set()

    def fit(self, documents):
        tokenised = [tokenize(doc) for doc in documents]
        doc_freq: dict = {}
        for tokens in tokenised:
            for term in set(tokens):
                doc_freq[term] = doc_freq.get(term, 0) + 1
        total = len(tokenised)
        self.idf = {t: math.log((1 + total) / (1 + f)) + 1.0 for t, f in doc_freq.items()}
        self.vocabulary = set(doc_freq)
        return self

    def transform(self, text: str) -> dict:
        counts: dict = {}
        for term in tokenize(text):
            counts[term] = counts.get(term, 0) + 1
        vector = {}
        for term, count in counts.items():
            if term in self.idf:
                vector[term] = (1.0 + math.log(count)) * self.idf[term]
        return _l2_norm(vector)

    def fit_transform(self, documents):
        self.fit(documents)
        return [self.transform(doc) for doc in documents]


class NaiveBayesClassifier:
    """Multinomial Naive Bayes with Laplace smoothing."""

    def __init__(self):
        self.class_counts: dict = {}
        self.token_counts: dict = {}
        self.class_token_totals: dict = {}
        self.vocabulary: set = set()
        self.total_documents = 0

    def train(self, samples):
        for label, text in samples:
            tokens = tokenize(text) or ["<empty>"]
            self.class_counts[label] = self.class_counts.get(label, 0) + 1
            counts = self.token_counts.setdefault(label, {})
            for token in tokens:
                counts[token] = counts.get(token, 0) + 1
                self.vocabulary.add(token)
            self.total_documents += 1
        for label, counts in self.token_counts.items():
            self.class_token_totals[label] = sum(counts.values()) or 1
        return self

    def predict_proba(self, text: str) -> dict:
        tokens = tokenize(text) or ["<empty>"]
        vocab_size = max(len(self.vocabulary), 1)
        log_scores = {}
        for label, class_count in self.class_counts.items():
            prior = math.log(class_count / self.total_documents)
            counts = self.token_counts.get(label, {})
            denominator = self.class_token_totals.get(label, 1) + vocab_size
            score = prior
            for token in tokens:
                score += math.log((counts.get(token, 0) + 1.0) / denominator)
            log_scores[label] = score
        if not log_scores:
            return {}
        highest = max(log_scores.values())
        exps = {label: math.exp(score - highest) for label, score in log_scores.items()}
        total = sum(exps.values()) or 1.0
        return {label: value / total for label, value in exps.items()}

    def predict(self, text: str):
        probabilities = self.predict_proba(text)
        if not probabilities:
            return "unknown", 0.0
        label = max(probabilities, key=probabilities.get)
        return label, probabilities[label]


class LogisticRegressionClassifier:
    """Multinomial logistic regression (softmax) trained by gradient descent."""

    def __init__(self, epochs=400, learning_rate=0.3, l2=0.001):
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.l2 = l2
        self.labels: list = []
        self.weights: dict = {}
        self.biases: dict = {}

    def _features(self, text: str) -> dict:
        counts = Counter(tokenize(text) or ["<empty>"])
        total = sum(counts.values()) or 1
        return {term: count / total for term, count in counts.items()}

    def _scores(self, features: dict) -> dict:
        scores = {}
        for label in self.labels:
            weight = self.weights[label]
            score = self.biases[label]
            for term, value in features.items():
                score += weight.get(term, 0.0) * value
            scores[label] = score
        return scores

    @staticmethod
    def _softmax(scores: dict) -> dict:
        if not scores:
            return {}
        highest = max(scores.values())
        exps = {label: math.exp(score - highest) for label, score in scores.items()}
        total = sum(exps.values()) or 1.0
        return {label: value / total for label, value in exps.items()}

    def train(self, samples):
        self.labels = sorted({label for label, _ in samples})
        self.weights = {label: {} for label in self.labels}
        self.biases = {label: 0.0 for label in self.labels}
        data = [(label, self._features(text)) for label, text in samples]
        for _ in range(self.epochs):
            for label, features in data:
                probabilities = self._softmax(self._scores(features))
                for candidate in self.labels:
                    error = (1.0 if candidate == label else 0.0) - probabilities[candidate]
                    weight = self.weights[candidate]
                    for term, value in features.items():
                        weight[term] = weight.get(term, 0.0) + self.learning_rate * (
                            error * value - self.l2 * weight.get(term, 0.0)
                        )
                    self.biases[candidate] += self.learning_rate * error
        return self

    def predict_proba(self, text: str) -> dict:
        if not self.labels:
            return {}
        return self._softmax(self._scores(self._features(text)))

    def predict(self, text: str):
        probabilities = self.predict_proba(text)
        if not probabilities:
            return "unknown", 0.0
        label = max(probabilities, key=probabilities.get)
        return label, probabilities[label]


class KNNClassifier:
    """k-Nearest-Neighbours classifier over TF-IDF vectors (cosine distance)."""

    def __init__(self, k=5):
        self.k = k
        self.vectorizer = TfidfVectorizer()
        self.samples: list = []

    def train(self, samples):
        self.vectorizer.fit([text for _, text in samples])
        self.samples = [
            (label, self.vectorizer.transform(text)) for label, text in samples
        ]
        return self

    def predict_proba(self, text: str) -> dict:
        if not self.samples:
            return {}
        query = self.vectorizer.transform(text)
        scored = sorted(
            ((cosine_similarity(query, vector), label) for label, vector in self.samples),
            key=lambda pair: pair[0], reverse=True,
        )[:self.k]
        totals: dict = defaultdict(float)
        for score, label in scored:
            totals[label] += max(score, 0.0) + 1e-6
        total = sum(totals.values()) or 1.0
        return {label: value / total for label, value in totals.items()}

    def predict(self, text: str):
        probabilities = self.predict_proba(text)
        if not probabilities:
            return "unknown", 0.0
        label = max(probabilities, key=probabilities.get)
        return label, probabilities[label]


class EnsembleClassifier:
    """Weighted soft-voting ensemble of several base classifiers."""

    def __init__(self, models, weights=None):
        self.models = models
        self.weights = weights or [1.0] * len(models)

    def train(self, samples):
        for model in self.models:
            model.train(samples)
        return self

    def predict_proba(self, text: str) -> dict:
        totals: dict = defaultdict(float)
        weight_sum = 0.0
        for model, weight in zip(self.models, self.weights):
            probabilities = model.predict_proba(text)
            if not probabilities:
                continue
            weight_sum += weight
            for label, probability in probabilities.items():
                totals[label] += weight * probability
        if weight_sum == 0:
            return {}
        return {label: value / weight_sum for label, value in totals.items()}

    def predict(self, text: str):
        probabilities = self.predict_proba(text)
        if not probabilities:
            return "unknown", 0.0
        label = max(probabilities, key=probabilities.get)
        return label, probabilities[label]


def _transpose(matrix):
    if not matrix:
        return []
    return [list(row) for row in zip(*matrix)]


def _matmul(a, b):
    if not a or not b:
        return []
    columns = _transpose(b)
    return [[sum(x * y for x, y in zip(row, col)) for col in columns] for row in a]


def _orthonormalize(matrix):
    """Gram-Schmidt orthonormalisation of the columns of a matrix."""
    if not matrix:
        return matrix
    rows = len(matrix)
    cols = len(matrix[0])
    result = [[0.0] * cols for _ in range(rows)]
    for c in range(cols):
        column = [matrix[r][c] for r in range(rows)]
        for prev in range(c):
            prev_col = [result[r][prev] for r in range(rows)]
            dot = sum(x * y for x, y in zip(column, prev_col))
            column = [x - dot * y for x, y in zip(column, prev_col)]
        norm = math.sqrt(sum(x * x for x in column)) or 1.0
        for r in range(rows):
            result[r][c] = column[r] / norm
    return result


def _normalize(vector):
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class TruncatedSVD:
    """Randomised truncated SVD (Latent Semantic Analysis) for dense, semantic
    document embeddings. Built with power iteration, no external libraries."""

    def __init__(self, n_components=8, n_iter=30, seed=42):
        self.n_components = n_components
        self.n_iter = n_iter
        self.seed = seed
        self.vocabulary: list = []
        self.idf: dict = {}
        self.components: list = []

    def _vectorise(self, tokens):
        counts = Counter(tokens)
        row = []
        for term in self.vocabulary:
            if term in counts:
                row.append((1.0 + math.log(counts[term])) * self.idf[term])
            else:
                row.append(0.0)
        return _normalize(row)

    def fit_transform(self, documents):
        tokenised = [tokenize(doc) for doc in documents]
        self.vocabulary = sorted({term for tokens in tokenised for term in tokens})
        if not self.vocabulary:
            self.components = []
            return [[] for _ in documents]
        doc_freq = Counter(term for tokens in tokenised for term in set(tokens))
        total = len(tokenised)
        self.idf = {t: math.log((1 + total) / (1 + doc_freq[t])) + 1.0
                    for t in self.vocabulary}
        matrix = [self._vectorise(tokens) for tokens in tokenised]
        k = max(1, min(self.n_components, len(self.vocabulary), total))
        rng = random.Random(self.seed)
        components = [[rng.random() for _ in range(k)] for _ in self.vocabulary]
        components = _orthonormalize(components)
        for _ in range(self.n_iter):
            doc_vectors = _orthonormalize(_matmul(matrix, components))
            components = _orthonormalize(_matmul(_transpose(matrix), doc_vectors))
        self.components = components
        return [_normalize(vec) for vec in _matmul(matrix, components)]

    def transform(self, text: str):
        if not self.components:
            return []
        row = self._vectorise(tokenize(text))
        projected = _matmul([row], self.components)
        return _normalize(projected[0]) if projected else []


class KMeans:
    """k-Means clustering (Lloyd's algorithm) with a fixed random seed."""

    def __init__(self, k=3, n_iter=50, seed=42):
        self.k = k
        self.n_iter = n_iter
        self.seed = seed
        self.centroids: list = []

    @staticmethod
    def _distance(a, b):
        return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))

    def fit(self, vectors):
        if not vectors:
            self.centroids = []
            return []
        rng = random.Random(self.seed)
        k = max(1, min(self.k, len(vectors)))
        self.centroids = [list(v) for v in rng.sample(vectors, k)]
        labels = [0] * len(vectors)
        for _ in range(self.n_iter):
            changed = False
            for i, vector in enumerate(vectors):
                distances = [self._distance(vector, c) for c in self.centroids]
                best = min(range(len(distances)), key=distances.__getitem__)
                if best != labels[i]:
                    labels[i] = best
                    changed = True
            for j in range(k):
                members = [vectors[i] for i in range(len(vectors)) if labels[i] == j]
                if members:
                    self.centroids[j] = [sum(col) / len(col) for col in zip(*members)]
            if not changed:
                break
        return labels


class NGramLanguageModel:
    """Bigram/trigram language model with add-k smoothing, used for
    autocomplete and Markov-chain text generation."""

    def __init__(self, order=2, smoothing=0.1):
        self.order = max(1, order)
        self.smoothing = smoothing
        self.contexts: dict = {}
        self.vocabulary: Counter = Counter()

    def train(self, texts):
        for text in texts:
            words = normalize(text).split()
            padded = ["<s>"] * (self.order - 1) + words
            for i, word in enumerate(words):
                context = tuple(padded[i:i + self.order - 1])
                self.contexts.setdefault(context, Counter())[word] += 1
                self.vocabulary[word] += 1
        return self

    def _next_distribution(self, context):
        distribution = Counter()
        for order in range(self.order - 1, 0, -1):
            key = tuple(context[-order:]) if order else ()
            counts = self.contexts.get(key)
            if counts:
                distribution.update(counts)
                break
        return distribution

    def autocomplete(self, prefix, max_results=5):
        context = tuple(normalize(prefix).split())
        distribution = self._next_distribution(context[-self.order + 1:] if context else [])
        return [word for word, _ in distribution.most_common(max_results)]

    @staticmethod
    def _stable_seed(text):
        return sum((index + 1) * ord(ch) for index, ch in enumerate(text or ""))

    def generate(self, seed, length=20):
        rng = random.Random(self._stable_seed(seed))
        words = normalize(seed).split()[-self.order + 1:] if seed else []
        output = list(words)
        for _ in range(length):
            distribution = self._next_distribution(words[-(self.order - 1):] if self.order > 1 else [])
            if not distribution:
                break
            options = list(distribution)
            weights = [distribution[w] for w in options]
            choice = rng.choices(options, weights=weights, k=1)[0]
            output.append(choice)
            words = output[-(self.order - 1):] if self.order > 1 else []
        return " ".join(output)


def _split_sentences(text):
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text or "") if s.strip()]


def textrank_keywords(text, top_k=8):
    """Unsupervised keyword extraction using a TextRank (PageRank) graph."""
    tokens = [w for w in normalize(text).split()
              if w not in STOPWORDS and len(w) > 2]
    graph: dict = defaultdict(Counter)
    for i, word in enumerate(tokens):
        for j in range(i + 1, min(i + 4, len(tokens))):
            other = tokens[j]
            if other != word:
                graph[word][other] += 1
                graph[other][word] += 1
    scores = {word: 1.0 for word in graph}
    for _ in range(25):
        updated = {}
        for word, neighbours in graph.items():
            score = 0.15
            for neighbour, weight in neighbours.items():
                total = sum(graph[neighbour].values()) or 1
                score += 0.85 * (weight / total) * scores[neighbour]
            updated[word] = score
        scores = updated
    return [word for word in sorted(scores, key=scores.get, reverse=True)][:top_k]


def textrank_summary(text, top_n=3):
    """Extractive summarisation: score sentences with TextRank over a
    TF-IDF cosine similarity graph."""
    sentences = _split_sentences(text)
    if len(sentences) <= top_n:
        return sentences
    vectors = TfidfVectorizer().fit_transform(sentences)
    size = len(sentences)
    similarity = [[0.0] * size for _ in range(size)]
    for i in range(size):
        for j in range(size):
            if i != j:
                similarity[i][j] = cosine_similarity(vectors[i], vectors[j])
    scores = [1.0] * size
    for _ in range(30):
        updated = []
        for i in range(size):
            score = 0.15
            for j in range(size):
                if i != j:
                    out_sum = sum(similarity[j]) or 1.0
                    score += 0.85 * similarity[i][j] / out_sum * scores[j]
            updated.append(score)
        scores = updated
    ranked = sorted(range(size), key=lambda i: scores[i], reverse=True)[:top_n]
    return [sentences[i] for i in sorted(ranked)]


POSITIVE_WORDS = {
    "good": 1, "great": 2, "excellent": 3, "amazing": 3, "awesome": 3,
    "happy": 2, "love": 2, "nice": 1, "thanks": 1, "thank": 1, "perfect": 2,
    "done": 1, "finished": 1, "success": 2, "win": 2, "helpful": 2, "clear": 1,
    "easy": 1, "better": 1, "best": 2, "glad": 2, "progress": 1,
}
NEGATIVE_WORDS = {
    "bad": -1, "terrible": -3, "awful": -3, "hate": -2, "sad": -2, "angry": -2,
    "late": -1, "overdue": -2, "stuck": -1, "wrong": -1, "fail": -2, "failed": -2,
    "problem": -1, "issue": -1, "hard": -1, "difficult": -1, "worse": -1,
    "worst": -2, "broken": -2, "confusing": -1, "annoyed": -2, "delay": -1,
}
NEGATORS = {"not", "no", "never", "without", "n't", "dont", "cannot"}


class SentimentAnalyzer:
    """Lexicon-based sentiment with simple negation handling."""

    def score(self, text: str) -> dict:
        tokens = normalize(text).split()
        total = 0
        for i, token in enumerate(tokens):
            value = POSITIVE_WORDS.get(token, 0) + NEGATIVE_WORDS.get(token, 0)
            if value == 0:
                continue
            window = tokens[max(0, i - 3):i]
            if any(negator in window for negator in NEGATORS):
                value = -value
            total += value
        label = "positive" if total > 0 else "negative" if total < 0 else "neutral"
        return {"polarity": total, "label": label}


def soundex(word: str) -> str:
    """Phonetic Soundex code (for fuzzy name matching)."""
    word = re.sub(r"[^a-z]", "", (word or "").lower())
    if not word:
        return ""
    codes = {"b": "1", "f": "1", "p": "1", "v": "1", "c": "2", "g": "2", "j": "2",
             "k": "2", "q": "2", "s": "2", "x": "2", "z": "2", "d": "3", "t": "3",
             "l": "4", "m": "5", "n": "5", "r": "6"}
    first = word[0].upper()
    tail = []
    previous = codes.get(word[0], "")
    for char in word[1:]:
        code = codes.get(char, "")
        if code and code != previous:
            tail.append(code)
        if char not in "hw":
            previous = code
    return (first + "".join(tail) + "000")[:4]


def jaro_winkler(a: str, b: str) -> float:
    """Jaro-Winkler similarity in [0, 1] (prefix-weighted string metric)."""
    a, b = (a or "").lower(), (b or "").lower()
    if a == b:
        return 1.0
    if not a or not b:
        return 0.0
    match_distance = max(len(a), len(b)) // 2 - 1
    a_matches = [False] * len(a)
    b_matches = [False] * len(b)
    matches = 0
    for i, char in enumerate(a):
        start = max(0, i - match_distance)
        end = min(i + match_distance + 1, len(b))
        for j in range(start, end):
            if not b_matches[j] and b[j] == char:
                a_matches[i] = b_matches[j] = True
                matches += 1
                break
    if matches == 0:
        return 0.0
    transpositions = 0
    k = 0
    for i in range(len(a)):
        if a_matches[i]:
            while not b_matches[k]:
                k += 1
            if a[i] != b[k]:
                transpositions += 1
            k += 1
    transpositions //= 2
    jaro = (matches / len(a) + matches / len(b)
            + (matches - transpositions) / matches) / 3
    prefix = 0
    for ca, cb in zip(a, b):
        if ca == cb and prefix < 4:
            prefix += 1
        else:
            break
    return jaro + prefix * 0.1 * (1 - jaro)


WEEKDAYS = {
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
    "friday": 4, "saturday": 5, "sunday": 6,
}
MONTHS = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3,
    "april": 4, "apr": 4, "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7,
    "august": 8, "aug": 8, "september": 9, "sep": 9, "sept": 9, "october": 10,
    "oct": 10, "november": 11, "nov": 11, "december": 12, "dec": 12,
}
PRIORITY_WORDS = {
    "urgent": "urgent", "asap": "urgent", "critical": "urgent",
    "high": "high", "important": "high",
    "low": "low", "someday": "low", "whenever": "low",
    "medium": "medium", "normal": "medium",
}


def extract_priority(text: str) -> str:
    lower = normalize(text)
    for word, priority in PRIORITY_WORDS.items():
        if re.search(rf"\b{word}\b", lower):
            return priority
    return "medium"


@dataclass
class TimeInfo:
    start: datetime | None = None
    end: datetime | None = None
    has_date: bool = False
    has_time: bool = False
    spans: list = field(default_factory=list)


def _combine(now: datetime, date_value, clock: time | None) -> datetime:
    base = now.replace(second=0, microsecond=0)
    if date_value is not None:
        base = base.replace(year=date_value.year, month=date_value.month,
                            day=date_value.day)
    if clock is not None:
        base = base.replace(hour=clock.hour, minute=clock.minute)
    return base


def parse_when(text: str, now: datetime) -> TimeInfo:
    """Extract a start (and default end) datetime plus matched spans from text."""
    lower = normalize(text)
    info = TimeInfo()
    date_value = None
    clock = None
    spans = []

    def mark(match):
        spans.append((match.start(), match.end()))

    iso = re.search(r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b", lower)
    if iso:
        date_value = now.replace(year=int(iso.group(1)), month=int(iso.group(2)),
                                 day=int(iso.group(3))).date()
        info.has_date = True
        mark(iso)

    if date_value is None:
        dm = re.search(r"\b(\d{1,2})\s+(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\b", lower)
        if dm:
            month = MONTHS.get(dm.group(2), None)
            if month:
                date_value = now.replace(month=month, day=int(dm.group(1))).date()
                info.has_date = True
                mark(dm)
        else:
            md = re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+(\d{1,2})\b", lower)
            if md:
                month = MONTHS.get(md.group(1), None)
                if month:
                    date_value = now.replace(month=month, day=int(md.group(2))).date()
                    info.has_date = True
                    mark(md)

    if date_value is None:
        offset = re.search(r"\bin\s+(\d{1,3})\s+(minute|min|hour|hr|day|week|month)s?\b", lower)
        if offset:
            amount = int(offset.group(1))
            unit = offset.group(2)
            delta = {
                "minute": timedelta(minutes=amount), "min": timedelta(minutes=amount),
                "hour": timedelta(hours=amount), "hr": timedelta(hours=amount),
                "day": timedelta(days=amount), "week": timedelta(weeks=amount),
                "month": timedelta(days=30 * amount),
            }.get(unit, timedelta())
            date_value = (now + delta).date()
            info.has_date = True
            mark(offset)

    if date_value is None:
        for word, delta_days in (("day after tomorrow", 2), ("tomorrow", 1),
                                 ("today", 0), ("tonight", 0)):
            if re.search(rf"\b{word}\b", lower):
                date_value = (now + timedelta(days=delta_days)).date()
                info.has_date = True
                info.spans.append(re.search(rf"\b{word}\b", lower).span())
                if word == "tonight":
                    clock = time(20, 0)
                    info.has_time = True
                break

    if date_value is None:
        next_wd = re.search(r"\b(?:next|this|on)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", lower)
        if next_wd:
            target = WEEKDAYS[next_wd.group(1)]
            ahead = (target - now.weekday()) % 7
            if ahead == 0 or "next" in next_wd.group(0):
                ahead = ahead or 7
            date_value = (now + timedelta(days=ahead)).date()
            info.has_date = True
            mark(next_wd)

    clock_tokens = [
        (r"\b(?:at\s+)?(\d{1,2}):(\d{2})\s*(am|pm)?\b", True),
        (r"\b(?:at\s+)?(\d{1,2})\s*(am|pm)\b", False),
    ]
    if clock is None:
        for pattern, has_minutes in clock_tokens:
            match = re.search(pattern, lower)
            if match:
                hour = int(match.group(1))
                minute = int(match.group(2)) if has_minutes else 0
                meridiem = match.group(3) if has_minutes else match.group(2)
                if meridiem == "pm" and hour < 12:
                    hour += 12
                if meridiem == "am" and hour == 12:
                    hour = 0
                if 0 <= hour <= 23 and 0 <= minute <= 59:
                    clock = time(hour, minute)
                    info.has_time = True
                    mark(match)
                    break

    if clock is None:
        for word, hour in (("noon", 12), ("midnight", 0), ("morning", 9),
                           ("afternoon", 14), ("evening", 18), ("night", 20)):
            if re.search(rf"\b{word}\b", lower):
                clock = time(hour, 0)
                info.has_time = True
                info.spans.append(re.search(rf"\b{word}\b", lower).span())
                break

    if date_value is None and clock is not None:
        candidate = _combine(now, None, clock)
        if candidate <= now:
            candidate += timedelta(days=1)
            info.has_date = True
        date_value = candidate.date()

    if date_value is None and clock is None:
        return info

    if clock is None:
        clock = time(9, 0)

    start = _combine(now, date_value, clock)
    info.start = start
    info.end = start + timedelta(hours=1)
    info.spans.extend(spans)
    return info


_CREATE_VERBS = re.compile(
    r"\b(add|create|make|schedule|set up|setup|remind me to|remind me|remember to|"
    r"note down|jot down|new|book|plan|put)\b", re.I)
_EVENT_NOUNS = re.compile(r"\b(meeting|event|appointment|call with|sync|standup|"
                          r"stand-up|interview|session|reminder|birthday|party|"
                          r"lunch|dinner|conference|webinar|class|lesson)\b", re.I)
_TASK_NOUNS = re.compile(r"\b(task|todo|to-do|chore|reminder|note|item)\b", re.I)
_LEAD = re.compile(
    r"^\s*(please\s+)?(add|create|make|schedule|set up|setup|remind me to|"
    r"remind me|remember to|note down|jot down|new task|new event|new|book|plan|"
    r"i need to|i want to|i have to|can you|could you)\b[\s:]*", re.I)


_ARTICLE = re.compile(r"^\s*(a|an|the)\s+", re.I)
_GENERIC_NOUN = re.compile(r"^\s*(task|todo|to-?do|reminder|note|item|chore|event)\b[\s:]*", re.I)
_CONNECTOR = re.compile(r"^\s*(to|for|about|regarding|that)\s+", re.I)


def clean_title(text: str, when: TimeInfo) -> str:
    """Reduce an instruction to a concise title by removing verbs/date phrases."""
    cleaned = text or ""
    for start, end in sorted(when.spans, reverse=True):
        cleaned = cleaned[:start] + " " + cleaned[end:]
    cleaned = _LEAD.sub("", cleaned)
    for _ in range(4):
        before = cleaned
        cleaned = _ARTICLE.sub("", cleaned)
        cleaned = _GENERIC_NOUN.sub("", cleaned)
        cleaned = _ARTICLE.sub("", cleaned)
        cleaned = _CONNECTOR.sub("", cleaned).lstrip()
        if cleaned == before or len(cleaned.split()) <= 1:
            cleaned = before
            break
    cleaned = re.sub(r"\b(for|at|on|by|due)\s*$", "", cleaned, flags=re.I)
    cleaned = re.sub(r"\b(urgent|asap|high priority|low priority|important)\b", "",
                     cleaned, flags=re.I)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .,-:;")
    if len(cleaned) < 2:
        cleaned = re.sub(r"\s+", " ", (text or "")).strip()
    return cleaned[:200]


def looks_like_creation(text: str) -> bool:
    return bool(_CREATE_VERBS.search(text))


INTENT_TRAINING = [
    ("greeting", "hi"), ("greeting", "hello"), ("greeting", "hey there"),
    ("greeting", "good morning"), ("greeting", "good evening"),
    ("greeting", "how are you"), ("greeting", "yo"), ("greeting", "hi there"),
    ("thanks", "thank you"), ("thanks", "thanks so much"), ("thanks", "much appreciated"),
    ("thanks", "cheers"), ("thanks", "brilliant thanks"), ("thanks", "great, thank you"),
    ("help", "what can you do"), ("help", "help me"), ("help", "help"),
    ("help", "how do i use this"), ("help", "show me commands"),
    ("help", "what are your features"), ("help", "give me a hand"),
    ("create_task", "add a task to call mom"),
    ("create_task", "create a task finish the report"),
    ("create_task", "remind me to buy milk"),
    ("create_task", "i need to submit my assignment tomorrow"),
    ("create_task", "add task pay electricity bill"),
    ("create_task", "make a to do review the pull request"),
    ("create_task", "note down pick up the dry cleaning"),
    ("create_task", "new task prepare slides"),
    ("create_event", "schedule a meeting with the team"),
    ("create_event", "book a dentist appointment"),
    ("create_event", "add an event for the product demo"),
    ("create_event", "plan a lunch with sarah"),
    ("create_event", "set up a call with the client at 3pm"),
    ("create_event", "schedule standup tomorrow morning"),
    ("create_event", "create a calendar event for the interview"),
    ("list_tasks", "what are my tasks"), ("list_tasks", "show my tasks"),
    ("list_tasks", "list open tasks"), ("list_tasks", "what do i have to do"),
    ("list_tasks", "any tasks due"), ("list_tasks", "show my to dos"),
    ("list_tasks", "what should i work on"), ("list_tasks", "my task list"),
    ("list_events", "what events do i have"), ("list_events", "show my schedule"),
    ("list_events", "list my meetings"), ("list_events", "what is on my calendar"),
    ("list_events", "upcoming events"), ("list_events", "my agenda"),
    ("list_events", "any appointments coming up"),
    ("summarize", "summarize my workspace"), ("summarize", "give me a summary"),
    ("summarize", "overview of my day"), ("summarize", "status report"),
    ("summarize", "what is going on"), ("summarize", "brief me"),
    ("summarize", "how am i doing today"), ("summarize", "summarise"),
    ("summarize", "summarize"), ("summarize", "summarise my day"),
    ("summarize", "summary"), ("summarize", "overview"), ("summarize", "brief summary"),
    ("summarize", "summarise the day"), ("summarize", "give me an overview"),
    ("find", "find the report task"), ("find", "search for the meeting"),
    ("find", "where is my note about the budget"), ("find", "look up project x"),
    ("find", "find anything about the launch"), ("find", "search notes"),
    ("find", "do i have anything about invoices"),
    ("smalltalk", "tell me a joke"), ("smalltalk", "what is the weather"),
    ("smalltalk", "who are you"), ("smalltalk", "what is your name"),
    ("smalltalk", "i am bored"), ("smalltalk", "how is it going"),
    ("keywords", "extract keywords"), ("keywords", "what are the main topics"),
    ("keywords", "key points please"), ("keywords", "give me the keywords"),
    ("keywords", "what themes are there"), ("keywords", "important words"),
    ("sentiment", "how does this sound"), ("sentiment", "is this positive or negative"),
    ("sentiment", "analyse the mood"), ("sentiment", "what is the tone"),
    ("sentiment", "is my week going well"), ("sentiment", "how am i feeling about this"),
    ("group", "group my tasks"), ("group", "cluster my tasks"),
    ("group", "organise my tasks by theme"), ("group", "categorise my tasks"),
    ("group", "group things together"), ("group", "what themes do my tasks fall into"),
    ("general", "what is the capital of peru"),
    ("general", "what is the capital of france"),
    ("general", "explain quantum entanglement"),
    ("general", "why is the sky blue"),
    ("general", "who invented the telephone"),
    ("general", "what is machine learning"),
    ("general", "tell me about photosynthesis"),
    ("general", "how does wifi work"),
    ("general", "define entropy in physics"),
    ("general", "largest planet in the solar system"),
    ("general", "what is the meaning of life"),
    ("general", "how do i learn faster"),
    ("general", "what is global warming"),
    ("general", "tell me about the internet"),
    ("general", "write me a poem"), ("general", "tell me a joke"),
    ("general", "write a short story"), ("general", "give me a fun fact"),
    ("general", "what is the weather like"), ("general", "who won the world cup"),
    ("math", "what is 12 * 7"), ("math", "compute 3 + 4"),
    ("math", "calculate 100 / 5"), ("math", "what is 2 to the power of 10"),
    ("math", "what is 15 minus 4"), ("math", "how much is 9 times 9"),
]


def _format_when(value: datetime) -> str:
    return value.strftime("%a %d %b, %H:%M")


# ---------------------------------------------------------------------------
# Cached training artifacts
#
# Training the intent ensemble is the only expensive step in the offline engine,
# so it is memoised by the training-data signature. The knowledge base and its
# TF-IDF index are likewise built once and reused.
# ---------------------------------------------------------------------------
_INTENT_CACHE: dict = {}
_INTENT_LOCK = threading.Lock()
_INTENT_CACHE_LIMIT = 8
_KB_SINGLETON = None
_KB_LOCK = threading.Lock()


def training_signature(examples):
    return hash(tuple(examples))


def get_intent_classifier(examples):
    """Return a (cached) fitted :class:`TextClassifier` for these examples."""
    key = training_signature(examples)
    cached = _INTENT_CACHE.get(key)
    if cached is not None:
        return cached
    with _INTENT_LOCK:
        cached = _INTENT_CACHE.get(key)
        if cached is None:
            classifier = build_intent_classifier(tokenizer=tokenize)
            classifier.fit(list(examples))
            if len(_INTENT_CACHE) >= _INTENT_CACHE_LIMIT:
                _INTENT_CACHE.clear()
            _INTENT_CACHE[key] = classifier
        return _INTENT_CACHE[key]


def get_knowledge_base():
    global _KB_SINGLETON
    if _KB_SINGLETON is None:
        with _KB_LOCK:
            if _KB_SINGLETON is None:
                _KB_SINGLETON = KnowledgeBase()
    return _KB_SINGLETON


_METRICS_CACHE: dict = {}
_METRICS_LOCK = threading.Lock()


def intent_metrics(examples, n_splits: int = 3):
    """Cross-validated metrics for the deployed intent model (memoised)."""
    key = training_signature(examples)
    cached = _METRICS_CACHE.get(key)
    if cached is not None:
        return cached
    with _METRICS_LOCK:
        cached = _METRICS_CACHE.get(key)
        if cached is None:
            classifier = build_intent_classifier(calibrate=False, tokenizer=tokenize)
            cached = classifier.evaluate(list(examples), n_splits=n_splits)
            if len(_METRICS_CACHE) >= _INTENT_CACHE_LIMIT:
                _METRICS_CACHE.clear()
            _METRICS_CACHE[key] = cached
        return _METRICS_CACHE[key]


def _format_number(value) -> str:
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return f"{value:g}" if isinstance(value, float) else str(value)


class LocalAssistant:
    """Intent-driven assistant that reasons over the user's own workspace.

    Intent is recognised by a calibrated soft-voting ensemble (Multinomial
    Naive Bayes + softmax regression + k-NN) over word n-gram TF-IDF features;
    TF-IDF + latent semantic analysis retrieve relevant items; a retrieval-
    augmented knowledge base answers general questions; and a safe arithmetic
    evaluator handles maths. Additional labelled examples (learned from user
    feedback) are folded into training so the model improves over time. Trained
    classifiers are memoised per training set, so repeated turns are cheap.
    """

    MODEL_WEIGHTS = {"nb": 1.0, "logreg": 1.2, "knn": 0.8}

    def __init__(self, now: datetime, extra_examples=None, corpus=None):
        self.now = now
        self.examples = list(INTENT_TRAINING) + list(extra_examples or [])
        self.classifier = get_intent_classifier(self.examples)
        self.language_model = NGramLanguageModel(order=2).train(corpus or [])

    def classify(self, text: str):
        label, confidence, _ = self.classifier.predict_with_confidence(text)
        if looks_like_creation(text):
            if _EVENT_NOUNS.search(text):
                return "create_event", max(confidence, 0.5)
            if _TASK_NOUNS.search(text):
                return "create_task", max(confidence, 0.5)
        return label, confidence

    def retrieve(self, text: str, items, top_k: int = 3):
        """Hybrid lexical (TF-IDF) + semantic (LSA) retrieval."""
        if not items:
            return []
        corpus = [f"{it.get('title', '')} {it.get('type', '')}" for it in items]
        vectorizer = TfidfVectorizer().fit(corpus)
        query = vectorizer.transform(text)
        semantic = None
        if len(corpus) >= 3:
            svd = TruncatedSVD(n_components=min(6, len(corpus)))
            embeddings = svd.fit_transform(corpus)
            query_embedding = svd.transform(text)
            semantic = (embeddings, query_embedding)
        scored = []
        for index, (item, document) in enumerate(zip(items, corpus)):
            lexical = cosine_similarity(query, vectorizer.transform(document))
            score = lexical
            if semantic:
                score = 0.6 * lexical + 0.4 * cosine_dense(
                    semantic[1], semantic[0][index]
                )
            if score > 0:
                scored.append((score, item))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:top_k]

    def cluster_items(self, items, k=3):
        """Group items into themes using LSA + k-Means."""
        texts = [it.get("title", "") for it in items if it.get("title")]
        if len(texts) < k:
            return []
        svd = TruncatedSVD(n_components=min(6, len(texts)))
        embeddings = svd.fit_transform(texts)
        labels = KMeans(k=k).fit(embeddings)
        groups: dict = defaultdict(list)
        for item, label in zip([it for it in items if it.get("title")], labels):
            groups[label].append(item)
        return [members for members in groups.values() if members]

    def respond(self, text: str, items):
        intent, confidence = self.classify(text)
        when = parse_when(text, self.now)
        priority = extract_priority(text)

        # General knowledge / arithmetic fallbacks: only used when the message
        # is not clearly a workspace action, so workspace intents keep priority.
        if intent in {"math", "general", "smalltalk", "unknown"}:
            value = evaluate_math(text)
            if value is not None:
                return Reply(f"That is {_format_number(value)}.",
                             intent="math", confidence=max(confidence, 0.9))
            knowledge = get_knowledge_base().answer(text)
            if knowledge is not None:
                return Reply(knowledge["answer"], intent="general",
                             confidence=max(confidence, knowledge["score"]))

        handler = getattr(self, f"_reply_{intent}", self._reply_smalltalk)
        reply = handler(text, items, when, priority)
        reply.intent = intent
        reply.confidence = confidence
        return reply

    def _reply_greeting(self, text, items, when, priority):
        open_tasks = [it for it in items if it.get("type") == "task" and not it.get("done")]
        body = "Hello! I'm NexaMind, your workspace assistant. "
        if open_tasks:
            body += f"You currently have {len(open_tasks)} open task(s). "
        body += "Ask me to add tasks, schedule events, or summarise your day."
        return Reply(body)

    def _reply_thanks(self, text, items, when, priority):
        return Reply("You're welcome! Anything else I can help you organise?")

    def _reply_help(self, text, items, when, priority):
        return Reply(
            "I can help you with your workspace offline:\n"
            "• “Add a task to call mom tomorrow at 5pm”\n"
            "• “Schedule a meeting next Monday at 10am”\n"
            "• “What are my tasks?” / “Show my events”\n"
            "• “Summarise my workspace” / “Find the report task”\n"
            "You can also use slash commands such as /task, /event, /summarize and /help."
        )

    def _reply_create_task(self, text, items, when, priority):
        title = clean_title(text, when)
        due = when.start
        action = {"type": "create_task", "payload": {
            "title": title, "priority": priority,
            "due_date": due.isoformat() if due else None,
            "description": "", "category": "",
        }}
        parts = [f"I can create a task titled “{title}”"]
        if priority != "medium":
            parts.append(f"with {priority} priority")
        if due:
            parts.append(f"due {_format_when(due)}")
        return Reply(" ".join(parts) + ".", [action])

    def _reply_create_event(self, text, items, when, priority):
        title = clean_title(text, when)
        start = when.start or (self.now + timedelta(hours=1)).replace(second=0, microsecond=0)
        end = when.end or (start + timedelta(hours=1))
        action = {"type": "create_event", "payload": {
            "title": title, "start": start.isoformat(), "end": end.isoformat(),
            "location": "", "description": "",
        }}
        return Reply(
            f"I can schedule “{title}” for {_format_when(start)}.",
            [action],
        )

    def _reply_list_tasks(self, text, items, when, priority):
        tasks = [it for it in items if it.get("type") == "task" and not it.get("done")]
        if when.has_date and when.start:
            target = when.start.date()
            tasks = [t for t in tasks
                     if t.get("due") and t["due"][:10] == target.isoformat()]
        if not tasks:
            return Reply("You have no open tasks right now. Nice and clear!")
        lines = [f"• {t['title']}" + (f" — due {t['due'][:16].replace('T', ' ')}" if t.get("due") else "")
                 + (f" ({t['priority']})" if t.get("priority") and t["priority"] != "medium" else "")
                 for t in tasks[:8]]
        more = f"\n…and {len(tasks) - 8} more." if len(tasks) > 8 else ""
        return Reply(f"You have {len(tasks)} open task(s):\n" + "\n".join(lines) + more)

    def _reply_list_events(self, text, items, when, priority):
        events = [it for it in items if it.get("type") == "event"
                  and it.get("start") and it["start"] >= self.now.isoformat()]
        events.sort(key=lambda e: e["start"])
        if not events:
            return Reply("You have no upcoming events.")
        lines = [f"• {e['title']} — {e['start'][:16].replace('T', ' ')}"
                 + (f" @ {e['location']}" if e.get("location") else "")
                 for e in events[:8]]
        return Reply(f"Here are your next {min(len(events), 8)} event(s):\n" + "\n".join(lines))

    def _reply_summarize(self, text, items, when, priority):
        tasks = [it for it in items if it.get("type") == "task"]
        open_tasks = [t for t in tasks if not t.get("done")]
        overdue = [t for t in open_tasks if t.get("due") and t["due"] < self.now.isoformat()]
        events = [it for it in items if it.get("type") == "event"
                  and it.get("start") and it["start"] >= self.now.isoformat()]
        return Reply(
            "Here's your workspace at a glance:\n"
            f"• {len(tasks)} task(s) total, {len(open_tasks)} open, {len(overdue)} overdue\n"
            f"• {len(events)} upcoming event(s)\n"
            + (f"• Next: {events[0]['title']} at {events[0]['start'][:16].replace('T', ' ')}"
               if events else "• No events scheduled")
        )

    def _reply_find(self, text, items, when, priority):
        matches = self.retrieve(text, items)
        if not matches:
            return Reply("I couldn't find anything in your workspace matching that.")
        lines = [f"• {m['title']} ({m['type']}"
                 + (f", due {m['due'][:10]}" if m.get("due") else "")
                 + (f", {m['start'][:16].replace('T', ' ')}" if m.get("start") else "")
                 + f") — match {int(score * 100)}%" for score, m in matches]
        return Reply("Here's what I found:\n" + "\n".join(lines))

    def _reply_keywords(self, text, items, when, priority):
        corpus = " ".join(it.get("title", "") for it in items)
        corpus = (corpus + " " + text).strip()
        keywords = textrank_keywords(corpus, top_k=8)
        if not keywords:
            return Reply("I couldn't find distinctive keywords in your workspace yet.")
        return Reply("Top keywords across your workspace:\n• " + "\n• ".join(keywords))

    def _reply_sentiment(self, text, items, when, priority):
        corpus = " ".join(it.get("title", "") for it in items)
        analyzer = SentimentAnalyzer()
        result = analyzer.score(corpus)
        reply = (
            f"Overall sentiment of your workspace looks {result['label']} "
            f"(polarity {result['polarity']:+d})."
        )
        events = [it for it in items if it.get("type") == "event" and it.get("start")]
        if events:
            reply += f" You have {len(events)} upcoming event(s) to keep an eye on."
        return Reply(reply)

    def _reply_group(self, text, items, when, priority):
        groups = self.cluster_items(items, k=min(3, max(1, len(items) // 2)))
        if not groups:
            return Reply("Add a few more tasks and I can group them into themes.")
        lines = []
        for i, members in enumerate(groups, 1):
            titles = [m.get("title", "") for m in members]
            keywords = textrank_keywords(" ".join(titles), top_k=3)
            theme = ", ".join(keywords) or "misc"
            lines.append(f"Theme {i} ({theme}): " + "; ".join(titles))
        return Reply("I clustered your items into themes:\n" + "\n".join(lines))

    def _reply_general(self, text, items, when, priority):
        return Reply(
            "That's outside my offline knowledge base, so I can't answer it "
            "accurately without making something up. I can help with your "
            "workspace offline, or an administrator can connect an AI provider "
            "for open-ended questions."
        )

    def _reply_smalltalk(self, text, items, when, priority):
        matches = self.retrieve(text, items)
        if matches and matches[0][0] >= 0.35:
            best_score, best = matches[0]
            return Reply(
                f"I'm an offline workspace assistant, so I can't chat about that. "
                f"I did notice something related: “{best['title']}” "
                f"(match {int(best_score * 100)}%)."
            )
        return Reply(
            "I focus on your tasks and schedule. Try “add a task…”, "
            "“schedule a meeting…”, “what are my tasks?” or “summarise my day”."
        )


@dataclass
class Reply:
    text: str
    actions: list = field(default_factory=list)
    intent: str = "unknown"
    confidence: float = 0.0
