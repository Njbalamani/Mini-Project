import pytest
from django.contrib.auth import get_user_model


@pytest.fixture
def user(db):
    User = get_user_model()
    return User.objects.create_user(email="tester@example.com", password="test-pass-123")


@pytest.fixture
def other_user(db):
    User = get_user_model()
    return User.objects.create_user(email="other@example.com", password="test-pass-123")
