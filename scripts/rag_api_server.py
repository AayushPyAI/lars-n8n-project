#!/usr/bin/env python3
"""
RAG API Server
Simple HTTP server for n8n to call for processing emails and storing in RAG database.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
import re
import hashlib
import json
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent))

from rag_database import RAGDatabase
from email_cleaner import clean_email_body
from classify_email import classify_email

app = Flask(__name__)
CORS(app)  # Allow n8n to call this API

# Initialize RAG database
# Use absolute path to ensure correct location
import os
import time
RAG_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rag_data")
rag_db = RAGDatabase(db_path=RAG_DB_PATH, ollama_url="http://localhost:11434")
print(f"RAG Database initialized at: {RAG_DB_PATH}")

# Simple deduplication cache (email_id -> timestamp)
# Prevents processing the same email multiple times within a short window
processed_emails = {}
DUPLICATE_WINDOW = 300  # 5 minutes (300 seconds) - Change to 30 for testing

# Draft storage (draft_id -> draft_data)
# Stores created drafts so we can match them with sent emails
drafts_storage = {}
DRAFTS_FILE = os.path.join(RAG_DB_PATH, "drafts_storage.json")

# Load existing drafts
def load_drafts():
    """Load drafts from disk."""
    global drafts_storage
    if os.path.exists(DRAFTS_FILE):
        try:
            with open(DRAFTS_FILE, 'r', encoding='utf-8') as f:
                drafts_storage = json.load(f)
            print(f"📋 Loaded {len(drafts_storage)} stored drafts", file=sys.stderr)
        except Exception as e:
            print(f"⚠️ Error loading drafts: {e}", file=sys.stderr)
            drafts_storage = {}

def save_drafts():
    """Save drafts to disk."""
    try:
        with open(DRAFTS_FILE, 'w', encoding='utf-8') as f:
            json.dump(drafts_storage, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"⚠️ Error saving drafts: {e}", file=sys.stderr)

# Load drafts on startup
load_drafts()


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "message": "RAG API Server is running"})


@app.route('/clear-cache', methods=['POST', 'GET'])
def clear_cache():
    """Clear deduplication cache (useful for testing)."""
    global processed_emails
    count = len(processed_emails)
    processed_emails = {}
    return jsonify({
        "success": True,
        "message": f"Cleared {count} entries from deduplication cache"
    })


@app.route('/process-email', methods=['POST'])
def process_email():
    """
    Process a single email: clean, classify, and add to RAG database.
    
    Expected JSON:
    {
        "subject": "Email subject",
        "from": "sender@example.com",
        "to": "recipient@example.com",
        "body": "Email body text",
        "bodyPreview": "Preview text",
        "receivedDateTime": "2024-01-01T00:00:00Z",
        "user_id": "user1"
    }
    """
    try:
        data = request.json
        
        # Prepare email data
        email_data = {
            'subject': data.get('subject', ''),
            'from': data.get('from', ''),
            'to': data.get('to', '') or (data.get('toRecipients', [{}])[0].get('emailAddress', {}).get('address', '') if isinstance(data.get('toRecipients'), list) else ''),
            'body': data.get('body') or data.get('bodyContent') or data.get('bodyPreview', ''),
            'receivedDateTime': data.get('receivedDateTime') or data.get('sentDateTime', ''),
            'user_id': data.get('user_id', 'default')
        }
        
        # Clean email
        email_data = clean_email_body(email_data)
        
        # Classify email
        email_data['category'] = classify_email(email_data)
        
        # Add to RAG database
        idx = rag_db.add_email(email_data)
        
        # Save database
        rag_db.save_database()
        
        return jsonify({
            "success": True,
            "index": idx,
            "category": email_data['category'],
            "message": "Email processed and added to RAG database"
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/process-batch', methods=['POST'])
def process_batch():
    """
    Process multiple emails in batch.
    
    Expected JSON:
    {
        "emails": [
            {
                "subject": "...",
                "from": "...",
                ...
            },
            ...
        ],
        "user_id": "user1"
    }
    """
    try:
        data = request.json
        emails = data.get('emails', [])
        user_id = data.get('user_id', 'default')
        
        results = []
        
        for email in emails:
            # Extract from email address (Outlook returns object)
            from_addr = ''
            if isinstance(email.get('from'), dict):
                from_addr = email.get('from', {}).get('emailAddress', {}).get('address', '')
            elif isinstance(email.get('from'), str):
                from_addr = email.get('from', '')
            
            # Extract to email addresses (Outlook returns array of objects)
            to_addr = ''
            if isinstance(email.get('toRecipients'), list) and len(email.get('toRecipients', [])) > 0:
                to_recipients = email.get('toRecipients', [])
                to_addr = ', '.join([
                    r.get('emailAddress', {}).get('address', '') 
                    for r in to_recipients 
                    if isinstance(r, dict) and r.get('emailAddress', {}).get('address')
                ])
            
            # Extract body content
            body_content = ''
            if email.get('body'):
                if isinstance(email.get('body'), dict):
                    body_content = email.get('body', {}).get('content', '')
                else:
                    body_content = email.get('body', '')
            elif email.get('bodyPreview'):
                body_content = email.get('bodyPreview', '')
            
            # Prepare email data
            email_data = {
                'subject': email.get('subject', ''),
                'from': from_addr,
                'to': to_addr,
                'body': body_content,
                'receivedDateTime': email.get('receivedDateTime') or email.get('sentDateTime', ''),
                'user_id': user_id
            }
            
            # Clean email
            email_data = clean_email_body(email_data)
            
            # Classify email
            email_data['category'] = classify_email(email_data)
            
            # Add to RAG database
            idx = rag_db.add_email(email_data)
            results.append({
                "index": idx,
                "subject": email_data['subject'],
                "category": email_data['category']
            })
        
        # Save database
        try:
            rag_db.save_database()
            print(f"✅ Database saved successfully. Total emails: {len(rag_db.metadata)}")
        except Exception as e:
            print(f"❌ Error saving database: {e}")
            import traceback
            traceback.print_exc()
        
        return jsonify({
            "success": True,
            "processed": len(results),
            "results": results,
            "message": f"Processed {len(results)} emails and added to RAG database",
            "total_in_db": len(rag_db.metadata)
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/search', methods=['POST'])
def search():
    """
    Search RAG database for similar emails.
    
    Expected JSON:
    {
        "query": "search text",
        "k": 5,
        "user_id": "user1",
        "category": "Rechnungen"
    }
    """
    try:
        data = request.json
        query = data.get('query', '')
        k = data.get('k', 5)
        user_id = data.get('user_id')
        category = data.get('category')
        
        results = rag_db.search(query, k=k, user_id=user_id, category=category)
        
        return jsonify({
            "success": True,
            "results": results,
            "count": len(results)
        })
    
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/generate-draft', methods=['POST'])
def generate_draft():
    """
    Generate an email draft based on incoming email and RAG context.
    
    Expected JSON:
    {
        "incoming_email": {
            "subject": "Email subject",
            "body": "Email body text",
            "from": "sender@example.com",
            "category": "Rechnungen"
        },
        "user_id": "user1"
    }
    """
    try:
        import requests as req
        import sys
        
        # Log raw request data for debugging
        data = request.json
        print("=" * 60, file=sys.stderr)
        print("🔍 RAW REQUEST DATA:", file=sys.stderr)
        print(f"   Full JSON: {data}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        
        # Handle both structures: direct or wrapped in "body" key
        if 'body' in data and isinstance(data.get('body'), dict):
            # Data is wrapped in "body" key (n8n sometimes does this)
            actual_data = data.get('body', {})
        else:
            # Data is at root level (expected structure)
            actual_data = data
        
        incoming_email = actual_data.get('incoming_email', {})
        user_id = actual_data.get('user_id', 'default')
        
        # Log what we extracted
        print(f"📧 Extracted data:", file=sys.stderr)
        print(f"   Subject: '{incoming_email.get('subject', '')}'", file=sys.stderr)
        print(f"   Body: '{incoming_email.get('body', '')[:100]}...'", file=sys.stderr)
        print(f"   From: '{incoming_email.get('from', '')}'", file=sys.stderr)
        print(f"   Category: '{incoming_email.get('category', '')}'", file=sys.stderr)
        print(f"   User ID: '{user_id}'", file=sys.stderr)
        
        # Get email ID for deduplication (use subject + from + body hash as unique key)
        # Normalize body (remove extra whitespace, normalize line breaks) before hashing
        body_normalized = re.sub(r'\s+', ' ', incoming_email.get('body', '').strip())
        body_hash = hashlib.md5(body_normalized.encode()).hexdigest()[:8]
        email_id = incoming_email.get('id') or f"{incoming_email.get('subject', '').strip()}_{incoming_email.get('from', '').strip()}_{body_hash}"
        
        print(f"🔑 Email ID for deduplication: {email_id[:80]}...", file=sys.stderr)
        
        # Use global processed_emails
        global processed_emails
        
        # Check for duplicate processing
        current_time = time.time()
        if email_id in processed_emails:
            last_processed = processed_emails[email_id]
            time_since = current_time - last_processed
            if time_since < DUPLICATE_WINDOW:
                wait_time = int(DUPLICATE_WINDOW - time_since)
                print(f"⚠️ Duplicate request detected for email: {incoming_email.get('subject', 'N/A')} (ID: {email_id[:50]})", file=sys.stderr)
                print(f"   Last processed: {int(time_since)}s ago, wait {wait_time}s more", file=sys.stderr)
                return jsonify({
                    "success": False,
                    "error": f"This email was already processed {int(time_since)} seconds ago. Please wait {wait_time} more seconds before generating another draft.",
                    "draft": None,
                    "wait_seconds": wait_time
                }), 429  # Too Many Requests
        
        # Validate required fields
        if not incoming_email.get('subject') and not incoming_email.get('body'):
            print("❌ ERROR: Missing both subject and body!", file=sys.stderr)
            print(f"   Incoming email data: {incoming_email}", file=sys.stderr)
        
        # Log the email being processed
        print(f"📧 Processing email draft request:", file=sys.stderr)
        print(f"   Subject: {incoming_email.get('subject', 'N/A')}", file=sys.stderr)
        print(f"   From: {incoming_email.get('from', 'N/A')}", file=sys.stderr)
        print(f"   Category: {incoming_email.get('category', 'N/A')}", file=sys.stderr)
        print(f"   Body preview: {incoming_email.get('body', '')[:100]}...", file=sys.stderr)
        
        # Mark as processed
        processed_emails[email_id] = current_time
        print(f"✅ Marked email as processed (ID: {email_id[:50]}...)", file=sys.stderr)
        print(f"   Total emails in cache: {len(processed_emails)}", file=sys.stderr)
        
        # Clean up old entries (older than 1 hour)
        cutoff_time = current_time - 3600
        processed_emails = {k: v for k, v in processed_emails.items() if v > cutoff_time}
        
        # Search RAG database for relevant context
        query_text = f"{incoming_email.get('subject', '')} {incoming_email.get('body', '')}"
        category = incoming_email.get('category')
        
        # First, try to get feedback emails (user-edited versions) - these are most valuable
        feedback_emails = []
        all_context = rag_db.search(query_text, k=10, user_id=user_id, category=None)  # Get more results
        for email in all_context:
            if email.get('is_feedback') or email.get('category') == 'user_feedback':
                feedback_emails.append(email)
        
        # Then get regular context emails
        context_emails = rag_db.search(query_text, k=5, user_id=user_id, category=category)
        
        # Prioritize feedback emails in style examples
        style_examples = []
        # Add feedback emails first (these represent user's preferred style)
        for email in feedback_emails[:2]:  # Top 2 feedback emails
            style_examples.append({
                "subject": email.get('subject', ''),
                "body": email.get('body', '')[:500],
                "is_feedback": True
            })
        # Then add regular context emails
        for email in context_emails[:3]:  # Top 3 regular emails
            if len(style_examples) < 5:  # Limit total to 5
                style_examples.append({
                    "subject": email.get('subject', ''),
                    "body": email.get('body', '')[:500]
                })
        
        # Build prompt for Ollama
        context_text = ""
        if context_emails:
            context_text = "\n\nRelevant past emails:\n"
            for i, email in enumerate(context_emails[:3], 1):
                context_text += f"\n{i}. Subject: {email.get('subject', '')}\n"
                context_text += f"   Body: {email.get('body', '')[:300]}...\n"
        
        style_text = ""
        if style_examples:
            style_text = "\n\nYour writing style examples (prioritize matching this style):\n"
            for i, ex in enumerate(style_examples, 1):
                feedback_note = " [USER-EDITED - HIGH PRIORITY]" if ex.get('is_feedback') else ""
                style_text += f"\n{i}. Subject: {ex['subject']}{feedback_note}\n"
                style_text += f"   Body: {ex['body'][:200]}...\n"
        
        # Extract sender name from email body signature or email address
        from_email = incoming_email.get('from', '')
        email_body = incoming_email.get('body', '')
        
        # Try to extract name from email signature (look for "Best regards," or "Regards," followed by name)
        sender_name = None
        
        # First, try to find signature closings and extract name from the line after
        signature_closings = ['Best regards', 'Regards', 'Sincerely', 'Kind regards', 'Thanks', 'Thank you']
        lines = email_body.split('\n')
        
        # Look for signature closing and get the next non-empty line as potential name
        for i, line in enumerate(lines):
            line_lower = line.strip().lower()
            # Check if this line contains a signature closing
            if any(closing.lower() in line_lower for closing in signature_closings):
                # Look at the next few lines for a name
                for j in range(i + 1, min(i + 4, len(lines))):
                    potential_name = lines[j].strip()
                    # Validate it looks like a name (2-3 words, proper capitalization, not too long)
                    if potential_name and len(potential_name.split()) >= 1 and len(potential_name.split()) <= 3:
                        # Check if it starts with capital letter and doesn't contain common non-name words
                        words = potential_name.split()
                        if (all(word[0].isupper() for word in words if word) and 
                            len(potential_name) < 50 and
                            not any(word.lower() in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday',
                                                     'afternoon', 'morning', 'evening', 'week', 'meeting', 'call', 'email'] 
                                    for word in words)):
                            sender_name = potential_name
                            print(f"✅ Extracted sender name from signature: '{sender_name}'", file=sys.stderr)
                            break
                if sender_name:
                    break
        
        # If not found, try regex patterns as fallback
        if not sender_name:
            signature_patterns = [
                # Pattern 1: "Best regards,\nSarah Johnson" (name on new line after closing)
                r'(?:Best regards|Regards|Sincerely|Kind regards)[,\s]*\n\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*$',
                # Pattern 2: "Best regards, Sarah Johnson" (name on same line)
                r'(?:Best regards|Regards|Sincerely|Kind regards)[,\s]+([A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s*$',
            ]
            for pattern in signature_patterns:
                match = re.search(pattern, email_body, re.IGNORECASE | re.MULTILINE)
                if match:
                    potential_name = match.group(1).strip()
                    # Validate it's a real name
                    words = potential_name.split()
                    if (len(words) >= 1 and len(words) <= 3 and
                        all(word[0].isupper() for word in words) and
                        not any(word.lower() in ['monday', 'tuesday', 'afternoon', 'morning', 'week', 'meeting'] 
                                for word in words)):
                        sender_name = potential_name
                        print(f"✅ Extracted sender name via regex: '{sender_name}'", file=sys.stderr)
                        break
        
        # If still not found, use generic greeting
        if not sender_name:
            sender_name = None
            print(f"⚠️ Could not extract sender name, will use generic greeting", file=sys.stderr)
        else:
            # Clean up the name
            sender_name = re.sub(r'\s+', ' ', sender_name).strip()
        
        # Detect language from incoming email
        email_text = f"{incoming_email.get('subject', '')} {incoming_email.get('body', '')}".lower()
        
        # Simple language detection based on common words
        german_words = ['ich', 'sie', 'der', 'die', 'das', 'und', 'mit', 'für', 'ist', 'haben', 'können', 'bitte', 'danke', 'sehr geehrte']
        english_words = ['the', 'and', 'for', 'you', 'can', 'please', 'thank', 'regards', 'meeting', 'schedule']
        
        german_count = sum(1 for word in german_words if word in email_text)
        english_count = sum(1 for word in english_words if word in email_text)
        
        # Determine language
        if german_count > english_count:
            language = "German"
            language_instruction = "auf Deutsch"
            greeting_examples = "Hallo, Guten Tag, Sehr geehrte/r"
            closing_examples = "Mit freundlichen Grüßen, Beste Grüße, Viele Grüße"
        else:
            language = "English"
            language_instruction = "in English"
            greeting_examples = "Hello, Hi, Dear"
            closing_examples = "Best regards, Sincerely, Kind regards"
        
        print(f"🌐 Detected language: {language}", file=sys.stderr)
        
        # Build the prompt with example
        example_prompt = """Example:
