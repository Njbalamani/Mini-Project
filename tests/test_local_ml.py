"""Tests for the offline NLP/ML engine and the learning layer."""
from datetime import datetime, timezone

import pytest
from django.test import Client

from apps.ai_assistant.models import AIProviderConfiguration, AssistantTrainingExample, Conversation
from apps.ai_assistant.services import get_provider
from apps.ai_assistant.services.learning import (
    examples_for,
    learn_correction,
    learn_from_feedback,
)
from apps.ai_assistant.services.local_ml import (
    EnsembleClassifier,
    KMeans,
    KNNClassifier,
    LocalAssistant,
    LogisticRegressionClassifier,
    NaiveBayesClassifier,
    NGramLanguageModel,
    SentimentAnalyzer,
    TfidfVectorizer,
    TruncatedSVD,
    clean_title,
    cosine_similarity,
    extract_priority,
    jaro_winkler,
    parse_when,
    soundex,
    textrank_keywords,
    textrank_summary,
    tokenize,
)
from apps.ai_assistant.services.providers import LocalMLProvider

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 10, 20, 10, 0, tzinfo=timezone.utc)
ITEMS = [
    {"type": "task", "title": "Pay electricity bill", "due": "2026-10-21T09:00:00", "priority": "high", "done": False},
    {"type": "task", "title": "Buy groceries", "due": None, "priority": "medium", "done": False},
    {"type": "task", "title": "Submit quarterly report", "due": "2026-10-25T09:00:00", "priority": "urgent", "done": False},
    {"type": "event", "title": "Team standup", "start": "2026-10-21T09:00:00", "end": "2026-10-21T09:30:00", "location": "Zoom"},
]


# --- Preprocessing -----------------------------------------------------------
def test_tokenize_stems_and_drops_stopwords():
    tokens = tokenize("Creating the reports for my meetings")
    assert "create" in tokens or "creat" in tokens
    assert "report" in tokens
    assert "the" not in tokens and "my" not in tokens


def test_tfidf_cosine_prefers_related_documents():
    vectorizer = TfidfVectorizer()
    vectors = vectorizer.fit_transform(["pay the electricity bill", "buy groceries", "team meeting"])
    query = vectorizer.transform("electricity bill payment")
    assert cosine_similarity(query, vectors[0]) > cosine_similarity(query, vectors[2])


# --- Classifiers -------------------------------------------------------------
def _training():
    return [
        ("greeting", "hi there"), ("greeting", "hello"),
        ("create_task", "add a task to call mom"), ("create_task", "remind me to buy milk"),
        ("create_event", "schedule a meeting at 3pm"), ("list_tasks", "what are my tasks"),
    ]


def test_all_classifiers_predict_intent():
    samples = _training()
    for model in (NaiveBayesClassifier(), LogisticRegressionClassifier(epochs=150), KNNClassifier(k=3)):
        model.train(samples)
        label, confidence = model.predict("what tasks do i have")
        assert label == "list_tasks"
        assert 0.0 <= confidence <= 1.0


def test_ensemble_combines_classifiers():
    samples = _training()
    ensemble = EnsembleClassifier(
        [NaiveBayesClassifier(), LogisticRegressionClassifier(epochs=150), KNNClassifier(k=3)],
        [1.0, 1.2, 0.8],
    ).train(samples)
    label, confidence = ensemble.predict("book a meeting")
    assert label == "create_event"
    assert confidence > 0.5


# --- Dimensionality reduction & clustering -----------------------------------
def test_truncated_svd_semantic_similarity():
    svd = TruncatedSVD(n_components=3)
    embeddings = svd.fit_transform([
        "pay the electricity bill", "electric bill payment",
        "buy groceries milk eggs", "team meeting agenda",
    ])
    assert len(embeddings) == 4
    from apps.ai_assistant.services.local_ml import cosine_dense
    assert cosine_dense(embeddings[0], embeddings[1]) > cosine_dense(embeddings[0], embeddings[3])


def test_kmeans_clusters_similar_vectors():
    labels = KMeans(k=2, seed=1).fit([[0.0, 0.0], [0.1, 0.05], [10.0, 10.0], [10.1, 9.9]])
    assert labels[0] == labels[1]
    assert labels[2] == labels[3]
    assert labels[0] != labels[2]


# --- Language model ----------------------------------------------------------
def test_ngram_autocomplete_and_generation():
    model = NGramLanguageModel(order=2).train(["call mom tomorrow", "call dad later", "buy milk"])
    assert "mom" in model.autocomplete("call")
    generated = model.generate("call", 3)
    assert generated.startswith("call")


# --- TextRank & sentiment ----------------------------------------------------
def test_textrank_keywords_and_summary():
    text = ("The quarterly report is overdue. Submit the quarterly report by Friday. "
            "Buy groceries and milk. The report needs the sales data reviewed.")
    keywords = textrank_keywords(text, 5)
    assert "report" in keywords
    summary = textrank_summary(text, 2)
    assert 1 <= len(summary) <= 2
    assert any("report" in sentence.lower() for sentence in summary)


