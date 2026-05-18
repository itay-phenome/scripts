
import boto3
import json
import csv
import os
from datetime import datetime, timedelta, timezone
from dateutil import tz
from botocore.exceptions import ClientError
from pathlib import Path


def get_all_regions():
    ec2 = boto3.client("ec2", region_name="us-east-1")
    regions = ec2.describe_regions(AllRegions=True)
    return [r["RegionName"] for r in regions["Regions"]]

def format_time_utc_israel(dt):
    israel = tz.gettz("Asia/Jerusalem")
    utc_time = dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    il_time = dt.astimezone(israel).strftime("%Y-%m-%d %H:%M:%S IDT")
    return f"{il_time} / {utc_time}"

def get_cloudtrail_events(username, start_time, end_time, region):
    client = boto3.client("cloudtrail", region_name=region)
    events = []
    next_token = None
    while True:
        try:
            kwargs = {
                "StartTime": start_time,
                "EndTime": end_time,
                "MaxResults": 50,
            }
            if username:
                kwargs["LookupAttributes"] = [{"AttributeKey": "Username", "AttributeValue": username}]
            if next_token:
                kwargs["NextToken"] = next_token

            response = client.lookup_events(**kwargs)
            for e in response.get("Events", []):
                e["RegionFallback"] = region
            events.extend(response.get("Events", []))
            next_token = response.get("NextToken")
            if not next_token:
                break
        except Exception as e:
            break
    return events

def parse_event(event):
    try:
        ct = json.loads(event.get("CloudTrailEvent", "{}"))
    except Exception:
        ct = {}

    dt = event["EventTime"]
    event_source = event.get("EventSource", ct.get("eventSource", "N/A"))
    region = event.get("AwsRegion") or event.get("RegionFallback", "N/A")
    if region in ("N/A", None) and "signin.amazonaws.com" in event_source:
        region = "global"

    return {
        "Time": format_time_utc_israel(dt),
        "User": event.get("Username", ct.get("userIdentity", {}).get("userName", "N/A")),
        "Action": event.get("EventName", "N/A"),
        "Service": event_source,
        "Region": region,
        "IP": ct.get("sourceIPAddress", "N/A"),
        "Status": ct.get("errorMessage") or ct.get("errorCode") or "Success",
    }

def write_reports(username, all_events, parsed_events, folder):
    Path(folder).mkdir(parents=True, exist_ok=True)
    base = f"{username}_" if username else "all_users_"

    json_path = os.path.join(folder, f"{base}cloudtrail_events.json")
    txt_path = os.path.join(folder, f"{base}cloudtrail_events.txt")
    csv_path = os.path.join(folder, f"{base}cloudtrail_events.csv")

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(all_events, f, indent=2, default=str)

    with open(txt_path, "w", encoding="utf-8") as f:
        for event in parsed_events:
            f.write(f"[{event['Time']}] {event['Action']} on {event['Service']} | Region: {event['Region']} | IP: {event['IP']} | User: {event['User']} | Status: {event['Status']}\n\n")

    with open(csv_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["Time", "User", "Action", "Service", "Region", "IP", "Status"])
        writer.writeheader()
        for row in parsed_events:
            writer.writerow(row)

def main():
    username = input("Enter IAM username to investigate (or type 'all' for all users): ").strip()
    if username.lower() == "all":
        username = None

    print("Select date range:")
    print("1. Today")
    print("2. Last 24 hours")
    print("3. Custom (DD-MM-YYYY)")
    choice = input("Choice (1/2/3): ").strip()

    now = datetime.now(timezone.utc)
    if choice == "1":
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = now
    elif choice == "2":
        start = now - timedelta(days=1)
        end = now
    elif choice == "3":
        fmt = "%d-%m-%Y"
        start_input = input("Start date (DD-MM-YYYY): ").strip()
        end_input = input("End date (DD-MM-YYYY): ").strip()
        try:
            start = datetime.strptime(start_input, fmt).replace(tzinfo=timezone.utc)
            end = datetime.strptime(end_input, fmt).replace(tzinfo=timezone.utc) + timedelta(days=1)
        except ValueError:
            print("Invalid date format. Exiting.")
            return
    else:
        print("Invalid choice. Exiting.")
        return

    all_events = []
    regions = get_all_regions()
    for region in regions:
        events = get_cloudtrail_events(username, start, end, region)
        all_events.extend(events)

    parsed = [parse_event(e) for e in all_events]
    user_label = username if username else "all_users"
    folder = f"report_{user_label}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    write_reports(username, all_events, parsed, folder)
    print(f"Report written to folder: {folder}")

if __name__ == "__main__":
    main()
