# Signature-Recognition-API-App

This project provides APIs for signature recognition and validation using machine learning models.

## Project Structure

- `Identifi_Code_API/` - Core signature recognition API
- `Identifi_Code_Streamlit/` - Streamlit web interface for the API

## Features

- Signature recognition and classification
- RESTful API endpoints
- Docker containerization
- Streamlit web interface

## Getting Started

1. Navigate to the desired API directory
2. Install dependencies: `pip install -r requirements.txt`
3. Run the application
4. For Docker: `docker build -t signature-api . && docker run -p 8000:8000 signature-api`

## API Endpoints

- `POST /predict` - Submit signature for recognition
- `GET /health` - Health check endpoint

## License

MIT License

