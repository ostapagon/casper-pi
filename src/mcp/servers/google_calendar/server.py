#!/usr/bin/env python3
"""Google Calendar MCP Server using Service Account"""

import asyncio
import json
import os
import sys
from datetime import datetime, timedelta
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from googleapiclient.discovery import build

# Load environment variables once at startup
load_dotenv()

# Service account key file path - from env or default location
SERVICE_ACCOUNT_FILE = os.getenv(
    'GOOGLE_CALENDAR_SERVICE_ACCOUNT_PATH',
    str(Path(__file__).parent.parent.parent.parent.parent / "calendar_key.json")
)

def get_user_calendar_email():
    """Get user calendar email dynamically"""
    return os.getenv('GOOGLE_CALENDAR_USER_EMAIL', None)

SCOPES = ['https://www.googleapis.com/auth/calendar']

# Global service instance
_calendar_service = None


def get_calendar_service():
    """Get or create Google Calendar service instance"""
    global _calendar_service
    if _calendar_service is None:
        service_account_path = Path(SERVICE_ACCOUNT_FILE)
        if not service_account_path.exists():
            raise FileNotFoundError(f"Service account file not found: {service_account_path}")
        creds = service_account.Credentials.from_service_account_file(
            str(service_account_path),
            scopes=SCOPES
        )
        _calendar_service = build('calendar', 'v3', credentials=creds)
    return _calendar_service


async def list_calendars():
    """List all accessible calendars"""
    service = get_calendar_service()
    calendar_list = service.calendarList().list(showHidden=True).execute()
    calendars = []
    for item in calendar_list.get('items', []):
        calendars.append({
            'id': item['id'],
            'summary': item.get('summary', 'No Title'),
            'primary': item.get('primary', False)
        })
    
    # If no calendars in list but we have access, try to get primary calendar directly
    # This handles cases where calendar is shared but not yet in calendarList
    if not calendars:
        try:
            primary = service.calendars().get(calendarId='primary').execute()
            calendars.append({
                'id': primary['id'],
                'summary': primary.get('summary', primary.get('id', 'Primary Calendar')),
                'primary': True
            })
        except Exception:
            pass
    
    return calendars


async def list_events(calendar_id='primary', max_results=10, time_min=None, time_max=None):
    """List events from a calendar
    
    Args:
        calendar_id: Calendar ID (default: 'primary', will use USER_CALENDAR_EMAIL if set)
        max_results: Maximum number of events to return
        time_min: Lower bound for event start time (RFC3339 format, e.g., '2026-01-21T00:00:00Z')
        time_max: Upper bound for event start time (RFC3339 format, e.g., '2026-01-21T23:59:59Z')
    """
    service = get_calendar_service()
    
    def _normalize_rfc3339(value: str, is_end: bool = False) -> str:
        """Normalize date/time to RFC3339 with timezone."""
        if not value:
            return value
        value = value.strip()
        # Date-only
        if len(value) == 10 and value.count("-") == 2:
            return f"{value}T23:59:59Z" if is_end else f"{value}T00:00:00Z"
        # If already has timezone info, keep
        if value.endswith("Z") or "+" in value[10:] or "-" in value[10:]:
            return value
        # Time provided but no timezone
        return f"{value}Z"
    
    if time_min is None:
        time_min = datetime.utcnow().isoformat() + 'Z'
    else:
        time_min = _normalize_rfc3339(time_min, is_end=False)
    
    if time_max:
        time_max = _normalize_rfc3339(time_max, is_end=True)
    
    # If calendar_id is 'primary', try user's calendar first, then fall back to service account's primary
    actual_calendar_id = calendar_id
    user_email = get_user_calendar_email()
    if calendar_id == 'primary' and user_email:
        actual_calendar_id = user_email
    
    # Build query parameters
    query_params = {
        'calendarId': actual_calendar_id,
        'timeMin': time_min,
        'maxResults': max_results,
        'singleEvents': True,
        'orderBy': 'startTime'
    }
    
    # Add timeMax if provided for date range filtering
    if time_max:
        query_params['timeMax'] = time_max
    
    try:
        events_result = service.events().list(**query_params).execute()
    except Exception as e:
        # If accessing user calendar failed and we tried that, fall back to service account's primary
        if actual_calendar_id != calendar_id:
            try:
                query_params['calendarId'] = 'primary'
                events_result = service.events().list(**query_params).execute()
                actual_calendar_id = 'primary'
            except Exception as e2:
                raise e2
        else:
            raise e
    
    events = []
    for event in events_result.get('items', []):
        start = event['start'].get('dateTime', event['start'].get('date'))
        end = event['end'].get('dateTime', event['end'].get('date'))
        events.append({
            'id': event['id'],
            'summary': event.get('summary', 'No Title'),
            'start': start,
            'end': end,
            'location': event.get('location', ''),
            'description': event.get('description', '')
        })
    return events


