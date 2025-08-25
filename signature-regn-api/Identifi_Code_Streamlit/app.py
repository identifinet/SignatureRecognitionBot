import streamlit as st
import requests
import json
from PIL import Image
import io
import base64

st.set_page_config(
    page_title="Signature Recognition App",
    page_icon="✍️",
    layout="wide"
)

st.title("✍️ Signature Recognition & Analysis")
st.markdown("Upload a signature image to analyze and classify it using our AI model.")

# Sidebar for API configuration
with st.sidebar:
    st.header("API Configuration")
    api_url = st.text_input(
        "API Base URL",
        value="http://localhost:8000",
        help="Base URL for the Signature Recognition API"
    )
    
    st.markdown("---")
    st.markdown("### Features")
    st.markdown("- Signature Classification")
    st.markdown("- Image Analysis")
    st.markdown("- Confidence Scoring")
    st.markdown("- Characteristic Detection")

# Main content area
col1, col2 = st.columns([1, 1])

with col1:
    st.header("📤 Upload Signature")
    uploaded_file = st.file_uploader(
        "Choose a signature image file",
        type=['png', 'jpg', 'jpeg'],
        help="Upload a clear image of a signature"
    )
    
    if uploaded_file is not None:
        # Display the uploaded image
        image = Image.open(uploaded_file)
        st.image(image, caption="Uploaded Signature", use_column_width=True)
        
        # Image info
        st.info(f"**File:** {uploaded_file.name}")
        st.info(f"**Size:** {image.size[0]} x {image.size[1]} pixels")
        st.info(f"**Format:** {image.format}")

with col2:
    st.header("🔍 Analysis Results")
    
    if uploaded_file is not None:
        # Create tabs for different analysis types
        tab1, tab2 = st.tabs(["📊 Prediction", "🔬 Detailed Analysis"])
        
        with tab1:
            if st.button("🚀 Get Prediction", type="primary"):
                with st.spinner("Analyzing signature..."):
                    try:
                        # Prepare file for API
                        files = {"file": uploaded_file.getvalue()}
                        
                        # Make API call
                        response = requests.post(f"{api_url}/predict", files=files)
                        
                        if response.status_code == 200:
                            result = response.json()
                            
                            # Display results
                            st.success("✅ Analysis Complete!")
                            
                            # Confidence meter
                            confidence = result.get("confidence", 0)
                            st.metric("Confidence Score", f"{confidence:.1%}")
                            
                            # Signature type
                            sig_type = result.get("signature_type", "Unknown")
                            st.info(f"**Signature Type:** {sig_type}")
                            
                            # Characteristics
                            if "characteristics" in result:
                                st.subheader("Characteristics")
                                chars = result["characteristics"]
                                for key, value in chars.items():
                                    st.write(f"**{key.replace('_', ' ').title()}:** {value}")
                            
                            # Raw JSON
                            with st.expander("📋 Raw API Response"):
                                st.json(result)
                                
                        else:
                            st.error(f"❌ API Error: {response.status_code}")
                            st.code(response.text)
                            
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")
        
        with tab2:
            if st.button("🔬 Analyze Image Details"):
                with st.spinner("Analyzing image details..."):
                    try:
                        # Prepare file for API
                        files = {"file": uploaded_file.getvalue()}
                        
                        # Make API call
                        response = requests.post(f"{api_url}/analyze", files=files)
                        
                        if response.status_code == 200:
                            result = response.json()
                            
                            st.success("✅ Analysis Complete!")
                            
                            # Display analysis results
                            col_a, col_b = st.columns(2)
                            
                            with col_a:
                                st.metric("Width", f"{result.get('image_dimensions', {}).get('width', 0)} px")
                                st.metric("Height", f"{result.get('image_dimensions', {}).get('height', 0)} px")
                                st.metric("Aspect Ratio", f"{result.get('aspect_ratio', 0):.2f}")
                            
                            with col_b:
                                st.metric("File Size", f"{result.get('file_size_bytes', 0)} bytes")
                                st.info(f"**Format:** {result.get('format', 'Unknown')}")
                                st.info(f"**Color Mode:** {result.get('mode', 'Unknown')}")
                            
                            # Raw JSON
                            with st.expander("📋 Raw Analysis Response"):
                                st.json(result)
                                
                        else:
                            st.error(f"❌ API Error: {response.status_code}")
                            st.code(response.text)
                            
                    except Exception as e:
                        st.error(f"❌ Error: {str(e)}")

# Footer
st.markdown("---")
st.markdown(
    "Built with ❤️ using FastAPI and Streamlit | "
    "[API Documentation](https://fastapi.tiangolo.com/) | "
    "[Streamlit Docs](https://docs.streamlit.io/)"
)
