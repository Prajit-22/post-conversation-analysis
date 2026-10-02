# Post-Conversation Analysis System

A Django REST API that automatically analyzes customer support conversations
across seven NLP metrics — sentiment, empathy, clarity, relevance, accuracy,
completeness, and response time — with Celery orchestrating scheduled
background analysis and a Django admin dashboard for reviewing results.

## Features

- **Upload conversations** — POST a user/AI message sequence; all content is stored.
- **Seven analysis metrics** — every conversation is scored on clarity,
  relevance, accuracy, completeness, empathy, sentiment, and average response
  time, plus fallback detection, resolution status, and escalation flags.
- **On-demand and scheduled analysis** — trigger analysis through the API, or
  let Celery Beat process pending conversations every minute.
- **Reports API** — list and filter analyses by sentiment and resolution,
  ordered by overall score.
- **Admin dashboard** — manage conversations, messages, and analyses from
  Django admin.

## Stack

- **Backend:** Django 4.2, Django REST Framework
- **NLP:** TextBlob, NLTK (spaCy optional — the analyzer degrades gracefully)
- **Task queue:** Celery + django-celery-beat (Redis broker)
- **Database:** SQLite by default (swap to PostgreSQL via `DATABASES`)

## Project layout

```
analysis/                  Django app
  analyzers.py             Metric computation (pure functions, no DB access)
  models.py                Conversation, Message, ConversationAnalysis
  serializers.py           API serializers (`message` field maps to Message.text)
  views.py                 Conversation / analyse / reports endpoints
  tasks.py                 Celery tasks (single + scheduled batch analysis)
  tests.py                 18-test suite: analyzer contract, behavior, API, tasks
conversation_analyzer/     Django project (settings, celery app)
sample_data/               Example payload accepted verbatim by the API
```

## Quick start

```bash
git clone https://github.com/Prajit-22/post-conversation-analysis.git
cd post-conversation-analysis
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

python manage.py migrate
python manage.py runserver
```

Optional, for scheduled background analysis (requires Redis):

```bash
celery -A conversation_analyzer worker -l info      # terminal 2
celery -A conversation_analyzer beat -l info        # terminal 3
```

## API usage

Create a conversation (the file in `sample_data/` works as-is):

```bash
curl -X POST http://localhost:8000/api/conversations/ \
  -H 'Content-Type: application/json' \
  -d @sample_data/sample_conversation.json
```

Trigger analysis:

```bash
curl -X POST http://localhost:8000/api/analyse/ \
  -H 'Content-Type: application/json' \
  -d '{"conversation_id": 1}'
```

Browse reports (filterable by `sentiment` and `resolution`):

```bash
curl 'http://localhost:8000/api/reports/?sentiment=negative&ordering=-overall_score'
```

| Endpoint | Method | Purpose |
|---|---|---|
| `/api/conversations/` | GET, POST | List/create conversations with nested messages |
| `/api/analyse/` | POST | Run analysis for a `conversation_id` (idempotent) |
| `/api/reports/` | GET | Paginated, filterable analysis results |
| `/admin/` | — | Admin dashboard |

## Configuration

Environment variables (all optional for local development):

| Variable | Default | Purpose |
|---|---|---|
| `SECRET_KEY` | built-in dev key | Override in production |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/0` | Celery result backend |

## Running the tests

```bash
python manage.py test
```

The suite covers the analyzer contract (score ranges, key completeness),
metric behavior (positive, fallback-loop, and timestamped conversations),
edge cases (mixed timestamp formats, question detection),
every API endpoint, and both Celery tasks. Tests run without Redis or a
spaCy model installed.

## Notes

- The analyzer is rule-based and deterministic — no external model downloads
  are required. If `en_core_web_sm` is installed it can be plugged in without
  changing the public API.
- `avg_response_time` is computed from optional ISO-8601 `timestamp` fields
  on each message; without them it falls back to a demo default (5 seconds).
  Timestamps without a UTC offset are read as UTC, so naive and offset-aware
  values can appear in the same conversation.
- A user turn counts as a question if it contains `?` or a whole question word
  (`how`, `what`, `why`, `when`, `where`, `which`, `can you`, `could you`);
  words that merely contain one, like "show", do not.
