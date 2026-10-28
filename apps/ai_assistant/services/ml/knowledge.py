"""Offline retrieval-augmented knowledge base.

The assistant uses this to answer general ("world knowledge") questions without
a network call: the question is matched against a curated corpus of facts using
TF-IDF + cosine similarity, and the best passage is returned as the answer when
the match is confident enough. A tiny safe arithmetic evaluator is included so
maths questions are handled exactly.
"""
from __future__ import annotations

import ast
import math
import operator
import re

from .features import TfidfFeatureExtractor

FACTS = [
    {"title": "Capital of Peru", "text": "The capital of Peru is Lima (Lima is the capital and largest city of Peru).",
     "tags": "peru lima capital country south america"},
    {"title": "Capital of France", "text": "The capital of France is Paris.",
     "tags": "france paris capital country europe"},
    {"title": "Capital of Japan", "text": "The capital of Japan is Tokyo.",
     "tags": "japan tokyo capital country asia"},
    {"title": "Capital of India", "text": "The capital of India is New Delhi.",
     "tags": "india new delhi capital country asia"},
    {"title": "Capital of Australia", "text": "The capital of Australia is Canberra (not Sydney or Melbourne).",
     "tags": "australia canberra capital country oceania"},
    {"title": "Capital of the United States", "text": "The capital of the United States is Washington, D.C.",
     "tags": "usa united states america washington dc capital country"},
    {"title": "Capital of the United Kingdom", "text": "The capital of the United Kingdom is London.",
     "tags": "uk united kingdom britain london capital europe"},
    {"title": "Capital of Canada", "text": "The capital of Canada is Ottawa.",
     "tags": "canada ottawa capital country"},
    {"title": "Capital of Brazil", "text": "The capital of Brazil is Brasilia.",
     "tags": "brazil brasilia capital country south america"},
    {"title": "Capital of Egypt", "text": "The capital of Egypt is Cairo.",
     "tags": "egypt cairo capital country africa"},
    {"title": "Largest planet", "text": "Jupiter is the largest planet in the Solar System.",
     "tags": "largest planet solar system astronomy jupiter space"},
    {"title": "Closest planet to the Sun", "text": "Mercury is the closest planet to the Sun.",
     "tags": "closest planet sun mercury astronomy space"},
    {"title": "The Sun", "text": "The Sun is a star at the centre of the Solar System; it provides light and heat to Earth.",
     "tags": "sun star solar system astronomy"},
    {"title": "The Moon", "text": "The Moon is Earth's only natural satellite.",
     "tags": "moon earth satellite astronomy space"},
    {"title": "Water chemical formula", "text": "Water's chemical formula is H2O: two hydrogen atoms bonded to one oxygen atom.",
     "tags": "water h2o chemistry formula molecule science"},
    {"title": "Speed of light", "text": "The speed of light in a vacuum is about 299,792,458 metres per second (roughly 300,000 km/s).",
     "tags": "speed of light physics constant c"},
    {"title": "Photosynthesis", "text": "Photosynthesis is the process by which green plants use sunlight, water and carbon dioxide to make glucose and oxygen.",
     "tags": "photosynthesis plants biology sunlight oxygen chlorophyll science"},
    {"title": "Gravity", "text": "Gravity is the force by which objects with mass attract one another; on Earth it accelerates objects at about 9.8 m/s^2.",
     "tags": "gravity physics force mass newton science"},
    {"title": "DNA", "text": "DNA (deoxyribonucleic acid) is the molecule that carries the genetic instructions used in the growth and functioning of all known living organisms.",
     "tags": "dna genetics biology molecule heredity science"},
    {"title": "Atoms", "text": "An atom is the smallest unit of ordinary matter; it consists of a nucleus of protons and neutrons surrounded by electrons.",
     "tags": "atom physics chemistry nucleus electron proton neutron science"},
    {"title": "Human heart", "text": "The human heart is a muscular organ that pumps blood through the circulatory system, beating roughly 60-100 times per minute at rest.",
     "tags": "heart human body anatomy biology blood"},
    {"title": "Quantum entanglement", "text": "Quantum entanglement is a phenomenon in which two or more particles become correlated so that measuring one instantly affects the state of the other, regardless of distance. Einstein called it 'spooky action at a distance'.",
     "tags": "quantum entanglement physics einstein spooky particles"},
    {"title": "Artificial intelligence", "text": "Artificial intelligence (AI) is the field of computer science that builds systems able to perform tasks that normally require human intelligence, such as learning, reasoning and perception.",
     "tags": "artificial intelligence ai machine learning computer science"},
    {"title": "Machine learning", "text": "Machine learning is a branch of AI in which algorithms improve their performance on a task by learning patterns from data rather than being explicitly programmed.",
     "tags": "machine learning ml ai data algorithms"},
    {"title": "Neural networks", "text": "An artificial neural network is a computing system loosely inspired by biological neurons, composed of layers of connected units that learn weights to map inputs to outputs.",
     "tags": "neural network deep learning ai neurons"},
    {"title": "The Internet", "text": "The Internet is a global network of interconnected computer networks that communicate using the Internet Protocol (IP).",
     "tags": "internet network computers protocol technology"},
    {"title": "World Wide Web", "text": "The World Wide Web is an information system of interlinked hypertext documents accessed via the Internet using browsers and HTTP.",
     "tags": "world wide web www internet hypertext http technology"},
    {"title": "Python programming language", "text": "Python is a high-level, interpreted programming language known for readable syntax; it is widely used in data science, web development and automation.",
     "tags": "python programming language code software"},
    {"title": "HTML", "text": "HTML (HyperText Markup Language) is the standard language for creating web pages, describing their structure with elements and tags.",
     "tags": "html web markup language code"},
    {"title": "HTTP", "text": "HTTP (HyperText Transfer Protocol) is the application-layer protocol used to transfer web pages and data over the Internet.",
     "tags": "http protocol web network"},
    {"title": "Database", "text": "A database is an organised collection of structured data, typically managed by a database management system (DBMS) such as PostgreSQL or SQLite.",
     "tags": "database sql data dbms storage"},
    {"title": "World War II", "text": "World War II was a global conflict from 1939 to 1945 involving most of the world's nations, ending with the defeat of Nazi Germany and Imperial Japan.",
     "tags": "world war 2 ii history 1939 1945 conflict"},
    {"title": "First Moon landing", "text": "The first crewed Moon landing was Apollo 11 in July 1969; Neil Armstrong became the first person to walk on the Moon.",
     "tags": "apollo 11 moon landing 1969 neil armstrong history space"},
    {"title": "The Renaissance", "text": "The Renaissance was a period of European cultural, artistic and intellectual 'rebirth' spanning roughly the 14th to 17th centuries.",
     "tags": "renaissance history europe art culture rebirth"},
    {"title": "Why is the sky blue", "text": "The sky looks blue because air molecules scatter short (blue) wavelengths of sunlight more than long wavelengths, a phenomenon called Rayleigh scattering.",
     "tags": "sky blue rayleigh scattering light physics"},
    {"title": "Why do we dream", "text": "Dreaming occurs mainly during REM sleep; theories suggest it helps memory consolidation, emotional processing and problem solving, though no single explanation is settled.",
     "tags": "dream sleep rem brain psychology"},
    {"title": "How does a rainbow form", "text": "A rainbow forms when sunlight enters water droplets, refracts, reflects internally and disperses into colours, appearing opposite the Sun.",
     "tags": "rainbow light water refraction dispersion physics"},
    {"title": "Largest ocean", "text": "The Pacific Ocean is the largest and deepest ocean on Earth.",
     "tags": "largest ocean pacific geography water"},
    {"title": "Highest mountain", "text": "Mount Everest is the highest mountain above sea level, at about 8,849 metres.",
     "tags": "highest mountain everest geography himalaya"},
    {"title": "Longest river", "text": "The Nile is traditionally regarded as the longest river, though the Amazon is the largest by discharge; their lengths are close.",
     "tags": "longest river nile amazon geography"},
    {"title": "Largest desert", "text": "Antarctica is the largest desert on Earth; the largest hot desert is the Sahara.",
     "tags": "largest desert antarctica sahara geography"},
    {"title": "Number of continents", "text": "There are seven continents: Africa, Antarctica, Asia, Europe, North America, Oceania (Australia) and South America.",
     "tags": "continents seven geography world"},
    {"title": "Number of planets", "text": "There are eight planets in the Solar System: Mercury, Venus, Earth, Mars, Jupiter, Saturn, Uranus and Neptune.",
     "tags": "planets eight solar system astronomy"},
    {"title": "Pi", "text": "Pi (π) is the ratio of a circle's circumference to its diameter, approximately 3.14159.",
     "tags": "pi circle mathematics constant geometry"},
    {"title": "Pythagorean theorem", "text": "The Pythagorean theorem states that in a right triangle, a^2 + b^2 = c^2, where c is the hypotenuse.",
     "tags": "pythagorean theorem mathematics triangle geometry"},
    {"title": "Prime number", "text": "A prime number is a natural number greater than 1 with no positive divisors other than 1 and itself, e.g. 2, 3, 5, 7, 11.",
     "tags": "prime number mathematics math"},
    {"title": "Meaning of life", "text": "That is a famously open philosophical question; answers range across science, ethics and personal values rather than a single fact.",
     "tags": "meaning of life philosophy"},
    {"title": "How to stay healthy", "text": "Common evidence-based advice: eat a balanced diet, exercise regularly, sleep 7-9 hours, stay hydrated, avoid smoking and manage stress.",
     "tags": "health healthy diet exercise sleep wellness"},
    {"title": "How to learn faster", "text": "Active recall, spaced repetition, interleaving and teaching others are well-supported techniques for faster, durable learning.",
     "tags": "learn faster study memory spaced repetition productivity"},
    {"title": "Time management", "text": "Prioritise by importance and urgency, break work into small tasks, time-box focus sessions and review progress regularly.",
     "tags": "time management productivity prioritise focus tasks"},
    {"title": "What is a todo list", "text": "A to-do list is a simple list of tasks to complete, often prioritised, that helps track and organise work.",
     "tags": "todo to-do list tasks productivity"},
    {"title": "Definition of entropy", "text": "Entropy is a measure of disorder or the number of microscopic configurations of a system; the second law of thermodynamics says it tends to increase.",
     "tags": "entropy thermodynamics physics disorder"},
    {"title": "Black holes", "text": "A black hole is a region of spacetime where gravity is so strong that nothing, not even light, can escape once past the event horizon.",
     "tags": "black hole gravity spacetime astronomy physics"},
    {"title": "Evolution", "text": "Evolution is the change in inherited characteristics of biological populations over successive generations, driven largely by natural selection.",
     "tags": "evolution biology darwin natural selection science"},
    {"title": "Vaccines", "text": "Vaccines train the immune system to recognise and fight a pathogen by exposing it to a harmless form of the pathogen or its instructions.",
     "tags": "vaccine immunity biology medicine health"},
    {"title": "Global warming", "text": "Global warming is the long-term heating of Earth's climate driven mainly by human emissions of greenhouse gases such as carbon dioxide and methane.",
     "tags": "global warming climate change greenhouse gases environment"},
    {"title": "Renewable energy", "text": "Renewable energy comes from naturally replenished sources such as sunlight, wind, water, geothermal heat and biomass.",
     "tags": "renewable energy solar wind environment sustainability"},
    {"title": "What is the stock market", "text": "The stock market is a marketplace where shares of publicly traded companies are bought and sold, enabling companies to raise capital and investors to own equity.",
     "tags": "stock market shares investing equity finance"},
    {"title": "Inflation", "text": "Inflation is the rate at which the general level of prices for goods and services rises, reducing purchasing power over time.",
     "tags": "inflation economics prices money finance"},
    {"title": "Gross domestic product", "text": "Gross Domestic Product (GDP) is the total monetary value of all finished goods and services produced within a country in a given period.",
     "tags": "gdp gross domestic product economics finance"},
    {"title": "What is democracy", "text": "Democracy is a system of government in which power is vested in the people, who rule directly or through elected representatives.",
     "tags": "democracy government politics people elections"},
    {"title": "Photosynthesis equation", "text": "6 CO2 + 6 H2O + light energy -> C6H12O6 (glucose) + 6 O2 summarises photosynthesis.",
     "tags": "photosynthesis equation chemistry biology"},
    {"title": "Nervous system", "text": "The nervous system is the network of neurons that transmits signals between parts of the body, including the brain, spinal cord and peripheral nerves.",
     "tags": "nervous system neurons brain biology anatomy"},
    {"title": "How does a computer work", "text": "A computer executes instructions from memory using a CPU that performs arithmetic and logic, with data stored in memory and moved via a bus.",
     "tags": "computer cpu memory instructions technology hardware"},
    {"title": "Encryption", "text": "Encryption transforms readable data (plaintext) into an unreadable form (ciphertext) using a key, so only authorised parties can decrypt it.",
     "tags": "encryption cryptography security plaintext ciphertext"},
    {"title": "How does WiFi work", "text": "WiFi transmits data over radio waves between devices and a wireless access point using standards in the IEEE 802.11 family.",
     "tags": "wifi wireless radio network ieee technology"},
    {"title": "Sunk cost", "text": "A sunk cost is money or effort already spent that cannot be recovered; sound decisions should ignore sunk costs and consider only future costs and benefits.",
     "tags": "sunk cost economics decision psychology"},
    {"title": "Compound interest", "text": "Compound interest is interest calculated on both the initial principal and the accumulated interest, so savings or debts grow faster over time.",
     "tags": "compound interest finance math money"},
]


