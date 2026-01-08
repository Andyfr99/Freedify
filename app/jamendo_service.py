"""
Jamendo service for Freedify.
Provides access to 600,000+ independent and Creative Commons licensed tracks.
Jamendo API docs: https://developer.jamendo.com/v3.0
"""
import os
import httpx
from typing import Optional, Dict, List, Any
import logging

logger = logging.getLogger(__name__)


class JamendoService:
    """Service for searching and streaming from Jamendo."""
    
    API_BASE = "https://api.jamendo.com/v3.0"
    
    def __init__(self):
        # Client ID: use env var or fallback for local testing
        self.client_id = os.environ.get("JAMENDO_CLIENT_ID", "90aefcef")
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def _api_request(self, endpoint: str, params: dict = None) -> dict:
        """Make API request to Jamendo."""
        if params is None:
            params = {}
        params["client_id"] = self.client_id
        params["format"] = "json"
        
        response = await self.client.get(f"{self.API_BASE}{endpoint}", params=params)
        response.raise_for_status()
        return response.json()
    
    # ========== TRACK METHODS ==========
    
    async def search_tracks(self, query: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Search for tracks."""
        data = await self._api_request("/tracks/", {
            "search": query,
            "limit": limit,
            "offset": offset,
            "include": "musicinfo licenses",
            "audioformat": "flac",  # Request FLAC URLs
        })
        return [self._format_track(item) for item in data.get("results", [])]
    
    async def get_track(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Get single track details."""
        try:
            clean_id = track_id.replace("jm_", "")
            data = await self._api_request("/tracks/", {
                "id": clean_id,
                "include": "musicinfo licenses",
                "audioformat": "flac",
            })
            results = data.get("results", [])
            if results:
                return self._format_track(results[0])
            return None
        except Exception as e:
            logger.error(f"Error fetching Jamendo track {track_id}: {e}")
            return None
    
    def _format_track(self, item: dict) -> dict:
        """Format track data for frontend (matching Spotify/Deezer format)."""
        # Get best quality audio URL (prefer FLAC, fallback to MP3)
        audio_url = item.get("audiodownload") or item.get("audio") or ""
        
        # Jamendo returns audio URL with format parameter
        # We'll use the direct audio field which respects audioformat param
        return {
            "id": f"jm_{item['id']}",
            "type": "track",
            "name": item.get("name", ""),
            "artists": item.get("artist_name", ""),
            "artist_names": [item.get("artist_name", "")],
            "artist_id": f"jm_artist_{item.get('artist_id', '')}",
            "album": item.get("album_name", ""),
            "album_id": f"jm_{item.get('album_id', '')}",
            "album_art": item.get("album_image") or item.get("image") or "",
            "duration_ms": item.get("duration", 0) * 1000,
            "duration": self._format_duration(item.get("duration", 0) * 1000),
            "audio_url": audio_url,  # Direct stream URL
            "license": item.get("license_ccurl", ""),
            "release_date": item.get("releasedate", ""),
            "source": "jamendo",
            "format": "flac" if "flac" in audio_url.lower() else "mp3",
        }
    
    # ========== ALBUM METHODS ==========
    
    async def search_albums(self, query: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Search for albums."""
        data = await self._api_request("/albums/", {
            "search": query,
            "limit": limit,
            "offset": offset,
        })
        return [self._format_album(item) for item in data.get("results", [])]
    
    async def get_album(self, album_id: str) -> Optional[Dict[str, Any]]:
        """Get album with all tracks."""
        try:
            clean_id = album_id.replace("jm_", "")
            
            # Get album info
            album_data = await self._api_request("/albums/", {"id": clean_id})
            albums = album_data.get("results", [])
            if not albums:
                return None
            
            album = self._format_album(albums[0])
            
            # Get album tracks
            tracks_data = await self._api_request("/albums/tracks/", {
                "id": clean_id,
                "audioformat": "flac",
            })
            
            tracks = []
            for item in tracks_data.get("results", []):
                for track in item.get("tracks", []):
                    track["album_name"] = album["name"]
                    track["album_image"] = album["album_art"]
                    track["album_id"] = clean_id
                    track["artist_name"] = album["artists"]
                    track["artist_id"] = albums[0].get("artist_id", "")
                    tracks.append(self._format_track(track))
            
            album["tracks"] = tracks
            return album
        except Exception as e:
            logger.error(f"Error fetching Jamendo album {album_id}: {e}")
            return None
    
    def _format_album(self, item: dict) -> dict:
        """Format album data for frontend."""
        return {
            "id": f"jm_{item['id']}",
            "type": "album",
            "name": item.get("name", ""),
            "artists": item.get("artist_name", ""),
            "artist_id": f"jm_artist_{item.get('artist_id', '')}",
            "album_art": item.get("image") or "",
            "release_date": item.get("releasedate", ""),
            "total_tracks": 0,  # Not always provided
            "source": "jamendo",
        }
    
    # ========== ARTIST METHODS ==========
    
    async def search_artists(self, query: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Search for artists."""
        data = await self._api_request("/artists/", {
            "search": query,
            "limit": limit,
            "offset": offset,
        })
        return [self._format_artist(item) for item in data.get("results", [])]
    
    async def get_artist(self, artist_id: str) -> Optional[Dict[str, Any]]:
        """Get artist info with top tracks."""
        try:
            clean_id = artist_id.replace("jm_artist_", "").replace("jm_", "")
            
            # Get artist info
            artist_data = await self._api_request("/artists/", {"id": clean_id})
            artists = artist_data.get("results", [])
            if not artists:
                return None
            
            artist = self._format_artist(artists[0])
            
            # Get artist's tracks
            tracks_data = await self._api_request("/artists/tracks/", {
                "id": clean_id,
                "limit": 20,
                "audioformat": "flac",
            })
            
            tracks = []
            for item in tracks_data.get("results", []):
                for track in item.get("tracks", []):
                    track["artist_name"] = artist["name"]
                    track["artist_id"] = clean_id
                    tracks.append(self._format_track(track))
            
            artist["tracks"] = tracks
            return artist
        except Exception as e:
            logger.error(f"Error fetching Jamendo artist {artist_id}: {e}")
            return None
    
    def _format_artist(self, item: dict) -> dict:
        """Format artist data for frontend."""
        return {
            "id": f"jm_artist_{item['id']}",
            "type": "artist",
            "name": item.get("name", ""),
            "image": item.get("image") or "",
            "website": item.get("website", ""),
            "source": "jamendo",
        }
    
    # ========== STREAM URL ==========
    
    async def get_stream_url(self, track_id: str, prefer_flac: bool = True) -> Optional[str]:
        """Get direct stream URL for a track. Tries FLAC first, falls back to MP3."""
        try:
            clean_id = track_id.replace("jm_", "")
            
            # Try FLAC first
            if prefer_flac:
                data = await self._api_request("/tracks/", {
                    "id": clean_id,
                    "audioformat": "flac",
                })
                results = data.get("results", [])
                if results:
                    url = results[0].get("audiodownload") or results[0].get("audio")
                    if url:
                        return url
            
            # Fallback to MP3 (mp32 = VBR good quality)
            data = await self._api_request("/tracks/", {
                "id": clean_id,
                "audioformat": "mp32",
            })
            results = data.get("results", [])
            if results:
                return results[0].get("audiodownload") or results[0].get("audio")
            
            return None
        except Exception as e:
            logger.error(f"Error getting Jamendo stream URL for {track_id}: {e}")
            return None
    
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
jamendo_service = JamendoService()
