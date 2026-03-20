"""
Cloud Storage Helper - Handles file uploads/deletes to Cloudflare R2
"""
import os
from urllib.parse import urlparse

import boto3
from botocore.client import Config
from dotenv import load_dotenv

load_dotenv()

# R2 Configuration
R2_ACCESS_KEY = os.getenv('R2_ACCESS_KEY')
R2_SECRET_KEY = os.getenv('R2_SECRET_KEY')
R2_BUCKET_NAME = os.getenv('R2_BUCKET_NAME')
R2_ENDPOINT = os.getenv('R2_ENDPOINT')
R2_PUBLIC_URL = os.getenv('R2_PUBLIC_URL')

# Initialize S3 client for R2
s3_client = boto3.client(
    's3',
    endpoint_url=R2_ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
   aws_secret_access_key=R2_SECRET_KEY,
    config=Config(signature_version='s3v4'),
    region_name='auto'  # R2 uses 'auto' as region
)

def upload_file_to_cloud(file_data, filename, content_type='image/jpeg'):
    """
    Upload a file to Cloudflare R2
    
    Args:
        file_data: File data (bytes or file-like object)
        filename: Name to save file as in R2
        content_type: MIME type of the file
    
    Returns:
        str: Public URL of the uploaded file
    """
    try:
        s3_client.put_object(
            Bucket=R2_BUCKET_NAME,
            Key=filename,
            Body=file_data,
            ContentType=content_type
        )
        
        # Return public URL
        public_url = f"{R2_PUBLIC_URL}/{filename}"
        return public_url
    
    except Exception as e:
        print(f"Error uploading to R2: {str(e)}")
        raise e

def delete_file_from_cloud(filename):
    """
    Delete a file from Cloudflare R2
    
    Args:
        filename: Name of file to delete from R2
    
    Returns:
        bool: True if successful
    """
    try:
        s3_client.delete_object(
            Bucket=R2_BUCKET_NAME,
            Key=filename
        )
        return True
    
    except Exception as e:
        print(f"Error deleting from R2: {str(e)}")
        return False

def extract_filename_from_url(url):
    """
    Extract filename from a full R2 URL
    
    Args:
        url: Full URL like 'https://pub-xxx.r2.dev/image.jpg'
    
    Returns:
        str: Just the filename 'image.jpg'
    """
    if not url:
        return None

    normalized_public_url = (R2_PUBLIC_URL or '').rstrip('/')
    if normalized_public_url and url.startswith(f"{normalized_public_url}/"):
        return url.split('/')[-1]

    parsed = urlparse(url)
    if parsed.scheme or parsed.netloc:
        return None

    return url
