import json
import boto3

# Initialize the SNS client in the Ireland region
sns = boto3.client('sns', region_name='eu-west-1')

# SNS topic ARN
SNS_TOPIC_ARN = "arn:aws:sns:eu-west-1:524574648815:ConsoleLogin"

def lambda_handler(event, context):
    try:
        # Log incoming event
        print("=== Incoming Event ===")
        print(json.dumps(event, indent=2))

        # Only handle AWS Console Sign In events
        if event.get("detail-type") != "AWS Console Sign In via CloudTrail":
            print("Ignoring non-login event")
            return {"statusCode": 200, "body": "Not a login event"}

        # Extract fields from event
        detail = event.get("detail", {})
        username = detail.get("userIdentity", {}).get("userName", "Unknown")
        ip_address = detail.get("sourceIPAddress", "Unknown IP")
        region = event.get("region", "Unknown region")
        result = detail.get("responseElements", {}).get("ConsoleLogin", "Unknown")
        mfa = detail.get("additionalEventData", {}).get("MFAUsed", "Unknown")
        time = detail.get("eventTime", "Unknown")

        # Build the alert message for SMS/email
        message = (f"🚨 CONSOLE ACCESS ALERT 🚨\n\n"
            f"👤 User: {username}\n"
            f"🌍 Region: {region}\n"
            f"🕓 Time: {time}\n"
            f"📍 Source IP: {ip_address}\n"
            f"🔐 MFA Used: {mfa}\n"
            f"✅ Result: {result}"
        )

        # Publish to SNS
        response = sns.publish(
            TopicArn=SNS_TOPIC_ARN,
            Subject=f"🚨 AWS Console Login Alert from {region}",
            Message=message
        )

        print("Formatted alert sent successfully.")
        print("SNS response:", response)

        return {"statusCode": 200, "body": "Formatted alert sent."}

    except Exception as e:
        print("Error occurred:", str(e))
        return {"statusCode": 500, "body": f"Error: {str(e)}"}