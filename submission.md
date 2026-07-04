# Codebase Map

## AI usage
I used AI primarily to explain unfamiliar code paths after I had already identified the relevant modules, rather than to guess the root cause from scratch. For example, I asked for help understanding the streak boundary logic and the difference between weekday() and isoweekday(), which confirmed the direction of the investigation before I verified it directly in the code and tests.

## Overview
Mixtape is a Flask + SQLAlchemy app for sharing songs, building collaborative playlists, tracking listening activity, and sending notifications between friends. The app is organized around a small Flask app factory in app.py, SQLAlchemy models in models.py, route blueprints in routes/, and business logic in services/.

## Main files and what they do

- app.py
  - Creates the Flask application with create_app().
  - Configures the SQLite database URI, secret key, and SQLAlchemy settings.
  - Registers the song, playlist, user, and feed blueprints.
  - Calls db.create_all() inside the app context so tables are created when the app starts.

- models.py
  - Defines the core database entities: User, Song, ListeningEvent, Rating, Playlist, Notification, and supporting association tables.
  - Implements the relationships that connect users to songs, playlists, ratings, notifications, and friendships.
  - Stores timestamps in UTC and uses UUIDs for entity IDs.

- routes/songs.py
  - Handles song-related endpoints: searching, retrieving a song, rating a song, and recording listens.
  - Keeps request parsing and JSON responses in the route layer and delegates the actual behavior to service functions.

- routes/playlists.py
  - Handles playlist creation, playlist detail lookup, playlist song listing, and adding songs to playlists.
  - Delegates playlist behavior to the playlist and notification services.

- routes/users.py
  - Exposes user profile lookup, streak retrieval, notification listing, and notification read/unread behavior.

- routes/feed.py
  - Exposes the feed endpoints for “Friends Listening Now” and the general activity feed.

- services/streak_service.py
  - Implements listening streak rules for users.
  - Updates streaks based on consecutive calendar-day listening behavior and resets when a day is skipped.

- services/feed_service.py
  - Retrieves recent listening activity from a user’s friends.
  - Returns both the “listening now” feed and a broader activity feed.

- services/search_service.py
  - Searches songs by title or artist and returns song dictionaries with associated tags.

- services/notification_service.py
  - Creates and retrieves notifications.
  - Handles notification behavior when a friend adds a song to a playlist and when a song is rated.

- services/playlist_service.py
  - Creates playlists and returns playlists and their songs in order.

- seed_data.py
  - Populates the database with sample users, songs, playlists, listening events, and notifications for testing and local exploration.

- tests/
  - Contains regression tests for streak logic, search behavior, and playlist song ordering.

## Example data flow: adding a song to a playlist
A concrete feature path looks like this:

1. A client sends a POST request to /playlists/<playlist_id>/songs.
2. routes/playlists.py reads the request JSON, extracts song_id and added_by, and calls add_to_playlist(...).
3. services/notification_service.py loads the song, playlist, and user.
4. If the song is not already in the playlist, it appends it to the playlist.
5. If the song’s original sharer is not the same person who added it, the service creates a Notification record for the sharer.
6. The route returns a JSON success response.

This path demonstrates the app’s main pattern: the route layer handles HTTP concerns, while the service layer handles the actual business logic and database updates.

## Patterns I noticed

- Thin routes, rich services
  - Route files mostly parse input, call a service, and format JSON output.
  - Business rules live in services/.

- Database-oriented domain model
  - The relational model is central to the system, with many features driven by joins, associations, and timestamps.

- Explicit ordering and state tracking
  - Playlists use a join table with a position column to preserve song order.
  - Listening streaks and notifications are both stateful features that depend on timestamps.

- Test-driven bug hunting focus
  - The existing tests target the likely issue areas directly: streak updates, duplicate search results, and playlist song retrieval.

## Open issue areas noted from the project brief
The README identifies five issue areas that will guide the next milestone:

- Streak reset logic in services/streak_service.py
- Friends Listening Now filtering in services/feed_service.py
- Duplicate search results in services/search_service.py
- Missing rating notifications in services/notification_service.py
- Missing last-song retrieval in services/playlist_service.py

## Reproduction steps and root cause analysis
I verified the current behavior by running pytest -q from the project root. The run reported 3 failing tests and 10 passing tests, which gave me concrete repro paths for three of the issues.

### Issue #1 — Sunday streak reset
1. Issue number and title
   - Issue #1: My listening streak keeps resetting
2. How you reproduced it
   - I created a fresh user in an in-memory SQLite database and called update_listening_streak(...) twice: once with a Saturday timestamp and once with a Sunday timestamp. The streak stayed at 1 instead of increasing to 2.
3. How you found the root cause
   - I followed the flow from the test entry point into services/streak_service.py. The route layer calls record_listening_event(...) in routes/songs.py, which then calls update_listening_streak(...). I inspected that function directly and found the Sunday-specific condition in the one-day-gap branch.
4. The root cause
   - The streak logic treated Sunday as a special case that blocked an increment when the user listened on consecutive days. The condition `days_since_last == 1 and today.weekday() != 6` prevented the streak from increasing when the current day was Sunday, even though Saturday -> Sunday is a valid consecutive-day progression.
5. Your fix and side-effect check
   - I removed the Sunday-only exclusion so a one-day gap always increments the streak, while larger gaps still reset it. I re-ran the streak tests and confirmed the Sunday case now passes without breaking the other streak scenarios.

### Issue #3 — duplicate search results
1. Issue number and title
   - Issue #3: The same song keeps showing up twice in search
2. How you reproduced it
   - I seeded a song with multiple tags and searched for a term that matched the song title. The same song appeared once for each tag association in the join table.
3. How you found the root cause
   - I traced the request from routes/songs.py into services/search_service.py. The search endpoint calls search_songs(query), and the suspicious logic was in the query construction there. The join to song_tags caused one row per tag to be returned, which made the symptom obvious.
4. The root cause
   - The database query joined the song_tags association table without deduplicating rows. When a song had multiple tag rows, it was returned multiple times in the result set.
5. Your fix and side-effect check
   - I removed the unnecessary join and used distinct(Song.id) so each song is returned once even when it has many tags. I verified the search tests and confirmed the duplicate-song cases now pass without affecting other search results.

### Issue #5 — last song missing from playlist results
1. Issue number and title
   - Issue #5: The last song in a playlist never shows up
2. How you reproduced it
   - I created a playlist with five songs in positions 1 through 5 and called get_playlist_songs(playlist_id). The endpoint returned only four songs, with the last one omitted.
3. How you found the root cause
   - I traced the request from routes/playlists.py into services/playlist_service.py. The route calls get_playlist_songs(...), and the bug was in that service function’s return statement.
4. The root cause
   - The function sliced the query result with songs[:-1], which removed the final item from the playlist result set even when the database contained it.
5. Your fix and side-effect check
   - I removed the slice so the full ordered query result is returned. I re-ran the playlist tests and confirmed the full playlist now comes back in the correct order.
