from celery import shared_task
from django.utils import timezone
from .models import Conversation, ConversationAnalysis
from .analyzers import analyze_conversation

@shared_task
def analyze_conversation_task(conversation_id):
    try:
        conversation = Conversation.objects.get(id=conversation_id)
        messages = list(conversation.messages.values('sender', 'text'))
        if not messages:
            return {'conversation_id': conversation_id, 'status': 'error',
                    'message': 'Conversation has no messages to analyze.'}
        messages_formatted = [{'sender': msg['sender'], 'message': msg['text']} for msg in messages]
        analysis_results = analyze_conversation(messages_formatted)
        analysis, created = ConversationAnalysis.objects.update_or_create(
            conversation=conversation,
            defaults=analysis_results
        )
        conversation.is_analyzed = True
        conversation.save()
        return {'conversation_id': conversation_id, 'status': 'success', 'overall_score': analysis_results['overall_score']}
    except Exception as e:
        return {'conversation_id': conversation_id, 'status': 'error', 'message': str(e)}

@shared_task
def analyze_all_pending_conversations():
    pending_conversations = Conversation.objects.filter(is_analyzed=False)
    for conv in pending_conversations:
        analyze_conversation_task(conv.id)
