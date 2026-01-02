"""
YouTube Music service for Freedify.
Uses ytmusicapi for searching YouTube Music catalog.
Streaming is handled by existing audio_service (yt-dlp).
"""
from ytmusicapi import YTMusic
from typing import Optional, Dict, List, Any
import logging

logger = logging.getLogger(__name__)


class YTMusicService:
    """Service for searching YouTube Music."""
    
    def __init__(self):
        # Initialize without auth (works for search)
        self.ytm = YTMusic()
    
    async def search_tracks(self, query: str, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """Search for songs on YouTube Music."""
        try:
            # YTMusic doesn't have native offset, so we fetch more and slice
            total_needed = offset + limit
            results = self.ytm.search(query, filter="songs", limit=total_needed)
            # Slice to get the offset range
            sliced = results[offset:offset + limit] if offset > 0 else results[:limit]
            return [self._format_track(item) for item in sliced if item.get("videoId")]
        except Exception as e:
            logger.error(f"YTMusic search error: {e}")
            return []
    
    async def search_albums(self, query: str, limit: int = 20) -> List[Dict[str, Any]]:
        """Search for albums on YouTube Music."""
        try:
            results = self.ytm.search(query, filter="albums", limit=limit)
            return [self._format_album(item) for item in results if item.get("browseId")]
        except Exception as e:
            logger.error(f"YTMusic album search error: {e}")
            return []
    
    async def get_album(self, album_id: str) -> Optional[Dict[str, Any]]:
        """Get album details with tracks."""
        try:
            # Remove ytm_ prefix if present
            clean_id = album_id.replace("ytm_", "")
            data = self.ytm.get_album(clean_id)
            
            album = {
                "id": f"ytm_{clean_id}",
                "type": "album",
                "name": data.get("title", ""),
                "artists": ", ".join([a.get("name", "") for a in data.get("artists", [])]),
                "album_art": self._get_thumbnail(data.get("thumbnails")),
                "total_tracks": data.get("trackCount", 0),
                "release_date": data.get("year", ""),
                "source": "ytmusic",
            }
            
            tracks = []
            for item in data.get("tracks", []):
                if not item.get("videoId"):
                    continue
                track = self._format_track(item)
                track["album"] = album["name"]
                track["album_art"] = album["album_art"]
                tracks.append(track)
            
            album["tracks"] = tracks
            return album
        except Exception as e:
            logger.error(f"YTMusic get_album error: {e}")
            return None
    
    def _format_track(self, item: dict) -> dict:
        """Format track data for frontend."""
        artists = item.get("artists", [])
        artist_str = ", ".join([a.get("name", "") for a in artists]) if artists else ""
        
        # Get album info if available
        album = item.get("album", {}) or {}
        
        # Duration can be in seconds or as string "3:45"
        duration_str = item.get("duration", "0:00")
        duration_ms = self._parse_duration(duration_str)
        
        return {
            "id": f"ytm_{item.get('videoId', '')}",
            "type": "track",
            "name": item.get("title", ""),
            "artists": artist_str,
            "artist_names": [a.get("name", "") for a in artists],
            "album": album.get("name", "") if isinstance(album, dict) else str(album),
            "album_id": f"ytm_{album.get('id', '')}" if isinstance(album, dict) else "",
            "album_art": self._get_thumbnail(item.get("thumbnails")),
            "duration_ms": duration_ms,
            "duration": duration_str if isinstance(duration_str, str) else self._format_duration(duration_ms),
            "isrc": f"ytm_{item.get('videoId', '')}",  # Use prefixed videoId for streaming
            "source": "ytmusic",
            "video_id": item.get("videoId", ""),  # Keep for reference
        }
    
    def _format_album(self, item: dict) -> dict:
        """Format album data for frontend."""
        artists = item.get("artists", [])
        artist_str = ", ".join([a.get("name", "") for a in artists]) if artists else ""
        
        return {
            "id": f"ytm_{item.get('browseId', '')}",
            "type": "album",
            "name": item.get("title", ""),
            "artists": artist_str,
            "album_art": self._get_thumbnail(item.get("thumbnails")),
            "release_date": item.get("year", ""),
            "source": "ytmusic",
        }
    
    def _get_thumbnail(self, thumbnails: list) -> str:
        """Get highest quality thumbnail."""
        if not thumbnails:
            return "/static/icon.svg"
        # Sort by width descending and get the largest
        sorted_thumbs = sorted(thumbnails, key=lambda x: x.get("width", 0), reverse=True)
        return sorted_thumbs[0].get("url", "/static/icon.svg")
    
    def _parse_duration(self, duration) -> int:
        """Parse duration string to milliseconds."""
        if isinstance(duration, int):
            return duration * 1000
        if not duration or not isinstance(duration, str):
            return 0
        try:
            parts = duration.split(":")
            if len(parts) == 2:
                return (int(parts[0]) * 60 + int(parts[1])) * 1000
            elif len(parts) == 3:
                return (int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])) * 1000
            return 0
        except:
            return 0
    
    def _format_duration(self, ms: int) -> str:
        """Format milliseconds to mm:ss."""
        seconds = ms // 1000
        mins = seconds // 60
        secs = seconds % 60
        return f"{mins}:{secs:02d}"


# Singleton instance
ytmusic_service = YTMusicService()
