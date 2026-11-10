import csv

from django.http import HttpResponse
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
    def export(self, request):
        """Download the filtered report set as a CSV attachment.

        Applies the same filters and ordering as the list endpoint, but
        ignores pagination, so an export always contains every matching row.
        """
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="reports.csv"'
        writer = csv.writer(response)
        writer.writerow([
            'conversation_id', 'conversation_title',
            'overall_score', 'clarity_score', 'relevance_score',
            'accuracy_score', 'completeness_score', 'empathy_score',
            'sentiment', 'sentiment_score', 'avg_response_time',
            'resolution', 'escalation_needed', 'fallback_count',
            'analyzed_at',
        ])
        queryset = self.filter_queryset(self.get_queryset())
        for analysis in queryset.select_related('conversation'):
            writer.writerow([
                analysis.conversation_id,
                analysis.conversation.title,
                round(analysis.overall_score, 3),
                round(analysis.clarity_score, 3),
                round(analysis.relevance_score, 3),
                round(analysis.accuracy_score, 3),
                round(analysis.completeness_score, 3),
                round(analysis.empathy_score, 3),
                analysis.sentiment,
                round(analysis.sentiment_score, 3),
                round(analysis.avg_response_time, 2),
                analysis.resolution,
                analysis.escalation_needed,
                analysis.fallback_count,
                analysis.created_at.isoformat(),
            ])
        return response

    @action(detail=False, methods=['get'])
    def summary(self, request):
        """Aggregate rollup over the filtered report set, for dashboards.

        Applies the same sentiment/resolution/escalation filters as the list
        endpoint, so a filtered summary describes exactly the rows you see.
        ``average_scores`` carries a mean per analysis metric over the same
        set, so a weak spot (say clarity) is visible without listing rows.
        """
        queryset = self.get_queryset()
        total = queryset.count()
        resolved = queryset.filter(resolution=True).count()
        escalations = queryset.filter(escalation_needed=True).count()
        aggregates = queryset.aggregate(
            avg_overall=Avg('overall_score'),
            avg_response=Avg('avg_response_time'),
            avg_fallbacks=Avg('fallback_count'),
            avg_clarity=Avg('clarity_score'),
            avg_relevance=Avg('relevance_score'),
            avg_accuracy=Avg('accuracy_score'),
            avg_completeness=Avg('completeness_score'),
            avg_empathy=Avg('empathy_score'),
            avg_sentiment=Avg('sentiment_score'),
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
            'average_scores': {
                'clarity': rounded(aggregates['avg_clarity'], 3),
                'relevance': rounded(aggregates['avg_relevance'], 3),
                'accuracy': rounded(aggregates['avg_accuracy'], 3),
                'completeness': rounded(aggregates['avg_completeness'], 3),
                'empathy': rounded(aggregates['avg_empathy'], 3),
                'sentiment': rounded(aggregates['avg_sentiment'], 3),
            },
            'by_sentiment': by_sentiment,
        })