Incoming email:
Subject: Meeting Request
From: john.smith@example.com
Body: Can we schedule a meeting next week?

Reply:
Hello,

Thank you for reaching out. I'd be happy to schedule a meeting with you next week. 

I'm available on Tuesday and Wednesday afternoon. Please let me know which time works best for you, and I'll send a calendar invitation.

Best regards
"""

        prompt = f"""You are a professional email assistant. Write a business email reply {language_instruction}.

{example_prompt}

Now write a reply to this email:

INCOMING EMAIL:
Subject: {incoming_email.get('subject', '')}
From: {from_email}
Sender Name: {sender_name if sender_name else 'Not specified - use generic greeting'}
Body: {incoming_email.get('body', '')}
Category: {category or 'sonstige'}

{context_text}

{style_text}

IMPORTANT INSTRUCTIONS:
1. LANGUAGE: Write the reply {language_instruction} (the same language as the incoming email)
2. GREETING: Use appropriate greeting in {language}: {greeting_examples}
3. ADDRESSING: Address the sender by name if available: {sender_name if sender_name else "use generic greeting"}
4. CONTENT: Respond appropriately to what they are asking - read the incoming email body carefully
5. STYLE: Match the writing style and tone from the examples above
6. LENGTH: Keep it concise (2-4 paragraphs)
7. CLOSING: End with a professional closing {language_instruction}: {closing_examples}
8. FORMAT: Write ONLY the email body text - DO NOT include "Subject:" line in the body
9. NO SEPARATORS: DO NOT include separators like "---" at the end
10. NO SIGNATURE: DO NOT sign with your own name - just end with the closing phrase

