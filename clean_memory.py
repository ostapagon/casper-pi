#!/usr/bin/env python3
"""Clean memory database - remove or translate non-English facts"""
import os
import sys
import json
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from services.memory import MemoryManager
from google import genai

def translate_to_english(client, model, text):
    """Use Gemini to translate text to English"""
    try:
        prompt = f"""Translate this text to English. If it's a proper name in Cyrillic, transliterate to Latin alphabet.
If it's already in English, return it as is.

Text: {text}

Translation (English only):"""
        
        response = client.models.generate_content(
            model=model,
            contents=prompt
        )
        return response.text.strip()
    except Exception as e:
        print(f"   Translation error: {e}")
        return None

def has_non_latin(text):
    """Check if text contains non-Latin characters (Cyrillic, Chinese, etc.)"""
    for char in text:
        code = ord(char)
        # Check for Cyrillic, Chinese, and other non-Latin scripts
        if (0x0400 <= code <= 0x04FF or  # Cyrillic
            0x4E00 <= code <= 0x9FFF or  # Chinese
            0x3040 <= code <= 0x309F or  # Hiragana
            0x30A0 <= code <= 0x30FF):   # Katakana
            return True
    return False

def main():
    print("\n=== MEMORY CLEANUP ===\n")
    
    memory = MemoryManager()
    
    if not memory.facts_collection:
        print("No facts collection found!")
        return
    
    # Get all facts
    try:
        results = memory.facts_collection.get(include=['documents', 'metadatas', 'ids'])
        if not results or not results.get('documents'):
            print("No facts found")
            return
    except Exception as e:
        print(f"Error reading facts: {e}")
        return
    
    # Find non-English facts
    non_english_facts = []
    for i, doc in enumerate(results['documents']):
        metadata = results['metadatas'][i] if results.get('metadatas') else {}
        fact_id = results['ids'][i]
        
        if has_non_latin(doc):
            non_english_facts.append({
                'id': fact_id,
                'fact': doc,
                'metadata': metadata
            })
    
    if not non_english_facts:
        print("✓ All facts are already in English/Latin alphabet!")
        return
    
    print(f"Found {len(non_english_facts)} facts with non-English characters:\n")
    for i, item in enumerate(non_english_facts, 1):
        print(f"{i}. {item['fact']}")
        print(f"   Category: {item['metadata'].get('category', 'N/A')}")
        print(f"   Source: {item['metadata'].get('source', 'N/A')}\n")
    
    print("\nOptions:")
    print("1. Delete these facts (clean slate)")
    print("2. Translate/transliterate to English (requires API call)")
    print("3. Cancel")
    
    choice = input("\nYour choice (1/2/3): ").strip()
    
    if choice == "1":
        # Delete non-English facts
        ids_to_delete = [item['id'] for item in non_english_facts]
        try:
            memory.facts_collection.delete(ids=ids_to_delete)
            print(f"\n✓ Deleted {len(ids_to_delete)} non-English facts")
        except Exception as e:
            print(f"Error deleting facts: {e}")
    
    elif choice == "2":
        # Translate facts
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            print("Error: GEMINI_API_KEY not found")
            return
        
        client = genai.Client(api_key=api_key)
        model = os.getenv("AGENT_MODEL", "gemini-1.5-flash")
        
        print("\nTranslating facts to English...")
        
        for item in non_english_facts:
            print(f"\nOriginal: {item['fact']}")
            
            # Translate fact
            english_fact = translate_to_english(client, model, item['fact'])
            if not english_fact:
                print("   Skipped (translation failed)")
                continue
            
            print(f"English:  {english_fact}")
            
            # Delete old fact
            try:
                memory.facts_collection.delete(ids=[item['id']])
            except Exception as e:
                print(f"   Error deleting old fact: {e}")
                continue
            
            # Save new English fact
            category = item['metadata'].get('category', 'information')
            confidence = float(item['metadata'].get('confidence', 1.0))
            source = item['metadata'].get('source', 'migration')
            tags_raw = item['metadata'].get('tags', '[]')
            try:
                tags = json.loads(tags_raw) if isinstance(tags_raw, str) else tags_raw
            except:
                tags = []
            scope = item['metadata'].get('scope', 'personal')
            date = item['metadata'].get('date')
            
            saved = memory.save_fact(
                fact_text=english_fact,
                category=category,
                confidence=confidence,
                source=f"{source}_translated",
                tags=tags,
                scope=scope,
                date=date
            )
            
            if saved:
                print("   ✓ Saved English version")
            else:
                print("   ⚠️ Could not save (may already exist)")
        
        print(f"\n✓ Migration complete!")
    
    else:
        print("\nCancelled")

if __name__ == "__main__":
    main()
