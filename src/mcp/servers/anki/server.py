#!/usr/bin/env python3
"""Custom Anki MCP Server - starting from working simple server"""

import asyncio
import json
import os
import sys
from datetime import datetime
from pathlib import Path

import httpx

ANKI_CONNECT_URL = "http://127.0.0.1:8765"
ANKI_EPOCH = datetime(2000, 1, 1)

# Load deck config
CONFIG_FILE = Path(__file__).parent / "decks.json"
deck_configs = {}
if CONFIG_FILE.exists():
    with open(CONFIG_FILE, 'r') as f:
        deck_configs = json.load(f)


async def anki_request(action: str, **params):
    """Make request to AnkiConnect"""
    async with httpx.AsyncClient(timeout=5.0) as client:
        payload = {"action": action, "version": 6, "params": params or {}}
        resp = await client.post(ANKI_CONNECT_URL, json=payload)
        resp.raise_for_status()
        result = resp.json()
        if result.get("error"):
            raise Exception(f"AnkiConnect error: {result['error']}")
        return result.get("result")
    

def get_today_days():
    """Get today as days since Anki epoch"""
    return (datetime.now() - ANKI_EPOCH).days


def is_card_due_today(card):
    """Check if card is actually due today - FIX: use interval to determine card type"""
    interval = card.get("interval", 0)
    card_type = card.get("type", 0)
    due = card.get("due", 0)
    today_days = get_today_days()
    
    # AnkiConnect bug: cards with interval > 0 are review cards (even if type=2)
    if interval > 0:
        # Review card - due is days since epoch
            return due <= today_days
    elif card_type == 1:
        # Learning card - due is seconds since epoch
            due_dt = datetime.fromtimestamp(due)
            return due_dt <= datetime.now()
    else:
        # New card (interval = 0) - always "due" if in is:due query
            return True


def get_deck_config(deck_name):
    """Get deck configuration from override file"""
    return deck_configs.get(deck_name, {})