REPLY ({language} email body only, no subject line, no signature):"""

        # Call Ollama to generate draft
        ollama_url = "http://localhost:11434"
        generate_url = f"{ollama_url}/api/generate"
        
        payload = {
            "model": "llama3.2:3b",
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": 0.8,
                "top_p": 0.95,
                "num_predict": 500
            }
        }
        
        response = req.post(generate_url, json=payload, timeout=60)
        response.raise_for_status()
        result = response.json()
        
        draft_body = result.get('response', '').strip()
        
        # Clean up the draft body
        # Remove subject line if included
        lines = draft_body.split('\n')
        cleaned_lines = []
        skip_next_if_empty = False
        
        for line in lines:
            line_stripped = line.strip()
            # Skip lines that are subject lines
            if line_stripped.lower().startswith('subject:'):
                skip_next_if_empty = True
                continue
            # Skip empty line after subject if present
            if skip_next_if_empty and not line_stripped:
                skip_next_if_empty = False
                continue
            skip_next_if_empty = False
            
            # Skip separator lines
            if line_stripped.startswith('---') or line_stripped == '---':
                continue
            
            cleaned_lines.append(line)
        
        draft_body = '\n'.join(cleaned_lines).strip()
        
        # Remove any remaining "---" at the end
        while draft_body.endswith('---') or draft_body.endswith('---'):
            draft_body = draft_body.rstrip('-').strip()
        
        # Remove common placeholders
        placeholder_patterns = [
            r'\[Your Name\]',
            r'\[Ihr Name\]',
            r'\[Name\]',
            r'\[Dein Name\]',
            r'\[Insert Name\]',
            r'\[Your Name Here\]'
        ]
        for pattern in placeholder_patterns:
            draft_body = re.sub(pattern, '', draft_body, flags=re.IGNORECASE)
        
        # Clean up any double newlines or trailing whitespace
        draft_body = re.sub(r'\n{3,}', '\n\n', draft_body).strip()
        
        # Clean up response - remove refusal messages completely
        refusal_phrases = [
            "i can't fulfill this request",
            "i cannot fulfill",
            "i'm not able to",
            "i cannot assist",
            "i can only assist",
            "i can only provide",
            "is there anything else i can help",
            "can i help you with something else",
            "explicit content"
        ]
        
        # Check if response is a refusal
        draft_lower = draft_body.lower()
        is_refusal = any(phrase in draft_lower for phrase in refusal_phrases)
        
        if is_refusal or len(draft_body) < 50:
            # Completely replace refusal with a proper reply based on email content
            subject = incoming_email.get('subject', '').lower()
            body = incoming_email.get('body', '').lower()
            category = incoming_email.get('category', 'sonstige')
            
            # Generate context-aware reply
            if 'invoice' in subject or 'invoice' in body or 'payment' in body or category == 'Rechnungen':
                draft_body = f"""Hello,

