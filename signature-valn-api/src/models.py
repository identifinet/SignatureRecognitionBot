from pydantic import BaseModel, HttpUrl
from typing import Optional
from typing import List
from uuid import UUID

class SignatureValidationRequest(BaseModel):
    taskId: str
    source: str = "Identifi Command Center"
    apiEndpoint: HttpUrl
    smartFolderId: int
    docAttributeId: int
    confidenceLevel: Optional[float] = 0.5
    resultAttributeId: Optional[int] = None
    apiKey: str

class SignatureValidationResponse(BaseModel):
    taskId: str
    source: str = "Identifi Signature Validator"
    status: str
    message: str
    sourceFiles: int
    stored: int
    errored: int
    unknown: int

class SignatureRecognitionWorkflowModel(BaseModel):
    """
    Workflow information related to the signature recognition request.
    """
    workflowPlanId: int
    workItemId: int

class SignatureRecognitionDocumentModel(BaseModel):
    """
    Document metadata and content for signature recognition.
    """
    documentNumber: int
    documentId: int
    applicationId: int
    pageCount: int
    signaturesCompleted: int
    signatureCount: int
    fileName: str
    file: bytes
    content_length: int

# class SignatureRecognitionRequestModel(BaseModel):
#     """
#     Request model for submitting documents for signature recognition.
#     """
#     taskId: str
#     source: str = "Identifi Command Center"
#     confidenceLevel: Optional[float] = 0.5
#     signatureRecognitionWorkflowModel: SignatureRecognitionWorkflowModel
#     documents: List[SignatureRecognitionDocumentModel]

# class SignatureRecognitionRequestModel(BaseModel):
#     blobURL: str