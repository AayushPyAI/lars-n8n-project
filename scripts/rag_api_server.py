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
DUPLICATE_WINDOW = 30  # 30 seconds (reduced for testing, can increase to 300 for production)


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
        context_emails = rag_db.search(query_text, k=5, user_id=user_id, category=category)
        
        # Extract user writing style from context emails
        style_examples = []
        for email in context_emails[:3]:  # Use top 3 for style
            style_examples.append({
                "subject": email.get('subject', ''),
                "body": email.get('body', '')[:500]  # Limit length
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
            style_text = "\n\nYour writing style examples:\n"
            for i, ex in enumerate(style_examples, 1):
                style_text += f"\n{i}. Subject: {ex['subject']}\n"
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

        prompt = f"""You are a professional email assistant. Write a business email reply in English.

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
1. Write ONLY the email body text - DO NOT include "Subject:" line in the body
2. Address the sender: {"Use 'Hello " + sender_name + ",' or 'Hi " + sender_name + ",' at the beginning" if sender_name else "Use 'Hello,' or 'Hi there,' (do NOT use the email address name)"}
3. Respond appropriately to what they are asking - read the incoming email body carefully
4. Match the writing style from the examples above
5. Keep it concise (2-4 paragraphs)
6. End with a professional closing (e.g., "Best regards," "Sincerely,") - DO NOT include your own name after the closing
7. DO NOT include separators like "---" or "---" at the end
8. DO NOT include the subject line in the body - only write the body content
9. DO NOT address yourself - address the person who sent you the email
10. DO NOT sign with your own name - just end with "Best regards," or similar

REPLY (email body only, no subject line, no signature):"""

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
        print(f"✅ Draft generated:")
        print(f"   Subject: {draft_subject}")
        print(f"   Body preview: {draft_body[:150]}...")
        print(f"   Context emails used: {len(context_emails)}")
        
        return jsonify({
            "success": True,
            "draft": {
                "subject": draft_subject,
                "body": draft_body
            },
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
    print("   - GET /stats - Get database statistics")
    print("   - GET /health - Health check")
    print()
    app.run(host='0.0.0.0', port=5000, debug=True)

