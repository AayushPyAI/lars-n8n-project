#!/usr/bin/env python3
"""
RAG Database Manager
Handles embedding generation, storage, and retrieval using FAISS.
"""

import os
import json
import pickle
import numpy as np
import faiss
import requests
from typing import List, Dict, Any, Optional
from pathlib import Path


class RAGDatabase:
    """Manages RAG database with FAISS for vector storage."""
    
    def __init__(self, db_path: str = "./rag_data", ollama_url: str = "http://localhost:11434"):
        """
        Initialize RAG database.
        
        Args:
            db_path: Path to store database files
            ollama_url: URL of Ollama API
        """
        self.db_path = Path(db_path)
        self.db_path.mkdir(exist_ok=True)
        
        self.ollama_url = ollama_url
        # Try to use nomic-embed-text for embeddings, fallback to llama3.2:3b
        self.embedding_model = "nomic-embed-text"  # Better for embeddings
        self.fallback_model = "llama3.2:3b"
        
        # FAISS index
        self.index = None
        self.dimension = 384  # Default embedding dimension (will be set from first embedding)
        self.metadata = []  # Store email metadata alongside vectors
        
        # Load existing database if available
        self.load_database()
    
    def generate_embedding(self, text: str) -> np.ndarray:
        """
        Generate embedding for text using Ollama.
        
        Args:
            text: Text to embed
            
        Returns:
            Numpy array of embedding vector
        """
        # For now, use a simple approach with Ollama
        # Note: Ollama doesn't have a dedicated embedding endpoint for all models
        # We'll use the generate endpoint with a special prompt
        
        # Simple embedding approach: use Ollama to generate a representation
        # In production, you'd use a dedicated embedding model like nomic-embed-text
        
        try:
            # Try to use Ollama's embedding endpoint
            # First try nomic-embed-text, then fallback
            for model in [self.embedding_model, self.fallback_model]:
                try:
                    response = requests.post(
                        f"{self.ollama_url}/api/embeddings",
                        json={
                            "model": model,
                            "prompt": text[:1000]  # Limit text length
                        },
                        timeout=30
                    )
                    
                    if response.status_code == 200:
                        data = response.json()
                        embedding = np.array(data.get('embedding', []), dtype=np.float32)
                        
                        # Set dimension from first embedding
                        if self.dimension is None or self.dimension == 384:
                            self.dimension = len(embedding)
                            if self.index is None:
                                self.index = faiss.IndexFlatL2(self.dimension)
                        
                        return embedding
                except:
                    continue
            
            # If both models fail, use fallback
            return self._simple_embedding(text)
        except Exception as e:
            print(f"Error generating embedding: {e}")
            return self._simple_embedding(text)
    
    def _simple_embedding(self, text: str) -> np.ndarray:
        """
        Simple fallback embedding using hash.
        This is a temporary solution until proper embedding model is set up.
        """
        import hashlib
        
        # Create a simple embedding based on text hash
        hash_obj = hashlib.sha256(text.encode())
        hash_bytes = hash_obj.digest()
        
        # Convert to float32 array
        embedding = np.frombuffer(hash_bytes[:self.dimension * 4], dtype=np.float32)
        
        if len(embedding) < self.dimension:
            # Pad if needed
            padding = np.zeros(self.dimension - len(embedding), dtype=np.float32)
            embedding = np.concatenate([embedding, padding])
        elif len(embedding) > self.dimension:
            embedding = embedding[:self.dimension]
        
        # Normalize
        norm = np.linalg.norm(embedding)
        if norm > 0:
            embedding = embedding / norm
        
        return embedding
    
    def add_email(self, email_data: Dict[str, Any]) -> int:
        """
        Add email to RAG database.
        
        Args:
            email_data: Dictionary containing email fields
            
        Returns:
            Index of added email
        """
        # Combine subject and body for embedding
        text = f"{email_data.get('subject', '')} {email_data.get('cleaned_body', '')}"
        
        if not text.strip():
            return -1
        
        # Generate embedding
        embedding = self.generate_embedding(text)
        
        # Ensure dimension is set
        if self.dimension is None:
            self.dimension = len(embedding)
            self.index = faiss.IndexFlatL2(self.dimension)
        
        # Reshape for FAISS (needs to be 2D)
        embedding = embedding.reshape(1, -1)
        
        # Add to FAISS index
        self.index.add(embedding.astype('float32'))
        
        # Store metadata
        metadata = {
            'id': len(self.metadata),
            'subject': email_data.get('subject', ''),
            'from': email_data.get('from', ''),
            'to': email_data.get('to', ''),
            'timestamp': email_data.get('receivedDateTime', ''),
            'category': email_data.get('category', 'sonstige'),
            'user_id': email_data.get('user_id', 'default'),
            'body': email_data.get('cleaned_body', ''),
        }
        self.metadata.append(metadata)
        
        return len(self.metadata) - 1
    
    def search(self, query: str, k: int = 5, user_id: Optional[str] = None, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Search for similar emails.
        
        Args:
            query: Search query text
            k: Number of results to return
            user_id: Filter by user ID (optional)
            category: Filter by category (optional)
            
        Returns:
            List of similar email metadata
        """
        if self.index is None or self.index.ntotal == 0:
            return []
        
        # Generate embedding for query
        query_embedding = self.generate_embedding(query)
        query_embedding = query_embedding.reshape(1, -1).astype('float32')
        
        # Search in FAISS
        distances, indices = self.index.search(query_embedding, min(k * 2, self.index.ntotal))
        
        # Filter and format results
        results = []
        for i, idx in enumerate(indices[0]):
            if idx < len(self.metadata):
                metadata = self.metadata[idx].copy()
                
                # Apply filters
                if user_id and metadata.get('user_id') != user_id:
                    continue
                if category and metadata.get('category') != category:
                    continue
                
                metadata['distance'] = float(distances[0][i])
                results.append(metadata)
                
                if len(results) >= k:
                    break
        
        return results
    
    def save_database(self):
        """Save database to disk."""
        # Save FAISS index
        if self.index is not None:
            faiss.write_index(self.index, str(self.db_path / "index.faiss"))
        
        # Save metadata
        with open(self.db_path / "metadata.json", 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, indent=2, ensure_ascii=False)
    
    def load_database(self):
        """Load database from disk."""
        index_path = self.db_path / "index.faiss"
        metadata_path = self.db_path / "metadata.json"
        
        if index_path.exists():
            self.index = faiss.read_index(str(index_path))
            # Get dimension from index
            self.dimension = self.index.d
        else:
            self.index = None
        
        if metadata_path.exists():
            with open(metadata_path, 'r', encoding='utf-8') as f:
                self.metadata = json.load(f)
        else:
            self.metadata = []
    
    def get_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        return {
            'total_emails': len(self.metadata),
            'index_size': self.index.ntotal if self.index else 0,
            'dimension': self.dimension,
        }


if __name__ == '__main__':
    # Example usage
    db = RAGDatabase()
    
    # Add sample email
    sample_email = {
        'subject': 'Test Email',
        'cleaned_body': 'This is a test email body',
        'from': 'test@example.com',
        'to': 'recipient@example.com',
        'receivedDateTime': '2024-01-01T00:00:00Z',
        'category': 'sonstige',
        'user_id': 'user1'
    }
    
    db.add_email(sample_email)
    db.save_database()
    
    # Search
    results = db.search('test email', k=3)
    print(f"Search results: {len(results)}")
    for result in results:
        print(f"- {result['subject']} (distance: {result['distance']:.4f})")
    
    print(f"\nDatabase stats: {db.get_stats()}")

