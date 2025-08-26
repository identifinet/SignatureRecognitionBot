"""
Utility functions for Signature Validation API
"""

import os
import json
import logging
import hashlib
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional
import requests
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class IdentifiAPIClient:
    """Client for interacting with Identifi API"""
    
    def __init__(self, api_url: str, api_key: str):
        self.api_url = api_url.rstrip('/')
        self.api_key = api_key
        self.session = requests.Session()
        self.session.headers.update({
            'Authorization': f'Bearer {api_key}',
            'Content-Type': 'application/json'
        })
    
    def update_document(self, document_id: str, attributes: Dict[str, Any], notes: str) -> Dict[str, Any]:
        """Update a document in Identifi with new attributes and notes"""
        try:
            payload = {
                'document_id': document_id,
                'attributes': attributes,
                'notes': notes,
                'update_timestamp': datetime.now(timezone.utc).isoformat()
            }
            
            response = self.session.post(
                f'{self.api_url}/documents/{document_id}/update',
                json=payload,
                timeout=30
            )
            
            if response.status_code == 200:
                logger.info(f'Successfully updated Identifi document {document_id}')
                return {'status': 'success', 'response': response.json()}
            else:
                logger.error(f'Failed to update Identifi document {document_id}: {response.status_code}')
                return {'status': 'failed', 'response_code': response.status_code, 'response': response.text}
                
        except Exception as e:
            logger.error(f'Error updating Identifi document {document_id}: {str(e)}')
            return {'status': 'error', 'error': str(e)}
    
    def get_document_info(self, document_id: str) -> Dict[str, Any]:
        """Retrieve document information from Identifi"""
        try:
            response = self.session.get(
                f'{self.api_url}/documents/{document_id}',
                timeout=30
            )
            
            if response.status_code == 200:
                return {'status': 'success', 'data': response.json()}
            else:
                return {'status': 'failed', 'response_code': response.status_code}
                
        except Exception as e:
            logger.error(f'Error retrieving document {document_id}: {str(e)}')
            return {'status': 'error', 'error': str(e)}

class DocumentProcessor:
    """Utility class for document processing operations"""
    
    @staticmethod
    def generate_document_hash(document_url: str, document_id: str) -> str:
        """Generate a unique hash for document identification"""
        content = f"{document_url}:{document_id}:{datetime.now(timezone.utc).isoformat()}"
        return hashlib.sha256(content.encode()).hexdigest()
    
    @staticmethod
    def validate_document_url(url: str) -> bool:
        """Validate if the document URL is accessible and valid"""
        try:
            parsed = urlparse(url)
            if not parsed.scheme or not parsed.netloc:
                return False
            
            # Check if URL is accessible
            response = requests.head(url, timeout=10)
            return response.status_code == 200
            
        except Exception as e:
            logger.warning(f"URL validation failed for {url}: {str(e)}")
            return False
    
    @staticmethod
    def extract_document_metadata(document_url: str) -> Dict[str, Any]:
        """Extract basic metadata from document URL"""
        try:
            parsed = urlparse(document_url)
            filename = os.path.basename(parsed.path)
            file_extension = os.path.splitext(filename)[1].lower()
            
            return {
                'filename': filename,
                'file_extension': file_extension,
                'domain': parsed.netloc,
                'scheme': parsed.scheme,
                'path': parsed.path
            }
        except Exception as e:
            logger.error(f"Error extracting metadata from {document_url}: {str(e)}")
            return {}

