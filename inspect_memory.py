#!/usr/bin/env python3
"""Quick script to inspect current memory contents"""
import os
import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from services.memory import MemoryManager

def main():
    memory = MemoryManager()
    
    print("\n=== MEMORY INSPECTION ===\n")
    
    # Get stats
    stats = memory.get_stats()
    print(f"Total facts: {stats.get('total_facts', 0)}")
    print(f"Total conversations: {stats.get('total_conversations', 0)}")
    print(f"Task patterns: {stats.get('task_patterns', 0)}")
    
    # Get all facts from ChromaDB
    if memory.facts_collection:
        print("\n=== ALL FACTS ===")
        try:
            results = memory.facts_collection.get(include=['documents', 'metadatas'])
            if results and results.get('documents'):
                for i, doc in enumerate(results['documents']):
                    metadata = results['metadatas'][i] if results.get('metadatas') else {}
                    print(f"\n{i+1}. [{metadata.get('category', 'N/A')}] {doc}")
                    print(f"   Source: {metadata.get('source', 'N/A')}")
                    print(f"   Confidence: {metadata.get('confidence', 'N/A')}")
                    print(f"   Date: {metadata.get('date', 'N/A')}")
            else:
                print("No facts found")
        except Exception as e:
            print(f"Error reading facts: {e}")
    
    # Get recent conversations
    if memory.conversations_collection:
        print("\n=== RECENT CONVERSATIONS ===")
        try:
            results = memory.conversations_collection.get(include=['documents', 'metadatas'])
            if results and results.get('documents'):
                for i, doc in enumerate(results['documents'][:5]):  # Show last 5
                    metadata = results['metadatas'][i] if results.get('metadatas') else {}
                    print(f"\n{i+1}. {doc[:100]}...")
                    print(f"   Session: {metadata.get('session_id', 'N/A')}")
                    print(f"   Timestamp: {metadata.get('timestamp', 'N/A')}")
            else:
                print("No conversations found")
        except Exception as e:
            print(f"Error reading conversations: {e}")

if __name__ == "__main__":
    main()
