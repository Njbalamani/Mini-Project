"""NexaMind's dependency-free machine-learning toolkit.

A small, numpy-free re-implementation of the parts of the classic ML toolkit
the assistant needs: feature extraction, supervised models, evaluation metrics,
probability calibration, word embeddings, sequence labelling and a retrieval-
augmented knowledge base.
"""
from .calibration import TemperatureScaler
from .embeddings import RandomProjectionLSH, WordVectors
from .features import (
    CharNGramVectorizer,
    FeatureExtractor,
    FeatureUnion,
    HashingFeatureExtractor,
    TfidfFeatureExtractor,
    char_ngrams,
    word_ngrams,
    word_tokens,
)
from .knowledge import FACTS, KnowledgeBase, evaluate_math
from .metrics import (
    accuracy,
    classification_report,
    confusion_matrix,
    cross_val_predict,
    cross_val_score,
    precision_recall_f1,
    roc_auc_binary,
    stratified_folds,
    train_test_split,
)
from .models import (
    DecisionTreeClassifier,
    GradientBoostingClassifier,
    KNNClassifier,
    LinearSVM,
    MLPClassifier,
    MultinomialNB,
    PerceptronClassifier,
    RandomForestClassifier,
    RegressionTree,
    SoftmaxRegression,
    StackingEnsemble,
    VotingEnsemble,
)
from .pipeline import (
    TextClassifier,
    build_intent_classifier,
    default_intent_models,
    fast_intent_models,
)
from .registry import load_model, save_model
from .sequence import LanguageDetector, NERTagger, POSTagger, SpellCorrector

__all__ = [
    "TemperatureScaler",
    "WordVectors",
    "RandomProjectionLSH",
    "FeatureExtractor",
    "TfidfFeatureExtractor",
    "HashingFeatureExtractor",
    "FeatureUnion",
    "CharNGramVectorizer",
    "word_tokens",
    "word_ngrams",
    "char_ngrams",
    "KnowledgeBase",
    "FACTS",
    "evaluate_math",
    "accuracy",
    "classification_report",
    "confusion_matrix",
    "cross_val_predict",
    "cross_val_score",
    "precision_recall_f1",
    "roc_auc_binary",
    "stratified_folds",
    "train_test_split",
    "DecisionTreeClassifier",
    "GradientBoostingClassifier",
    "KNNClassifier",
    "LinearSVM",
    "MLPClassifier",
    "MultinomialNB",
    "PerceptronClassifier",
    "RandomForestClassifier",
    "RegressionTree",
    "SoftmaxRegression",
    "StackingEnsemble",
    "VotingEnsemble",
    "TextClassifier",
    "build_intent_classifier",
    "default_intent_models",
    "fast_intent_models",
    "save_model",
    "load_model",
    "POSTagger",
    "NERTagger",
    "SpellCorrector",
    "LanguageDetector",
]
