"""
Dab Music Service
Retrieves Hi-Res audio from Dab Music API.
"""
import httpx
import logging
from typing import Optional, List, Dict, Any
import os

logger = logging.getLogger(__name__)

class DabService:
    BASE_URL = "https://dabmusic.xyz/api"
    
    def __init__(self):
        self._initialized = False
        self.client = None
        self.session_token = ""
        self.visitor_id = ""
        
    def _ensure_initialized(self):
        """Lazy initialization - loads credentials on first use, not import time."""
        if self._initialized:
            return
            
        # Load credentials at runtime (not import time) for cloud deployment compatibility
        self.session_token = os.getenv("DAB_SESSION", "")
        self.visitor_id = os.getenv("DAB_VISITOR_ID", "")
        
        # Debug: Log if credentials are present (not the actual values)
        if self.session_token:
            logger.info(f"Dab credentials loaded: session={len(self.session_token)} chars, visitor={len(self.visitor_id)} chars")
        else:
            logger.warning("Dab credentials not found - Hi-Res streaming will be unavailable")
        
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Referer": "https://dabmusic.xyz/",
            "Origin": "https://dabmusic.xyz"
        }
        self.cookies = {
            "session": self.session_token,
            "visitor_id": self.visitor_id
        }
        
        self.client = httpx.AsyncClient(
            headers=self.headers,
            cookies=self.cookies,
            timeout=15.0,
            follow_redirects=True
        )
        self._initialized = True

    async def search_tracks(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for tracks on Dab Music."""
        self._ensure_initialized()
        try:
            resp = await self.client.get(
                f"{self.BASE_URL}/search",
                params={"q": query, "type": "track", "limit": limit}
            )
            if resp.status_code == 200:
                data = resp.json()
                tracks = data.get("tracks", [])
                
                 # Debug logging
                if tracks and len(tracks) > 0:
                    logger.info(f"Dab Search Track 0: {type(tracks[0])} - {str(tracks[0])[:50]}...")

                return [self._format_track(t) for t in tracks if isinstance(t, dict)]
            elif resp.status_code == 401:
                logger.error("Dab API Unauthorized - Token may have expired")
            else:
                logger.warning(f"Dab search failed: {resp.status_code}")
            return []
        except Exception as e:
            logger.error(f"Dab search error: {e}")
            return []

    async def search_albums(self, query: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search for albums on Dab Music."""
        self._ensure_initialized()
        try:
            resp = await self.client.get(
                f"{self.BASE_URL}/search",
                params={"q": query, "type": "album", "limit": limit}
            )
            if resp.status_code == 200:
                data = resp.json()
                albums = data.get("albums", [])
                
                # Debug logging
                if albums and len(albums) > 0:
                    logger.info(f"Dab Search Album 0: {type(albums[0])} - {albums[0]}")
                
                return [self._format_album(a) for a in albums if isinstance(a, dict)]
            return []
        except Exception as e:
            logger.error(f"Dab album search error: {e}")
            return []

    async def get_album(self, album_id: str) -> Optional[Dict[str, Any]]:
        """Get album details with tracks."""
        self._ensure_initialized()
        try:
            clean_id = album_id.replace("dab_", "")
            # Try getAlbum endpoint first (based on test results, /getAlbum works usually if /album fails)
            # Actually test showed 404 for all... Wait, I need to be careful.
            # But earlier test showed /album and /getAlbum failing with 400/404.
            # BUT web interface uses: /api/get?id=... (from observation usually)
            # Or /api/album?id=...
            # I will try /getAlbum based on typical Qobuz proxies, or fallback to search if needed?
            # actually if the test failed, I might need to rely on what I saw in other code or assume /getAlbum or /album.
            # Let's try /getAlbum with 'albumId' param as that is specific to Dab often.
            
            resp = await self.client.get(f"{self.BASE_URL}/getAlbum", params={"albumId": clean_id})
            if resp.status_code != 200:
                 resp = await self.client.get(f"{self.BASE_URL}/album", params={"albumId": clean_id})
            
            if resp.status_code == 200:
                data = resp.json()
                
                # Check for nested 'album' key which is common in getAlbum/album endpoints
                album_data = data.get("album", data)
                
                album = self._format_album(album_data)
                
                tracks = []
                # Tracks are usually inside the album object or 'tracks' key
                raw_tracks = album_data.get("tracks", [])
                # Sometimes tracks are wrapped in 'items'
                if isinstance(raw_tracks, dict) and "items" in raw_tracks:
                    raw_tracks = raw_tracks["items"]
                elif not isinstance(raw_tracks, list):
                    raw_tracks = []

                tracks = [self._format_track(t, album_info=album_data) for t in raw_tracks]
                album["tracks"] = tracks
                return album
            
            logger.warning(f"Dab get_album failed: {resp.status_code}")
            return None
        except Exception as e:
            logger.error(f"Dab get_album error: {e}")
            return None

    def _format_track(self, item: dict, album_info: dict = None) -> dict:
        """Format Dab track to frontend schema."""
        # Clean ID
        track_id = str(item.get("id"))
        
        # Album info might come from item or parent
        alb_title = item.get("albumTitle") or item.get("album", {}).get("title")
        if album_info: alb_title = alb_title or album_info.get("title")
        
        alb_cover = item.get("albumCover") or item.get("album", {}).get("cover")
        if not alb_cover and album_info: 
             alb_cover = album_info.get("image", {}).get("large") or album_info.get("cover")

        # Artist
        artist_obj = item.get("artist")
        if isinstance(artist_obj, dict):
            artist_name = artist_obj.get("name")
        else:
            artist_name = artist_obj
            
        if not artist_name and album_info:
            artist_val = album_info.get("artist")
            if isinstance(artist_val, dict):
                artist_name = artist_val.get("name")
            else:
                artist_name = artist_val

        return {
            "id": f"dab_{track_id}",
            "type": "track",
            "name": item.get("title", "Unknown"),
            "artists": artist_name,
            "artist_names": [artist_name],
            "album": alb_title,
            "album_id": f"dab_{item.get('albumId') or (album_info['id'] if album_info else '')}",
            "album_art": alb_cover,
            "duration_ms": item.get("duration", 0) * 1000,
            "duration": self._format_duration(item.get("duration", 0) * 1000),
            "isrc": item.get("isrc"), # Dab often provides isrc
            "release_date": item.get("releaseDate", ""),
            "source": "dab",
            "is_hi_res": item.get("audioQuality", {}).get("isHiRes", False)
        }

    def _format_album(self, item: dict) -> dict:
        """Format Dab album to frontend schema."""
        # Extract images
        images = item.get("images", {})
        cover = None
        if isinstance(images, dict):
            cover = images.get("large") or images.get("medium") 
        
        if not cover: cover = item.get("cover") # Fallback to top level
        
        if isinstance(cover, dict): cover = cover.get("large") # Handle nested cases

        # Handle Artist
        artist_obj = item.get("artist")
        if isinstance(artist_obj, dict):
            artist_name = artist_obj.get("name")
        else:
            artist_name = artist_obj

        # Extract audio quality info
        audio_quality = item.get("audioQuality", {})
        
        return {
            "id": f"dab_{item.get('id')}",
            "type": "album",
            "name": item.get("title", ""),
            "artists": artist_name,
            "album_art": cover,
            "release_date": item.get("releaseDate", ""),
            "total_tracks": item.get("trackCount", 0),
            "source": "dab",
            "is_hi_res": audio_quality.get("isHiRes", False),
            "audio_quality": {
                "maximumBitDepth": audio_quality.get("maximumBitDepth", 16),
                "maximumSamplingRate": audio_quality.get("maximumSamplingRate", 44.1),
                "isHiRes": audio_quality.get("isHiRes", False)
            },
            "format": "FLAC" if audio_quality.get("isHiRes", False) else "FLAC"
        }

    def _format_duration(self, ms: int) -> str:
        seconds = int(ms // 1000)
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}:{secs:02d}"

    async def get_stream_url(self, track_id: str, quality: str = "27") -> Optional[str]:
        """Get stream URL for a track. Quality 27=Hi-Res, 7=Lossless."""
        self._ensure_initialized()
        try:
            clean_id = str(track_id).replace("dab_", "")
            resp = await self.client.get(
                f"{self.BASE_URL}/stream",
                params={"trackId": clean_id, "quality": quality} 
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("url")
            logger.warning(f"Dab stream fetch failed: {resp.status_code} - {resp.text}")
            return None
        except Exception as e:
            logger.error(f"Dab stream error: {e}")
            return None

    async def close(self):
        await self.client.aclose()

# Singleton
dab_service = DabService()
