"""Test suite for the post-conversation analysis API and analyzers.

Run with: python manage.py test
"""
import json

from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from .analyzers import (
    analyze_conversation,
    get_ai_messages,
    get_user_messages,
)
from .models import Conversation, ConversationAnalysis, Message
from .tasks import analyze_all_pending_conversations, analyze_conversation_task

EXPECTED_KEYS = {
    'clarity_score', 'relevance_score', 'accuracy_score', 'completeness_score',
    'sentiment', 'sentiment_score', 'empathy_score', 'avg_response_time',
    'resolution', 'fallback_count', 'overall_score', 'escalation_needed',
}

HAPPY_PATH = [
    {'sender': 'user', 'message': 'Hi, my order has not arrived and I am really upset. Where is it?'},
    {'sender': 'ai', 'message': 'I am sorry to hear that. I understand how frustrating this is. Can you share your order ID so I can track it?'},
    {'sender': 'user', 'message': 'It is 12345.'},
    {'sender': 'ai', 'message': 'Thanks! Your order 12345 was shipped yesterday and will arrive tomorrow.'},
    {'sender': 'user', 'message': 'Great, thank you so much!'},
]

FALLBACK_LOOP = [
    {'sender': 'user', 'message': 'This is terrible, nothing works and I am furious. Why was I charged twice?'},
    {'sender': 'ai', 'message': "I don't understand. Could you rephrase that?"},
    {'sender': 'user', 'message': 'I was charged twice for the same order! Fix it now.'},
    {'sender': 'ai', 'message': "I'm not sure I can help with that. Please try again later."},
    {'sender': 'user', 'message': 'This is the worst support ever.'},
    {'sender': 'ai', 'message': "I don't know the answer. Could you rephrase?"},
]


class AnalyzerContractTests(TestCase):
    def test_result_has_all_model_keys(self):
        result = analyze_conversation(HAPPY_PATH)
        self.assertEqual(set(result.keys()), EXPECTED_KEYS)

    def test_scores_stay_in_valid_ranges(self):
        for conversation in (HAPPY_PATH, FALLBACK_LOOP, [], [{'sender': 'user', 'message': 'hello'}]):
            result = analyze_conversation(conversation)
            for key in ('clarity_score', 'relevance_score', 'accuracy_score',
                        'completeness_score', 'empathy_score', 'overall_score'):
                self.assertGreaterEqual(result[key], 0.0, key)
                self.assertLessEqual(result[key], 1.0, key)
            self.assertGreaterEqual(result['sentiment_score'], -1.0)
            self.assertLessEqual(result['sentiment_score'], 1.0)
            self.assertIn(result['sentiment'], ('positive', 'neutral', 'negative'))
            self.assertGreaterEqual(result['fallback_count'], 0)

    def test_empty_input_is_safe_and_neutral(self):
        result = analyze_conversation([])
        self.assertEqual(result['sentiment'], 'neutral')
        self.assertFalse(result['resolution'])
        self.assertFalse(result['escalation_needed'])


class AnalyzerBehaviorTests(TestCase):
    def test_resolved_conversation_scores_positive(self):
        result = analyze_conversation(HAPPY_PATH)
        self.assertEqual(result['sentiment'], 'positive')
        self.assertGreater(result['sentiment_score'], 0.1)
        self.assertTrue(result['resolution'])
        self.assertEqual(result['fallback_count'], 0)
        self.assertFalse(result['escalation_needed'])
        self.assertGreater(result['overall_score'], 0.6)

    def test_fallback_loop_flags_escalation(self):
        result = analyze_conversation(FALLBACK_LOOP)
        self.assertEqual(result['fallback_count'], 3)
        self.assertEqual(result['sentiment'], 'negative')
        self.assertFalse(result['resolution'])
        self.assertTrue(result['escalation_needed'])

    def test_empathy_detected_for_upset_user(self):
        result = analyze_conversation(HAPPY_PATH)
        # AI apologized and acknowledged frustration.
        self.assertGreaterEqual(result['empathy_score'], 0.6)

    def test_response_time_from_iso_timestamps(self):
        messages = [
            {'sender': 'user', 'message': 'Where is my refund?',
             'timestamp': '2026-01-01T10:00:00+00:00'},
            {'sender': 'ai', 'message': 'Your refund was processed today.',
             'timestamp': '2026-01-01T10:00:30+00:00'},
        ]
        result = analyze_conversation(messages)
        self.assertEqual(result['avg_response_time'], 30.0)

    def test_message_split_helpers(self):
        self.assertEqual(len(get_ai_messages(HAPPY_PATH)), 2)
        self.assertEqual(len(get_user_messages(HAPPY_PATH)), 3)