Thank you for your email regarding the invoice.

I've received your message and will review the details. I'll get back to you shortly with an update.

If you have any questions in the meantime, please don't hesitate to reach out.

Best regards"""
            elif 'meeting' in subject or 'meeting' in body or 'schedule' in body or category == 'Terminabstimmung':
                draft_body = f"""Hello,

Thank you for your meeting request.

I'd be happy to schedule a meeting with you. Could you please let me know your availability for next week? I'm flexible with times and can work around your schedule.

Please let me know what works best for you.

Best regards"""
            else:
                draft_body = f"""Hello,

Thank you for your email regarding "{incoming_email.get('subject', 'this matter')}".

I've received your message and will review it carefully. I'll get back to you shortly with a response.

If you need immediate assistance, please don't hesitate to reach out.

Best regards"""
        
        # Generate subject (usually "Re: " + original subject)
        original_subject = incoming_email.get('subject', '')
        if not original_subject.startswith('Re:'):
            draft_subject = f"Re: {original_subject}"
        else:
            draft_subject = original_subject
        
        # Log generated draft
        print(f"✅ Draft generated:", file=sys.stderr)
        print(f"   Subject: {draft_subject}", file=sys.stderr)
        print(f"   Body preview: {draft_body[:150]}...", file=sys.stderr)
        print(f"   Context emails used: {len(context_emails)}", file=sys.stderr)
        
        # Store draft for feedback tracking
        draft_id = f"{email_id}_draft_{int(time.time())}"
        global drafts_storage
        drafts_storage[draft_id] = {
            "draft_id": draft_id,
            "original_draft": {
                "subject": draft_subject,
                "body": draft_body
            },
            "incoming_email_id": email_id,
            "incoming_email": {
                "subject": incoming_email.get('subject', ''),
                "from": incoming_email.get('from', ''),
                "body": incoming_email.get('body', '')[:200]  # Store preview
            },
            "user_id": user_id,
            "created_at": time.time(),
            "category": category
        }
        save_drafts()
        print(f"💾 Draft stored with ID: {draft_id}", file=sys.stderr)
        
        return jsonify({
            "success": True,
            "draft": {
                "subject": draft_subject,
                "body": draft_body
            },
            "draft_id": draft_id,  # Return draft ID for tracking
            "context_used": len(context_emails),
            "style_examples_used": len(style_examples)
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/find-draft', methods=['POST'])
def find_draft():
    """
    Find a draft by subject and recipient (for matching sent emails with drafts).
    
    Expected JSON:
    {
        "subject": "Re: ...",
        "to": "recipient@example.com",
        "user_id": "user1"
    }
    """
    try:
        import sys
        data = request.json
        subject = data.get('subject', '').strip()
        to_email = data.get('to', '').strip()
        user_id = data.get('user_id', 'default')
        
        print(f"🔍 Searching for draft:", file=sys.stderr)
        print(f"   Subject: {subject}", file=sys.stderr)
        print(f"   To: {to_email}", file=sys.stderr)
        print(f"   User ID: {user_id}", file=sys.stderr)
        
        global drafts_storage
        matching_drafts = []
        
        # Search for matching drafts (within last 7 days)
        current_time = time.time()
        seven_days_ago = current_time - (7 * 24 * 60 * 60)
        
        for draft_id, draft_data in drafts_storage.items():
            # Check if draft matches
            if draft_data.get('user_id') != user_id:
                continue
            
            # Check if draft is recent (within 7 days)
            if draft_data.get('created_at', 0) < seven_days_ago:
                continue
            
            draft_subject = draft_data.get('original_draft', {}).get('subject', '').strip()
            
            # Match by subject (fuzzy match - remove "Re:" and compare)
            subject_clean = re.sub(r'^Re:\s*', '', subject, flags=re.IGNORECASE).strip()
            draft_subject_clean = re.sub(r'^Re:\s*', '', draft_subject, flags=re.IGNORECASE).strip()
            
            if subject_clean.lower() == draft_subject_clean.lower():
                matching_drafts.append({
                    "draft_id": draft_id,
                    "draft": draft_data.get('original_draft', {}),
                    "incoming_email_id": draft_data.get('incoming_email_id', ''),
                    "created_at": draft_data.get('created_at', 0)
                })
        
        # Sort by creation time (most recent first)
        matching_drafts.sort(key=lambda x: x.get('created_at', 0), reverse=True)
        
        if matching_drafts:
            best_match = matching_drafts[0]
            print(f"✅ Found matching draft: {best_match['draft_id']}", file=sys.stderr)
            return jsonify({
                "success": True,
                "found": True,
                "draft": best_match
            })
        else:
            print(f"⚠️ No matching draft found", file=sys.stderr)
            return jsonify({
                "success": True,
                "found": False,
                "draft": None
            })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/update-feedback', methods=['POST'])
def update_feedback():
    """
    Capture user edits to AI-generated drafts for improving future suggestions.
    
    Expected JSON:
    {
        "original_draft": {
            "subject": "Re: ...",
            "body": "Original draft text..."
        },
        "edited_version": {
            "subject": "Re: ...",
            "body": "Edited/sent version..."
        },
        "incoming_email_id": "email_id",
        "user_id": "user1"
    }
    """
    try:
        import sys
        data = request.json
        edited_version = data.get('edited_version', {})
        user_id = data.get('user_id', 'default')
        
        # If original_draft not provided, try to find it automatically
        original_draft = data.get('original_draft', {})
        incoming_email_id = data.get('incoming_email_id', '')
        
        if not original_draft.get('subject') or not original_draft.get('body'):
            # Try to find draft by subject
            subject = edited_version.get('subject', '')
            if subject:
                print(f"🔍 Original draft not provided, searching by subject: {subject}", file=sys.stderr)
                global drafts_storage
                matching_drafts = []
                current_time = time.time()
                seven_days_ago = current_time - (7 * 24 * 60 * 60)
                
                for draft_id, draft_data in drafts_storage.items():
                    if draft_data.get('user_id') != user_id:
                        continue
                    if draft_data.get('created_at', 0) < seven_days_ago:
                        continue
                    
                    draft_subject = draft_data.get('original_draft', {}).get('subject', '').strip()
                    subject_clean = re.sub(r'^Re:\s*', '', subject, flags=re.IGNORECASE).strip()
                    draft_subject_clean = re.sub(r'^Re:\s*', '', draft_subject, flags=re.IGNORECASE).strip()
                    
                    if subject_clean.lower() == draft_subject_clean.lower():
                        matching_drafts.append((draft_data, draft_data.get('created_at', 0)))
                
                if matching_drafts:
                    # Get most recent match
                    matching_drafts.sort(key=lambda x: x[1], reverse=True)
                    best_match = matching_drafts[0][0]
                    original_draft = best_match.get('original_draft', {})
                    incoming_email_id = best_match.get('incoming_email_id', incoming_email_id)
                    print(f"✅ Found matching draft: {best_match.get('draft_id', 'N/A')}", file=sys.stderr)
                else:
                    print(f"⚠️ No matching draft found, will store edited version anyway", file=sys.stderr)
        
        print("=" * 60, file=sys.stderr)
        print("📝 Processing feedback/edits:", file=sys.stderr)
        print(f"   Original subject: {original_draft.get('subject', 'N/A')}", file=sys.stderr)
        print(f"   Edited subject: {edited_version.get('subject', 'N/A')}", file=sys.stderr)
        print(f"   User ID: {user_id}", file=sys.stderr)
        print("=" * 60, file=sys.stderr)
        
        # Compare original vs edited to identify changes
        original_body = original_draft.get('body', '').strip()
        edited_body = edited_version.get('body', '').strip()
        
        # Calculate similarity (simple character-based for now)
        if original_body and edited_body:
            # Normalize whitespace for comparison
            orig_norm = re.sub(r'\s+', ' ', original_body)
            edit_norm = re.sub(r'\s+', ' ', edited_body)
            
            # Simple similarity check
            if orig_norm == edit_norm:
                changes_detected = False
                print("ℹ️ No changes detected - draft was sent as-is", file=sys.stderr)
            else:
                changes_detected = True
                print("✅ Changes detected - storing edited version for learning", file=sys.stderr)
        else:
            changes_detected = False
        
        # Store the edited version in RAG database as a "sent" email
        # This represents the user's preferred style/response
        idx = None
        if changes_detected or True:  # Always store to learn from user's final version
            email_data = {
                'subject': edited_version.get('subject', original_draft.get('subject', '')),
                'body': edited_body,
                'from': user_id,  # The user who sent it
                'to': '',  # Will be filled from incoming email if available
                'receivedDateTime': '',  # Will use current time
                'user_id': user_id,
                'category': 'user_feedback',  # Special category for feedback
                'is_feedback': True,  # Mark as feedback
                'original_draft_id': incoming_email_id
            }
            
            # Clean and classify
            email_data = clean_email_body(email_data)
            # Don't reclassify feedback emails - keep as 'user_feedback'
            
            # Add to RAG database
            idx = rag_db.add_email(email_data)
            rag_db.save_database()
            
            print(f"✅ Stored edited version in RAG database (index: {idx})", file=sys.stderr)
            print(f"   This will be used to improve future draft generation", file=sys.stderr)
        
        return jsonify({
            "success": True,
            "changes_detected": changes_detected,
            "message": "Feedback processed and stored in RAG database",
            "index": idx
        })
    
    except Exception as e:
        import traceback
        traceback.print_exc()
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


@app.route('/stats', methods=['GET'])
def stats():
    """Get RAG database statistics."""
    try:
        stats = rag_db.get_stats()
        return jsonify({
            "success": True,
            "stats": stats
        })
    except Exception as e:
        return jsonify({
            "success": False,
            "error": str(e)
        }), 500


if __name__ == '__main__':
    print("🚀 Starting RAG API Server...")
    print("📡 Server will run on http://localhost:5000")
    print("📋 Endpoints:")
    print("   - POST /process-email - Process single email")
    print("   - POST /process-batch - Process multiple emails")
    print("   - POST /search - Search RAG database")
    print("   - POST /generate-draft - Generate email draft")
    print("   - POST /find-draft - Find draft by subject/recipient")
    print("   - POST /update-feedback - Capture user edits for learning")
    print("   - GET /stats - Get database statistics")
    print("   - GET /health - Health check")
    print("   - GET/POST /clear-cache - Clear deduplication cache")
    print()
    app.run(host='0.0.0.0', port=5000, debug=True)

