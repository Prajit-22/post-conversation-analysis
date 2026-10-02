"""Rule-based NLP analyzers for customer support conversations.

Every metric returns a float in [0.0, 1.0] except ``sentiment_score``
([-1.0, 1.0]) and ``avg_response_time`` (seconds). The public entry point is
:func:`analyze_conversation`, which expects a list of message dicts with at
least ``sender`` ("user" or "ai") and ``message`` keys. Optional ISO-8601
``timestamp`` values enable response-time measurement.

Heavy NLP stacks (spaCy) are optional: the module degrades to TextBlob +
NLTK + regex heuristics so it runs from a plain ``requirements.txt``
install and in CI.
"""

import re
from datetime import datetime, timezone
from typing import Dict, List, Optional

from textblob import TextBlob

try:
    import nltk
    try:
        nltk.data.find('tokenizers/punkt')
    except LookupError:
        nltk.download('punkt', quiet=True)
except ImportError:  # pragma: no cover - nltk is in requirements.txt
    nltk = None

try:
    import spacy
except ImportError:
    spacy = None
    nlp = None
else:
    try:
        nlp = spacy.load('en_core_web_sm')
    except OSError:
        # Model not downloaded; fall back to the heuristic pipeline.
        nlp = None

_WORD_RE = re.compile(r"[a-z']+")

STOPWORDS = {
    'a', 'an', 'the', 'is', 'it', 'its', 'i', 'me', 'my', 'we', 'you',
    'your', 'and', 'or', 'to', 'of', 'in', 'on', 'for', 'with', 'can',
    'could', 'please', 'hi', 'hello', 'thanks', 'thank', 'do', 'does',
}

FALLBACK_PATTERNS = [
    "i don't understand", "i do not understand", "didn't understand",
    "could you rephrase", "can you rephrase", "please rephrase",
    "i'm not sure", "i am not sure", "i don't know", "i do not know",
    "cannot help", "can't help", "unable to help", "try again later",
]

EMPATHY_PATTERNS = [
    "i understand", "i'm sorry", "i am sorry", "sorry to hear",
    "apologize", "apologies", "i can imagine", "that sounds frustrating",
    "i'm here to help", "i am here to help",
]

HEDGE_PATTERNS = ["i think", "maybe", "perhaps", "probably", "not sure", "might be"]

# Question words must match whole words: a bare substring test treats "show"
# as "how" and "whenever" as "when", counting statements as unanswered questions.
_QUESTION_RE = re.compile(
    r"\b(?:how|what|why|when|where|which|can you|could you)\b"
)


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def get_ai_messages(messages: List[Dict]) -> List[str]:
    return [msg['message'] for msg in messages if msg.get('sender') == 'ai']


def get_user_messages(messages: List[Dict]) -> List[str]:
    return [msg['message'] for msg in messages if msg.get('sender') == 'user']


def _content_words(text: str) -> set:
    return {w for w in _WORD_RE.findall(text.lower()) if w not in STOPWORDS and len(w) > 2}


def _split_sentences(text: str) -> List[str]:
    parts = re.split(r'[.!?]+', text)
    return [p.strip() for p in parts if p.strip()]


def _sentiment(messages: List[str]) -> (str, float):
    if not messages:
        return 'neutral', 0.0
    polarity = sum(TextBlob(m).sentiment.polarity for m in messages) / len(messages)
    if polarity > 0.1:
        return 'positive', round(polarity, 3)
    if polarity < -0.1:
        return 'negative', round(polarity, 3)
    return 'neutral', round(polarity, 3)


def _clarity(ai_messages: List[str]) -> float:
    """Reward medium-length sentences; penalize walls of text and fragments."""
    if not ai_messages:
        return 0.5
    scores = []
    for msg in ai_messages:
        sentences = _split_sentences(msg) or [msg]
        lengths = [len(s.split()) for s in sentences]
        avg = sum(lengths) / len(lengths)
        score = 1.0
        if avg > 25:
            score -= min(0.5, (avg - 25) * 0.03)
        elif avg < 3:
            score -= 0.2
        long_sentences = sum(1 for l in lengths if l > 40)
        score -= 0.1 * long_sentences
        scores.append(_clamp(score))
    return round(sum(scores) / len(scores), 3)


def _relevance(messages: List[Dict]) -> float:
    """Word-overlap between each user turn and the AI turn that follows it."""
    pairs = 0
    total = 0.0
    for i, msg in enumerate(messages):
        if msg.get('sender') != 'user':
            continue
        nxt = messages[i + 1] if i + 1 < len(messages) else None
        if not nxt or nxt.get('sender') != 'ai':
            continue
        user_words = _content_words(msg['message'])
        ai_words = _content_words(nxt['message'])
        if not user_words or not ai_words:
            continue
        overlap = len(user_words & ai_words) / len(user_words)
        total += min(1.0, 0.4 + overlap)  # a direct echo is not required to be relevant
        pairs += 1
    if pairs == 0:
        return 0.5
    return round(_clamp(total / pairs), 3)


