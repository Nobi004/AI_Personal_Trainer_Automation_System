# apps/chatbot/whatsapp_handler.py
import json
import logging
import requests
from django.conf import settings
from django.http import HttpResponse, HttpResponseBadRequest
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from django.utils.decorators import method_decorator
from django.utils.translation import gettext as _
from django.utils.translation import activate
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from apps.users.models import User
from apps.chatbot.message_processor import MessageProcessor
from apps.chatbot.models import Conversation, Message
from apps.core.utils import get_or_create_user_by_whatsapp
from celery import shared_task

logger = logging.getLogger(__name__)

class WhatsAppWebhookView(APIView):
    """Handle WhatsApp webhook events"""
    
    def get(self, request):
        """Webhook verification"""
        verify_token = request.GET.get('hub.verify_token')
        challenge = request.GET.get('hub.challenge')
        
        if verify_token == settings.WHATSAPP_WEBHOOK_VERIFY_TOKEN:
            return HttpResponse(challenge)
        else:
            return HttpResponseBadRequest('Invalid verify token')
    
    def post(self, request):
        """Handle incoming WhatsApp messages"""
        try:
            body = json.loads(request.body)
            
            if 'entry' in body:
                for entry in body['entry']:
                    if 'changes' in entry:
                        for change in entry['changes']:
                            if change['field'] == 'messages':
                                self.process_message_change(change['value'])
            
            return Response({'status': 'success'}, status=status.HTTP_200_OK)
            
        except Exception as e:
            logger.error(f"Error processing WhatsApp webhook: {str(e)}")
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
    
    def process_message_change(self, value):
        """Process individual message changes"""
        if 'messages' in value:
            for message in value['messages']:
                # Process message asynchronously
                process_whatsapp_message.delay(message, value.get('metadata', {}))


@shared_task
def process_whatsapp_message(message_data, metadata):
    """Process WhatsApp message asynchronously"""
    try:
        from_number = message_data.get('from')
        message_type = message_data.get('type')
        timestamp = message_data.get('timestamp')
        
        # Get or create user
        user = get_or_create_user_by_whatsapp(from_number)
        
        # Activate user's preferred language
        activate(user.preferred_language)
        
        # Get or create conversation
        conversation = get_or_create_conversation(user)
        
        # Extract message content based on type
        content = extract_message_content(message_data)
        
        # Save incoming message
        incoming_message = Message.objects.create(
            conversation=conversation,
            sender_type='user',
            content=content,
            message_type=message_type,
            whatsapp_message_id=message_data.get('id'),
            timestamp=timestamp
        )
        
        # Process message with AI
        processor = MessageProcessor(user, conversation)
        response = processor.process_message(content, message_type)
        
        # Save AI response
        response_message = Message.objects.create(
            conversation=conversation,
            sender_type='assistant',
            content=response,
            message_type='text'
        )
        
        # Send response via WhatsApp
        whatsapp_client = WhatsAppClient()
        whatsapp_client.send_message(from_number, response)
        
        # Update user activity
        user.update_last_active()
        
        logger.info(f"Processed message from {from_number}: {content[:50]}...")
        
    except Exception as e:
        logger.error(f"Error processing WhatsApp message: {str(e)}")


def extract_message_content(message_data):
    """Extract content based on message type"""
    message_type = message_data.get('type')
    
    if message_type == 'text':
        return message_data.get('text', {}).get('body', '')
    elif message_type == 'button':
        return message_data.get('button', {}).get('text', '')
    elif message_type == 'interactive':
        interactive = message_data.get('interactive', {})
        if 'button_reply' in interactive:
            return interactive['button_reply'].get('title', '')
        elif 'list_reply' in interactive:
            return interactive['list_reply'].get('title', '')
    elif message_type == 'image':
        return _("Image received")
    elif message_type == 'document':
        return _("Document received")
    elif message_type == 'audio':
        return _("Audio message received")
    elif message_type == 'video':
        return _("Video received")
    
    return _("Unsupported message type")


