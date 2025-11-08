from rest_framework import serializers
from .models import Conversation, Message, ConversationAnalysis

class MessageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Message
        fields = ['id', 'sender', 'text', 'timestamp']
        read_only_fields = ['id', 'timestamp']

class ConversationSerializer(serializers.ModelSerializer):
    messages = MessageSerializer(many=True)
    class Meta:
        model = Conversation
        fields = ['id', 'title', 'messages', 'created_at', 'is_analyzed']
        read_only_fields = ['id', 'created_at', 'is_analyzed']
    def create(self, validated_data):
        messages_data = validated_data.pop('messages')
        conversation = Conversation.objects.create(**validated_data)
        for message_data in messages_data:
            Message.objects.create(conversation=conversation, **message_data)
        return conversation

class ConversationAnalysisSerializer(serializers.ModelSerializer):
    conversation_title = serializers.CharField(source='conversation.title', read_only=True)
    class Meta:
        model = ConversationAnalysis
        fields = [
            'id', 'conversation', 'conversation_title',
            'clarity_score', 'relevance_score', 'accuracy_score',
            'completeness_score', 'sentiment', 'sentiment_score',
            'empathy_score', 'avg_response_time', 'resolution',
            'escalation_needed', 'fallback_count', 'overall_score',
            'created_at', 'updated_at'
        ]
        read_only_fields = ['id', 'created_at', 'updated_at']

class AnalyzeRequestSerializer(serializers.Serializer):
    conversation_id = serializers.IntegerField()
    def validate_conversation_id(self, value):
        if not Conversation.objects.filter(id=value).exists():
            raise serializers.ValidationError(f"Conversation with id {value} does not exist.")
        return value