def test_sentiment_analyzer_with_negation():
    analyzer = SentimentAnalyzer()
    assert analyzer.score("this is great and perfect")["label"] == "positive"
    assert analyzer.score("terrible and late")["label"] == "negative"
    assert analyzer.score("not great at all")["polarity"] <= 0


# --- Fuzzy matching ----------------------------------------------------------
def test_fuzzy_matching_helpers():
    assert soundex("robert") == soundex("rupert")
    assert jaro_winkler("martha", "marhta") > 0.9
    assert jaro_winkler("abc", "xyz") == 0.0


# --- Entity extraction -------------------------------------------------------
def test_parse_when_extracts_date_and_time():
    info = parse_when("call mom tomorrow at 5pm", NOW)
    assert info.has_date and info.has_time
    assert info.start.hour == 17
    assert (info.start.date() - NOW.date()).days == 1


def test_priority_and_clean_title():
    when = parse_when("add a task to call mom tomorrow at 5pm", NOW)
    assert extract_priority("finish this urgent report") == "urgent"
    assert clean_title("add a task to call mom tomorrow at 5pm", when) == "call mom"


# --- Assistant orchestration -------------------------------------------------
def test_local_assistant_recognises_intents():
    assistant = LocalAssistant(NOW)
    assert assistant.respond("what are my tasks", ITEMS).intent == "list_tasks"
    assert assistant.respond("summarise my workspace", ITEMS).intent == "summarize"
    assert assistant.respond("extract keywords", ITEMS).intent == "keywords"
    assert assistant.respond("group my tasks", ITEMS).intent == "group"


def test_local_assistant_proposes_task_action():
    reply = LocalAssistant(NOW).respond("add a task to call mom tomorrow at 5pm", ITEMS)
    assert reply.actions and reply.actions[0]["type"] == "create_task"
    assert reply.actions[0]["payload"]["title"] == "call mom"


def test_local_assistant_learns_extra_examples():
    assistant = LocalAssistant(NOW, extra_examples=[("greeting", "yo yo custom phrase")])
    assert assistant.classify("yo yo custom phrase")[0] == "greeting"


# --- Provider wiring ---------------------------------------------------------
def test_get_provider_returns_local_ml_provider(user):
    AIProviderConfiguration.objects.create(user=user, provider="local")
    provider = get_provider(user)
    assert isinstance(provider, LocalMLProvider)
    assert provider.name == "local"


def test_local_provider_streams_and_sets_structured(user):
    conversation = Conversation.objects.create(owner=user, title="t")
    from apps.ai_assistant.models import Message
    Message.objects.create(conversation=conversation, role=Message.Role.USER,
                           content="add a task to call mom")
    provider = LocalMLProvider(user=user)
    history = [{"role": "user", "content": "add a task to call mom"}]
    text = "".join(provider.stream_chunks(history))
    assert text
    assert provider.last_structured["actions"][0]["type"] == "create_task"


def test_send_message_with_local_provider_responds(user):
    AIProviderConfiguration.objects.create(user=user, provider="local")
    conversation = Conversation.objects.create(owner=user, title="New conversation")
    client = Client()
    client.force_login(user)
    response = client.post(f"/assistant/c/{conversation.pk}/send/", {"message": "add a task to call mom"})
    payload = response.json()
    assert payload["ok"] is True
    assert payload["assistant_message"]["content"]
    assert payload["assistant_message"]["actions"][0]["type"] == "create_task"


# --- Learning layer ----------------------------------------------------------
def test_learn_from_feedback_creates_examples(user):
    from apps.ai_assistant.models import Message
    conversation = Conversation.objects.create(owner=user, title="t")
    user_message = Message.objects.create(conversation=conversation, role=Message.Role.USER,
                                          content="what are my tasks")
    assistant_message = Message.objects.create(conversation=conversation, role=Message.Role.ASSISTANT,
                                               content="You have none")
    learn_from_feedback(assistant_message, 1)
    assert AssistantTrainingExample.objects.filter(user=user, text="what are my tasks").exists()
    assert examples_for(user)


def test_learn_correction_teaches_intent(user):
    learn_correction(user, "yo custom phrase xyz", "greeting")
    examples = examples_for(user)
    assert ("greeting", "yo custom phrase xyz") in examples


# --- New endpoints -----------------------------------------------------------
def test_insights_and_autocomplete_endpoints(user):
    AIProviderConfiguration.objects.create(user=user, provider="local")
    client = Client()
    client.force_login(user)
    assert client.get("/assistant/insights/").status_code == 200
    response = client.get("/assistant/autocomplete/?q=call")
    assert response.status_code == 200
    assert response.json()["ok"] is True
