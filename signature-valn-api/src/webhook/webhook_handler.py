"""
Webhook handler for processing incoming notifications
"""

import json
import logging
import hmac
import hashlib
from typing import Dict, Any, Optional
from datetime import datetime
import requests

logger = logging.getLogger(__name__)

class WebhookHandler:
    """Handles incoming webhook notifications and validates them"""
    
    def __init__(self, secret_key: str):
        self.secret_key = secret_key
    
    def validate_signature(self, payload: str, signature: str) -> bool:
        """Validate webhook signature for security"""
        try:
            expected_signature = hmac.new(
                self.secret_key.encode('utf-8'),
                payload.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            
            return hmac.compare_digest(signature, expected_signature)
        except Exception as e:
            logger.error(f"Error validating webhook signature: {str(e)}")
            return False
    
    def process_webhook(self, payload: str, signature: str, headers: Dict[str, str]) -> Dict[str, Any]:
        """Process incoming webhook and return response"""
        try:
            # Validate signature
            if not self.validate_signature(payload, signature):
                logger.warning("Invalid webhook signature received")
                return {
                    "status": "error",
                    "error": "Invalid signature",
                    "timestamp": datetime.utcnow().isoformat()
                }
            
            # Parse payload
            data = json.loads(payload)
            webhook_type = data.get('type')
            
            logger.info(f"Processing webhook of type: {webhook_type}")
            
            # Process based on webhook type
            if webhook_type == 'document_ready':
                return self._handle_document_ready(data)
            elif webhook_type == 'validation_complete':
                return self._handle_validation_complete(data)
            elif webhook_type == 'error_notification':
                return self._handle_error_notification(data)
            else:
                logger.warning(f"Unknown webhook type: {webhook_type}")
                return {
                    "status": "error",
                    "error": f"Unknown webhook type: {webhook_type}",
                    "timestamp": datetime.utcnow().isoformat()
                }
                
        except json.JSONDecodeError as e:
            logger.error(f"Invalid JSON in webhook payload: {str(e)}")
            return {
                "status": "error",
                "error": "Invalid JSON payload",
                "timestamp": datetime.utcnow().isoformat()
            }
        except Exception as e:
            logger.error(f"Error processing webhook: {str(e)}")
            return {
                "status": "error",
                "error": f"Internal error: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            }
    
    def _handle_document_ready(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle document ready for validation webhook"""
        try:
            document_id = data.get('document_id')
            document_url = data.get('document_url')
            document_type = data.get('document_type')
            
            if not all([document_id, document_url, document_type]):
                return {
                    "status": "error",
                    "error": "Missing required fields in document_ready webhook",
                    "timestamp": datetime.utcnow().isoformat()
                }
            
            logger.info(f"Document ready for validation: {document_id}")
            
            # Here you would trigger the signature validation process
            # For now, return success response
            return {
                "status": "success",
                "message": "Document ready webhook processed",
                "document_id": document_id,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error handling document ready webhook: {str(e)}")
            return {
                "status": "error",
                "error": f"Error processing document ready: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            }
    
    def _handle_validation_complete(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle validation complete webhook"""
        try:
            document_id = data.get('document_id')
            validation_result = data.get('validation_result')
            
            if not document_id or not validation_result:
                return {
                    "status": "error",
                    "error": "Missing required fields in validation_complete webhook",
                    "timestamp": datetime.utcnow().isoformat()
                }
            
            logger.info(f"Validation complete for document: {document_id}")
            
            # Here you would update Identifi with the validation results
            # For now, return success response
            return {
                "status": "success",
                "message": "Validation complete webhook processed",
                "document_id": document_id,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error handling validation complete webhook: {str(e)}")
            return {
                "status": "error",
                "error": f"Error processing validation complete: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            }
    
    def _handle_error_notification(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Handle error notification webhook"""
        try:
            error_message = data.get('error_message')
            document_id = data.get('document_id')
            
            logger.error(f"Error notification received for document {document_id}: {error_message}")
            
            # Here you would handle the error (log, alert, etc.)
            # For now, return success response
            return {
                "status": "success",
                "message": "Error notification processed",
                "document_id": document_id,
                "timestamp": datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Error handling error notification webhook: {str(e)}")
            return {
                "status": "error",
                "error": f"Error processing error notification: {str(e)}",
                "timestamp": datetime.utcnow().isoformat()
            }
