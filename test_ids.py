import sys
from playwright.sync_api import sync_playwright

def check():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        found_any = False
        for i in range(1001, 1015):
            url = f"https://vistarvision.com/appointment_letter?no=VV/26/ICT-II/{i}"
            try:
                page.goto(url, wait_until="networkidle")
                text = page.locator("body").inner_text()
                if "Ref : VV/26/ICT-II" in text or "Date" in text or len(text) > 200:
                    print(f"SUCCESS: ID {i} exists!")
                    found_any = True
                else:
                    print(f"FAILED: ID {i} is empty or missing.")
            except Exception as e:
                print(f"ERROR: ID {i} failed - {e}")
        browser.close()
        
        if found_any:
            print("\nYES! There are candidates with ID > 1000.")
        else:
            print("\nNO! It seems 1000 is the limit.")

if __name__ == "__main__":
    check()
