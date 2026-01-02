"""
ListenBrainz service for Freedify.
Handles scrobbling (listening history) and personalized recommendations.
"""
import os
import time
import httpx
from typing import Optional, Dict, List, Any
import logging
from app.musicbrainz_service import musicbrainz_service

logger = logging.getLogger(__name__)

# User token from environment (can also be set via frontend settings)
LISTENBRAINZ_TOKEN = os.getenv("LISTENBRAINZ_TOKEN", "")


class ListenBrainzService:
    """Service for ListenBrainz scrobbling and recommendations."""
    
    API_BASE = "https://api.listenbrainz.org"
    
    def __init__(self):
        self.token = LISTENBRAINZ_TOKEN
        self.client = httpx.AsyncClient(timeout=15.0)
    
    def set_token(self, token: str):
        """Set user token (from settings UI)."""
        self.token = token
    
    def is_configured(self) -> bool:
        """Check if ListenBrainz token is configured."""
        return bool(self.token)
    
    def _get_headers(self) -> dict:
        """Get headers with authorization."""
        return {
            "Authorization": f"Token {self.token}",
            "Content-Type": "application/json"
        }
    
    async def submit_now_playing(self, track: Dict[str, Any]) -> bool:
        """Submit 'now playing' status when a track starts.
        
        Args:
            track: Track info with name, artists, album, duration_ms
        """
        if not self.is_configured():
            logger.debug("ListenBrainz not configured, skipping now playing")
            return False
        
        try:
            payload = {
                "listen_type": "playing_now",
                "payload": [self._format_track_payload(track)]
            }
            
            response = await self.client.post(
                f"{self.API_BASE}/1/submit-listens",
                headers=self._get_headers(),
                json=payload
            )
            
            if response.status_code == 200:
                logger.info(f"ListenBrainz now playing: {track.get('name')}")
                return True
            else:
                logger.warning(f"ListenBrainz now playing failed: {response.status_code}")
                return False
                
        except Exception as e:
            logger.error(f"ListenBrainz now playing error: {e}")
            return False
    
    async def submit_listen(self, track: Dict[str, Any], listened_at: Optional[int] = None) -> bool:
        """Submit a completed listen (scrobble).
        
        Should be called after user listens to 50% of track or 4 minutes, whichever is shorter.
        
        Args:
            track: Track info with name, artists, album, duration_ms
            listened_at: Unix timestamp when listening started (defaults to now)
        """
        if not self.is_configured():
            logger.debug("ListenBrainz not configured, skipping scrobble")
            return False
        
        try:
            track_payload = self._format_track_payload(track)
            track_payload["listened_at"] = listened_at or int(time.time())
            
            payload = {
                "listen_type": "single",
                "payload": [track_payload]
            }
            
            response = await self.client.post(
                f"{self.API_BASE}/1/submit-listens",
                headers=self._get_headers(),
                json=payload
            )
            
            if response.status_code == 200:
                logger.info(f"ListenBrainz scrobbled: {track.get('name')}")
                return True
            else:
                logger.warning(f"ListenBrainz scrobble failed: {response.status_code} - {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"ListenBrainz scrobble error: {e}")
            return False
    
    def _format_track_payload(self, track: Dict[str, Any]) -> dict:
        """Format track data for ListenBrainz API."""
        # Get artist name (handle both string and list formats)
        artist = track.get("artists", "")
        if isinstance(artist, list):
            artist = ", ".join(artist)
        
        additional_info = {}
        
        # Add duration if available
        duration_ms = track.get("duration_ms")
        if duration_ms:
            additional_info["duration_ms"] = duration_ms
        
        # Add release name (album)
        if track.get("album"):
            additional_info["release_name"] = track["album"]
        
        # Add ISRC if available (helps with MusicBrainz matching)
        if track.get("isrc") and not track["isrc"].startswith(("dz_", "ytm_", "LINK:", "pod_")):
            additional_info["isrc"] = track["isrc"]
        
        # Add track number if available
        if track.get("track_number"):
            additional_info["tracknumber"] = track["track_number"]
        
        return {
            "track_metadata": {
                "artist_name": artist,
                "track_name": track.get("name", "Unknown"),
                "additional_info": additional_info if additional_info else None
            }
        }
    
    async def get_recommendations(self, username: str, count: int = 25) -> List[Dict[str, Any]]:
        """Get personalized recommendations for a user.
        
        Note: Recommendations are generated weekly by ListenBrainz based on listening history.
        
        Args:
            username: ListenBrainz username
            count: Number of recommendations to fetch
        """
        try:
            response = await self.client.get(
                f"{self.API_BASE}/1/cf/recommendation/recording/{username}",
                params={"count": count}
            )
            
            if response.status_code != 200:
                logger.warning(f"ListenBrainz recommendations failed: {response.status_code}")
                return []
            
            data = response.json()
            payload = data.get("payload", {})
            
            recommendations = []
            mbids = [rec.get("recording_mbid") for rec in payload.get("mbids", [])[:15]] # Limit to 15 for performance
            
            for mbid in mbids:
                if not mbid: continue
                # Lookup metadata from MusicBrainz
                track_data = await musicbrainz_service.lookup_recording(mbid)
                if track_data:
                    track_data["type"] = "recommendation"
                    track_data["source"] = "listenbrainz"
                    recommendations.append(track_data)
            
            return recommendations
            
        except Exception as e:
            logger.error(f"ListenBrainz recommendations error: {e}")
            return []
    
    async def get_user_listens(self, username: str, count: int = 25) -> List[Dict[str, Any]]:
        """Get recent listens for a user."""
        try:
            response = await self.client.get(
                f"{self.API_BASE}/1/user/{username}/listens",
                params={"count": count}
            )
            
            if response.status_code != 200:
                return []
            
            data = response.json()
            listens = data.get("payload", {}).get("listens", [])
            
            return [{
                "track_name": l.get("track_metadata", {}).get("track_name"),
                "artist_name": l.get("track_metadata", {}).get("artist_name"),
                "listened_at": l.get("listened_at"),
                "source": "listenbrainz"
            } for l in listens]
            
        except Exception as e:
            logger.error(f"ListenBrainz get listens error: {e}")
            return []
    
    async def validate_token(self) -> Optional[str]:
        """Validate token and return username if valid."""
        if not self.is_configured():
            return None
        
        try:
            response = await self.client.get(
                f"{self.API_BASE}/1/validate-token",
                headers=self._get_headers()
            )
            
            if response.status_code == 200:
                data = response.json()
                if data.get("valid"):
                    return data.get("user_name")
            
            return None
            
        except Exception as e:
            logger.error(f"ListenBrainz token validation error: {e}")
            return None
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Singleton instance
listenbrainz_service = ListenBrainzService()
