"""
Test if R2 images are accessible and configure public access if needed
"""
import requests
import sys
sys.path.insert(0, '.')

from cloud_storage import s3_client, R2_BUCKET_NAME, R2_PUBLIC_URL

def test_image_access():
    """Test if a migrated image is publicly accessible"""
    test_url = f"{R2_PUBLIC_URL}/252684_101591246600120_4397727_n.jpg"
    
    print(f"Testing image access: {test_url}")
    
    try:
        response = requests.get(test_url, timeout=10)
        if response.status_code == 200:
            print("SUCCESS! Images are already publicly accessible!")
            return True
        else:
            print(f"Image not accessible. Status code: {response.status_code}")
            return False
    except Exception as e:
        print(f"Error accessing image: {e}")
        return False

def make_bucket_public():
    """Set bucket policy to allow public read access"""
    print("\nAttempting to make bucket public via policy...")
    
    # Public read policy for R2
    bucket_policy = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "PublicRead",
                "Effect": "Allow",
                "Principal": "*",
                "Action": "s3:GetObject",
                "Resource": f"arn:aws:s3:::{R2_BUCKET_NAME}/*"
            }
        ]
    }
    
    import json
    policy_json = json.dumps(bucket_policy)
    
    try:
        s3_client.put_bucket_policy(
            Bucket=R2_BUCKET_NAME,
            Policy=policy_json
        )
        print("Bucket policy set successfully!")
        return True
    except Exception as e:
        print(f"Error setting bucket policy: {e}")
        print("\nNote: You may need to enable public access in Cloudflare R2 dashboard first.")
        return False

def set_bucket_cors():
    """Configure CORS for the bucket"""
    print("\nConfiguring CORS...")
    
    cors_config = {
        'CORSRules': [
            {
                'AllowedOrigins': ['*'],
                'AllowedMethods': ['GET', 'HEAD'],
                'AllowedHeaders': ['*'],
                'MaxAgeSeconds': 3000
            }
        ]
    }
    
    try:
        s3_client.put_bucket_cors(
            Bucket=R2_BUCKET_NAME,
            CORSConfiguration=cors_config
        )
        print("CORS configured successfully!")
        return True
    except Exception as e:
        print(f"CORS configuration failed: {e}")
        return False

if __name__ == "__main__":
    print("=" * 60)
    print("R2 PUBLIC ACCESS CONFIGURATION")
    print("=" * 60)
    
    # Step 1: Test current access
    if test_image_access():
        print("\nNo configuration needed - images are already accessible!")
        sys.exit(0)
    
    # Step 2: Try setting bucket policy
    print("\nImages are not publicly accessible yet.")
    print("Attempting to configure public access...")
    
    policy_success = make_bucket_public()
    cors_success = set_bucket_cors()
    
    # Step 3: Test again
    print("\nTesting access after configuration...")
    if test_image_access():
        print("\nSUCCESS! Bucket is now public!")
    else:
        print("\nCould not enable public access automatically.")
        print("\nPlease try these steps in Cloudflare dashboard:")
        print("1. Go to R2 > chitalishte-uploads")
        print("2. Look for 'Bucket Configuration' or 'Access'")
        print("3. Enable 'Public Access' or 'Allow Public Reads'")
        print("4. Or contact Cloudflare support for help")