async def create_event(calendar_id='primary', summary=None, start_time=None, end_time=None, description=None, location=None):
    """Create a new calendar event"""
    service = get_calendar_service()
    
    # Resolve 'primary' to user's calendar email if set (same logic as list_events)
    actual_calendar_id = calendar_id
    user_email = get_user_calendar_email()
    if calendar_id == 'primary' and user_email:
        actual_calendar_id = user_email
    
    if start_time is None:
        start_time = datetime.utcnow()
    if end_time is None:
        end_time = start_time + timedelta(hours=1)
    
    event = {
        'summary': summary or 'New Event',
        'start': {
            'dateTime': start_time.isoformat(),
            'timeZone': 'UTC',
        },
        'end': {
            'dateTime': end_time.isoformat(),
            'timeZone': 'UTC',
        },
    }
    
    if description:
        event['description'] = description
    if location:
        event['location'] = location
    
    created_event = service.events().insert(calendarId=actual_calendar_id, body=event).execute()
    return {
        'id': created_event['id'],
        'summary': created_event.get('summary', ''),
        'start': created_event['start'].get('dateTime', created_event['start'].get('date')),
        'htmlLink': created_event.get('htmlLink', '')
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
                            "name": "google-calendar",
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
                                "name": "list_calendars",
                                "description": "List all accessible Google Calendars",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {}
                                }
                            },
                            {
                                "name": "list_calendar_events",
                                "description": "List events from a Google Calendar. Supports date filtering with time_min and time_max for efficient queries.",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "calendar_id": {
                                            "type": "string",
                                            "description": "Calendar ID (default: 'primary', will use USER_CALENDAR_EMAIL if set)",
                                            "default": "primary"
                                        },
                                        "max_results": {
                                            "type": "integer",
                                            "description": "Maximum number of events to return",
                                            "default": 10
                                        },
                                        "time_min": {
                                            "type": "string",
                                            "description": "Lower bound (exclusive) for event start time. RFC3339 timestamp with timezone, e.g., '2026-01-21T00:00:00Z' for start of a day"
                                        },
                                        "time_max": {
                                            "type": "string",
                                            "description": "Upper bound (exclusive) for event start time. RFC3339 timestamp with timezone, e.g., '2026-01-21T23:59:59Z' for end of a day"
                                        }
                                    }
                                }
                            },
                            {
                                "name": "create_event",
                                "description": "Create a new calendar event",
                                "inputSchema": {
                                    "type": "object",
                                    "properties": {
                                        "calendar_id": {
                                            "type": "string",
                                            "description": "Calendar ID (default: 'primary')",
                                            "default": "primary"
                                        },
                                        "summary": {
                                            "type": "string",
                                            "description": "Event title/summary"
                                        },
                                        "start_time": {
                                            "type": "string",
                                            "description": "Start time in ISO format (e.g., '2024-01-15T10:00:00')"
                                        },
                                        "end_time": {
                                            "type": "string",
                                            "description": "End time in ISO format (e.g., '2024-01-15T11:00:00')"
                                        },
                                        "description": {
                                            "type": "string",
                                            "description": "Event description"
                                        },
                                        "location": {
                                            "type": "string",
                                            "description": "Event location"
                                        }
                                    },
                                    "required": ["summary"]
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
                
                if tool_name == "list_calendars":
                    try:
                        calendars = asyncio.run(list_calendars())
                        result = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "content": [{
                                    "type": "text",
                                    "text": json.dumps({"calendars": calendars, "total": len(calendars)})
                                }]
                            }
                        }
                        print(json.dumps(result), flush=True)
                    except Exception as e:
                        error_response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": f"Failed to list calendars: {str(e)}"}
                        }
                        print(json.dumps(error_response), flush=True)
                
                elif tool_name == "list_calendar_events":
                    try:
                        calendar_id = args.get("calendar_id", "primary")
                        max_results = args.get("max_results", 10)
                        time_min = args.get("time_min")
                        time_max = args.get("time_max")
                        events = asyncio.run(list_events(calendar_id, max_results, time_min, time_max))
                        result = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "content": [{
                                    "type": "text",
                                    "text": json.dumps({"events": events, "total": len(events)})
                                }]
                            }
                        }
                        print(json.dumps(result), flush=True)
                    except Exception as e:
                        error_response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": f"Failed to list events: {str(e)}"}
                        }
                        print(json.dumps(error_response), flush=True)
                
                elif tool_name == "create_event":
                    try:
                        calendar_id = args.get("calendar_id", "primary")
                        summary = args.get("summary")
                        if not summary:
                            raise ValueError("summary is required")
                        
                        start_time_str = args.get("start_time")
                        end_time_str = args.get("end_time")
                        
                        start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00')) if start_time_str else None
                        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00')) if end_time_str else None
                        
                        event = asyncio.run(create_event(
                            calendar_id=calendar_id,
                            summary=summary,
                            start_time=start_time,
                            end_time=end_time,
                            description=args.get("description"),
                            location=args.get("location")
                        ))
                        result = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "result": {
                                "content": [{
                                    "type": "text",
                                    "text": json.dumps({"event": event, "success": True})
                                }]
                            }
                        }
                        print(json.dumps(result), flush=True)
                    except Exception as e:
                        error_response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": f"Failed to create event: {str(e)}"}
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