class AnalyzerEdgeCaseTests(TestCase):
    """Regression tests for timestamp mixing and question detection."""

    def test_mixed_naive_and_aware_timestamps_do_not_crash(self):
        messages = [
            {'sender': 'user', 'message': 'Hi there', 'timestamp': '2024-01-01T10:00:00Z'},
            {'sender': 'ai', 'message': 'Hello, how can I help?', 'timestamp': '2024-01-01T10:00:05'},
        ]
        result = analyze_conversation(messages)
        self.assertEqual(result['avg_response_time'], 5.0)

    def test_offset_timestamps_are_compared_in_absolute_time(self):
        messages = [
            {'sender': 'user', 'message': 'Hi', 'timestamp': '2024-01-01T10:00:00+00:00'},
            {'sender': 'ai', 'message': 'Hello', 'timestamp': '2024-01-01T15:30:10+05:30'},
        ]
        self.assertEqual(analyze_conversation(messages)['avg_response_time'], 10.0)

    def test_statement_containing_question_word_is_not_a_question(self):
        # "shows" contains "how"; it is a statement, not an unanswered question.
        messages = [
            {'sender': 'user', 'message': 'That shows it, thanks'},
            {'sender': 'ai', 'message': 'ok'},
        ]
        self.assertEqual(analyze_conversation(messages)['completeness_score'], 0.8)

    def test_real_question_without_question_mark_still_counts(self):
        messages = [
            {'sender': 'user', 'message': 'how do I reset my password'},
            {'sender': 'ai', 'message': 'Open settings and choose reset password.'},
        ]
        self.assertEqual(analyze_conversation(messages)['completeness_score'], 1.0)

    def test_question_mark_mid_message_counts_as_question(self):
        messages = [
            {'sender': 'user', 'message': 'Is it open? Thanks'},
            {'sender': 'ai', 'message': 'ok'},
        ]
        self.assertEqual(analyze_conversation(messages)['completeness_score'], 0.0)


class ConversationApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.payload = {
            'title': 'Order inquiry',
            'messages': [
                {'sender': 'user', 'message': 'Where is my order?'},
                {'sender': 'ai', 'message': 'Your order 12345 was shipped yesterday and arrives tomorrow.'},
                {'sender': 'user', 'message': 'Perfect, thanks!'},
            ],
        }

    def _create_conversation(self):
        response = self.client.post('/api/conversations/', self.payload, format='json')
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        return response.data['id']

    def test_create_conversation_with_messages(self):
        conversation_id = self._create_conversation()
        conversation = Conversation.objects.get(id=conversation_id)
        self.assertEqual(conversation.messages.count(), 3)
        self.assertFalse(conversation.is_analyzed)

    def test_create_conversation_requires_messages(self):
        response = self.client.post('/api/conversations/', {'title': 'Empty'}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_analyze_endpoint_creates_analysis(self):
        conversation_id = self._create_conversation()
        response = self.client.post('/api/analyse/', {'conversation_id': conversation_id}, format='json')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn('analysis', response.data)
        conversation = Conversation.objects.get(id=conversation_id)
        self.assertTrue(conversation.is_analyzed)
        analysis = ConversationAnalysis.objects.get(conversation=conversation)
        self.assertGreaterEqual(analysis.overall_score, 0.0)
        self.assertLessEqual(analysis.overall_score, 1.0)

    def test_analyze_endpoint_is_idempotent(self):
        conversation_id = self._create_conversation()
        for _ in range(2):
            response = self.client.post('/api/analyse/', {'conversation_id': conversation_id}, format='json')
            self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(ConversationAnalysis.objects.count(), 1)

    def test_analyze_rejects_unknown_conversation(self):
        response = self.client.post('/api/analyse/', {'conversation_id': 9999}, format='json')
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_reports_endpoint_lists_analyses(self):
        conversation_id = self._create_conversation()
        self.client.post('/api/analyse/', {'conversation_id': conversation_id}, format='json')
        response = self.client.get('/api/reports/')
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]['conversation_title'], 'Order inquiry')

    def test_reports_filter_by_sentiment(self):
        conversation_id = self._create_conversation()
        self.client.post('/api/analyse/', {'conversation_id': conversation_id}, format='json')
        response = self.client.get('/api/reports/?sentiment=negative')
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 0)
        response = self.client.get('/api/reports/?sentiment=positive')
        results = response.data.get('results', response.data)
        self.assertEqual(len(results), 1)


class CeleryTaskTests(TestCase):
    def _conversation(self, analyzed=False):
        conversation = Conversation.objects.create(title='Refund request')
        Message.objects.create(conversation=conversation, sender='user',
                               text='I want a refund for order 12345, this is unacceptable.')
        Message.objects.create(conversation=conversation, sender='ai',
                               text='I am sorry about that. I have issued a full refund for order 12345 today.')
        conversation.is_analyzed = analyzed
        conversation.save()
        return conversation

    def test_analyze_conversation_task(self):
        conversation = self._conversation()
        result = analyze_conversation_task(conversation.id)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['conversation_id'], conversation.id)
        conversation.refresh_from_db()
        self.assertTrue(conversation.is_analyzed)
        self.assertTrue(ConversationAnalysis.objects.filter(conversation=conversation).exists())

    def test_analyze_conversation_task_handles_missing_id(self):
        result = analyze_conversation_task(9999)
        self.assertEqual(result['status'], 'error')

    def test_analyze_all_pending_conversations(self):
        pending = self._conversation(analyzed=False)
        done = self._conversation(analyzed=True)
        analyze_all_pending_conversations()
        pending.refresh_from_db()
        done.refresh_from_db()
        self.assertTrue(pending.is_analyzed)
        # Already-analyzed conversation is not reprocessed.
        self.assertFalse(ConversationAnalysis.objects.filter(conversation=done).exists())
