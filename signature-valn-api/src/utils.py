import requests
import base64
import json
import os
# API endpoint
# get_document_ids_url = "https://demosales.identifi.net/api/documents/smart-folder/124/export-ids"

# Replace 'your_api_key_here' with the actual API key
identifi_api_key = os.getenv("IDENTIFI_API_KEY")

# Set headers with the X-API-KEY
headers = {
    "X-API-KEY": identifi_api_key
}

def delete_notes(smartFolderID, text):

    try:
        # Make the GET request
        response = requests.get(f"https://demosales.identifi.net/api/documents/smart-folder/{smartFolderID}/export-ids", headers=headers)
        
        # Check if the request was successful
        response.raise_for_status()
        
        documents = list(response.json())
        # print(lst)
        for doc in documents:
            document_id = doc.get("documentId")
            application_id = doc.get("applicationId")

            notes_response = requests.get(f'https://demosales.identifi.net/api/document/{application_id}/{document_id}', headers=headers)
            notes = notes_response.json()["notes"]
            print(f"Application ID: {application_id} and Document ID: {document_id}")
            print(notes)
            

            # for note_to_delete in notes:
            # records_to_delete = [note['id'] for note in notes if note['userName'] == 'hsubramanian']

            # Using specified text:
            records_to_delete = [note['id'] for note in notes if text in note['text']]
                
            print(records_to_delete)
            for record in records_to_delete:
                print(record)
                del_response = requests.delete(f'https://demosales.identifi.net/api/document/{application_id}/{document_id}/notes/{record}', headers=headers)
                # Check if the request was successful
                del_response.raise_for_status()
                
                # Print the response content
                print("Response Status Code:", del_response.status_code)


    except requests.exceptions.HTTPError as http_err:
        print(f"HTTP error occurred: {http_err}")
    except requests.exceptions.RequestException as err:
        print(f"Error occurred: {err}")