def _accuracy(ai_messages: List[str], fallback_count: int) -> float:
    """Proxy for confident, grounded answers: penalize hedging and fallbacks."""
    if not ai_messages:
        return 0.5
    hedges = sum(
        1 for msg in ai_messages for pat in HEDGE_PATTERNS if pat in msg.lower()
    )
    score = 1.0 - 0.1 * hedges - 0.15 * fallback_count
    return round(_clamp(score), 3)


def _completeness(messages: List[Dict], fallback_count: int) -> float:
    """Fraction of user questions/requests that received a substantive answer."""
    asked = 0
    answered = 0
    for i, msg in enumerate(messages):
        if msg.get('sender') != 'user':
            continue
        text = msg['message'].lower()
        is_question = '?' in text or bool(_QUESTION_RE.search(text))
        if not is_question:
            continue
        asked += 1
        nxt = messages[i + 1] if i + 1 < len(messages) else None
        if nxt and nxt.get('sender') == 'ai':
            reply = nxt['message'].lower()
            substantive = len(reply.split()) >= 5 and not any(p in reply for p in FALLBACK_PATTERNS)
            if substantive:
                answered += 1
    if asked == 0:
        return 0.8 if fallback_count == 0 else 0.5
    return round(_clamp(answered / asked), 3)


def _empathy(messages: List[Dict], user_sentiment_score: float) -> float:
    ai_text = ' '.join(get_ai_messages(messages)).lower()
    empathy_hits = sum(1 for pat in EMPATHY_PATTERNS if pat in ai_text)
    if user_sentiment_score < -0.1:
        # Upset user: empathy matters most here.
        return round(_clamp(0.3 + 0.35 * empathy_hits), 3)
    return round(_clamp(0.6 + 0.2 * empathy_hits), 3)


def _fallback_count(ai_messages: List[str]) -> int:
    return sum(
        1 for msg in ai_messages
        if any(pat in msg.lower() for pat in FALLBACK_PATTERNS)
    )


def _avg_response_time(messages: List[Dict]) -> float:
    """Mean seconds from a user turn to the next AI turn, when ISO timestamps exist."""
    def parse(ts: str) -> Optional[datetime]:
        try:
            parsed = datetime.fromisoformat(str(ts).replace('Z', '+00:00'))
        except (ValueError, TypeError):
            return None
        if parsed.tzinfo is None:
            # Naive timestamps are read as UTC so they can be compared with
            # offset-aware ones in the same conversation.
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed

    deltas = []
    for i, msg in enumerate(messages):
        if msg.get('sender') != 'user' or 'timestamp' not in msg:
            continue
        nxt = messages[i + 1] if i + 1 < len(messages) else None
        if not nxt or nxt.get('sender') != 'ai' or 'timestamp' not in nxt:
            continue
        t0, t1 = parse(msg['timestamp']), parse(nxt['timestamp'])
        if t0 and t1 and t1 >= t0:
            deltas.append((t1 - t0).total_seconds())
    if not deltas:
        return 5.0  # demo default when timestamps are unavailable
    return round(sum(deltas) / len(deltas), 2)


def _resolution(messages: List[Dict], fallback_count: int) -> bool:
    ai_messages = get_ai_messages(messages)
    if not ai_messages or fallback_count >= 2:
        return False
    last_ai = ai_messages[-1].lower()
    if any(pat in last_ai for pat in FALLBACK_PATTERNS):
        return False
    # Trailing unanswered user question means the conversation is still open.
    user_messages = get_user_messages(messages)
    if messages and messages[-1].get('sender') == 'user' and messages[-1]['message'].strip().endswith('?'):
        return False
    return bool(user_messages)


def analyze_conversation(messages: List[Dict]) -> Dict:
    """Analyze a conversation and return the full metric bundle.

    Keys match the ``ConversationAnalysis`` model exactly so callers can pass
    the result straight to ``update_or_create(defaults=...)``.
    """
    messages = [m for m in (messages or []) if m.get('message')]
    ai_messages = get_ai_messages(messages)

    sentiment_label, sentiment_score = _sentiment(get_user_messages(messages))
    fallback_count = _fallback_count(ai_messages)
    clarity = _clarity(ai_messages)
    relevance = _relevance(messages)
    accuracy = _accuracy(ai_messages, fallback_count)
    completeness = _completeness(messages, fallback_count)
    empathy = _empathy(messages, sentiment_score)
    response_time = _avg_response_time(messages)
    resolution = _resolution(messages, fallback_count)
    escalation = (sentiment_score < -0.2 and not resolution) or fallback_count >= 3

    overall = (
        0.25 * clarity
        + 0.25 * relevance
        + 0.20 * accuracy
        + 0.20 * completeness
        + 0.10 * empathy
    )

    return {
        'clarity_score': round(clarity, 3),
        'relevance_score': round(relevance, 3),
        'accuracy_score': round(accuracy, 3),
        'completeness_score': round(completeness, 3),
        'sentiment': sentiment_label,
        'sentiment_score': round(sentiment_score, 3),
        'empathy_score': round(empathy, 3),
        'avg_response_time': response_time,
        'resolution': resolution,
        'fallback_count': fallback_count,
        'overall_score': round(_clamp(overall), 3),
        'escalation_needed': bool(escalation),
    }
