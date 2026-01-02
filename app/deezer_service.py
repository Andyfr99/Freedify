"""
Deezer service for Freedify.
Provides search (tracks, albums, artists) as fallback when Spotify is rate limited.
Deezer API is free and doesn't require authentication for basic searches.
"""
import httpx
from typing import Optional, Dict, List, Any
import logging

logger = logging.getLogger(__name__)


class DeezerService:
    """Service for searching and fetching metadata from Deezer."""
    
    API_BASE = "https://api.deezer.com"
    
    def __init__(self):
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def _api_request(self, endpoint: str, params: dict = None) -> dict:
        """Make API request to Deezer."""
        response = await self.client.get(f"{self.API_BASE}{endpoint}", params=params)
        response.raise_for_status()
        return response.json()
    
    # ========== TRACK METHODS ==========
    
    async def search_tracks(self, query: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Search for tracks."""
        data = await self._api_request("/search/track", {"q": query, "limit": limit, "index": offset})
        return [self._format_track(item) for item in data.get("data", [])]
    
    def _format_track(self, item: dict) -> dict:
        """Format track data for frontend (matching Spotify format)."""
        album = item.get("album", {})
        artist = item.get("artist", {})
        return {
            "id": f"dz_{item['id']}",
            "type": "track",
            "name": item.get("title", ""),
            "artists": artist.get("name", ""),
            "artist_names": [artist.get("name", "")],
            "album": album.get("title", ""),
            "album_id": f"dz_{album.get('id', '')}",
            "album_art": album.get("cover_xl") or album.get("cover_big") or album.get("cover_medium"),
            "duration_ms": item.get("duration", 0) * 1000,
            "duration": self._format_duration(item.get("duration", 0) * 1000),
            "isrc": item.get("isrc"),
            "preview_url": item.get("preview"),
            "release_date": album.get("release_date", ""),
            "source": "deezer",
        }
    
    # ========== ALBUM METHODS ==========
    
    async def search_albums(self, query: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Search for albums."""
        data = await self._api_request("/search/album", {"q": query, "limit": limit, "index": offset})
        return [self._format_album(item) for item in data.get("data", [])]
    
    async def get_album(self, album_id: str) -> Optional[Dict[str, Any]]:
        """Get album with all tracks."""
        try:
            # Remove dz_ prefix if present
            clean_id = album_id.replace("dz_", "")
            data = await self._api_request(f"/album/{clean_id}")
            album = self._format_album(data)
            
            # Format tracks
            tracks = []
            for item in data.get("tracks", {}).get("data", []):
                track = {
                    "id": f"dz_{item['id']}",
                    "type": "track",
                    "name": item.get("title", ""),
                    "artists": data.get("artist", {}).get("name", ""),
                    "artist_names": [data.get("artist", {}).get("name", "")],
                    "album": data.get("title", ""),
                    "album_id": f"dz_{clean_id}",
                    "album_art": album["album_art"],
                    "duration_ms": item.get("duration", 0) * 1000,
                    "duration": self._format_duration(item.get("duration", 0) * 1000),
                    "isrc": item.get("isrc"),
                    "preview_url": item.get("preview"),
                    "source": "deezer",
                }
                tracks.append(track)
            
            album["tracks"] = tracks
            return album
        except Exception as e:
            logger.error(f"Error fetching Deezer album {album_id}: {e}")
            return None
    
    def _format_album(self, item: dict) -> dict:
        """Format album data for frontend."""
        artist = item.get("artist", {})
        return {
            "id": f"dz_{item['id']}",
            "type": "album",
            "name": item.get("title", ""),
            "artists": artist.get("name", ""),
            "album_art": item.get("cover_xl") or item.get("cover_big") or item.get("cover_medium"),
            "release_date": item.get("release_date", ""),
            "total_tracks": item.get("nb_tracks", 0),
            "source": "deezer",
        }
    
    # ========== ARTIST METHODS ==========
    
    async def search_artists(self, query: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Search for artists."""
        data = await self._api_request("/search/artist", {"q": query, "limit": limit, "index": offset})
        return [self._format_artist(item) for item in data.get("data", [])]
    
    async def get_artist(self, artist_id: str) -> Optional[Dict[str, Any]]:
        """Get artist info with top tracks."""
        try:
            clean_id = artist_id.replace("dz_", "")
            data = await self._api_request(f"/artist/{clean_id}")
            artist = self._format_artist(data)
            
            # Get top tracks
            top_tracks = await self._api_request(f"/artist/{clean_id}/top", {"limit": 10})
            artist["tracks"] = [self._format_track(t) for t in top_tracks.get("data", [])]
            
            return artist
        except Exception as e:
            logger.error(f"Error fetching Deezer artist {artist_id}: {e}")
            return None
    
    def _format_artist(self, item: dict) -> dict:
        """Format artist data for frontend."""
        return {
            "id": f"dz_{item['id']}",
            "type": "artist",
            "name": item.get("name", ""),
            "image": item.get("picture_xl") or item.get("picture_big") or item.get("picture_medium"),
            "fans": item.get("nb_fan", 0),
            "source": "deezer",
        }
    
    # ========== UTILITIES ==========
    
    def _format_duration(self, ms: int) -> str:
        """Format duration from ms to MM:SS."""
        seconds = ms // 1000
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}:{secs:02d}"
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Singleton instance
deezer_service = DeezerService()
