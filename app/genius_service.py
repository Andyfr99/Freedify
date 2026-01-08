"""
Genius service for Freedify.
Provides lyrics, annotations, and song information from Genius.
API docs: https://docs.genius.com/
"""
import os
import re
import httpx
from typing import Optional, Dict, Any
import logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class GeniusService:
    """Service for fetching lyrics and annotations from Genius."""
    
    API_BASE = "https://api.genius.com"
    
    def __init__(self):
        # Access token: use env var (required for production)
        self.access_token = os.environ.get("GENIUS_ACCESS_TOKEN", "")
        if not self.access_token:
            logger.warning("GENIUS_ACCESS_TOKEN not set - lyrics will not work")
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def _api_request(self, endpoint: str, params: dict = None) -> dict:
        """Make authenticated API request to Genius."""
        headers = {"Authorization": f"Bearer {self.access_token}"}
        if params is None:
            params = {}
        
        response = await self.client.get(
            f"{self.API_BASE}{endpoint}",
            headers=headers,
            params=params
        )
        response.raise_for_status()
        return response.json()
    
    async def search_song(self, query: str) -> Optional[Dict[str, Any]]:
        """Search for a song on Genius. Returns the best match."""
        try:
            data = await self._api_request("/search", {"q": query})
            hits = data.get("response", {}).get("hits", [])
            
            # Find first song result
            for hit in hits:
                if hit.get("type") == "song":
                    song = hit.get("result", {})
                    return {
                        "id": song.get("id"),
                        "title": song.get("title"),
                        "artist": song.get("primary_artist", {}).get("name"),
                        "url": song.get("url"),
                        "thumbnail": song.get("song_art_image_thumbnail_url"),
                        "full_title": song.get("full_title"),
                    }
            return None
        except Exception as e:
            logger.error(f"Genius search error: {e}")
            return None
    
    async def get_song_details(self, song_id: int) -> Optional[Dict[str, Any]]:
        """Get detailed song information including annotations."""
        try:
            data = await self._api_request(f"/songs/{song_id}")
            song = data.get("response", {}).get("song", {})
            
            # Extract useful info
            description = song.get("description", {})
            if isinstance(description, dict):
                description_text = description.get("plain", "")
            else:
                description_text = str(description) if description else ""
            
            return {
                "id": song.get("id"),
                "title": song.get("title"),
                "artist": song.get("primary_artist", {}).get("name"),
                "album": song.get("album", {}).get("name") if song.get("album") else None,
                "release_date": song.get("release_date_for_display"),
                "url": song.get("url"),
                "thumbnail": song.get("song_art_image_url"),
                "description": description_text,
                "apple_music_id": song.get("apple_music_id"),
                "recording_location": song.get("recording_location"),
                "producer_artists": [p.get("name") for p in song.get("producer_artists", [])],
                "writer_artists": [w.get("name") for w in song.get("writer_artists", [])],
                "featured_artists": [f.get("name") for f in song.get("featured_artists", [])],
            }
        except Exception as e:
            logger.error(f"Genius song details error: {e}")
            return None
    
    async def scrape_lyrics(self, genius_url: str) -> Optional[str]:
        """Scrape lyrics from a Genius song page."""
        try:
            # Fetch the page
            response = await self.client.get(genius_url, follow_redirects=True)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, "html.parser")
            
            # Genius uses data-lyrics-container for lyrics sections
            lyrics_containers = soup.find_all("div", {"data-lyrics-container": "true"})
            
            if lyrics_containers:
                lyrics_parts = []
                for container in lyrics_containers:
                    # Get text, preserving line breaks
                    for br in container.find_all("br"):
                        br.replace_with("\n")
                    lyrics_parts.append(container.get_text())
                
                lyrics = "\n".join(lyrics_parts)
                # Clean up extra whitespace
                lyrics = re.sub(r'\n{3,}', '\n\n', lyrics)
                return lyrics.strip()
            
            # Fallback: try older format
            lyrics_div = soup.find("div", class_="lyrics")
            if lyrics_div:
                return lyrics_div.get_text().strip()
            
            logger.warning(f"Could not find lyrics on page: {genius_url}")
            return None
            
        except Exception as e:
            logger.error(f"Genius lyrics scrape error: {e}")
            return None
    
    async def get_song_referents(self, song_id: int) -> list:
        """Get annotations for a song using the Genius API referents endpoint."""
        annotations = []
        try:
            # Use API to get referents (annotated sections)
            data = await self._api_request(f"/referents", {
                "song_id": song_id,
                "text_format": "plain",
                "per_page": 20
            })
            
            referents = data.get("response", {}).get("referents", [])
            
            for ref in referents[:15]:  # Limit to 15 annotations
                fragment = ref.get("fragment", "")
                annotation_list = ref.get("annotations", [])
                
                for ann in annotation_list:
                    # Get the annotation body
                    body = ann.get("body", {})
                    if isinstance(body, dict):
                        plain_text = body.get("plain", "")
                    else:
                        plain_text = str(body) if body else ""
                    
                    # Also get the annotation state/votes for quality filtering
                    votes_total = ann.get("votes_total", 0)
                    
                    if plain_text and len(plain_text) > 10:
                        annotations.append({
                            "fragment": fragment[:150] + "..." if len(fragment) > 150 else fragment,
                            "text": plain_text,
                            "votes": votes_total
                        })
            
            # Sort by votes (most upvoted first)
            annotations.sort(key=lambda x: x.get("votes", 0), reverse=True)
            
            return annotations
            
        except Exception as e:
            logger.error(f"Genius referents API error: {e}")
            return []
    
    async def get_lyrics_and_info(self, artist: str, title: str) -> Dict[str, Any]:
        """
        Main method: Search for a song, get lyrics and details.
        Returns a dict with lyrics, about info, annotations, and metadata.
        """
        result = {
            "found": False,
            "lyrics": None,
            "title": title,
            "artist": artist,
            "about": None,
            "album": None,
            "release_date": None,
            "producers": [],
            "writers": [],
            "annotations": [],
            "genius_url": None,
            "thumbnail": None,
        }
        
        # Search for the song
        query = f"{artist} {title}"
        song = await self.search_song(query)
        
        if not song:
            logger.info(f"No Genius match for: {query}")
            return result
        
        result["found"] = True
        result["genius_url"] = song.get("url")
        result["thumbnail"] = song.get("thumbnail")
        result["title"] = song.get("title", title)
        result["artist"] = song.get("artist", artist)
        
        # Get detailed info
        song_id = song.get("id")
        if song_id:
            details = await self.get_song_details(song_id)
            if details:
                result["about"] = details.get("description")
                result["album"] = details.get("album")
                result["release_date"] = details.get("release_date")
                result["producers"] = details.get("producer_artists", [])
                result["writers"] = details.get("writer_artists", [])
        
        # Scrape lyrics
        if song.get("url"):
            lyrics = await self.scrape_lyrics(song["url"])
            result["lyrics"] = lyrics
        
        # Get annotations via API (requires song_id)
        if song_id:
            annotations = await self.get_song_referents(song_id)
            result["annotations"] = annotations
        
        return result
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# Singleton instance
genius_service = GeniusService()