async def get_due_cards(deck_name=None, limit=None):
    """Get cards due today with proper filtering and deck limits
    
    Logic:
    1. New cards: limit to 5 total (perDay from config)
    2. Review cards: 
       - perDay - studied = cards_due_left (remaining limit)
       - Get cards with due=0 (due today) + Again cards
       - If remaining space: cards_due_left - due0_count + again_count = next_due_left
       - Get next_due_left cards from due=1 (tomorrow)
    """
    # Get deck config first
    deck_config = get_deck_config(deck_name) if deck_name else {}
    rev_per_day = deck_config.get("rev", {}).get("perDay", 200) if deck_config else 200
    new_per_day = deck_config.get("new", {}).get("perDay", 20) if deck_config else 20
    
    # Get cards reviewed today (to calculate remaining limit)
    query_reviewed = "rated:1"
    if deck_name:
        query_reviewed = f'deck:"{deck_name}" {query_reviewed}'
    
    card_ids_reviewed_today = await anki_request("findCards", query=query_reviewed)
    reviewed_set = set(card_ids_reviewed_today) if card_ids_reviewed_today else set()
    reviewed_count = len(reviewed_set)
    
    # Get cards rated "Again" today - these need review again
    query_again = "rated:1:1"  # rated today, ease 1 (Again)
    if deck_name:
        query_again = f'deck:"{deck_name}" {query_again}'
    
    card_ids_again_today = await anki_request("findCards", query=query_again)
    again_set = set(card_ids_again_today) if card_ids_again_today else set()
    again_count = len(again_set)
    
    # Calculate remaining review limit: perDay - studied
    cards_due_left = rev_per_day - reviewed_count
    
    # Get cards due TODAY (prop:due=0)
    query_due0 = "prop:due=0"
    if deck_name:
        query_due0 = f'deck:"{deck_name}" {query_due0}'
    
    card_ids_due0 = await anki_request("findCards", query=query_due0)
    
    # Filter logic:
    # - due today = prop:due=0
    # - studied = rated:1 (all cards reviewed today)
    # - again = rated:1:1 (cards rated "Again" today, ease=1)
    # 
    # Filter: Exclude cards that are studied (rated:1) but NOT again (rated:1:1)
    # These are done for today and should not be included
    exclude_set = reviewed_set - again_set  # studied - again = done cards
    card_ids_due0_filtered = [cid for cid in card_ids_due0 if cid not in exclude_set]
    
    # Add Again cards (rated:1:1) - they need review again even if not in due=0
    for cid in again_set:
        if cid not in card_ids_due0_filtered:
            card_ids_due0_filtered.append(cid)
    
    # Calculate counts
    due0_raw_count = len(card_ids_due0)  # All cards with due=0
    due0_count = len(card_ids_due0_filtered)  # Filtered count (after excluding done cards, including again)
    
    # Calculate how many cards we can get from due=1 (tomorrow)
    # Formula: cards_due_left - due0_raw + again = next_due_left
    # Use raw due0 count (all cards with due=0), not filtered count
    next_due_left = cards_due_left - due0_raw_count + again_count
    
    # Get cards from due=1 (tomorrow) if we have space
    card_ids_due1 = []
    if next_due_left > 0:
        query_due1 = "prop:due=1"
        if deck_name:
            query_due1 = f'deck:"{deck_name}" {query_due1}'
        card_ids_due1_all = await anki_request("findCards", query=query_due1)
        # Limit to next_due_left
        card_ids_due1 = card_ids_due1_all[:next_due_left] if card_ids_due1_all else []
    
    # Combine due0 and due1 cards
    card_ids_review = card_ids_due0_filtered + card_ids_due1
    
    # Get NEW cards (limit to 5 per day)
    query_new = "is:new"
    if deck_name:
        query_new = f'deck:"{deck_name}" {query_new}'
    
    card_ids_new_all = await anki_request("findCards", query=query_new)
    card_ids_new = card_ids_new_all[:new_per_day] if card_ids_new_all else []
    
    # Combine all card IDs and remove duplicates
    card_ids = list(dict.fromkeys(card_ids_review + card_ids_new))  # Preserves order, removes duplicates
    
    if not card_ids:
        return {
            "cards": [], 
            "total": 0, 
            "total_all": due0_count,
            "reviewed_today": reviewed_count,
            "again_today": again_count,
            "returned": 0, 
            "message": f"No cards due today (already reviewed {reviewed_count} cards, {again_count} rated Again)"
        }
    
    # Get ALL cards info
    cards_info = await anki_request("cardsInfo", cards=card_ids)
    
    if not cards_info:
        return {"cards": [], "total": 0, "returned": 0, "message": "No cards due"}
    
    # Separate by type - FIX: AnkiConnect bug - cards with interval > 0 are review cards
    # even if type=2. Use interval to determine actual card type.
    review_cards = []
    learning_cards = []
    new_cards = []
    
    for c in cards_info:
        interval = c.get("interval", 0)
        card_type = c.get("type", 0)
        
        # AnkiConnect bug: cards with intervals are review cards, even if type=2
        if interval > 0:
            # Has been studied before - it's a review card
            review_cards.append(c)
        elif card_type == 1:
            # Learning card (in learning phase)
            learning_cards.append(c)
        else:
            # Truly new card (never studied, interval = 0)
            new_cards.append(c)
    
    # Apply new card limit AFTER classification (in case some cards were misclassified)
    # This ensures we never return more than new_per_day new cards
    if len(new_cards) > new_per_day:
        new_cards = new_cards[:new_per_day]
    
    # Store original counts for reporting
    review_count_before = len(review_cards)
    learning_count_before = len(learning_cards)
    new_count_before = len(new_cards)
    
    # Apply sorting based on reviewOrder (from config or default)
    review_order = deck_config.get("reviewOrder", 1)  # Default: due date (1)
    
    if review_order == 0:  # Random
        import random
        random.shuffle(review_cards)
        random.shuffle(learning_cards)
        random.shuffle(new_cards)
    elif review_order == 1:  # Due date (oldest first)
        review_cards.sort(key=lambda c: c.get("due", 0))
        learning_cards.sort(key=lambda c: c.get("due", 0))
        new_cards.sort(key=lambda c: c.get("due", 0))
    elif review_order == 3:  # Intervals ascending (shortest intervals first)
        review_cards.sort(key=lambda c: (c.get("interval", 0), c.get("due", 0)))
        learning_cards.sort(key=lambda c: (c.get("interval", 0), c.get("due", 0)))
        new_cards.sort(key=lambda c: (c.get("interval", 0), c.get("due", 0)))
    else:
        # Default: by due date
        review_cards.sort(key=lambda c: c.get("due", 0))
        learning_cards.sort(key=lambda c: c.get("due", 0))
        new_cards.sort(key=lambda c: c.get("due", 0))
    
    # Limits are already applied when fetching cards, but ensure we don't exceed
    # (cards are already limited: review from due0+due1, new to new_per_day)
    
    # Mix new and review based on config
    mix_new_and_review = deck_config.get("mixNewAndReview", True) if deck_config else True
    if mix_new_and_review:
        # Interleave: reviews first, then mix new with remaining reviews
        today_cards = review_cards + learning_cards + new_cards
    else:
        # Separate: all reviews first, then all new
        today_cards = review_cards + learning_cards + new_cards
    
    # Apply user limit if specified
    if limit:
        today_cards = today_cards[:limit]
    
    # Get note info for selected cards - batch call for performance
    note_ids = [card.get("note") for card in today_cards if card.get("note")]
    notes_info = await anki_request("notesInfo", notes=note_ids) if note_ids else []
    
    # Create a map of note_id -> note_info for quick lookup
    notes_map = {note.get("noteId"): note for note in notes_info if note}
    
    # Remove duplicates by cardId before building final list
    seen_card_ids = set()
    due_cards = []
    for card in today_cards:
        card_id = card.get("cardId")
        if card_id in seen_card_ids:
            continue  # Skip duplicate
        seen_card_ids.add(card_id)
        
        note_id = card.get("note")
        if note_id and note_id in notes_map:
            note = notes_map[note_id]
            fields = note.get("fields", {})
            front = fields.get("Front", {}).get("value", "")
            back = fields.get("Back", {}).get("value", "")
            if not front and not back:
                field_vals = list(fields.values())
                if field_vals:
                    front = field_vals[0].get("value", "")
                if len(field_vals) > 1:
                    back = field_vals[1].get("value", "")
            
            due_cards.append({
                "cardId": card_id,
                "front": front,
                "back": back,
                "deckName": card.get("deckName", "Unknown"),
                "modelName": card.get("modelName", "Unknown"),
                "due": card.get("due"),
                "interval": card.get("interval", 0),
                "type": card.get("type", 0),
            })
    
    # Build detailed message
    total_found = len(review_cards) + len(learning_cards) + len(new_cards)
    completed_today = reviewed_count - again_count
    
    msg_parts = []
    msg_parts.append(f"Found {total_found} cards to review (limit: {rev_per_day} review/day, {new_per_day} new/day, {reviewed_count} already studied, {again_count} rated Again)")
    if review_count_before > 0 or learning_count_before > 0 or new_count_before > 0:
        type_breakdown = []
        if review_count_before > 0:
            type_breakdown.append(f"{review_count_before} review (limited to {len(review_cards)})")
        if learning_count_before > 0:
            type_breakdown.append(f"{learning_count_before} learning (limited to {len(learning_cards)})")
        if new_count_before > 0:
            type_breakdown.append(f"{new_count_before} new (limited to {len(new_cards)})")
        if type_breakdown:
            msg_parts.append(f"Breakdown: {', '.join(type_breakdown)}")
    msg_parts.append(f"Returning {len(due_cards)} cards total ({len(review_cards)} review + {len(learning_cards)} learning + {len(new_cards)} new)")
    message = ". ".join(msg_parts)
    
    return {
        "cards": due_cards,
        "total": len(due_cards),
        "total_all": due0_count,
        "reviewed_today": reviewed_count,
        "again_today": again_count,
        "cards_due_left": cards_due_left,
        "next_due_left": next_due_left,
        "returned": len(due_cards),
        "breakdown": {
            "review": {"found": review_count_before, "returned": len(review_cards)},
            "learning": {"found": learning_count_before, "returned": len(learning_cards)},
            "new": {"found": new_count_before, "returned": len(new_cards)}
        },
        "message": message
    }


