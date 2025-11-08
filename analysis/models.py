from django.db import models
from django.core.validators import MinValueValidator, MaxValueValidator

class Conversation(models.Model):
    title = models.CharField(max_length=255)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_analyzed = models.BooleanField(default=False)
    class Meta:
        ordering = ['-created_at']
    def __str__(self):
        return f"{self.title} ({self.created_at.strftime('%Y-%m-%d')})"

class Message(models.Model):
    SENDER_CHOICES = [
        ('user', 'User'),
        ('ai', 'AI'),
    ]
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name='messages')
    sender = models.CharField(max_length=20, choices=SENDER_CHOICES)
    text = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)
    class Meta:
        ordering = ['timestamp']
    def __str__(self):
        return f"{self.sender}: {self.text[:50]}..."

class ConversationAnalysis(models.Model):
    SENTIMENT_CHOICES = [
        ('positive', 'Positive'),
        ('neutral', 'Neutral'),
        ('negative', 'Negative'),
    ]
    conversation = models.OneToOneField(Conversation, on_delete=models.CASCADE, related_name='analysis')
    clarity_score = models.FloatField(validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    relevance_score = models.FloatField(validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    accuracy_score = models.FloatField(validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    completeness_score = models.FloatField(validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    sentiment = models.CharField(max_length=20, choices=SENTIMENT_CHOICES)
    sentiment_score = models.FloatField(validators=[MinValueValidator(-1.0), MaxValueValidator(1.0)])
    empathy_score = models.FloatField(validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    avg_response_time = models.FloatField()
    resolution = models.BooleanField()
    escalation_needed = models.BooleanField()
    fallback_count = models.IntegerField(default=0, validators=[MinValueValidator(0)])
    overall_score = models.FloatField(validators=[MinValueValidator(0.0), MaxValueValidator(1.0)])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    class Meta:
        ordering = ['-created_at']
    def __str__(self):
        return f"Analysis: {self.conversation.title} - {self.overall_score:.2f}"
