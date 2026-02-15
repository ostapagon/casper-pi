"""Memory system for agent learning and conversation persistence"""
import hashlib
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional

from google import genai
import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer


class MemoryManager:
    """Manages long-term memory for the agent"""
    
    def __init__(self, db_path: Optional[str] = None, api_key: Optional[str] = None, 
                 use_embeddings: bool = True):
        """Initialize memory manager
        
        Args:
            db_path: Path used for local storage (default: data/memory.db)
            api_key: Gemini API key for fact extraction
            use_embeddings: Enable local embedding model for semantic search (default: True)
        """
        # Setup storage directory (ChromaDB + local artifacts)
        self.db_path = db_path or os.path.join(os.getcwd(), "data", "memory.db")
        data_dir = Path(self.db_path).parent
        data_dir.mkdir(parents=True, exist_ok=True)
        
        # Gemini client for fact extraction
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None
        self.model = os.getenv("AGENT_MODEL", "gemini-1.5-flash")
        
        # Initialize local embedding model (tiny, fast, runs on Pi!)
        self.use_embeddings = use_embeddings and os.getenv("USE_VECTOR_MEMORY", "true").lower() == "true"
        self.embedding_model = None
        
        if self.use_embeddings:
            try:
                print("🔧 Loading embedding model (all-MiniLM-L6-v2, ~80MB, one-time download)...")
                self.embedding_model = SentenceTransformer('all-MiniLM-L6-v2', device='cpu')
                self.embedding_model.max_seq_length = 128  # Limit for speed on Pi
                dim = self.embedding_model.get_sentence_embedding_dimension()
                print(f"✓ Embedding model ready ({dim}D vectors)")
            except Exception as e:
                print(f"⚠️ Could not load embedding model: {e}")
                print("  → Falling back to keyword search")
                self.use_embeddings = False
        
        # Initialize ChromaDB (vector memory storage)
        if self.use_embeddings:
            chroma_path = os.path.join(data_dir, "chroma")
            self.chroma_client = chromadb.PersistentClient(
                path=str(chroma_path),
                settings=Settings(anonymized_telemetry=False)
            )
            self.facts_collection = self.chroma_client.get_or_create_collection(
                name="facts",
                metadata={"description": "Vector embeddings of learned facts"}
            )
            self.conversations_collection = self.chroma_client.get_or_create_collection(
                name="conversations",
                metadata={"description": "Conversation summaries and metadata"}
            )
            self.task_patterns_collection = self.chroma_client.get_or_create_collection(
                name="task_patterns",
                metadata={"description": "Task usage patterns and preferences"}
            )
        else:
            self.chroma_client = None
            self.facts_collection = None
            self.conversations_collection = None
            self.task_patterns_collection = None
    
    
    def store_conversation(self, session_id: str, messages: List[Dict[str, Any]], 
                          summary: Optional[str] = None) -> str:
        """Store a conversation in memory
        
        Args:
            session_id: Session identifier
            messages: List of conversation messages
            summary: Optional pre-generated summary
            
        Returns:
            conversation_id: ID of stored conversation
        """
        if not self.conversations_collection:
            return ""
        
        # Extract key topics (simple keyword extraction)
        key_topics = self._extract_topics(messages)
        
        # Generate summary if not provided
        if not summary and len(messages) > 2:
            summary = self._generate_summary(messages)
        
        timestamp = datetime.now().isoformat()
        summary_text = summary or "No summary"
        doc_text = summary_text
        if key_topics:
            doc_text += f"\nTopics: {', '.join(key_topics)}"
        
        embedding = self._get_embedding(doc_text)
        if not embedding:
            return ""
        
        conv_id_seed = f"{session_id}:{timestamp}:{summary_text}"
        conv_id = f"conv_{hashlib.sha1(conv_id_seed.encode('utf-8')).hexdigest()[:12]}"
        
        metadata = {
            "session_id": session_id,
            "timestamp": timestamp,
            "key_topics": json.dumps(key_topics),
            "message_count": len(messages),
            "created_at": timestamp
        }
        
        try:
            self.conversations_collection.add(
                ids=[conv_id],
                embeddings=[embedding],
                documents=[doc_text],
                metadatas=[metadata]
            )
        except Exception as e:
            print(f"⚠️ Error storing conversation: {e}")
            return ""
        
        return conv_id
    
    def _get_embedding(self, text: str) -> Optional[List[float]]:
        """Generate embedding for text using local model (fast, no API)
        
        Args:
            text: Text to embed
            
        Returns:
            List of floats (embedding vector) or None if failed
        """
        if not self.embedding_model:
            return None
        
        try:
            # Generate embedding locally (no API call!)
            embedding = self.embedding_model.encode(text, convert_to_numpy=True)
            return embedding.tolist()
        except Exception as e:
            print(f"⚠️ Embedding generation failed: {e}")
            return None

    def _fact_id(self, category: str, fact_text: str) -> str:
        """Stable ID for a fact"""
        key = f"{category}:{fact_text}".strip().lower()
        return f"fact_{hashlib.sha1(key.encode('utf-8')).hexdigest()[:12]}"

    def save_fact(
        self,
        fact_text: str,
        category: str = "general",
        confidence: float = 1.0,
        source: str = "manual",
        tags: Optional[List[str]] = None,
        scope: Optional[str] = None,
        date: Optional[str] = None
    ) -> bool:
        """Store a single fact in vector memory with metadata"""
        if not self.facts_collection:
            return False
        
        if not fact_text:
            return False
        
        embedding = self._get_embedding(fact_text)
        if not embedding:
            return False
        
        created_at = datetime.now().isoformat()
        date_value = date or created_at.split("T")[0]
        scope_value = scope or ("personal" if source.startswith(("telegram", "voice")) else "generic")
        
        tags_list = [t.strip() for t in (tags or []) if t and t.strip()]
        if category and category not in tags_list:
            tags_list.append(category)
        
        fact_id = self._fact_id(category, fact_text)
        try:
            existing = self.facts_collection.get(ids=[fact_id])
            if existing and existing.get("ids"):
                return False
        except Exception:
            pass
        
        metadata = {
            "category": category,
            "confidence": float(confidence),
            "source": source,
            "scope": scope_value,
            "date": date_value,
            "created_at": created_at,
            "tags": json.dumps(tags_list)
        }
        
        try:
            self.facts_collection.add(
                ids=[fact_id],
                embeddings=[embedding],
                documents=[fact_text],
                metadatas=[metadata]
            )
            return True
        except Exception as e:
            print(f"⚠️ Error storing fact: {e}")
            return False
    
    def extract_and_store_facts(self, messages: List[Dict[str, Any]], source: str = "conversation", 
                                force: bool = False):
        """Extract facts from conversation and store them in ChromaDB
        
        Args:
            messages: List of conversation messages
            source: Source identifier for these facts
            force: Force extraction even if rate limited
        """
        if not self.client:
            return
        
        # Skip fact extraction if too few messages (not worth API call)
        if len(messages) < 4:
            return
        
        # Use Gemini to extract facts
        facts = self._extract_facts_with_ai(messages)
        
        if not facts:
            return
        
        stored_count = 0
        # Keep only the most confident facts (limit per conversation)
        max_facts = int(os.getenv("FACTS_PER_CONVERSATION", "5"))
        min_confidence = float(os.getenv("FACT_MIN_CONFIDENCE", "0.6"))
        facts = sorted(
            facts,
            key=lambda f: float(f.get("confidence", 0.0)) if isinstance(f, dict) else 0.0,
            reverse=True
        )
        facts = [
            f for f in facts
            if isinstance(f, dict) and float(f.get("confidence", 0.0)) >= min_confidence
        ][:max_facts]
        for fact_data in facts:
            try:
                fact_text = fact_data.get("fact", "")
                category = fact_data.get("category", "general")
                confidence = fact_data.get("confidence", 1.0)
                tags = fact_data.get("tags") if isinstance(fact_data.get("tags"), list) else None
                scope = fact_data.get("scope")
                date = fact_data.get("date")
                
                if self.save_fact(
                    fact_text=fact_text,
                    category=category,
                    confidence=confidence,
                    source=source,
                    tags=tags,
                    scope=scope,
                    date=date
                ):
                    stored_count += 1
                            
            except Exception as e:
                print(f"⚠️ Error storing fact: {e}")
        
        if stored_count > 0:
            print(f"  ✓ Stored {stored_count} new facts (with embeddings)")
    
    def record_task_usage(self, task_type: str, preferences: Optional[Dict[str, Any]] = None):
        """Record task usage for learning patterns
        
        Args:
            task_type: Type of task executed
            preferences: Optional preferences/parameters used
        """
        if not self.task_patterns_collection:
            return
        
        current_time = datetime.now()
        hour = current_time.strftime("%H")
        task_id = f"task_{hashlib.sha1(task_type.encode('utf-8')).hexdigest()[:12]}"
        
        existing_meta = None
        try:
            existing = self.task_patterns_collection.get(ids=[task_id], include=["metadatas"])
            if existing and existing.get("metadatas"):
                existing_meta = existing["metadatas"][0]
        except Exception:
            existing_meta = None
        
        frequency = int(existing_meta.get("frequency", 0)) + 1 if existing_meta else 1
        
        metadata = {
            "task_type": task_type,
            "frequency": frequency,
            "preferences": json.dumps(preferences) if preferences else None,
            "typical_time": hour,
            "last_used": current_time.isoformat(),
            "created_at": existing_meta.get("created_at") if existing_meta else current_time.isoformat()
        }
        # Chroma metadata cannot contain None values
        metadata = {key: value for key, value in metadata.items() if value is not None}
        
        doc_text = f"Task: {task_type} | frequency={frequency}"
        if preferences:
            doc_text += f" | preferences={json.dumps(preferences)}"
        embedding = self._get_embedding(doc_text) or self._get_embedding(task_type)
        if not embedding:
            return
        
        try:
            if existing_meta:
                self.task_patterns_collection.update(
                    ids=[task_id],
                    embeddings=[embedding],
                    documents=[doc_text],
                    metadatas=[metadata]
                )
            else:
                self.task_patterns_collection.add(
                    ids=[task_id],
                    embeddings=[embedding],
                    documents=[doc_text],
                    metadatas=[metadata]
                )
        except Exception as e:
            print(f"⚠️ Error recording task usage: {e}")
    
    def get_facts_by_time(self, days_ago: int = 0, max_facts: int = 20) -> List[Dict[str, Any]]:
        """Get facts from a specific day (0=today, 1=yesterday, etc.)"""
        if not self.facts_collection:
            return []
        
        try:
            target_date = (datetime.now().date() - timedelta(days=days_ago)).isoformat()
            
            results = self.facts_collection.get(
                where={"date": target_date},
                include=['documents', 'metadatas']
            )
            
            facts = []
            if results and results.get('documents'):
                for i, doc in enumerate(results['documents']):
                    metadata = results['metadatas'][i] if results.get('metadatas') else {}
                    tags_raw = metadata.get("tags", "[]")
                    try:
                        tags = json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or [])
                    except Exception:
                        tags = []
                    facts.append({
                        "category": metadata.get("category", "general"),
                        "fact": doc,
                        "confidence": metadata.get("confidence", 1.0),
                        "date": metadata.get("date", target_date),
                        "scope": metadata.get("scope", "personal"),
                        "tags": tags
                    })
            
            return facts[:max_facts]
        except Exception as e:
            print(f"⚠️ Time-based filtering failed: {e}")
            return []
    
    def get_relevant_context(self, session_id: str, current_message: str, 
                            max_facts: int = 10, max_conversations: int = 3,
                            time_filter: Optional[str] = None) -> Dict[str, Any]:
        """Retrieve relevant memory context using vector search
        
        Args:
            session_id: Current session ID
            current_message: Current user message (for relevance matching)
            max_facts: Maximum number of facts to retrieve
            max_conversations: Maximum past conversations to include
            time_filter: Optional time filter ('today', 'yesterday', 'recent')
            
        Returns:
            Dictionary with relevant memories
        """
        context = {
            "facts": [],
            "recent_conversations": [],
            "task_patterns": []
        }
        
        # Check for time-based queries
        if time_filter or any(word in current_message.lower() for word in ['today', "today's", 'yesterday', "yesterday's"]):
            # Use time-based filtering
            if 'today' in current_message.lower() or time_filter == 'today':
                return {"facts": self.get_facts_by_time(days_ago=0, max_facts=max_facts),
                       "recent_conversations": [], "task_patterns": []}
            elif 'yesterday' in current_message.lower() or time_filter == 'yesterday':
                return {"facts": self.get_facts_by_time(days_ago=1, max_facts=max_facts),
                       "recent_conversations": [], "task_patterns": []}
        
        # Use vector search (semantic matching)
        vector_facts = []
        if self.embedding_model and self.facts_collection and current_message:
            try:
                # Generate embedding for query
                query_embedding = self._get_embedding(current_message)
                
                if query_embedding:
                    # Search vector database
                    results = self.facts_collection.query(
                        query_embeddings=[query_embedding],
                        n_results=min(max_facts * 2, 20)  # Get extras for filtering
                    )
                    
                    # Convert ChromaDB results to our format
                    if results and results['documents'] and len(results['documents'][0]) > 0:
                        for i, doc in enumerate(results['documents'][0]):
                            metadata = results['metadatas'][0][i] if results['metadatas'] else {}
                            distance = results['distances'][0][i] if results['distances'] else 999.0
                            
                            # ChromaDB uses cosine distance (0 = identical, 2 = opposite)
                            # Include semantically relevant facts (distance < 1.6 for good matches)
                            if distance < 1.6:
                                tags_raw = metadata.get("tags", "[]")
                                try:
                                    tags = json.loads(tags_raw) if isinstance(tags_raw, str) else (tags_raw or [])
                                except Exception:
                                    tags = []
                                vector_facts.append({
                                    "category": metadata.get("category", "general"),
                                    "fact": doc,
                                    "confidence": metadata.get("confidence", 1.0),
                                    "similarity": max(0, 1.0 - (distance / 2.0)),  # Normalize to 0-1
                                    "scope": metadata.get("scope", "personal"),
                                    "tags": tags,
                                    "date": metadata.get("date")
                                })
                        
                        print(f"  ✓ Vector search found {len(vector_facts)} relevant facts")
            except Exception as e:
                print(f"⚠️ Vector search failed: {e}")
        
        # Sort by similarity and return top results
        # Optional metadata filters from query text
        scope_filter = None
        if current_message:
            message_lower = current_message.lower()
            if "personal" in message_lower:
                scope_filter = "personal"
            elif "generic" in message_lower:
                scope_filter = "generic"
            tag_filters = [word[1:].lower() for word in message_lower.split() if word.startswith("#")]
        else:
            tag_filters = []
        
        if scope_filter or tag_filters:
            filtered_facts = []
            for fact in vector_facts:
                if scope_filter and fact.get("scope") != scope_filter:
                    continue
                if tag_filters:
                    fact_tags = [t.lower() for t in (fact.get("tags") or [])]
                    if not any(tag in fact_tags for tag in tag_filters):
                        continue
                filtered_facts.append(fact)
            vector_facts = filtered_facts
        
        context["facts"] = sorted(vector_facts, key=lambda x: x.get('similarity', 0), reverse=True)[:max_facts]
        
        # Get recent conversations from this session
        if self.conversations_collection:
            try:
                results = self.conversations_collection.get(
                    where={"session_id": session_id},
                    include=["documents", "metadatas"]
                )
                conversations = []
                if results and results.get("documents"):
                    for i, doc in enumerate(results["documents"]):
                        metadata = results["metadatas"][i] if results.get("metadatas") else {}
                        topics_raw = metadata.get("key_topics", "[]")
                        try:
                            topics = json.loads(topics_raw) if isinstance(topics_raw, str) else (topics_raw or [])
                        except Exception:
                            topics = []
                        summary_text = doc.split("\n")[0] if doc else ""
                        conversations.append({
                            "summary": summary_text,
                            "topics": topics,
                            "timestamp": metadata.get("timestamp")
                        })
                context["recent_conversations"] = sorted(
                    conversations,
                    key=lambda x: x.get("timestamp", ""),
                    reverse=True
                )[:max_conversations]
            except Exception as e:
                print(f"⚠️ Conversation retrieval failed: {e}")
        
        # Get common task patterns
        if self.task_patterns_collection:
            try:
                results = self.task_patterns_collection.get(include=["metadatas"])
                patterns = []
                if results and results.get("metadatas"):
                    for metadata in results["metadatas"]:
                        if not metadata:
                            continue
                        prefs_raw = metadata.get("preferences")
                        try:
                            prefs = json.loads(prefs_raw) if isinstance(prefs_raw, str) else prefs_raw
                        except Exception:
                            prefs = None
                        patterns.append({
                            "task": metadata.get("task_type"),
                            "frequency": int(metadata.get("frequency", 0)),
                            "preferences": prefs,
                            "typical_time": metadata.get("typical_time")
                        })
                context["task_patterns"] = sorted(
                    patterns,
                    key=lambda x: x.get("frequency", 0),
                    reverse=True
                )[:10]
            except Exception as e:
                print(f"⚠️ Task pattern retrieval failed: {e}")
        
        return context
    
    def _extract_topics(self, messages: List[Dict[str, Any]]) -> List[str]:
        """Extract key topics from messages (simple keyword extraction)"""
        topics = set()
        keywords = ["anki", "card", "deck", "calendar", "event", "schedule", "task", 
                   "reminder", "learn", "study", "chinese", "language"]
        
        for msg in messages:
            content = str(msg.get("content", "")).lower()
            for keyword in keywords:
                if keyword in content:
                    topics.add(keyword)
        
        return list(topics)
    
    def _generate_summary(self, messages: List[Dict[str, Any]]) -> str:
        """Generate a summary of the conversation"""
        if not self.client or len(messages) < 2:
            return "Brief conversation"
        
        try:
            # Build conversation text
            conversation_text = "\n".join([
                f"{msg.get('role', 'user')}: {msg.get('content', '')}"
                for msg in messages[-10:]  # Last 10 messages
            ])
            
            prompt = f"""Summarize this conversation in one concise sentence (max 100 characters).
Write the summary in English regardless of the conversation language.

{conversation_text}

Summary (in English):"""
            
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt
            )
            
            summary = response.text.strip()
            return summary[:200]  # Max 200 chars
            
        except Exception as e:
            # If rate limited, return simple summary
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                return "Voice conversation (rate limited, skipped summary)"
            print(f"⚠️ Summary generation failed: {e}")
            return "Conversation about tasks"

    def summarize_messages(self, messages: List[Dict[str, Any]]) -> str:
        """Public helper to summarize a list of messages"""
        return self._generate_summary(messages)
    
    def _extract_facts_with_ai(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Use AI to extract important facts from conversation"""
        if not self.client or len(messages) < 2:
            return []
        
        # Retry logic for rate limiting
        max_retries = 3
        base_delay = 5  # Start with 5 seconds for rate limits
        
        for attempt in range(max_retries):
            try:
                # Build conversation text
                conversation_text = "\n".join([
                    f"{msg.get('role', 'user')}: {msg.get('content', '')}"
                    for msg in messages
                ])
                
                prompt = f"""Extract important facts about the user from this conversation. 
Focus on:
- Preferences (what they like/dislike)
- Habits (regular activities, schedules)
- Important information (names, relationships, goals)
- Learning patterns (subjects they study, decks they use)

IMPORTANT: Write all facts in English, regardless of the conversation language. 
If the conversation contains non-English words (Ukrainian, Chinese, etc.), translate or transliterate names/terms appropriately.
For proper names, use Latin alphabet transliteration (e.g., "Ostap" not "Остап").

Conversation:
{conversation_text}

Return a JSON array of facts. Each fact should have:
- category: one of [preference, habit, information, learning]
- fact: a clear, concise statement IN ENGLISH
- confidence: 0.0 to 1.0
- tags: optional array of short tags (in English)
- scope: optional "personal" or "generic"
- date: optional ISO date (YYYY-MM-DD) if a time is mentioned

Example: {{"category": "learning", "fact": "Studies Chinese language daily", "confidence": 0.9}}

Return ONLY the JSON array, no other text:"""
                
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt
                )
                
                # Parse JSON response
                text = response.text.strip()
                # Remove markdown code blocks if present
                if text.startswith("```"):
                    text = text.split("```")[1]
                    if text.startswith("json"):
                        text = text[4:]
                
                facts = json.loads(text)
                return facts if isinstance(facts, list) else []
                
            except Exception as e:
                error_str = str(e)
                # Check if it's a rate limit error (429)
                if "429" in error_str or "RESOURCE_EXHAUSTED" in error_str:
                    if attempt < max_retries - 1:
                        wait_time = base_delay * (attempt + 1)
                        print(f"⚠️ Rate limited during fact extraction, will retry in {wait_time}s (attempt {attempt + 1}/{max_retries})")
                        time.sleep(wait_time)
                        continue
                    else:
                        # Max retries reached, silently fail (not critical)
                        print(f"⚠️ Fact extraction skipped due to rate limiting (will try next time)")
                        return []
                else:
                    # Other error, log and return
                    print(f"⚠️ Fact extraction failed: {e}")
                    return []
        
        return []

    
    def get_stats(self) -> Dict[str, Any]:
        """Get memory statistics"""
        stats: Dict[str, Any] = {}
        
        # Count conversations
        if self.conversations_collection:
            try:
                stats["total_conversations"] = self.conversations_collection.count()
            except Exception:
                stats["total_conversations"] = 0
        else:
            stats["total_conversations"] = 0
        
        # Count facts by category
        stats["facts_by_category"] = {}
        if self.facts_collection:
            try:
                results = self.facts_collection.get(include=["metadatas"])
                if results and results.get("metadatas"):
                    for metadata in results["metadatas"]:
                        if not metadata:
                            continue
                        category = metadata.get("category", "general")
                        stats["facts_by_category"][category] = stats["facts_by_category"].get(category, 0) + 1
                stats["total_facts"] = sum(stats["facts_by_category"].values())
            except Exception:
                stats["total_facts"] = 0
        else:
            stats["total_facts"] = 0
        
        # Count task patterns
        if self.task_patterns_collection:
            try:
                stats["task_patterns"] = self.task_patterns_collection.count()
            except Exception:
                stats["task_patterns"] = 0
        else:
            stats["task_patterns"] = 0
        
        # Most accessed facts (not tracked in vector store)
        stats["top_facts"] = []
        
        return stats
    
    def clear_old_conversations(self, days: int = 90):
        """Clear conversations older than specified days
        
        Args:
            days: Keep conversations from last N days
        """
        if not self.conversations_collection:
            return 0
        
        cutoff_dt = datetime.now() - timedelta(days=days)
        delete_ids = []
        
        try:
            results = self.conversations_collection.get(include=["metadatas", "ids"])
            if results and results.get("ids"):
                for i, conv_id in enumerate(results["ids"]):
                    metadata = results["metadatas"][i] if results.get("metadatas") else {}
                    created_at = metadata.get("created_at") or metadata.get("timestamp")
                    if not created_at:
                        continue
                    try:
                        created_dt = datetime.fromisoformat(created_at)
                        if created_dt < cutoff_dt:
                            delete_ids.append(conv_id)
                    except Exception:
                        continue
            
            if delete_ids:
                self.conversations_collection.delete(ids=delete_ids)
            
            return len(delete_ids)
        except Exception as e:
            print(f"⚠️ Clear old conversations failed: {e}")
            return 0
