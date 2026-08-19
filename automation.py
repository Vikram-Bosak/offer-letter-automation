import os
import re
import time

# Google APIs
import gspread
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

# Web scraping & PDF
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup

# ==========================================
# CONFIGURATION - PLEASE UPDATE THESE VALUES
# ==========================================
CREDENTIALS_FILE = 'credentials.json'  # Saved automatically
GOOGLE_SHEET_URL = 'https://docs.google.com/spreadsheets/d/1PkC4sfRTk1E1shoYzAD5tJdqpkBd4ElNX_5hZNNxDy0/edit?usp=sharing'
DRIVE_FOLDER_ID = '1zy-VUyCC8ejOQ3S2wP3-D24xKwlKiHMm'

# ==========================================
# SCRAPING RANGE (Edit these as needed)
# ==========================================
START_NUMBER = 1
END_NUMBER = 1000
BASE_URL = 'https://vistarvision.com/appointment_letter?no=VV/26/ICT-II/'

SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]

def extract_details_from_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    text = soup.get_text(separator=' ')
    
    details = {
        'candidate_name': '',
        'father_name': '',
        'ref_number': '',
        'udise_code': '',
        'district': '',
        'block': '',
        'school': ''
    }
    
    # 1. Candidate Name & Father's Name
    span_tags = soup.find_all('span')
    for span in span_tags:
        if 'Georgia' in span.get('style', '') or 'font-family' in span.get('style', ''):
            lines = span.get_text(separator='\n').split('\n')
            if len(lines) > 0:
                details['candidate_name'] = lines[0].strip()
            if len(lines) > 1 and 'C/O-' in lines[1]:
                details['father_name'] = lines[1].replace('C/O-', '').strip()
            break

    # 2. Ref Number
    ref_div = soup.find('div', string=re.compile(r'Ref\s*:'))
    if ref_div:
        details['ref_number'] = ref_div.get_text().strip()

    # 3. UDISE Code
    udise_match = re.search(r'\(UDISECode:\s*(\d+)\)', text)
    if udise_match:
        details['udise_code'] = udise_match.group(1)

    # 4. District
    district_match = re.search(r'जिला:\s*([A-Z\s]+?)\s*(?:में|को)', text)
    if district_match:
        details['district'] = district_match.group(1).strip()

    # 5. Block
    block_match = re.search(r'प्रखंड(?:ः|:)?\s*([A-Z\s]+?)\s*,?\s*जिला:', text)
    if block_match:
        details['block'] = block_match.group(1).strip()

    # 6. School Name
    school_match = re.search(r'विद्यालय:\s*([A-Z\s]+?)\s*\(UDISECode', text)
    if school_match:
        details['school'] = school_match.group(1).strip()
    else:
        school_match2 = re.search(r'प्राचार्य/प्रधानाध्यापक:\s*([A-Z\s]+?)\s*\(UDISECode', text)
        if school_match2:
            details['school'] = school_match2.group(1).strip()

    return details

def upload_to_drive(drive_service, filepath, filename):
    pass # Replaced inline in the loop

def setup_sheet_headers(sheet):
    headers = [
        "S.No.", "Candidate Name", "Father's Name", "Block", "District", 
        "School Name", "UDISE Code", "Letter Number / Ref", 
        "Original Letter Link", "Google Drive File Name", 
        "Google Drive Public URL", "Status"
    ]
    # Check if headers exist, if not write them
    first_row = sheet.row_values(1)
    if not first_row or first_row[0] != "S.No.":
        sheet.insert_row(headers, 1)

def get_processed_ids(sheet):
    """Returns a set of sequence numbers already successfully uploaded in the sheet."""
    records = sheet.get_all_records()
    processed = set()
    for row in records:
        if row.get('Status') == 'Uploaded' and 'Original Letter Link' in row:
            link = str(row['Original Letter Link'])
            match = re.search(r'/(\d+)$', link)
            if match:
                processed.add(int(match.group(1)))
    return processed

def main():
    print("Authenticating with Google...")
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)
    drive_service = build('drive', 'v3', credentials=creds)

    print("Opening Google Sheet...")
    sheet = gc.open_by_url(GOOGLE_SHEET_URL).sheet1
    setup_sheet_headers(sheet)
    
    # Get already processed IDs to skip them
    processed_ids = get_processed_ids(sheet)
    next_row_index = len(sheet.get_all_values()) + 1
    
    # Start Playwright for PDF generation
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()

        for current_id in range(START_NUMBER, END_NUMBER + 1):
            target_url = f"{BASE_URL}{current_id}"
            
            if current_id in processed_ids:
                print(f"ID {current_id} already uploaded. Skipping.")
                continue

            print(f"Processing ID {current_id} - Link: {target_url}")
            
            try:
                # 1. Download PDF using Playwright
                page.emulate_media(media="print")
                page.goto(target_url, wait_until="networkidle", timeout=60000)
                html_content = page.content()
                details = extract_details_from_html(html_content)
                
                if not details['candidate_name'] or not details['ref_number']:
                    print(f"No candidate data found for ID {current_id}. Skipping to next.")
                    continue
                
                # Format Filename
                safe_ref = details['ref_number'].replace('Ref : ', '').strip()
                safe_filename = safe_ref.replace('/', '-') + '.pdf'
                
                drive_url = ""
                status_msg = "Uploaded"
                
                try:
                    # Generate PDF locally
                    temp_pdf_path = f"temp_{safe_filename}"
                    page.pdf(path=temp_pdf_path, format="A4", print_background=True)
                    
                    # 2. Upload to Google Drive (with supportsAllDrives=True)
                    print(f"  Uploading {safe_filename} to Drive...")
                    file_metadata = {
                        'name': safe_filename,
                        'parents': [DRIVE_FOLDER_ID]
                    }
                    media = MediaFileUpload(temp_pdf_path, mimetype='application/pdf', resumable=True)
                    file = drive_service.files().create(body=file_metadata, media_body=media, fields='id, webViewLink', supportsAllDrives=True).execute()
                    file_id = file.get('id')
                    
                    permission = {
                        'type': 'anyone',
                        'role': 'reader'
                    }
                    drive_service.permissions().create(fileId=file_id, body=permission, supportsAllDrives=True).execute()
                    drive_url = file.get('webViewLink')
                    
                    if os.path.exists(temp_pdf_path):
                        os.remove(temp_pdf_path)
                except Exception as upload_error:
                    status_msg = f"Failed Upload: {str(upload_error)[:80]}"
                    print(f"Drive Upload Error for ID {current_id}: {upload_error}")
                
                # 3. Update Google Sheet with whatever details we have
                print(f"  Adding to Google Sheet...")
                row_data = [
                    current_id, details['candidate_name'], details['father_name'],
                    details['block'], details['district'], details['school'],
                    details['udise_code'], details['ref_number'], target_url,
                    safe_filename, drive_url, status_msg
                ]
                
                sheet.insert_row(row_data, next_row_index)
                next_row_index += 1
                
                print(f"ID {current_id}: Processed (Status: {status_msg})")
                time.sleep(2)

            except Exception as e:
                error_msg = f"Failed Processing: {str(e)}"
                print(f"ID {current_id}: {error_msg}")
                # Log total failure to sheet (if page completely fails)
                fail_row = [
                    current_id, "", "", "", "", "", "", "", target_url, "", "", error_msg[:100]
                ]
                sheet.insert_row(fail_row, next_row_index)
                next_row_index += 1

        browser.close()
        print("Automation process completed!")

if __name__ == "__main__":
    main()
