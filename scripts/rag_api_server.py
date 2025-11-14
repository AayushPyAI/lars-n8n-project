#!/usr/bin/env python3
"""
RAG API Server
Simple HTTP server for n8n to call for processing emails and storing in RAG database.
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
import sys
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
RAG_DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rag_data")
rag_db = RAGDatabase(db_path=RAG_DB_PATH, ollama_url="http://localhost:11434")
print(f"RAG Database initialized at: {RAG_DB_PATH}")


@app.route('/health', methods=['GET'])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "message": "RAG API Server is running"})


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
    print("   - GET /stats - Get database statistics")
    print("   - GET /health - Health check")
    print()
    app.run(host='0.0.0.0', port=5000, debug=True)

