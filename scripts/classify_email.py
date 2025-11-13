#!/usr/bin/env python3
"""
Email Classification Script
Classifies emails into predefined categories for better RAG retrieval.

Categories:
- Rechnungen (Invoices)
- Terminabstimmung (Appointment Scheduling)
- Intern (Internal)
- Fachliche Information intern (Technical Information Internal)
- Fachliche Information extern (Technical Information External)
- sonstige (Other)
"""

from typing import Dict, Any, List
import re


# Category keywords for classification
CATEGORY_KEYWORDS = {
    'Rechnungen': [
        'rechnung', 'invoice', 'zahlung', 'payment', 'betrag', 'amount',
        'rechnungsnummer', 'invoice number', 'zahlungsziel', 'due date',
        'rechnung', 'invoice', 'zahlung', 'payment', 'betrag', 'amount',
        'rechnungsnummer', 'invoice number', 'zahlungsziel', 'due date',
        'rechnung', 'invoice', 'zahlung', 'payment', 'betrag', 'amount',
        'rechnungsnummer', 'invoice number', 'zahlungsziel', 'due date',
    ],
    'Terminabstimmung': [
        'termin', 'appointment', 'meeting', 'besprechung', 'kalender',
        'uhrzeit', 'time', 'datum', 'date', 'verfügbar', 'available',
        'meeting', 'call', 'anruf', 'telefonat',
    ],
    'Intern': [
        'intern', 'internal', 'kollege', 'colleague', 'team', 'abteilung',
        'department', 'mitarbeiter', 'employee', 'interne', 'internal',
    ],
    'Fachliche Information intern': [
        'technisch', 'technical', 'dokumentation', 'documentation',
        'code', 'implementierung', 'implementation', 'system', 'architektur',
        'architecture', 'intern', 'internal', 'kollege', 'colleague',
    ],
    'Fachliche Information extern': [
        'technisch', 'technical', 'dokumentation', 'documentation',
        'code', 'implementierung', 'implementation', 'system', 'architektur',
        'architecture', 'extern', 'external', 'kunde', 'customer', 'client',
    ],
    'sonstige': []  # Default category
}


def classify_email(email_data: Dict[str, Any]) -> str:
    """
    Classify email into one of the predefined categories.
    
    Args:
        email_data: Dictionary containing email fields (subject, body, etc.)
        
    Returns:
        Category name as string
    """
    # Combine subject and body for analysis
    subject = email_data.get('subject', '') or email_data.get('subject', '')
    body = email_data.get('cleaned_body', '') or email_data.get('body', '') or email_data.get('bodyContent', '')
    
    text = f"{subject} {body}".lower()
    
    # Score each category based on keyword matches
    category_scores = {}
    
    for category, keywords in CATEGORY_KEYWORDS.items():
        if category == 'sonstige':
            continue
            
        score = 0
        for keyword in keywords:
            # Count occurrences of keyword
            score += len(re.findall(r'\b' + re.escape(keyword.lower()) + r'\b', text))
        
        if score > 0:
            category_scores[category] = score
    
    # Handle special case: Fachliche Information intern vs extern
    if 'Fachliche Information intern' in category_scores and 'Fachliche Information extern' in category_scores:
        # Check if email is internal or external
        is_internal = any(keyword in text for keyword in ['intern', 'internal', 'kollege', 'colleague', 'team'])
        if is_internal:
            category_scores.pop('Fachliche Information extern', None)
        else:
            category_scores.pop('Fachliche Information intern', None)
    
    # Return category with highest score, or 'sonstige' if no matches
    if category_scores:
        return max(category_scores, key=category_scores.get)
    else:
        return 'sonstige'


def classify_batch(emails: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Classify a batch of emails.
    
    Args:
        emails: List of email dictionaries
        
    Returns:
        List of emails with 'category' field added
    """
    classified = []
    for email in emails:
        category = classify_email(email)
        email['category'] = category
        classified.append(email)
    
    return classified


if __name__ == '__main__':
    # Example usage
    sample_emails = [
        {
            'subject': 'Rechnung für März 2024',
            'body': 'Sehr geehrter Kunde, bitte finden Sie die Rechnung für März 2024 im Anhang.',
            'from': 'billing@example.com'
        },
        {
            'subject': 'Termin für Besprechung',
            'body': 'Hallo, können wir einen Termin für nächste Woche vereinbaren?',
            'from': 'colleague@example.com'
        },
        {
            'subject': 'Technische Dokumentation',
            'body': 'Hier ist die technische Dokumentation für das neue System.',
            'from': 'tech@example.com'
        }
    ]
    
    classified = classify_batch(sample_emails)
    for email in classified:
        print(f"Subject: {email['subject']}")
        print(f"Category: {email['category']}\n")

