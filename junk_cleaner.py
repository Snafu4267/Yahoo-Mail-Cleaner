#!/usr/bin/env python3
"""
Yahoo Mail Junk Cleaner - Automatically delete adult spam from Junk + Inbox
Run on GitHub Actions every 30 minutes, or manually: python junk_cleaner.py
"""

import imaplib
import email
import os
import sys
import re
from email.header import decode_header

# Keywords to match (case-insensitive)
KEYWORDS = [
    'sex', 'sexual', 'intercourse', 'adult', 'xxx', 'porn',
    'erotic', 'naked', 'nude', 'hookup', 'escort', 'onlyfans', 'fuck'
]

YAHOO_IMAP = 'imap.mail.yahoo.com'
YAHOO_PORT = 993


def build_keyword_patterns():
    """Compile boundary-aware keyword regexes to reduce false positives."""
    patterns = {}
    for keyword in KEYWORDS:
        patterns[keyword] = re.compile(rf'\b{re.escape(keyword)}\b', re.IGNORECASE)
    return patterns


KEYWORD_PATTERNS = build_keyword_patterns()
RE_SUBJECT_PATTERN = re.compile(r'\bre\s*:', re.IGNORECASE)


def get_text(msg_part):
    """Extract text from email part, decode if needed."""
    try:
        if msg_part.get_content_type() == 'text/plain':
            return msg_part.get_payload(decode=True).decode('utf-8', errors='ignore')
    except Exception:
        pass
    return ''


def extract_subject_and_body(msg):
    """Extract subject and body text from email message."""
    subject = ''
    body = ''

    # Get subject
    if msg['Subject']:
        decoded_parts = decode_header(msg['Subject'])
        subject_parts = []
        for part, encoding in decoded_parts:
            if isinstance(part, bytes):
                subject_parts.append(part.decode(encoding or 'utf-8', errors='ignore'))
            else:
                subject_parts.append(part)
        subject = ' '.join(subject_parts)

    # Get body
    if msg.is_multipart():
        for part in msg.walk():
            body += get_text(part)
    else:
        body = get_text(msg)

    return subject, body


def matches_keyword(text, keywords=None):
    """Check if text contains any full keyword token (case-insensitive)."""
    active_keywords = keywords if keywords is not None else KEYWORDS
    for keyword in active_keywords:
        pattern = KEYWORD_PATTERNS[keyword]
        if pattern.search(text):
            return keyword
    return None


def matches_subject_rule(subject):
    """Match subjects like Re:, RE:, Re : etc."""
    return bool(RE_SUBJECT_PATTERN.search(subject or ''))


def parse_list_folder_name(line):
    """Extract folder name from an IMAP LIST response line."""
    # Prefer quoted folder names to preserve spaces.
    quoted = re.findall(r'"([^"]+)"', line)
    if quoted:
        return quoted[-1]
    # Fallback for unquoted names: take the text after the final delimiter.
    parts = line.rsplit(') ', 1)
    if len(parts) == 2:
        remainder = parts[1].strip()
        if ' ' in remainder:
            return remainder.split(' ', 1)[1].strip('"')
        return remainder.strip('"')
    return line.strip()


def find_junk_folders(mail):
    """Find all likely junk folders by IMAP flags and common names."""
    junk_folders = []
    seen = set()
    try:
        status, data = mail.list()
        if status == 'OK':
            for raw in data:
                if not raw:
                    continue
                line = raw.decode('utf-8', errors='ignore')
                folder = parse_list_folder_name(line)
                if not folder:
                    continue
                folder_lower = folder.lower()
                is_junkish = '\\junk' in line.lower() or any(
                    token in folder_lower for token in ['junk', 'bulk', 'spam']
                )
                if is_junkish and folder not in seen:
                    junk_folders.append(folder)
                    seen.add(folder)
    except Exception as e:
        print(f"⚠ Could not inspect folder list: {e}")

    if junk_folders:
        return junk_folders
    return ['Bulk Mail', 'Junk']


