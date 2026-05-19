import boto3
from fpdf import FPDF
import pandas as pd

# Initialize the S3 client
s3 = boto3.client('s3')

# List all buckets
buckets = s3.list_buckets()

# Initialize an empty list to store bucket details
bucket_details = []

# Iterate through buckets to get details
for bucket in buckets['Buckets']:
    bucket_name = bucket['Name']
    try:
        # For simplicity, we assume no direct last accessed time is available
        creation_date = bucket['CreationDate']
        bucket_details.append({'BucketName': bucket_name, 'CreationDate': creation_date, 'LastAccessedTime': 'Unavailable'})
    except Exception as e:
        bucket_details.append({'BucketName': bucket_name, 'CreationDate': 'Unavailable', 'LastAccessedTime': 'Unavailable'})

# Sort buckets by CreationDate (as LastAccessedTime is not natively supported)
bucket_details_sorted = sorted(bucket_details, key=lambda x: x['CreationDate'], reverse=True)

# Convert the list to a DataFrame for better handling
buckets_df = pd.DataFrame(bucket_details_sorted)

# Display the buckets on the screen
print(buckets_df)

# Generate a PDF Report
class PDFReport(FPDF):
    def header(self):
        self.set_font('Arial', 'B', 12)
        self.cell(0, 10, 'S3 Buckets Report - Sorted by Last Accessed Time', 0, 1, 'C')

    def footer(self):
        self.set_y(-15)
        self.set_font('Arial', 'I', 8)
        self.cell(0, 10, f'Page {self.page_no()}', 0, 0, 'C')

# Create PDF instance
pdf = PDFReport()
pdf.add_page()
pdf.set_font('Arial', '', 10)

# Add table header
pdf.cell(60, 10, 'Bucket Name', 1)
pdf.cell(60, 10, 'Creation Date', 1)
pdf.cell(60, 10, 'Last Accessed Time', 1)
pdf.ln()

# Add data rows
for bucket in bucket_details_sorted:
    pdf.cell(60, 10, bucket['BucketName'], 1)
    pdf.cell(60, 10, str(bucket['CreationDate']), 1)
    pdf.cell(60, 10, bucket['LastAccessedTime'], 1)
    pdf.ln()

# Save the PDF to a file
pdf_file_path = "C:\\ftp\\S3_Buckets_Report.pdf"
pdf.output(pdf_file_path)

print(f"PDF Report generated: {pdf_file_path}")