def get_or_create_conversation(user):
    """Get or create active conversation for user"""
    conversation, created = Conversation.objects.get_or_create(
        user=user,
        is_active=True,
        defaults={'title': _('WhatsApp Chat')}
    )
    return conversation


class WhatsAppClient:
    """WhatsApp Business API client"""
    
    def __init__(self):
        self.access_token = settings.WHATSAPP_ACCESS_TOKEN
        self.phone_number_id = settings.WHATSAPP_PHONE_NUMBER_ID
        self.base_url = f"https://graph.facebook.com/v18.0/{self.phone_number_id}"
        self.headers = {
            'Authorization': f'Bearer {self.access_token}',
            'Content-Type': 'application/json'
        }
    
    def send_message(self, to_number, message, message_type='text'):
        """Send message to WhatsApp number"""
        try:
            url = f"{self.base_url}/messages"
            
            if message_type == 'text':
                payload = {
                    "messaging_product": "whatsapp",
                    "to": to_number,
                    "type": "text",
                    "text": {"body": message}
                }
            elif message_type == 'interactive_buttons':
                payload = self._create_interactive_buttons_payload(to_number, message)
            elif message_type == 'interactive_list':
                payload = self._create_interactive_list_payload(to_number, message)
            elif message_type == 'template':
                payload = self._create_template_payload(to_number, message)
            else:
                payload = {
                    "messaging_product": "whatsapp",
                    "to": to_number,
                    "type": "text",
                    "text": {"body": str(message)}
                }
            
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            
            logger.info(f"Message sent successfully to {to_number}")
            return response.json()
            
        except requests.exceptions.RequestException as e:
            logger.error(f"Error sending WhatsApp message to {to_number}: {str(e)}")
            raise
    
    def send_interactive_buttons(self, to_number, text, buttons):
        """Send interactive buttons message"""
        try:
            url = f"{self.base_url}/messages"
            
            # Format buttons for WhatsApp API
            formatted_buttons = []
            for i, button in enumerate(buttons[:3]):  # Max 3 buttons
                formatted_buttons.append({
                    "type": "reply",
                    "reply": {
                        "id": f"btn_{i}",
                        "title": button[:20]  # Max 20 characters
                    }
                })
            
            payload = {
                "messaging_product": "whatsapp",
                "to": to_number,
                "type": "interactive",
                "interactive": {
                    "type": "button",
                    "body": {"text": text},
                    "action": {"buttons": formatted_buttons}
                }
            }
            
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Error sending interactive buttons: {str(e)}")
            # Fallback to regular text message
            return self.send_message(to_number, f"{text}\n\n" + "\n".join([f"{i+1}. {btn}" for i, btn in enumerate(buttons)]))
    
    def send_interactive_list(self, to_number, text, options):
        """Send interactive list message"""
        try:
            url = f"{self.base_url}/messages"
            
            # Format options for WhatsApp API
            rows = []
            for i, option in enumerate(options[:10]):  # Max 10 options
                rows.append({
                    "id": f"option_{i}",
                    "title": option[:24],  # Max 24 characters
                    "description": option.get('description', '')[:72] if isinstance(option, dict) else ''
                })
            
            payload = {
                "messaging_product": "whatsapp",
                "to": to_number,
                "type": "interactive",
                "interactive": {
                    "type": "list",
                    "body": {"text": text},
                    "action": {
                        "button": _("Select an option"),
                        "sections": [{
                            "title": _("Options"),
                            "rows": rows
                        }]
                    }
                }
            }
            
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Error sending interactive list: {str(e)}")
            # Fallback to regular text message
            option_text = "\n".join([f"{i+1}. {opt}" for i, opt in enumerate(options)])
            return self.send_message(to_number, f"{text}\n\n{option_text}")
    
    def send_document(self, to_number, document_url, filename, caption=""):
        """Send document via WhatsApp"""
        try:
            url = f"{self.base_url}/messages"
            
            payload = {
                "messaging_product": "whatsapp",
                "to": to_number,
                "type": "document",
                "document": {
                    "link": document_url,
                    "filename": filename,
                    "caption": caption
                }
            }
            
            response = requests.post(url, headers=self.headers, json=payload, timeout=30)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Error sending document: {str(e)}")
            raise
    
    def _create_interactive_buttons_payload(self, to_number, message_data):
        """Create interactive buttons payload"""
        return {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "interactive",
            "interactive": message_data
        }
    
    def _create_interactive_list_payload(self, to_number, message_data):
        """Create interactive list payload"""
        return {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "interactive",
            "interactive": message_data
        }
    
    def _create_template_payload(self, to_number, template_data):
        """Create template message payload"""
        return {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "template",
            "template": template_data
        }
    
    def mark_message_as_read(self, message_id):
        """Mark message as read"""
        try:
            url = f"{self.base_url}/messages"
            payload = {
                "messaging_product": "whatsapp",
                "status": "read",
                "message_id": message_id
            }
            
            response = requests.post(url, headers=self.headers, json=payload, timeout=10)
            response.raise_for_status()
            
            return response.json()
            
        except Exception as e:
            logger.error(f"Error marking message as read: {str(e)}")