def delete_from_folder(mail, folder_name, search_subject_only=False, keywords=None):
    """
    Search folder for keywords and delete matches.

    Args:
        mail: IMAP connection
        folder_name: IMAP folder name (e.g., 'Bulk Mail', 'INBOX')
        search_subject_only: If True, only search subject line (safer for Inbox)

    Returns:
        (count_deleted, subjects_deleted)
    """
    try:
        status, _ = mail.select(folder_name)
        if status != 'OK':
            print(f"❌ Could not select {folder_name}")
            return 0, []
    except Exception as e:
        print(f"❌ Error selecting {folder_name}: {e}")
        return 0, []

    deleted_subjects = []

    try:
        # Search for emails matching keywords
        email_ids = set()

        active_keywords = keywords if keywords is not None else KEYWORDS
        for keyword in active_keywords:
            # Search subject
            status, data = mail.search(None, f'(SUBJECT "{keyword}")')
            if status == 'OK' and data[0]:
                email_ids.update(data[0].split())

            # Search body (only if not restricted)
            if not search_subject_only:
                status, data = mail.search(None, f'(BODY "{keyword}")')
                if status == 'OK' and data[0]:
                    email_ids.update(data[0].split())

        if not email_ids:
            print(f"  ✓ {folder_name}: No matches found")
            return 0, []

        print(f"  📧 {folder_name}: Found {len(email_ids)} matches, fetching details...")

        # Verify each email contains a keyword before deleting
        confirmed_ids = []
        for email_id in email_ids:
            try:
                status, data = mail.fetch(email_id, '(RFC822)')
                if status == 'OK':
                    msg = email.message_from_bytes(data[0][1])
                    subject, body = extract_subject_and_body(msg)

                    matched_keyword = None
                    if matches_subject_rule(subject):
                        matched_keyword = 're:'
                    elif matches_keyword(subject, active_keywords):
                        matched_keyword = matches_keyword(subject, active_keywords)
                    elif matches_keyword(body, active_keywords):
                        matched_keyword = matches_keyword(body, active_keywords)

                    if matched_keyword:
                        confirmed_ids.append(email_id)
                        deleted_subjects.append(f'[{matched_keyword}] {subject[:60]}')
            except Exception as e:
                print(f"    ⚠ Error verifying email {email_id}: {e}")

        if not confirmed_ids:
            print(f"  ✓ {folder_name}: No confirmed matches")
            return 0, []

        # Delete confirmed emails
        for email_id in confirmed_ids:
            mail.store(email_id, '+FLAGS', '\\Deleted')

        mail.expunge()
        count = len(confirmed_ids)
        print(f"  🗑 {folder_name}: Deleted {count} email(s)")

        return count, deleted_subjects

    except Exception as e:
        print(f"❌ Error processing {folder_name}: {e}")
        return 0, []


def main():
    """Connect to Yahoo Mail and clean junk."""
    email_addr = os.environ.get('YAHOO_EMAIL')
    app_password = os.environ.get('YAHOO_APP_PASSWORD')

    if not email_addr or not app_password:
        print("❌ Missing YAHOO_EMAIL or YAHOO_APP_PASSWORD environment variables")
        sys.exit(1)

    print(f"\n🔧 Connecting to Yahoo Mail ({email_addr})...")

    try:
        mail = imaplib.IMAP4_SSL(YAHOO_IMAP, YAHOO_PORT)
        mail.login(email_addr, app_password)
        print("✅ Connected!")
    except imaplib.IMAP4.error as e:
        print(f"❌ Login failed: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"❌ Connection error: {e}")
        sys.exit(1)

    print("\n📋 Scanning folders...\n")

    total_deleted = 0
    all_subjects = []

    # Scan junk folders (aggressive: subject + body)
    junk_folders = find_junk_folders(mail)
    print(f"  ℹ Using junk folders: {', '.join(junk_folders)}")
    for junk_folder in junk_folders:
        count, subjects = delete_from_folder(
            mail, junk_folder, search_subject_only=False, keywords=KEYWORDS
        )
        total_deleted += count
        all_subjects.extend(subjects)

    # Scan Inbox (conservative: subject only)
    inbox_keywords = [k for k in KEYWORDS if k != 'adult']
    count, subjects = delete_from_folder(mail, 'INBOX', search_subject_only=True, keywords=inbox_keywords)
    total_deleted += count
    all_subjects.extend(subjects)

    mail.logout()

    print(f"\n{'='*60}")
    print(f"✅ Cleanup complete! Deleted {total_deleted} email(s)")
    if all_subjects:
        print(f"\n📌 Deleted subjects:")
        for subject in all_subjects[:10]:  # Show first 10
            print(f"   {subject}")
        if len(all_subjects) > 10:
            print(f"   ... and {len(all_subjects) - 10} more")
    print(f"{'='*60}\n")


if __name__ == '__main__':
    main()
