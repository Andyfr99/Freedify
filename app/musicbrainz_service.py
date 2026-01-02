"""
MusicBrainz service for Freedify.
Provides metadata enrichment: release year, label, and cover art from Cover Art Archive.
"""
import httpx
from typing import Optional, Dict, Any
import logging

logger = logging.getLogger(__name__)


class MusicBrainzService:
    """Service for enriching track metadata from MusicBrainz."""
    
    MB_API = "https://musicbrainz.org/ws/2"
    CAA_API = "https://coverartarchive.org"
    USER_AGENT = "Freedify/1.0 (https://github.com/freedify)"
    
    def __init__(self):
        self.client = httpx.AsyncClient(
            timeout=15.0,
            headers={"User-Agent": self.USER_AGENT}
        )
    
    async def lookup_by_isrc(self, isrc: str) -> Optional[Dict[str, Any]]:
        """Look up a recording by ISRC and return enriched metadata.
        
        Returns:
            {
                'release_date': '2020-01-15',
                'label': 'Atlantic Records',
                'cover_art_url': 'https://...',
                'genres': ['pop', 'electronic'],
                'release_id': '...'  # for further lookups
            }
        """
        try:
            # Skip non-standard ISRCs (like dz_ or ytm_ prefixed IDs)
            if not isrc or isrc.startswith(('dz_', 'ytm_', 'LINK:')):
                return None
            
            logger.info(f"Looking up ISRC on MusicBrainz: {isrc}")
            
            # Search for recording by ISRC
            response = await self.client.get(
                f"{self.MB_API}/isrc/{isrc}",
                params={"fmt": "json", "inc": "releases+release-groups+labels+genres"}
            )
            
            if response.status_code != 200:
                logger.debug(f"No MusicBrainz result for ISRC: {isrc}")
                return None
            
            data = response.json()
            recordings = data.get("recordings", [])
            
            if not recordings:
                return None
            
            # Get the first recording's release info
            recording = recordings[0]
            releases = recording.get("releases", [])
            
            if not releases:
                return None
            
            # Use the first release (typically the original)
            release = releases[0]
            release_id = release.get("id", "")
            
            result = {
                "release_date": release.get("date", ""),
                "release_id": release_id,
                "label": "",
                "cover_art_url": "",
                "genres": []
            }
            
            # Get label from label-info
            label_info = release.get("label-info", [])
            if label_info and label_info[0].get("label"):
                result["label"] = label_info[0]["label"].get("name", "")
            
            # Get genres from recording
            genres = recording.get("genres", [])
            result["genres"] = [g.get("name", "") for g in genres[:5]]
            
            # Try to get cover art from Cover Art Archive
            if release_id:
                cover_url = await self._get_cover_art(release_id)
                if cover_url:
                    result["cover_art_url"] = cover_url
            
            logger.info(f"MusicBrainz enrichment found: year={result['release_date']}, label={result['label']}")
            return result
            
        except Exception as e:
            logger.debug(f"MusicBrainz lookup error for {isrc}: {e}")
            return None
    
    async def _get_cover_art(self, release_id: str) -> Optional[str]:
        """Get cover art URL from Cover Art Archive."""
        try:
            response = await self.client.get(
                f"{self.CAA_API}/release/{release_id}",
                follow_redirects=True
            )
            
            if response.status_code != 200:
                return None
            
            data = response.json()
            images = data.get("images", [])
            
            # Get front cover, prefer large size
            for img in images:
                if img.get("front"):
                    # Prefer 500px version for quality/speed balance
                    thumbnails = img.get("thumbnails", {})
                    return thumbnails.get("500") or thumbnails.get("large") or img.get("image")
            
            # Fallback to first image
            if images:
                return images[0].get("image")
            
            return None
        except Exception as e:
            logger.debug(f"Cover Art Archive error: {e}")
            return None
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Singleton instance
musicbrainz_service = MusicBrainzService()
