from rest_framework import viewsets, status
from rest_framework.response import Response
from django.shortcuts import get_object_or_404

from .models import Conversation, ConversationAnalysis
from .serializers import (
    ConversationSerializer, 
    ConversationAnalysisSerializer,
    AnalyzeRequestSerializer
)

from .analyzers import analyze_conversation

class ConversationViewSet(viewsets.ModelViewSet):
    queryset = Conversation.objects.all()
    serializer_class = ConversationSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        headers = self.get_success_headers(serializer.data)
        return Response(
            serializer.data,
            status=status.HTTP_201_CREATED,
            headers=headers
        )

class AnalysisViewSet(viewsets.ViewSet):
    def create(self, request):
        serializer = AnalyzeRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        conversation_id = serializer.validated_data['conversation_id']
        conversation = get_object_or_404(Conversation, id=conversation_id)
        messages = list(conversation.messages.values('sender', 'text'))
        messages_formatted = [
            {'sender': msg['sender'], 'message': msg['text']}
            for msg in messages
        ]
        analysis_results = analyze_conversation(messages_formatted)
        analysis, created = ConversationAnalysis.objects.update_or_create(
            conversation=conversation,
            defaults=analysis_results
        )
        conversation.is_analyzed = True
        conversation.save()
        response_serializer = ConversationAnalysisSerializer(analysis)
        return Response(
            {
                'message': 'Analysis completed successfully',
                'analysis': response_serializer.data
            },
            status=status.HTTP_200_OK
        )

class ReportViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ConversationAnalysis.objects.all()
    serializer_class = ConversationAnalysisSerializer
    filterset_fields = ['sentiment', 'resolution', 'escalation_needed']
    ordering_fields = ['overall_score', 'created_at']
    ordering = ['-overall_score']
    def get_queryset(self):
        queryset = super().get_queryset()
        sentiment = self.request.query_params.get('sentiment', None)
        if sentiment:
            queryset = queryset.filter(sentiment=sentiment)
        resolution = self.request.query_params.get('resolution', None)
        if resolution is not None:
            resolution_bool = resolution.lower() == 'true'
            queryset = queryset.filter(resolution=resolution_bool)
        return queryset
