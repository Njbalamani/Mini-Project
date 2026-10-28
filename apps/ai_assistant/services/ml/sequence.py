"""Sequence-labelling and text-normalisation utilities.

* ``POSTagger``       – hidden Markov model part-of-speech tagger (Viterbi).
* ``NERTagger``       – BIO named-entity recognition (gazetteer + heuristics).
* ``SpellCorrector``  – Norvig-style edit-distance spelling correction.
* ``LanguageDetector``– character n-gram language identification.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from .features import word_tokens

# A compact tagged corpus (word/tag) used to estimate HMM parameters. Tags use
# the universal POS set so the chat pipeline can reason about word roles.
TAGGED_CORPUS = [
    [("add", "VERB"), ("a", "DET"), ("task", "NOUN"), ("to", "PART"), ("call", "VERB"), ("mom", "NOUN")],
    [("schedule", "VERB"), ("a", "DET"), ("meeting", "NOUN"), ("with", "ADP"), ("the", "DET"), ("team", "NOUN")],
    [("remind", "VERB"), ("me", "PRON"), ("to", "PART"), ("buy", "VERB"), ("milk", "NOUN")],
    [("what", "PRON"), ("are", "VERB"), ("my", "PRON"), ("tasks", "NOUN")],
    [("show", "VERB"), ("my", "PRON"), ("schedule", "NOUN")],
    [("summarize", "VERB"), ("my", "PRON"), ("workspace", "NOUN")],
    [("the", "DET"), ("report", "NOUN"), ("is", "VERB"), ("due", "ADJ"), ("tomorrow", "ADV")],
    [("i", "PRON"), ("will", "VERB"), ("finish", "VERB"), ("the", "DET"), ("project", "NOUN"), ("today", "ADV")],
    [("please", "INTJ"), ("create", "VERB"), ("a", "DET"), ("new", "ADJ"), ("note", "NOUN")],
    [("call", "VERB"), ("the", "DET"), ("dentist", "NOUN"), ("asap", "ADV")],
    [("book", "VERB"), ("a", "DET"), ("hotel", "NOUN"), ("in", "ADP"), ("paris", "NOUN")],
    [("send", "VERB"), ("an", "DET"), ("email", "NOUN"), ("to", "ADP"), ("john", "NOUN")],
]

# Deterministic suffix heuristics to tag unseen words.
_SUFFIX_TAGS = [
    ("ing", "VERB"), ("ed", "VERB"), ("ly", "ADV"),
    ("ous", "ADJ"), ("ive", "ADJ"), ("able", "ADJ"), ("ful", "ADJ"),
]


class POSTagger:
    """Bigram HMM POS tagger trained with add-one smoothing, decoded by Viterbi."""

    def __init__(self, tagger_corpus=None, suffix_heuristics=True):
        self.suffix_heuristics = suffix_heuristics
        self.tags: list = []
        self.transitions: dict = {}
        self.emissions: dict = {}
        self.tag_counts: Counter = Counter()
        self._train(tagger_corpus or TAGGED_CORPUS)

    def _train(self, corpus):
        transition_counts: dict = defaultdict(Counter)
        emission_counts: dict = defaultdict(Counter)
        for sentence in corpus:
            previous = "<s>"
            for word, tag in sentence:
                transition_counts[previous][tag] += 1
                emission_counts[tag][word.lower()] += 1
                self.tag_counts[tag] += 1
                previous = tag
        self.tags = sorted(self.tag_counts)
        vocab = set()
        for counts in emission_counts.values():
            vocab.update(counts)
        vocab_size = len(vocab) or 1
        for previous in transition_counts:
            row = transition_counts[previous]
            denominator = sum(row.values()) + len(self.tags)
            self.transitions[previous] = {
                tag: (row.get(tag, 0) + 1) / denominator for tag in self.tags
            }
        for tag in self.tags:
            row = emission_counts.get(tag, Counter())
            denominator = sum(row.values()) + vocab_size
            self.emissions[tag] = {
                word: (count + 1) / denominator for word, count in row.items()
            }
            self.emissions[tag]["<unk>"] = 1 / denominator

    def _emission(self, word, tag):
        row = self.emissions.get(tag, {})
        return row.get(word.lower(), row.get("<unk>", 1e-9))

    def _guess_tag(self, word):
        lower = word.lower()
        if not self.suffix_heuristics:
            return max(self.tag_counts, key=self.tag_counts.get)
        for suffix, tag in _SUFFIX_TAGS:
            if lower.endswith(suffix):
                return tag
        return max(self.tag_counts, key=self.tag_counts.get)

    def tag(self, text):
        words = word_tokens(text)
        if not words:
            return []
        # Seed emissions: known words use the model, unknown words use heuristics.
        viterbi = [{}]
        backpointer = [{}]
        for tag in self.tags:
            emission = self._emission(words[0], tag)
            viterbi[0][tag] = math.log(self.transitions["<s>"].get(tag, 1e-9)) + math.log(emission)
            backpointer[0][tag] = None
        for t in range(1, len(words)):
            viterbi.append({})
            backpointer.append({})
            for tag in self.tags:
                best_previous, best_score = None, -math.inf
                for prev_tag in self.tags:
                    score = viterbi[t - 1][prev_tag] \
                        + math.log(self.transitions.get(prev_tag, {}).get(tag, 1e-9))
                    if score > best_score:
                        best_score, best_previous = score, prev_tag
                viterbi[t][tag] = best_score + math.log(self._emission(words[t], tag))
                backpointer[t][tag] = best_previous
        last_tag = max(viterbi[-1], key=viterbi[-1].get)
        tags = [last_tag]
        for t in range(len(words) - 1, 0, -1):
            tags.append(backpointer[t][tags[-1]])
        tags.reverse()
        return list(zip(words, tags))


# Gazetteers used by the NER tagger.
_DATE_WORDS = {"today", "tomorrow", "tonight", "yesterday", "monday", "tuesday",
               "wednesday", "thursday", "friday", "saturday", "sunday", "january",
               "february", "march", "april", "may", "june", "july", "august",
               "september", "october", "november", "december"}
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_URL_RE = re.compile(r"https?://\S+|www\.\S+")
_MONEY_RE = re.compile(r"(?:[$£€]|\b(?:usd|eur|inr|gbp)\b)\s?\d[\d,]*(?:\.\d+)?", re.I)


class NERTagger:
    """Extracts named entities as ``(text, label)`` spans.

    Labels: DATE, TIME, MONEY, EMAIL, URL, PERSON, ORG, LOC, GPE, MISC.
    Uses gazetteers plus surface heuristics (capitalisation, digit patterns).
    """

    def entities(self, text):
        found = []
        for regex, label in ((_EMAIL_RE, "EMAIL"), (_URL_RE, "URL"), (_MONEY_RE, "MONEY")):
            for match in regex.finditer(text or ""):
                found.append((match.group(0), label, match.start(), match.end()))
        tokens = [(m.group(0), m.start()) for m in re.finditer(r"[A-Za-z0-9:'@./-]+", text or "")]
        for i, (word, position) in enumerate(tokens):
            lower = word.lower()
            if lower in _DATE_WORDS:
                found.append((word, "DATE", position, position + len(word)))
            elif re.fullmatch(r"\d{1,2}(:\d{2})?\s?(am|pm)?", lower):
                found.append((word, "TIME" if ":" in word or lower.endswith(("am", "pm")) else "NUMBER",
                              position, position + len(word)))
            elif word[:1].isupper() and i > 0:
                label = "PERSON"
                previous = tokens[i - 1][0].lower()
                if previous in {"at", "in", "to", "from", "near"}:
                    label = "GPE"
                elif previous in {"inc", "corp", "ltd", "llc"} or lower.endswith(("inc", "corp", "ltd")):
                    label = "ORG"
                found.append((word, label, position, position + len(word)))
        # Resolve overlaps by keeping the earliest, longest span.
        found.sort(key=lambda span: (span[2], -(span[3] - span[2])))
        result, last_end = [], -1
        for item in found:
            if item[2] >= last_end:
                result.append((item[0], item[1]))
                last_end = item[3]
        return result


def _edits(word):
    letters = "abcdefghijklmnopqrstuvwxyz"
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    deletes = [left + right[1:] for left, right in splits if right]
    transposes = [left + right[1] + right[0] + right[2:] for left, right in splits if len(right) > 1]
    replaces = [left + c + right[1:] for left, right in splits if right for c in letters]
    inserts = [left + c + right for left, right in splits for c in letters]
    return set(deletes + transposes + replaces + inserts)


class SpellCorrector:
    """Norvig-style spelling corrector over a learnable vocabulary."""

    def __init__(self, vocabulary=None, max_distance=2):
        self.vocabulary = set(vocabulary or []) or {"the", "task", "meeting", "today", "tomorrow"}
        self.max_distance = max_distance

    def fit(self, texts):
        counts: Counter = Counter()
        for text in texts:
            counts.update(word_tokens(text))
        self.vocabulary = set(counts) or self.vocabulary
        self._frequency = counts
        return self

    def _known(self, words):
        return {word for word in words if word in self.vocabulary}

    def correct(self, word):
        word = word.lower()
        if word in self.vocabulary:
            return word
        candidates = self._known(_edits(word))
        if not candidates and self.max_distance >= 2:
            candidates = self._known(e for e1 in _edits(word) for e in _edits(e1))
        if not candidates:
            return word
        frequency = getattr(self, "_frequency", Counter())
        return max(candidates, key=lambda candidate: (frequency.get(candidate, 0), candidate))

    def correct_text(self, text):
        return " ".join(self.correct(word) for word in (text or "").split())


# Character n-gram profiles for language identification.
_LANGUAGE_SAMPLES = {
    "english": "the quick brown fox jumps over the lazy dog and then the cat runs away",
    "spanish": "el rápido zorro marrón salta sobre el perro perezoso y luego corre",
    "french": "le renard brun rapide saute par dessus le chien paresseux ensuite",
    "german": "der schnelle braune fuchs springt über den faulen hund dann",
}


class LanguageDetector:
    """Naive character n-gram language identification."""

    def __init__(self, n=3):
        self.n = n
        self.profiles = {lang: Counter(self._grams(text))
                         for lang, text in _LANGUAGE_SAMPLES.items()}

    def _grams(self, text):
        text = " " + re.sub(r"\s+", " ", (text or "").lower()).strip() + " "
        return [text[i:i + self.n] for i in range(len(text) - self.n + 1)]

    def detect(self, text):
        grams = self._grams(text)
        if not grams:
            return "unknown", 0.0
        scores = {}
        for lang, profile in self.profiles.items():
            total = sum(profile.values()) or 1
            score = 0.0
            for gram in grams:
                score += math.log((profile.get(gram, 0) + 0.5) / (total + 0.5 * len(profile)))
            scores[lang] = score / len(grams)
        best = max(scores, key=scores.get)
        # Convert to a rough confidence via softmax over the length-normalised scores.
        highest = scores[best]
        exps = {lang: math.exp(value - highest) for lang, value in scores.items()}
        return best, exps[best] / (sum(exps.values()) or 1.0)
