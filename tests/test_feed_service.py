"""
Tests for feed service boundary behavior.
"""

import pytest
from datetime import datetime, timedelta, timezone

from app import create_app, db
from models import User, Song, ListeningEvent
from services import feed_service


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def viewer_and_friend(app):
    with app.app_context():
        viewer = User(username="viewer", email="viewer@example.com")
        friend = User(username="friend", email="friend@example.com")
        db.session.add_all([viewer, friend])
        db.session.flush()

        viewer.friends.append(friend)

        song = Song(title="Recent Track", artist="Artist", shared_by=friend.id)
        db.session.add(song)
        db.session.commit()

        yield {"viewer": viewer, "friend": friend, "song": song}


def test_get_friends_listening_now_includes_boundary_event(app, viewer_and_friend, monkeypatch):
    """Events exactly at the threshold should be treated as recent."""
    with app.app_context():
        viewer = viewer_and_friend["viewer"]
        friend = viewer_and_friend["friend"]
        song = viewer_and_friend["song"]

        fixed_now = datetime(2024, 6, 10, 12, 0, 0, tzinfo=timezone.utc)

        class FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return fixed_now if tz is None else fixed_now.astimezone(tz)

        monkeypatch.setattr(feed_service, "datetime", FrozenDateTime)

        boundary_event = ListeningEvent(
            user_id=friend.id,
            song_id=song.id,
            listened_at=fixed_now - timedelta(hours=24),
        )
        old_event = ListeningEvent(
            user_id=friend.id,
            song_id=song.id,
            listened_at=fixed_now - timedelta(hours=24, seconds=1),
        )
        db.session.add_all([boundary_event, old_event])
        db.session.commit()

        feed = feed_service.get_friends_listening_now(viewer.id)
        assert len(feed) == 1
        assert feed[0]["song"]["title"] == "Recent Track"


def test_get_friends_listening_now_returns_empty_for_user_without_friends(app):
    """A user with no friends should get an empty feed rather than an error."""
    with app.app_context():
        viewer = User(username="solo", email="solo@example.com")
        db.session.add(viewer)
        db.session.commit()

        feed = feed_service.get_friends_listening_now(viewer.id)
        assert feed == []
