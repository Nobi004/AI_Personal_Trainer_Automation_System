# apps/users/models.py
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils.translation import gettext_lazy as _
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import uuid

class User(AbstractUser):
    """Extended User model for AI Personal Trainer system"""
    
    GENDER_CHOICES = [
        ('M', _('Male')),
        ('F', _('Female')),
        ('O', _('Other')),
    ]
    
    ACTIVITY_LEVEL_CHOICES = [
        ('sedentary', _('Sedentary (little/no exercise)')),
        ('lightly_active', _('Lightly active (light exercise/sports 1-3 days/week)')),
        ('moderately_active', _('Moderately active (moderate exercise/sports 3-5 days/week)')),
        ('very_active', _('Very active (hard exercise/sports 6-7 days a week)')),
        ('extremely_active', _('Extremely active (very hard exercise/sports & physical job)')),
    ]
    
    LANGUAGE_CHOICES = [
        ('en', _('English')),
        ('es', _('Spanish')),
    ]
    
    # Basic Information
    phone_number = models.CharField(max_length=20, unique=True, null=True, blank=True)
    whatsapp_number = models.CharField(max_length=20, unique=True)
    date_of_birth = models.DateField(null=True, blank=True)
    gender = models.CharField(max_length=1, choices=GENDER_CHOICES, null=True, blank=True)
    preferred_language = models.CharField(max_length=2, choices=LANGUAGE_CHOICES, default='en')
    
    # Physical Information
    height = models.FloatField(
        null=True, 
        blank=True, 
        help_text=_('Height in cm'),
        validators=[MinValueValidator(50), MaxValueValidator(300)]
    )
    current_weight = models.FloatField(
        null=True, 
        blank=True, 
        help_text=_('Current weight in kg'),
        validators=[MinValueValidator(20), MaxValueValidator(500)]
    )
    target_weight = models.FloatField(
        null=True, 
        blank=True, 
        help_text=_('Target weight in kg'),
        validators=[MinValueValidator(20), MaxValueValidator(500)]
    )
    
    # Fitness Information
    activity_level = models.CharField(
        max_length=20, 
        choices=ACTIVITY_LEVEL_CHOICES, 
        null=True, 
        blank=True
    )
    fitness_goals = models.TextField(null=True, blank=True)
    medical_conditions = models.TextField(null=True, blank=True)
    dietary_restrictions = models.TextField(null=True, blank=True)
    
    # Subscription & Status
    is_subscribed = models.BooleanField(default=True)
    subscription_start_date = models.DateTimeField(default=timezone.now)
    subscription_end_date = models.DateTimeField(null=True, blank=True)
    is_onboarded = models.BooleanField(default=False)
    onboarding_completed_at = models.DateTimeField(null=True, blank=True)
    
    # Preferences
    preferred_contact_method = models.CharField(
        max_length=20,
        choices=[('whatsapp', 'WhatsApp'), ('email', 'Email')],
        default='whatsapp'
    )
    timezone = models.CharField(max_length=50, default='UTC')
    receive_motivational_messages = models.BooleanField(default=True)
    receive_weekly_reports = models.BooleanField(default=True)
    
    # Metadata
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    last_active = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        verbose_name = _('User')
        verbose_name_plural = _('Users')
        indexes = [
            models.Index(fields=['whatsapp_number']),
            models.Index(fields=['is_subscribed']),
            models.Index(fields=['created_at']),
        ]
    
    def __str__(self):
        return f"{self.username} ({self.whatsapp_number})"
    
    @property
    def age(self):
        if self.date_of_birth:
            today = timezone.now().date()
            return today.year - self.date_of_birth.year - ((today.month, today.day) < (self.date_of_birth.month, self.date_of_birth.day))
        return None
    
    @property
    def bmi(self):
        if self.height and self.current_weight:
            height_m = self.height / 100
            return round(self.current_weight / (height_m ** 2), 1)
        return None
    
    def update_last_active(self):
        self.last_active = timezone.now()
        self.save(update_fields=['last_active'])


class UserProfile(models.Model):
    """Extended profile information for users"""
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='profile')
    
    # Additional fitness preferences
    preferred_workout_time = models.TimeField(null=True, blank=True)
    workout_duration_preference = models.IntegerField(
        null=True, 
        blank=True, 
        help_text=_('Preferred workout duration in minutes')
    )
    equipment_available = models.JSONField(default=list, blank=True)
    
    # Nutrition preferences
    meals_per_day = models.IntegerField(default=3, validators=[MinValueValidator(1), MaxValueValidator(10)])
    calories_target = models.IntegerField(null=True, blank=True)
    protein_target = models.IntegerField(null=True, blank=True)
    
    # Progress tracking preferences
    weigh_in_frequency = models.CharField(
        max_length=20,
        choices=[
            ('daily', _('Daily')),
            ('weekly', _('Weekly')),
            ('biweekly', _('Bi-weekly')),
            ('monthly', _('Monthly')),
        ],
        default='weekly'
    )
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('User Profile')
        verbose_name_plural = _('User Profiles')


