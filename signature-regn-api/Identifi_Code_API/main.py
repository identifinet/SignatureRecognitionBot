from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
import numpy as np
from PIL import Image
import io
import base64
import json
from typing import Dict, Any

app = FastAPI(title="Signature Recognition API", version="1.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Signature Recognition API is running"}

@app.get("/health")
async def health_check():
    return {"status": "healthy", "service": "signature-recognition-api"}

@app.post("/predict")
async def predict_signature(file: UploadFile = File(...)):
    """
    Predict signature characteristics from uploaded image
    """
    try:
        # Validate file type
        if not file.content_type.startswith('image/'):
            raise HTTPException(status_code=400, detail="File must be an image")
        
        # Read and process image
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        
        # Convert to grayscale and resize
        image = image.convert('L')
        image = image.resize((224, 224))
        
        # Convert to numpy array
        img_array = np.array(image)
        
        # Normalize pixel values
        img_array = img_array / 255.0
        
        # Mock prediction (replace with actual ML model)
        prediction = {
            "signature_type": "handwritten",
            "confidence": 0.85,
            "characteristics": {
                "stroke_width": "medium",
                "style": "cursive",
                "complexity": "moderate"
            },
            "processed_image_size": f"{img_array.shape[0]}x{img_array.shape[1]}"
        }
        
        return prediction
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing image: {str(e)}")

@app.post("/analyze")
async def analyze_signature(file: UploadFile = File(...)):
    """
    Detailed signature analysis
    """
    try:
        contents = await file.read()
        image = Image.open(io.BytesIO(contents))
        
        # Basic image analysis
        width, height = image.size
        aspect_ratio = width / height
        
        analysis = {
            "image_dimensions": {"width": width, "height": height},
            "aspect_ratio": round(aspect_ratio, 2),
            "file_size_bytes": len(contents),
            "format": image.format,
            "mode": image.mode,
            "analysis_timestamp": "2024-01-01T00:00:00Z"
        }
        
        return analysis
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error analyzing image: {str(e)}")

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
