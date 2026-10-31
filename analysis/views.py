from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from django.db.models import Avg, Count
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
        messages = list(conversation.messages.values('sender', 'text', 'timestamp'))
        if not messages:
            raise ValidationError(
                {'conversation_id': 'Conversation has no messages to analyze.'}
            )
        messages_formatted = [
            {'sender': msg['sender'], 'message': msg['text'],
             'timestamp': msg['timestamp'].isoformat()}
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

TRUE_VALUES = {'true', '1', 'yes'}
FALSE_VALUES = {'false', '0', 'no'}


def parse_bool_param(request, name):
    """Return True/False for a boolean query parameter, or None when absent.

    Unrecognized values raise a 400 instead of silently filtering on False.
    """
    raw = request.query_params.get(name)
    if raw is None or raw == '':
        return None
    value = raw.strip().lower()
    if value in TRUE_VALUES:
        return True
    if value in FALSE_VALUES:
        return False
    raise ValidationError({name: "Use true or false."})


def parse_score_param(request, name):
    """Return a float in [0, 1] for a score-band query parameter, or None when absent.

    Non-numeric or out-of-range values (including NaN and infinity) raise a
    400 instead of silently ignoring the band, matching parse_bool_param.
    """
    raw = request.query_params.get(name)
    if raw is None or raw == '':
        return None
    try:
        value = float(raw)
    except ValueError:
        raise ValidationError({name: "Use a number between 0 and 1."})
    if not 0.0 <= value <= 1.0:
        raise ValidationError({name: "Use a number between 0 and 1."})
    return value


class ReportViewSet(viewsets.ReadOnlyModelViewSet):
    queryset = ConversationAnalysis.objects.all()
    serializer_class = ConversationAnalysisSerializer
    ordering_fields = ['overall_score', 'created_at']
    ordering = ['-overall_score']

    def get_queryset(self):
        queryset = super().get_queryset()
        sentiment = self.request.query_params.get('sentiment')
        if sentiment:
            queryset = queryset.filter(sentiment=sentiment)
        for name in ('resolution', 'escalation_needed'):
            value = parse_bool_param(self.request, name)
            if value is not None:
                queryset = queryset.filter(**{name: value})
        min_score = parse_score_param(self.request, 'min_score')
        max_score = parse_score_param(self.request, 'max_score')
        if min_score is not None and max_score is not None and min_score > max_score:
            raise ValidationError({'min_score': "min_score cannot exceed max_score."})
        if min_score is not None:
            queryset = queryset.filter(overall_score__gte=min_score)
        if max_score is not None:
            queryset = queryset.filter(overall_score__lte=max_score)
        return queryset

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Aggregate rollup over the filtered report set, for dashboards.

        Applies the same sentiment/resolution/escalation filters as the list
        endpoint, so a filtered summary describes exactly the rows you see.
        """
        queryset = self.get_queryset()
        total = queryset.count()
        resolved = queryset.filter(resolution=True).count()
        escalations = queryset.filter(escalation_needed=True).count()
        aggregates = queryset.aggregate(
            avg_overall=Avg('overall_score'),
            avg_response=Avg('avg_response_time'),
            avg_fallbacks=Avg('fallback_count'),
        )
        by_sentiment = {value: 0 for value, _ in ConversationAnalysis.SENTIMENT_CHOICES}
        for row in queryset.values('sentiment').annotate(count=Count('id')):
            by_sentiment[row['sentiment']] = row['count']

        def rounded(value, digits):
            return round(value, digits) if value is not None else None

        return Response({
            'total_analyses': total,
            'resolved': resolved,
            'resolution_rate': round(resolved / total, 3) if total else None,
            'escalations': escalations,
            'average_overall_score': rounded(aggregates['avg_overall'], 3),
            'average_response_time': rounded(aggregates['avg_response'], 2),
            'average_fallback_count': rounded(aggregates['avg_fallbacks'], 2),
            'by_sentiment': by_sentiment,
        })