class WeightEntry(models.Model):
    """Track user weight over time"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='weight_entries')
    weight = models.FloatField(validators=[MinValueValidator(20), MaxValueValidator(500)])
    date_recorded = models.DateField(default=timezone.now)
    notes = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        verbose_name = _('Weight Entry')
        verbose_name_plural = _('Weight Entries')
        unique_together = ['user', 'date_recorded']
        ordering = ['-date_recorded']
    
    def __str__(self):
        return f"{self.user.username} - {self.weight}kg on {self.date_recorded}"


class ProgressEntry(models.Model):
    """Track various progress metrics"""
    
    ENERGY_LEVEL_CHOICES = [
        (1, _('Very Low')),
        (2, _('Low')),
        (3, _('Moderate')),
        (4, _('High')),
        (5, _('Very High')),
    ]
    
    ADHERENCE_CHOICES = [
        (1, _('Poor (0-20%)')),
        (2, _('Fair (21-40%)')),
        (3, _('Good (41-60%)')),
        (4, _('Very Good (61-80%)')),
        (5, _('Excellent (81-100%)')),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='progress_entries')
    week_start_date = models.DateField()
    
    # Progress metrics
    energy_level = models.IntegerField(choices=ENERGY_LEVEL_CHOICES, null=True, blank=True)
    workout_adherence = models.IntegerField(choices=ADHERENCE_CHOICES, null=True, blank=True)
    diet_adherence = models.IntegerField(choices=ADHERENCE_CHOICES, null=True, blank=True)
    sleep_quality = models.IntegerField(choices=ENERGY_LEVEL_CHOICES, null=True, blank=True)
    stress_level = models.IntegerField(choices=ENERGY_LEVEL_CHOICES, null=True, blank=True)
    
    # Measurements
    chest = models.FloatField(null=True, blank=True, help_text=_('Chest measurement in cm'))
    waist = models.FloatField(null=True, blank=True, help_text=_('Waist measurement in cm'))
    hips = models.FloatField(null=True, blank=True, help_text=_('Hip measurement in cm'))
    arms = models.FloatField(null=True, blank=True, help_text=_('Arm measurement in cm'))
    thighs = models.FloatField(null=True, blank=True, help_text=_('Thigh measurement in cm'))
    
    # Notes and feedback
    challenges = models.TextField(blank=True)
    achievements = models.TextField(blank=True)
    feedback = models.TextField(blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Progress Entry')
        verbose_name_plural = _('Progress Entries')
        unique_together = ['user', 'week_start_date']
        ordering = ['-week_start_date']
    
    def __str__(self):
        return f"{self.user.username} - Week of {self.week_start_date}"


class WorkoutPlan(models.Model):
    """AI-generated workout plans for users"""
    
    DIFFICULTY_CHOICES = [
        ('beginner', _('Beginner')),
        ('intermediate', _('Intermediate')),
        ('advanced', _('Advanced')),
    ]
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='workout_plans')
    title = models.CharField(max_length=200)
    description = models.TextField()
    difficulty_level = models.CharField(max_length=20, choices=DIFFICULTY_CHOICES)
    duration_weeks = models.IntegerField(default=4)
    plan_data = models.JSONField()  # Structured workout data
    
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Workout Plan')
        verbose_name_plural = _('Workout Plans')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.user.username}"


class NutritionPlan(models.Model):
    """AI-generated nutrition plans for users"""
    
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='nutrition_plans')
    title = models.CharField(max_length=200)
    description = models.TextField()
    daily_calories = models.IntegerField()
    daily_protein = models.IntegerField()
    daily_carbs = models.IntegerField()
    daily_fats = models.IntegerField()
    plan_data = models.JSONField()  # Structured meal plan data
    
    is_active = models.BooleanField(default=True)
    start_date = models.DateField(default=timezone.now)
    end_date = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        verbose_name = _('Nutrition Plan')
        verbose_name_plural = _('Nutrition Plans')
        ordering = ['-created_at']
    
    def __str__(self):
        return f"{self.title} - {self.user.username}"