class WhatsAppMessageBuilder:
    """Helper class to build WhatsApp messages"""
    
    @staticmethod
    def create_welcome_message(user_name, language='en'):
        """Create welcome message for new users"""
        activate(language)
        
        message = _("""🎉 Welcome to your AI Personal Trainer, {name}!

I'm here to help you achieve your fitness goals with personalized workout plans, nutrition guidance, and 24/7 support.

Let's get started with a quick setup to create your perfect fitness plan!

Ready to begin? 💪""").format(name=user_name)
        
        buttons = [
            _("Let's Start! 🚀"),
            _("Learn More ℹ️"),
            _("Choose Language 🌐")
        ]
        
        return message, buttons
    
    @staticmethod
    def create_onboarding_message(step, language='en'):
        """Create onboarding messages for different steps"""
        activate(language)
        
        messages = {
            'personal_info': _("Let's start with some basic information about you.\n\nWhat's your age?"),
            'physical_info': _("Great! Now let's get your physical measurements.\n\nWhat's your current weight in kg?"),
            'goals': _("What are your main fitness goals?"),
            'activity_level': _("How would you describe your current activity level?"),
            'preferences': _("What's your preferred workout time?"),
            'complete': _("🎉 Perfect! Your profile is complete!\n\nI'm now generating your personalized fitness and nutrition plan. This will take just a moment...")
        }
        
        return messages.get(step, _("Please provide the requested information."))
    
    @staticmethod
    def create_menu_message(language='en'):
        """Create main menu message"""
        activate(language)
        
        message = _("""🏋️ What would you like to do today?

Choose an option below:""")
        
        options = [
            _("📋 View My Plan"),
            _("📊 Track Progress"),
            _("💬 Ask Question"),
            _("⚙️ Settings"),
            _("📱 Get Weekly Report"),
            _("🎯 Update Goals"),
            _("❌ Cancel Subscription")
        ]
        
        return message, options
    
    @staticmethod
    def create_cancellation_message(language='en'):
        """Create subscription cancellation message"""
        activate(language)
        
        message = _("""😔 We're sorry to see you go!

Are you sure you want to cancel your subscription?

This will:
• Stop your personalized plans
• Disable progress tracking  
• End motivational messages
• Remove access to 24/7 support

You can always reactivate later.""")
        
        buttons = [
            _("Yes, Cancel ❌"),
            _("No, Keep Active ✅"),
            _("Pause Instead 🔄")
        ]
        
        return message, buttons