def main():
    # Unbuffered output
    sys.stdout.reconfigure(line_buffering=True) if hasattr(sys.stdout, 'reconfigure') else None
    
    while True:
        try:
            line = sys.stdin.readline()
            if not line:
                break
            
            line = line.strip()
            if not line:
                continue
            
            request = json.loads(line)
            method = request.get("method")
            request_id = request.get("id")
            
            # Handle initialize
            if method == "initialize":
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "protocolVersion": request.get("params", {}).get("protocolVersion", "2024-11-05"),
                        "capabilities": {
                            "tools": {}
                        },
                        "serverInfo": {
                            "name": "anki",
                            "version": "1.0.0"
                        }
                    }
                }
                print(json.dumps(response), flush=True)
            
            # Handle tools/list
            elif method == "tools/list":
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "result": {
                        "tools": [
                            {
                                "name": "list_decks",
                                "description": "List all Anki decks",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {}
                                }
                            },
                            {
                                "name": "get_due_cards",
                                "description": "Get cards due for review today. Filters to only cards actually due today, applies deck limits and sorting from decks.json",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "deck_name": {
                                            "type": "string",
                                            "description": "Deck name (required)"
                                        },
                                        "limit": {
                                            "type": "integer",
                                            "description": "Max cards to return (optional, uses deck limits if not specified)"
                                        }
                                    },
                                    "required": ["deck_name"]
                                }
                            },
                            {
                                "name": "get_next_card",
                                "description": "Get the next card due for review. Returns the first card from the sorted due cards list.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "deck_name": {
                                            "type": "string",
                                            "description": "Deck name (required)"
                                        }
                                    },
                                    "required": ["deck_name"]
                                }
                            },
                            {
                                "name": "rate_card",
                                "description": "Rate a card after reviewing. 1=Again (show again soon), 2=Hard, 3=Good, 4=Easy. This schedules the next review.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "card_id": {
                                            "type": "integer",
                                            "description": "Card ID to rate"
                                        },
                                        "rating": {
                                            "type": "integer",
                                            "description": "Rating: 1=Again, 2=Hard, 3=Good, 4=Easy",
                                            "minimum": 1,
                                            "maximum": 4
                                        }
                                    },
                                    "required": ["card_id", "rating"]
                                }
                            },
                            {
                                "name": "sync",
                                "description": "Sync Anki with AnkiWeb to upload/download changes.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {}
                                }
                            }
                        ]
                    }
                }
                print(json.dumps(response), flush=True)
            
            # Handle tools/call
            elif method == "tools/call":
                tool_name = request.get("params", {}).get("name")
                args = request.get("params", {}).get("arguments", {})
                
                if tool_name == "list_decks":
                    try:
                        decks = asyncio.run(anki_request("deckNames"))
                        result = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                                "content": [{
                                    "type": "text",
                                    "text": json.dumps({"decks": decks, "total": len(decks)})
                                }]
                            }
                        }
                        print(json.dumps(result), flush=True)
                    except Exception as e:
                        error_response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": f"Failed to list decks: {str(e)}"}
                        }
                        print(json.dumps(error_response), flush=True)
                
                elif tool_name == "get_due_cards":
                    try:
                        deck_name = args.get("deck_name")
                        if not deck_name:
                            raise ValueError("deck_name is required")
                        limit = args.get("limit")
                        result_data = asyncio.run(get_due_cards(deck_name=deck_name, limit=limit))
                        result = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                                "content": [{
                                    "type": "text",
                                    "text": json.dumps(result_data)
                                }]
                            }
                        }
                        print(json.dumps(result), flush=True)
                    except Exception as e:
                        error_response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": f"Failed to get due cards: {str(e)}"}
                        }
                        print(json.dumps(error_response), flush=True)
                
                elif tool_name == "get_next_card":
                    try:
                        deck_name = args.get("deck_name")
                        if not deck_name:
                            raise ValueError("deck_name is required")
                        # Get all cards to review (sorted by config) and pick the top one
                        result_data = asyncio.run(get_due_cards(deck_name=deck_name))
                        cards = result_data.get("cards", [])
                        if cards:
                            card = cards[0]  # Top card from sorted list
                            result = {
                                "jsonrpc": "2.0",
                                "id": request_id,
                                "result": {
                                    "content": [{
                                        "type": "text",
                                        "text": json.dumps({
                                            "card": card,
                                            "message": "Next card ready for review"
                                        })
                                    }]
                                }
                            }
                        else:
                            result = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                                    "content": [{
                                        "type": "text",
                                        "text": json.dumps({
                                            "card": None,
                                            "message": "Nothing to review"
                                        })
                                    }]
                                }
                            }
                        print(json.dumps(result), flush=True)
                    except Exception as e:
                        error_response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": f"Failed to get next card: {str(e)}"}
                        }
                        print(json.dumps(error_response), flush=True)
                
                elif tool_name == "present_card":
                    try:
                        card_id = args.get("card_id")
                        show_answer = args.get("show_answer", False)
                        cards = asyncio.run(anki_request("cardsInfo", cards=[card_id]))
                        if cards:
                            card = cards[0]
                            note_id = card.get("note")
                            note_info = asyncio.run(anki_request("notesInfo", notes=[note_id]))
                            if note_info:
                                note = note_info[0]
                            fields = note.get("fields", {})
                            front = fields.get("Front", {}).get("value", "")
                            back = fields.get("Back", {}).get("value", "")
                            if not front and not back:
                                field_vals = list(fields.values())
                                if field_vals:
                                    front = field_vals[0].get("value", "")
                                if len(field_vals) > 1:
                                    back = field_vals[1].get("value", "")
                                result_data = {"cardId": card_id, "front": front}
                                if show_answer:
                                    result_data["back"] = back
                                result = {
                                    "jsonrpc": "2.0",
                                    "id": request_id,
                                    "result": {
                                        "content": [{
                                            "type": "text",
                                            "text": json.dumps(result_data)
                                        }]
                                    }
                                }
                                print(json.dumps(result), flush=True)
                            else:
                                raise Exception("Could not get note info")
                        else:
                            raise Exception("Card not found")
                    except Exception as e:
                        error_response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": f"Failed to present card: {str(e)}"}
                        }
                        print(json.dumps(error_response), flush=True)
                
                elif tool_name == "rate_card":
                    try:
                        card_id = args.get("card_id")
                        rating = args.get("rating")
                        rating_names = {1: "Again", 2: "Hard", 3: "Good", 4: "Easy"}
                        
                        # First select the card to put it at top of queue
                        asyncio.run(anki_request("guiSelectCard", card=card_id))
                        # Small delay to let Anki process the selection
                        import time
                        time.sleep(0.3)
                        # Now answer it using answerCards (works without GUI)
                        result_data = asyncio.run(anki_request("answerCards", answers=[{"cardId": card_id, "ease": rating}]))
                        success = result_data[0] if isinstance(result_data, list) and len(result_data) > 0 else bool(result_data)
                        
                        result = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                                "content": [{
                                    "type": "text",
                                    "text": json.dumps({
                                "success": success,
                                "card_id": card_id,
                                "rating": rating,
                                        "rating_name": rating_names.get(rating, "Unknown"),
                                        "message": f"Card rated: {rating_names.get(rating, 'Unknown')}"
                                    })
                                }]
                            }
                        }
                        print(json.dumps(result), flush=True)
                    except Exception as e:
                        error_response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                            "error": {"code": -32603, "message": f"Failed to rate card: {str(e)}"}
                        }
                        print(json.dumps(error_response), flush=True)
                
                elif tool_name == "sync":
                    try:
                        # Sync with AnkiWeb (returns None on success)
                        result_data = asyncio.run(anki_request("sync"))
                        # AnkiConnect sync returns None on success, so no exception means success
                        result = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "content": [{
                                    "type": "text",
                                    "text": json.dumps({
                                        "success": True,
                                        "message": "Anki synced with AnkiWeb successfully"
                                    })
                                }]
                            }
                        }
                        print(json.dumps(result), flush=True)
                    except Exception as e:
                        error_response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": f"Failed to sync: {str(e)}"}
                        }
                        print(json.dumps(error_response), flush=True)
                
                else:
                    error_response = {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"}
                    }
                    print(json.dumps(error_response), flush=True)
            
            # Handle notifications (no response)
            elif method and not request_id:
                    continue
                
            else:
                # Unknown method
                response = {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": "Method not found"}
                }
                print(json.dumps(response), flush=True)
                
        except (KeyboardInterrupt, EOFError):
            break
        except Exception as e:
            error_response = {
                "jsonrpc": "2.0",
                "id": request.get("id") if 'request' in locals() else None,
                "error": {"code": -32603, "message": str(e)}
            }
            print(json.dumps(error_response), flush=True)

if __name__ == "__main__":
    main()
