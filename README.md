# Post-Conversation Analysis Project

A Django REST API for automatic analysis of customer support conversations using NLP, sentiment, and clarity metrics. Powered by Celery for background processing and Redis/SQLite for scalable data storage.

## Features

- **Upload Conversations:** Add any user/AI message sequence, store all content.
- **Automated Analysis:** Background Celery worker analyzes all conversations for:
  - Sentiment, empathy, clarity, relevance, accuracy, completeness, response time
- **REST API Endpoints:** Easily create, analyze, and view all results.
- **Admin Dashboard:** View/manage all conversations and analysis.
- **Background Tasks:** Scheduled automatic analysis every minute (demo).

## Stack

- **Backend:** Django, Django REST Framework
- **NLP:** spaCy, NLTK, TextBlob
- **Task Queue:** Celery
- **Database:** SQLite (easy swap to PostgreSQL)
- **Broker:** Redis (for Celery beat/worker)

## Quick Start

1. **Clone the repo:**
