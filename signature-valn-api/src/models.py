"""
Data models and validation schemas for Signature Validation API
"""

from typing import List, Optional, Dict, Any
from datetime import datetime
from dataclasses import dataclass
from enum import Enum

class DocumentType(str, Enum):
    """Supported document types for signature validation"""
    SIGNATURE_CARD = "signature_card"
    LOAN_APPLICATION = "loan_application"
    CONTRACT = "contract"
    CONSENT_FORM = "consent_form"
    WITHDRAWAL_FORM = "withdrawal_form"
    LEGAL_DOCUMENT = "legal_document"
    GOVERNMENT_FORM = "government_form"

class ValidationStatus(str, Enum):
    """Signature validation status values"""
    VALID = "valid"
    INVALID = "invalid"
    SUSPICIOUS = "suspicious"
    UNVERIFIABLE = "unverifiable"
    PENDING = "pending"

class SignatureType(str, Enum):
    """Types of signatures that can be detected"""
    HANDWRITTEN = "handwritten"
    DIGITAL = "digital"
    ELECTRONIC = "electronic"
    STAMP = "stamp"
    UNKNOWN = "unknown"

@dataclass
class SignatureLocation:
    """Represents the location of a signature within a document"""
    page_number: int
    x_coordinate: float
    y_coordinate: float
    width: float
    height: float
    confidence: float

@dataclass
class SignatureDetails:
    """Detailed information about a detected signature"""
    signature_id: str
    signature_type: SignatureType
    confidence_score: float
    quality_score: float
    location: SignatureLocation
    detected_at: datetime
    validation_status: ValidationStatus

@dataclass
class ValidationRequest:
    """Request model for signature validation"""
    document_id: str
    document_url: str
    document_type: DocumentType
    priority: Optional[str] = "normal"
    callback_url: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

@dataclass
class ValidationResult:
    """Result model for signature validation"""
    document_id: str
    document_type: DocumentType
    signatures_found: int
    signatures_validated: int
    confidence_score: float
    validation_status: ValidationStatus
    processing_time: str
    validation_timestamp: datetime
    signature_details: List[SignatureDetails]
    overall_quality_score: float
    validation_notes: Optional[str] = None

@dataclass
class IdentifiUpdateRequest:
    """Request model for updating Identifi documents"""
    document_id: str
    attributes: Dict[str, Any]
    notes: str
    update_timestamp: datetime

@dataclass
class BulkValidationRequest:
    """Request model for bulk signature validation"""
    documents: List[ValidationRequest]
    batch_id: Optional[str] = None
    priority: Optional[str] = "normal"
    callback_url: Optional[str] = None

@dataclass
class BulkValidationResult:
    """Result model for bulk signature validation"""
    batch_id: str
    status: str
    total_documents: int
    successful: int
    failed: int
    results: List[Dict[str, Any]]
    timestamp: datetime
    processing_summary: Dict[str, Any]

@dataclass
class ValidationMetrics:
    """Metrics for validation performance monitoring"""
    total_documents_processed: int
    successful_validations: int
    failed_validations: int
    average_processing_time: float
    average_confidence_score: float
    validation_accuracy: float
    timestamp: datetime

class DocumentValidator:
    """Validator class for document-related data"""
    
    @staticmethod
    def validate_document_type(document_type: str) -> bool:
        """Validate if document type is supported"""
        try:
            DocumentType(document_type)
            return True
        except ValueError:
            return False
    
    @staticmethod
    def validate_document_id(document_id: str) -> bool:
        """Validate document ID format"""
        if not document_id or not isinstance(document_id, str):
            return False
        if len(document_id.strip()) == 0:
            return False
        return True
    
    @staticmethod
    def validate_document_url(document_url: str) -> bool:
        """Validate document URL format"""
        if not document_url or not isinstance(document_url, str):
            return False
        if len(document_url.strip()) == 0:
            return False
        # Basic URL validation
        if not (document_url.startswith('http://') or document_url.startswith('https://') or document_url.startswith('file://')):
            return False
        return True
    
    @staticmethod
    def validate_validation_request(request: ValidationRequest) -> List[str]:
        """Validate a validation request and return list of errors"""
        errors = []
        
        if not DocumentValidator.validate_document_id(request.document_id):
            errors.append("Invalid document_id")
        
        if not DocumentValidator.validate_document_url(request.document_url):
            errors.append("Invalid document_url")
        
        if not DocumentValidator.validate_document_type(request.document_type):
            errors.append("Invalid document_type")
        
        return errors

class ResponseModels:
    """Standard response models for API endpoints"""
    
    @staticmethod
    def success_response(data: Any, message: str = "Success") -> Dict[str, Any]:
        """Standard success response format"""
        return {
            "status": "success",
            "message": message,
            "data": data,
            "timestamp": datetime.utcnow().isoformat()
        }
    
    @staticmethod
    def error_response(error: str, error_code: str = "VALIDATION_ERROR", details: Optional[Any] = None) -> Dict[str, Any]:
        """Standard error response format"""
        response = {
            "status": "error",
            "error": error,
            "error_code": error_code,
            "timestamp": datetime.utcnow().isoformat()
        }
        if details:
            response["details"] = details
        return response
    
    @staticmethod
    def validation_response(validation_result: ValidationResult) -> Dict[str, Any]:
        """Response format for signature validation results"""
        return {
            "status": "success",
            "message": "Signature validation completed",
            "data": {
                "document_id": validation_result.document_id,
                "validation_result": validation_result,
                "timestamp": datetime.utcnow().isoformat()
            }
        }
