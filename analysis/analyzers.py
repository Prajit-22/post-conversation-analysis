import re
import nltk
import spacy
from textblob import TextBlob
from typing import List, Dict, Tuple

# Download required NLTK data if missing
try:
    nltk.data.find('tokenizers/punkt')
except LookupError:
    nltk.download('punkt', quiet=True)

# Load spaCy model
try:
    nlp = spacy.load('en_core_web_sm')
except OSError:
    nlp = None

def get_ai_messages(messages: List[Dict]) -> List[str]:
    return [msg['message'] for msg in messages if msg['sender'] == 'ai']

def get_user_messages(messages: List[Dict]) -> List[str]:
    return [msg['message'] for msg in messages if msg['sender'] == 'user']

# Example simple analyzer logic below - replace with full logic later
def analyze_conversation(messages: List[Dict]) -> Dict:
    clarity = 0.8
    relevance = 0.8
    accuracy = 0.8
    completeness = 0.8
    sentiment_label = 'neutral'
    sentiment_score = 0.0
    empathy = 0.5
    response_time = 5.0
    fallback_count = 0
    resolution = False
    overall = 0.7
    escalation = False
    return {
        'clarity_score': clarity,
        'relevance_score': relevance,
        'accuracy_score': accuracy,
        'completeness_score': completeness,
        'sentiment': sentiment_label,
        'sentiment_score': sentiment_score,
        'empathy_score': empathy,
        'avg_response_time': response_time,
        'resolution': resolution,
        'fallback_count': fallback_count,
        'overall_score': overall,
        'escalation_needed': escalation,
    }
