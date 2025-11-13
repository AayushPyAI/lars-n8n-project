#!/usr/bin/env python3
"""
Test script for RAG database functionality.
"""

import sys
from pathlib import Path

# Add scripts to path
sys.path.insert(0, str(Path(__file__).parent))

from rag_database import RAGDatabase
from email_cleaner import clean_email_body
from classify_email import classify_email


def test_rag_database():
    """Test RAG database with sample emails."""
    print("🧪 Testing RAG Database...")
    print()
    
    # Initialize database
    db = RAGDatabase(db_path="./rag_data", ollama_url="http://localhost:11434")
    
    # Sample emails
    sample_emails = [
        {
            'subject': 'Rechnung für März 2024',
            'body': '<html><body>Sehr geehrter Kunde,<br><br>Bitte finden Sie die Rechnung für März 2024 im Anhang.<br><br>Betrag: 1.500,00 EUR<br><br>Best regards,<br>Billing Team</body></html>',
            'from': 'billing@example.com',
            'to': 'customer@example.com',
            'receivedDateTime': '2024-03-15T10:00:00Z',
            'user_id': 'user1'
        },
        {
            'subject': 'Termin für Besprechung',
            'body': 'Hallo, können wir einen Termin für nächste Woche vereinbaren? Ich bin am Montag und Dienstag verfügbar.',
            'from': 'colleague@example.com',
            'to': 'user@example.com',
            'receivedDateTime': '2024-03-16T14:30:00Z',
            'user_id': 'user1'
        },
        {
            'subject': 'Technische Dokumentation - Intern',
            'body': 'Hier ist die technische Dokumentation für das neue System. Bitte intern prüfen.',
            'from': 'tech@example.com',
            'to': 'team@example.com',
            'receivedDateTime': '2024-03-17T09:15:00Z',
            'user_id': 'user1'
        }
    ]
    
    # Process and add emails
    print("📧 Processing and adding emails...")
    for email in sample_emails:
        # Clean email
        email = clean_email_body(email)
        
        # Classify email
        email['category'] = classify_email(email)
        
        # Add to database
        idx = db.add_email(email)
        print(f"  ✓ Added: {email['subject']} (Category: {email['category']})")
    
    # Save database
    db.save_database()
    print()
    
    # Test search
    print("🔍 Testing search...")
    queries = [
        "Rechnung Zahlung",
        "Termin Besprechung",
        "Technische Dokumentation"
    ]
    
    for query in queries:
        print(f"\nQuery: '{query}'")
        results = db.search(query, k=2)
        for i, result in enumerate(results, 1):
            print(f"  {i}. {result['subject']} (Category: {result['category']}, Distance: {result['distance']:.4f})")
    
    # Stats
    print()
    print("📊 Database Statistics:")
    stats = db.get_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
    
    print()
    print("✅ RAG Database test complete!")


if __name__ == '__main__':
    test_rag_database()

