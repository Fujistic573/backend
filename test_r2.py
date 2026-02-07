"""
Test R2 Cloud Storage Connection
"""
import sys
sys.path.insert(0, '.')

from cloud_storage import upload_file_to_cloud, delete_file_from_cloud

def test_upload():
    print("Testing Cloudflare R2 connection...")
    
    try:
        # Test uploading a small text file
        test_content = b"Hello from Chitalishte! This is a test."
        test_filename = "test_connection_check.txt"
        
        result_url = upload_file_to_cloud(test_content, test_filename, "text/plain")
        print(f"SUCCESS! Uploaded to: {result_url}")
        
        # Clean up - delete test file
        print("Cleaning up test file...")
        delete_file_from_cloud(test_filename)
        print("Test file deleted.")
        
        print("\n✅ R2 Cloud Storage is working correctly!")
        return True
        
    except Exception as e:
        print(f"ERROR: {str(e)}")
        print("\n❌ R2 connection failed. Check your credentials in .env")
        return False

if __name__ == "__main__":
    test_upload()
