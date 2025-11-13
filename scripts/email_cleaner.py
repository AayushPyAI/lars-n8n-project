#!/usr/bin/env python3
"""
Email Cleaner Script
Preprocesses and cleans email text for RAG database storage.
"""

import re
from typing import Dict, Any
from html import unescape
from bs4 import BeautifulSoup
import html2text


def remove_html_tags(text: str) -> str:
    """Remove HTML tags from email body."""
    if not text:
        return ""
    
    # Parse HTML
    soup = BeautifulSoup(text, 'html.parser')
    
    # Get text content
    text = soup.get_text()
    
    # Decode HTML entities
    text = unescape(text)
    
    return text.strip()


def remove_signatures(text: str) -> str:
    """Remove email signatures from text."""
    signature_patterns = [
        r'--\s*\n.*',  # Content after '--'
        r'Best regards.*',
        r'Mit freundlichen Grüßen.*',
        r'Kind regards.*',
        r'Sincerely.*',
        r'Viele Grüße.*',
        r'Freundliche Grüße.*',
    ]
    
    for pattern in signature_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)
    
    return text.strip()


def remove_disclaimers(text: str) -> str:
    """Remove legal disclaimers and footers."""
    disclaimer_patterns = [
        r'This email.*confidential.*',
        r'Diese E-Mail.*vertraulich.*',
        r'CONFIDENTIALITY.*',
        r'Disclaimer.*',
        r'Vertraulich.*',
    ]
    
    for pattern in disclaimer_patterns:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE | re.DOTALL)
    
    return text.strip()


def remove_quoted_text(text: str) -> str:
    """Remove quoted/replied email content."""
    lines = text.split('\n')
    cleaned_lines = []
    
    for line in lines:
        # Stop at quoted content markers
        if line.strip().startswith('>') or line.strip().startswith('|'):
            break
        if re.match(r'^On .* wrote:', line, re.IGNORECASE):
            break
        if re.match(r'^Von .* geschrieben:', line, re.IGNORECASE):
            break
        cleaned_lines.append(line)
    
    return '\n'.join(cleaned_lines).strip()


def clean_email_body(email_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Main cleaning function for email body text.
    
    Args:
        email_data: Dictionary containing email fields
        
    Returns:
        Dictionary with cleaned body text
    """
    body = email_data.get('body', '') or email_data.get('bodyContent', '')
    
    if not body:
        email_data['cleaned_body'] = ''
        return email_data
    
    # Remove HTML tags
    body = remove_html_tags(body)
    
    # Apply cleaning functions
    body = remove_quoted_text(body)
    body = remove_signatures(body)
    body = remove_disclaimers(body)
    
    # Normalize whitespace
    body = re.sub(r'\s+', ' ', body)
    body = body.strip()
    
    email_data['cleaned_body'] = body
    return email_data


if __name__ == '__main__':
    # Example usage
    sample_email = {
        'subject': 'Test Email',
        'body': '<html><body>Hello,<br><br>This is a test email.<br><br>Best regards,<br>John Doe<br><br>--<br>Confidential</body></html>',
        'from': 'john@example.com',
        'to': 'recipient@example.com'
    }
    
    cleaned = clean_email_body(sample_email)
    print("Original:", sample_email['body'])
    print("\nCleaned:", cleaned['cleaned_body'])