_WORD_RE = re.compile(r"[a-z0-9]+")


class KnowledgeBase:
    """TF-IDF retriever over a corpus of factual passages."""

    def __init__(self, facts=None, threshold=0.25):
        self.facts = list(facts if facts is not None else FACTS)
        self.threshold = threshold
        self.extractor = TfidfFeatureExtractor(ngram_range=(1, 2))
        self._documents = [f"{fact['title']} {fact['text']} {fact.get('tags', '')}"
                           for fact in self.facts]
        self.extractor.fit(self._documents)
        self._vectors = [self.extractor.transform(document) for document in self._documents]

    def search(self, question, top_k=3):
        query = self.extractor.transform(question)
        scored = []
        for fact, vector in zip(self.facts, self._vectors):
            score = sum(q * v for q, v in zip(query, vector))
            scored.append((score, fact))
        scored.sort(key=lambda pair: pair[0], reverse=True)
        return scored[:top_k]

    def answer(self, question, threshold=None):
        scatter = threshold if threshold is not None else self.threshold
        matches = self.search(question, top_k=1)
        if not matches:
            return None
        score, fact = matches[0]
        if score < scatter:
            return None
        return {"answer": fact["text"], "title": fact["title"], "score": score,
                "tags": fact.get("tags", "")}


_ALLOWED_OPERATORS = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
    ast.FloorDiv: operator.floordiv, ast.USub: operator.neg, ast.UAdd: operator.pos,
}


