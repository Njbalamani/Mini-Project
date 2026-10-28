"""Distributional word/document embeddings and approximate nearest neighbours.

Word vectors are learned with the classic *count* recipe: build a word-context
co-occurrence matrix, weight it with positive pointwise mutual information
(PPMI), then factorise it with a truncated SVD (Levy & Goldberg, 2014). No
external numerical libraries are required.
"""
from __future__ import annotations

import math
import random
from collections import Counter

from .features import word_tokens


def _orthonormalize(matrix):
    if not matrix:
        return matrix
    rows, cols = len(matrix), len(matrix[0])
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


def _transpose(matrix):
    return [list(row) for row in zip(*matrix)] if matrix else []


def _matmul(a, b):
    if not a or not b:
        return []
    columns = _transpose(b)
    return [[sum(x * y for x, y in zip(row, col)) for col in columns] for row in a]


def _l2(vector):
    norm = math.sqrt(sum(value * value for value in vector)) or 1.0
    return [value / norm for value in vector]


class WordVectors:
    """PPMI + truncated-SVD word embeddings learned from a text corpus."""

    def __init__(self, dimensions=50, window=4, min_count=1, max_vocab=600,
                 n_iter=20, seed=42):
        self.dimensions = dimensions
        self.window = window
        self.min_count = min_count
        self.max_vocab = max_vocab
        self.n_iter = n_iter
        self.seed = seed
        self.vocabulary: list = []
        self.vectors: dict = {}

    def fit(self, texts):
        counts: Counter = Counter()
        tokenised = []
        for text in texts:
            tokens = word_tokens(text)
            tokenised.append(tokens)
            counts.update(tokens)
        self.vocabulary = [word for word, freq in counts.most_common(self.max_vocab)
                           if freq >= self.min_count]
        index = {word: i for i, word in enumerate(self.vocabulary)}
        vocab_size = len(self.vocabulary)
        if vocab_size == 0:
            self.vectors = {}
            return self

        cooc = [[0.0] * vocab_size for _ in range(vocab_size)]
        for tokens in tokenised:
            ids = [index[t] for t in tokens if t in index]
            for i, center in enumerate(ids):
                left = max(0, i - self.window)
                right = min(len(ids), i + self.window + 1)
                for j in range(left, right):
                    if j != i:
                        cooc[center][ids[j]] += 1.0

        total = sum(sum(row) for row in cooc) or 1.0
        row_sums = [sum(row) or 1.0 for row in cooc]
        col_sums = [sum(cooc[i][j] for i in range(vocab_size)) or 1.0 for j in range(vocab_size)]
        ppmi = [[0.0] * vocab_size for _ in range(vocab_size)]
        for i in range(vocab_size):
            for j in range(vocab_size):
                count = cooc[i][j]
                if count <= 0:
                    continue
                pmi = math.log((count * total) / (row_sums[i] * col_sums[j]))
                ppmi[i][j] = max(pmi, 0.0)

        k = max(1, min(self.dimensions, vocab_size - 1))
        rng = random.Random(self.seed)
        components = [[rng.random() for _ in range(k)] for _ in range(vocab_size)]
        components = _orthonormalize(components)
        for _ in range(self.n_iter):
            doc_vectors = _orthonormalize(_matmul(ppmi, components))
            components = _orthonormalize(_matmul(_transpose(ppmi), doc_vectors))
        embeddings = _matmul(ppmi, components)
        self.vectors = {word: _l2(embeddings[i]) for i, word in enumerate(self.vocabulary)}
        return self

    def vector(self, word):
        return self.vectors.get(word, [])

    def doc_vector(self, text):
        tokens = [t for t in word_tokens(text) if t in self.vectors]
        if not tokens:
            return []
        dims = len(self.vectors[tokens[0]])
        total = [0.0] * dims
        for token in tokens:
            for i, value in enumerate(self.vectors[token]):
                total[i] += value
        return _l2(total)

    def similarity(self, word_a, word_b) -> float:
        a, b = self.vector(word_a), self.vector(word_b)
        if not a or not b:
            return 0.0
        return sum(x * y for x, y in zip(a, b))

    def most_similar(self, word, top_k=5):
        target = self.vector(word)
        if not target:
            return []
        scored = []
        for other, vector in self.vectors.items():
            if other == word:
                continue
            scored.append((sum(x * y for x, y in zip(target, vector)), other))
        scored.sort(reverse=True)
        return scored[:top_k]


class RandomProjectionLSH:
    """Approximate nearest-neighbour index using signed random projections.

    Each vector is hashed to a binary signature; vectors that share a bucket are
    treated as candidate neighbours, giving sub-linear lookup for retrieval.
    """

    def __init__(self, dim, n_bits=16, seed=42):
        self.dim = dim
        self.n_bits = n_bits
        rng = random.Random(seed)
        self.planes = [[rng.gauss(0, 1) for _ in range(dim)] for _ in range(n_bits)]
        self.buckets: dict = {}
        self.payloads: list = []

    def _signature(self, vector):
        code = 0
        for b, plane in enumerate(self.planes):
            if sum(p * v for p, v in zip(plane, vector)) >= 0:
                code |= (1 << b)
        return code

    def add(self, vector, payload):
        code = self._signature(vector)
        self.buckets.setdefault(code, []).append(len(self.payloads))
        self.payloads.append((vector, payload))

    def query(self, vector, max_results=5):
        code = self._signature(vector)
        candidates = self.buckets.get(code)
        if not candidates:
            candidates = range(len(self.payloads))
        scored = []
        for idx in candidates:
            stored, payload = self.payloads[idx]
            dot = sum(x * y for x, y in zip(vector, stored))
            norm = (math.sqrt(sum(x * x for x in vector))
                    * math.sqrt(sum(y * y for y in stored))) or 1.0
            scored.append((dot / norm, payload))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:max_results]