class ValidationMetrics:
    """Utility class for tracking validation metrics"""
    
    def __init__(self):
        self.metrics = {
            'total_documents': 0,
            'successful_validations': 0,
            'failed_validations': 0,
            'total_processing_time': 0.0,
            'confidence_scores': [],
            'document_types': {},
            'validation_statuses': {}
        }
    
    def record_validation(self, result: Dict[str, Any], processing_time: float):
        """Record validation metrics"""
        self.metrics['total_documents'] += 1
        self.metrics['total_processing_time'] += processing_time
        
        # Record success/failure
        if result.get('status') == 'success':
            self.metrics['successful_validations'] += 1
        else:
            self.metrics['failed_validations'] += 1
        
        # Record confidence score
        confidence = result.get('validation_result', {}).get('confidence_score', 0)
        if confidence > 0:
            self.metrics['confidence_scores'].append(confidence)
        
        # Record document type
        doc_type = result.get('validation_result', {}).get('document_type', 'unknown')
        self.metrics['document_types'][doc_type] = self.metrics['document_types'].get(doc_type, 0) + 1
        
        # Record validation status
        status = result.get('validation_result', {}).get('validation_status', 'unknown')
        self.metrics['validation_statuses'][status] = self.metrics['validation_statuses'].get(status, 0) + 1
    
    def get_summary(self) -> Dict[str, Any]:
        """Get summary of validation metrics"""
        total = self.metrics['total_documents']
        if total == 0:
            return self.metrics
        
        avg_processing_time = self.metrics['total_processing_time'] / total
        avg_confidence = sum(self.metrics['confidence_scores']) / len(self.metrics['confidence_scores']) if self.metrics['confidence_scores'] else 0
        success_rate = (self.metrics['successful_validations'] / total) * 100
        
        return {
            **self.metrics,
            'average_processing_time': round(avg_processing_time, 2),
            'average_confidence_score': round(avg_confidence, 3),
            'success_rate_percentage': round(success_rate, 2),
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    def reset_metrics(self):
        """Reset all metrics to initial state"""
        self.metrics = {
            'total_documents': 0,
            'successful_validations': 0,
            'failed_validations': 0,
            'total_processing_time': 0.0,
            'confidence_scores': [],
            'document_types': {},
            'validation_statuses': {}
        }

class ConfigManager:
    """Utility class for managing configuration"""
    
    @staticmethod
    def load_environment_config() -> Dict[str, Any]:
        """Load configuration from environment variables"""
        config = {
            'identifi_api_url': os.getenv('IDENTIFI_API_URL', 'https://api.identifi.com'),
            'identifi_api_key': os.getenv('IDENTIFI_API_KEY'),
            'max_document_size_mb': int(os.getenv('MAX_DOCUMENT_SIZE_MB', '50')),
            'validation_timeout_seconds': int(os.getenv('VALIDATION_TIMEOUT_SECONDS', '300')),
            'max_concurrent_validations': int(os.getenv('MAX_CONCURRENT_VALIDATIONS', '10')),
            'retry_attempts': int(os.getenv('RETRY_ATTEMPTS', '3')),
            'log_level': os.getenv('LOG_LEVEL', 'INFO')
        }
        
        # Validate required configuration
        if not config['identifi_api_key']:
            logger.warning('IDENTIFI_API_KEY not configured - Identifi integration will be disabled')
        
        return config
    
    @staticmethod
    def validate_config(config: Dict[str, Any]) -> List[str]:
        """Validate configuration and return list of errors"""
        errors = []
        
        if not config['identifi_api_url']:
            errors.append('IDENTIFI_API_URL is required')
        
        if config['max_document_size_mb'] <= 0:
            errors.append('MAX_DOCUMENT_SIZE_MB must be positive')
        
        if config['validation_timeout_seconds'] <= 0:
            errors.append('VALIDATION_TIMEOUT_SECONDS must be positive')
        
        if config['max_concurrent_validations'] <= 0:
            errors.append('MAX_CONCURRENT_VALIDATIONS must be positive')
        
        if config['retry_attempts'] < 0:
            errors.append('RETRY_ATTEMPTS must be non-negative')
        
        return errors

class ErrorHandler:
    """Utility class for consistent error handling"""
    
    @staticmethod
    def format_error(error: Exception, context: str = "") -> Dict[str, Any]:
        """Format error information consistently"""
        return {
            'error_type': type(error).__name__,
            'error_message': str(error),
            'context': context,
            'timestamp': datetime.now(timezone.utc).isoformat()
        }
    
    @staticmethod
    def is_retryable_error(error: Exception) -> bool:
        """Determine if an error is retryable"""
        retryable_errors = (
            requests.exceptions.Timeout,
            requests.exceptions.ConnectionError,
            requests.exceptions.HTTPError
        )
        return isinstance(error, retryable_errors)
    
    @staticmethod
    def get_retry_delay(attempt: int, base_delay: float = 1.0) -> float:
        """Calculate exponential backoff delay for retries"""
        return base_delay * (2 ** (attempt - 1))
