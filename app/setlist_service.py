"""
Setlist.fm service for Freedify.
Searches for concert setlists and matches them to audio sources (Phish.in, Archive.org).
"""
import os
import httpx
from typing import Optional, Dict, List, Any
from datetime import datetime
import logging

logger = logging.getLogger(__name__)

# API key from environment
SETLIST_FM_API_KEY = os.getenv("SETLIST_FM_API_KEY", "")


class SetlistService:
    """Service for searching and retrieving concert setlists from Setlist.fm."""
    
    API_BASE = "https://api.setlist.fm/rest/1.0"
    
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=15.0,
            headers={
                "Accept": "application/json",
                "x-api-key": SETLIST_FM_API_KEY
            }
        )
    
    async def search_setlists(self, query: str, page: int = 1) -> List[Dict[str, Any]]:
        """Search for setlists by artist name or date.
        
        Examples:
            "Grateful Dead" - search by artist
            "Phish 2023" - artist + year
            "Pearl Jam 1991-09-20" - specific date
        """
        if not SETLIST_FM_API_KEY:
            logger.warning("Setlist.fm API key not configured")
            return []
        
        try:
            # Parse query for artist and potential date
            params = {"p": page}
            
            # Check if query contains a date pattern (YYYY-MM-DD)
            import re
            date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', query)
            year_match = re.search(r'\b(19\d{2}|20\d{2})\b', query)
            
            if date_match:
                # Search by specific date
                params["date"] = date_match.group(0)
                artist_query = query.replace(date_match.group(0), "").strip()
                if artist_query:
                    params["artistName"] = artist_query
            elif year_match:
                # Search by year
                params["year"] = year_match.group(0)
                artist_query = query.replace(year_match.group(0), "").strip()
                if artist_query:
                    params["artistName"] = artist_query
            else:
                # Just artist name
                params["artistName"] = query
            
            logger.info(f"Searching Setlist.fm: {params}")
            response = await self.client.get(f"{self.API_BASE}/search/setlists", params=params)
            
            if response.status_code == 404:
                return []
            
            response.raise_for_status()
            data = response.json()
            
            setlists = data.get("setlist", [])
            return [self._format_setlist(s) for s in setlists[:20]]
            
        except Exception as e:
            logger.error(f"Setlist.fm search error: {e}")
            return []
    
    async def get_setlist(self, setlist_id: str) -> Optional[Dict[str, Any]]:
        """Get full setlist details by ID."""
        if not SETLIST_FM_API_KEY:
            return None
        
        try:
            response = await self.client.get(f"{self.API_BASE}/setlist/{setlist_id}")
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            return self._format_setlist_detail(data)
            
        except Exception as e:
            logger.error(f"Setlist.fm get_setlist error: {e}")
            return None
    
    def _format_setlist(self, item: dict) -> dict:
        """Format setlist data for search results."""
        artist = item.get("artist", {})
        venue = item.get("venue", {})
        city = venue.get("city", {})
        
        # Parse date (format: DD-MM-YYYY)
        event_date = item.get("eventDate", "")
        formatted_date = ""
        iso_date = ""
        if event_date:
            try:
                dt = datetime.strptime(event_date, "%d-%m-%Y")
                formatted_date = dt.strftime("%B %d, %Y")
                iso_date = dt.strftime("%Y-%m-%d")
            except:
                formatted_date = event_date
        
        # Count songs
        song_count = 0
        for setlist_set in item.get("sets", {}).get("set", []):
            song_count += len(setlist_set.get("song", []))
        
        return {
            "id": f"setlist_{item.get('id', '')}",
            "type": "setlist",
            "name": f"{artist.get('name', 'Unknown')} at {venue.get('name', 'Unknown Venue')}",
            "artists": artist.get("name", ""),
            "artist_mbid": artist.get("mbid", ""),
            "venue": venue.get("name", ""),
            "city": f"{city.get('name', '')}, {city.get('stateCode', '')} {city.get('country', {}).get('code', '')}".strip(", "),
            "date": formatted_date,
            "iso_date": iso_date,
            "song_count": song_count,
            "setlist_id": item.get("id", ""),
            "url": item.get("url", ""),
            "source": "setlist.fm",
            # For display
            "album_art": "/static/setlist-icon.svg",  # Placeholder
            "total_tracks": song_count,
            "release_date": iso_date,
        }
    
    def _format_setlist_detail(self, item: dict) -> dict:
        """Format full setlist with all songs."""
        base = self._format_setlist(item)
        
        # Extract all songs from all sets
        tracks = []
        set_idx = 0
        for setlist_set in item.get("sets", {}).get("set", []):
            set_name = setlist_set.get("name") or f"Set {set_idx + 1}"
            if setlist_set.get("encore"):
                set_name = "Encore"
            
            for song in setlist_set.get("song", []):
                song_name = song.get("name", "Unknown")
                
                # Build track info
                track = {
                    "id": f"setlist_song_{base['setlist_id']}_{len(tracks)}",
                    "name": song_name,
                    "artists": base["artists"],
                    "set_name": set_name,
                    "with_info": song.get("with", {}).get("name"),  # Guest artist
                    "cover_info": song.get("cover", {}).get("name"),  # Original artist if cover
                    "info": song.get("info", ""),  # Additional notes
                    "duration": "",  # Setlist.fm doesn't have duration
                    "type": "track",
                    "source": "setlist.fm",
                }
                tracks.append(track)
            
            set_idx += 1
        
        base["tracks"] = tracks
        base["type"] = "album"  # Treat as album for detail view
        
        # Determine audio source
        artist_lower = base["artists"].lower()
        if "phish" in artist_lower:
            base["audio_source"] = "phish.in"
            base["audio_url"] = f"https://phish.in/{base['iso_date']}"
        else:
            base["audio_source"] = "archive.org"
            # Format for Archive search: "Artist Name YYYY-MM-DD"
            base["audio_search"] = f"{base['artists']} {base['iso_date']}"
        
        return base
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Singleton instance
setlist_service = SetlistService()