def _eval_node(node):
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError("constant not numeric")
    if isinstance(node, ast.BinOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](_eval_node(node.left), _eval_node(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in _ALLOWED_OPERATORS:
        return _ALLOWED_OPERATORS[type(node.op)](_eval_node(node.operand))
    raise ValueError("unsupported expression")


def evaluate_math(expression: str):
    """Safely evaluate an arithmetic expression; return float or ``None``.

    Only numbers and the operators + - * / ** % // are permitted, so arbitrary
    code cannot be executed.
    """
    cleaned = (expression or "").lower()
    cleaned = cleaned.replace("^", "**").replace("×", "*").replace("÷", "/")
    root = re.search(r"(square root|sqrt|cube root|cbrt)\s*(?:of\s*)?(\d+(?:\.\d+)?)", cleaned)
    if root:
        value = float(root.group(2))
        if "cube" in root.group(1) or "cbrt" in root.group(1):
            return round(value ** (1.0 / 3.0), 10)
        return math.sqrt(value)
    cleaned = re.sub(r"\b(to the power of|raised to|to the|power of)\b", "**", cleaned)
    cleaned = re.sub(r"\b(divided by|over)\b", "/", cleaned)
    cleaned = re.sub(r"\b(multiplied by|times)\b", "*", cleaned)
    cleaned = re.sub(r"\bplus\b", "+", cleaned)
    cleaned = re.sub(r"\b(minus|less)\b", "-", cleaned)
    cleaned = re.sub(r"\b(mod|modulo)\b", "%", cleaned)
    cleaned = re.sub(r"\b(what|is|are|the|value|of|calculate|compute|equals?|please|"
                     r"result|answer|how|much|many)\b", "", cleaned)
    cleaned = re.sub(r"[?]", "", cleaned)
    cleaned = cleaned.strip()
    if not re.search(r"\d", cleaned):
        return None
    if not re.fullmatch(r"[\d\s+\-*/().%]+", cleaned):
        return None
    try:
        tree = ast.parse(cleaned.strip(), mode="eval")
    except SyntaxError:
        return None
    try:
        value = _eval_node(tree.body)
    except (ValueError, ZeroDivisionError, OverflowError):
        return None
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value
