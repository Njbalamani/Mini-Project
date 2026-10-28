"""Feature extraction for the pure-Python ML framework.

Provides count/TF-IDF vectorisers over word n-grams and character n-grams, a
feature-union combinator and a hashing vectoriser. Everything works on dense
Python lists of floats so downstream models need no external libraries.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN_RE = re.compile(r"[a-z0-9']+")


def word_tokens(text: str):
    return _TOKEN_RE.findall((text or "").lower())


def word_ngrams(tokens, n: int):
    if n <= 1:
        return list(tokens)
    return [" ".join(tokens[i:i + n]) for i in range(len(tokens) - n + 1)]


def char_ngrams(text: str, n: int, pad: bool = True):
    stripped = re.sub(r"\s+", " ", (text or "").lower()).strip()
    if pad:
        stripped = " " + stripped + " "
    if len(stripped) < n:
        return [stripped]
    return [stripped[i:i + n] for i in range(len(stripped) - n + 1)]


def _l2_normalize(vector):
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class FeatureExtractor:
    """Base class: fit a vocabulary, transform text into a dense vector."""

    def fit(self, texts):
        raise NotImplementedError

    def transform(self, text):
        raise NotImplementedError

    def fit_transform(self, texts):
        self.fit(texts)
        return [self.transform(text) for text in texts]

    @property
    def names(self):
        return []

    @property
    def dim(self) -> int:
        return len(self.names)


class TfidfFeatureExtractor(FeatureExtractor):
    """TF-IDF over word n-grams and (optionally) character n-grams.

    Uses sublinear term frequency (``1 + log(tf)``), smoothed IDF and L2
    normalisation, matching the standard text-classification recipe.
    """

    def __init__(self, ngram_range=(1, 2), use_char=False, char_range=(3, 5),
                 min_df=1, sublinear=True, max_features=None, tokenizer=None):
        self.ngram_range = ngram_range
        self.use_char = use_char
        self.char_range = char_range
        self.min_df = min_df
        self.sublinear = sublinear
        self.max_features = max_features
        self.tokenizer = tokenizer or word_tokens
        self._vocabulary: list = []
        self._index: dict = {}
        self._idf: dict = {}

    def _features(self, text: str):
        tokens = self.tokenizer(text)
        features = []
        for n in range(self.ngram_range[0], self.ngram_range[1] + 1):
            features.extend(word_ngrams(tokens, n))
        if self.use_char:
            for n in range(self.char_range[0], self.char_range[1] + 1):
                features.extend(f"#{gram}" for gram in char_ngrams(text, n))
        return features

    def fit(self, texts):
        doc_freq: Counter = Counter()
        total = 0
        for text in texts:
            total += 1
            for term in set(self._features(text)):
                doc_freq[term] += 1
        candidates = [term for term, freq in doc_freq.items() if freq >= self.min_df]
        if self.max_features and len(candidates) > self.max_features:
            # Keep the most frequent terms (highest document frequency).
            candidates.sort(key=lambda term: (-doc_freq[term], term))
            candidates = candidates[:self.max_features]
        self._vocabulary = sorted(candidates)
        self._index = {term: i for i, term in enumerate(self._vocabulary)}
        self._idf = {
            term: math.log((1 + total) / (1 + doc_freq[term])) + 1.0
            for term in self._vocabulary
        }
        return self

    def transform(self, text):
        vector = [0.0] * len(self._vocabulary)
        counts = Counter(self._features(text))
        for term, count in counts.items():
            position = self._index.get(term)
            if position is None:
                continue
            term_freq = (1.0 + math.log(count)) if self.sublinear else float(count)
            vector[position] = term_freq * self._idf.get(term, 1.0)
        return _l2_normalize(vector)

    @property
    def names(self):
        return list(self._vocabulary)


class HashingFeatureExtractor(FeatureExtractor):
    """Feature hashing (the hashing trick) with optional signed buckets."""

    def __init__(self, n_features=2 ** 12, ngram_range=(1, 2), alternate_sign=True):
        self.n_features = n_features
        self.ngram_range = ngram_range
        self.alternate_sign = alternate_sign

    @staticmethod
    def _hash(token: str) -> int:
        # Deterministic FNV-1a hash (Python's hash() is salted per process).
        value = 2166136261
        for char in token:
            value ^= ord(char)
            value = (value * 16777619) & 0xFFFFFFFF
        return value

    def _features(self, text: str):
        tokens = word_tokens(text)
        for n in range(self.ngram_range[0], self.ngram_range[1] + 1):
            for gram in word_ngrams(tokens, n):
                yield gram

    def fit(self, texts):
        return self

    def transform(self, text):
        vector = [0.0] * self.n_features
        for gram in self._features(text):
            bucket = self._hash(gram) % self.n_features
            sign = 1.0
            if self.alternate_sign and (self._hash(gram) >> 31) & 1:
                sign = -1.0
            vector[bucket] += sign
        return _l2_normalize(vector)

    @property
    def names(self):
        return [f"bucket_{i}" for i in range(self.n_features)]


class CharNGramVectorizer(TfidfFeatureExtractor):
    """TF-IDF restricted to character n-grams (robust to typos/morphology)."""

    def __init__(self, char_range=(3, 5), min_df=1):
        super().__init__(ngram_range=(1, 1), use_char=True,
                         char_range=char_range, min_df=min_df)


class FeatureUnion(FeatureExtractor):
    """Concatenate the outputs of several extractors into one vector."""

    def __init__(self, extractors):
        self.extractors = list(extractors)

    def fit(self, texts):
        for extractor in self.extractors:
            extractor.fit(texts)
        return self

    def transform(self, text):
        vector = []
        for extractor in self.extractors:
            vector.extend(extractor.transform(text))
        return vector

    @property
    def names(self):
        names = []
        for extractor in self.extractors:
            names.extend(extractor.names)
        return names
