"""
Spotify service for Freedify.
Provides playlist/album fetching and URL parsing.
ONLY used when a Spotify URL is pasted - not for search (to avoid rate limits).
"""
import httpx
import re
from typing import Optional, Dict, List, Any, Tuple
import logging
from random import randrange

logger = logging.getLogger(__name__)


def get_random_user_agent():
    return f"Mozilla/5.0 (Macintosh; Intel Mac OS X 10_{randrange(11, 15)}_{randrange(4, 9)}) AppleWebKit/{randrange(530, 537)}.{randrange(30, 37)} (KHTML, like Gecko) Chrome/{randrange(80, 105)}.0.{randrange(3000, 4500)}.{randrange(60, 125)} Safari/{randrange(530, 537)}.{randrange(30, 36)}"


class SpotifyService:
    """Service for fetching metadata from Spotify URLs (not for search)."""
    
    TOKEN_URL = "https://open.spotify.com/get_access_token?reason=transport&productType=web_player"
    AUTH_URL = "https://accounts.spotify.com/api/token"
    API_BASE = "https://api.spotify.com/v1"
    
    # Regex patterns for Spotify URLs
    URL_PATTERNS = {
        'track': re.compile(r'(?:spotify\.com/track/|spotify:track:)([a-zA-Z0-9]+)'),
        'album': re.compile(r'(?:spotify\.com/album/|spotify:album:)([a-zA-Z0-9]+)'),
        'playlist': re.compile(r'(?:spotify\.com/playlist/|spotify:playlist:)([a-zA-Z0-9]+)'),
        'artist': re.compile(r'(?:spotify\.com/artist/|spotify:artist:)([a-zA-Z0-9]+)'),
    }
    
    def __init__(self):
        import os
        self.access_token: Optional[str] = None
        self.client_id = os.environ.get("SPOTIFY_CLIENT_ID")
        self.client_secret = os.environ.get("SPOTIFY_CLIENT_SECRET")
        self.sp_dc = os.environ.get("SPOTIFY_SP_DC")
        self.client = httpx.AsyncClient(timeout=30.0)
    
    async def _get_access_token(self) -> str:
        """Get access token (Client Creds > Cookie > Web Player > Embed)."""
        if self.access_token:
            return self.access_token
            
        # 1. Try Client Credentials Flow
        if self.client_id and self.client_secret:
            try:
                import base64
                auth_str = f"{self.client_id}:{self.client_secret}"
                b64_auth = base64.b64encode(auth_str.encode()).decode()
                
                headers = {
                    "Authorization": f"Basic {b64_auth}",
                    "Content-Type": "application/x-www-form-urlencoded"
                }
                data = {"grant_type": "client_credentials"}
                
                response = await self.client.post(self.AUTH_URL, headers=headers, data=data)
                if response.status_code == 200:
                    token_data = response.json()
                    self.access_token = token_data.get("access_token")
                    logger.info("Got Spotify token via Client Credentials")
                    return self.access_token
            except Exception as e:
                logger.error(f"Client Credentials auth failed: {e}")

        # 2. Try Cookie Auth (sp_dc) - Mimics logged-in Web Player
        # This is the best fallback if Developer App creation is blocked
        cookies = None
        if self.sp_dc:
            cookies = {"sp_dc": self.sp_dc}
            logger.info("Using provided sp_dc cookie for authentication")

        # 3. Web Player Token (Anonymous or Authenticated via Cookie)
        headers = {
            "User-Agent": get_random_user_agent(),
            "Accept": "application/json",
            "Referer": "https://open.spotify.com/",
        }
        
        try:
            # If cookies are passed, this request becomes authenticated!
            response = await self.client.get(self.TOKEN_URL, headers=headers, cookies=cookies)
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("accessToken")
                if self.access_token:
                    logger.info(f"Got Spotify token via Web Player ({'Authenticated' if cookies else 'Anonymous'})")
                    return self.access_token
        except Exception as e:
            logger.warning(f"Web Player token fetch failed: {e}")
        
        # 4. Fallback: Embed Page
            if response.status_code == 200:
                data = response.json()
                self.access_token = data.get("accessToken")
                if self.access_token:
                    logger.info("Got Spotify token via direct method")
                    return self.access_token
        except Exception as e:
            logger.warning(f"Direct token fetch failed: {e}")
        
        # 3. Fallback: Embed Page
        try:
            embed_url = "https://open.spotify.com/embed/track/4cOdK2wGLETKBW3PvgPWqT"
            response = await self.client.get(embed_url, headers={"User-Agent": get_random_user_agent()})
            if response.status_code == 200:
                token_match = re.search(r'"accessToken":"([^"]+)"', response.text)
                if token_match:
                    self.access_token = token_match.group(1)
                    logger.info("Got Spotify token via embed page")
                    return self.access_token
        except Exception as e:
            logger.warning(f"Embed token fetch failed: {e}")
        
        raise Exception("Failed to get Spotify access token")
    
    async def _api_request(self, endpoint: str, params: dict = None) -> dict:
        """Make authenticated API request with rate limit handling."""
        import asyncio
        
        max_retries = 3
        retry_delay = 2
        
        for attempt in range(max_retries):
            token = await self._get_access_token()
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": get_random_user_agent(),
                "Accept": "application/json",
            }
            response = await self.client.get(f"{self.API_BASE}{endpoint}", headers=headers, params=params)
            
            if response.status_code == 401:
                logger.warning("Got 401, refreshing Spotify token...")
                self.access_token = None
                continue
            
            if response.status_code == 429:
                retry_after = min(int(response.headers.get("Retry-After", retry_delay)), 10)
                logger.warning(f"Rate limited (429). Waiting {retry_after}s before retry {attempt + 1}/{max_retries}")
                await asyncio.sleep(retry_after)
                retry_delay *= 2
                continue
            
            response.raise_for_status()
            return response.json()
        
        response.raise_for_status()
        return response.json()
    
    def parse_spotify_url(self, url: str) -> Optional[Tuple[str, str]]:
        """Parse Spotify URL and return (type, id) or None."""
        for url_type, pattern in self.URL_PATTERNS.items():
            match = pattern.search(url)
            if match:
                return (url_type, match.group(1))
        return None
    
    def is_spotify_url(self, url: str) -> bool:
        """Check if a URL is a Spotify URL."""
        return 'spotify.com/' in url or 'spotify:' in url
    
    # ========== TRACK METHODS ==========
    
    async def get_track_by_id(self, track_id: str) -> Optional[Dict[str, Any]]:
        """Get a single track by ID."""
        try:
            data = await self._api_request(f"/tracks/{track_id}", {"market": "US"})
            return self._format_track(data)
        except:
            return None
    
    def _format_track(self, item: dict) -> dict:
        """Format track data for frontend."""
        return {
            "id": item["id"],
            "type": "track",
            "name": item["name"],
            "artists": ", ".join(a["name"] for a in item["artists"]),
            "artist_names": [a["name"] for a in item["artists"]],
            "album": item["album"]["name"],
            "album_id": item["album"]["id"],
            "album_art": self._get_best_image(item["album"]["images"]),
            "duration_ms": item["duration_ms"],
            "duration": self._format_duration(item["duration_ms"]),
            "isrc": item.get("external_ids", {}).get("isrc"),
            "source": "spotify",
        }
    
    # ========== ALBUM METHODS ==========
    
    async def get_album(self, album_id: str) -> Optional[Dict[str, Any]]:
        """Get album with all tracks."""
        try:
            data = await self._api_request(f"/albums/{album_id}", {"market": "US"})
            album = self._format_album(data)
            
            tracks = []
            for item in data.get("tracks", {}).get("items", []):
                track = {
                    "id": item["id"],
                    "type": "track",
                    "name": item["name"],
                    "artists": ", ".join(a["name"] for a in item["artists"]),
                    "artist_names": [a["name"] for a in item["artists"]],
                    "album": data["name"],
                    "album_id": album_id,
                    "album_art": album["album_art"],
                    "duration_ms": item["duration_ms"],
                    "duration": self._format_duration(item["duration_ms"]),
                    "isrc": None,
                    "source": "spotify",
                }
                tracks.append(track)
            
            album["tracks"] = tracks
            return album
        except Exception as e:
            logger.error(f"Error fetching Spotify album {album_id}: {e}")
            return None
    
    def _format_album(self, item: dict) -> dict:
        return {
            "id": item["id"],
            "type": "album",
            "name": item["name"],
            "artists": ", ".join(a["name"] for a in item.get("artists", [])),
            "album_art": self._get_best_image(item.get("images", [])),
            "release_date": item.get("release_date", ""),
            "total_tracks": item.get("total_tracks", 0),
            "source": "spotify",
        }
    
    # ========== PLAYLIST METHODS ==========
    
    async def get_playlist(self, playlist_id: str) -> Optional[Dict[str, Any]]:
        """Get playlist with all tracks (handles pagination for 100+ songs)."""
        try:
            data = await self._api_request(f"/playlists/{playlist_id}", {"market": "US"})
            
            playlist = {
                "id": data["id"],
                "type": "playlist",
                "name": data["name"],
                "description": data.get("description", ""),
                "album_art": self._get_best_image(data.get("images", [])),
                "owner": data.get("owner", {}).get("display_name", ""),
                "total_tracks": data.get("tracks", {}).get("total", 0),
                "source": "spotify",
            }
            
            tracks = []
            # Process first page of tracks
            tracks_data = data.get("tracks", {})
            for item in tracks_data.get("items", []):
                track_data = item.get("track")
                if track_data and track_data.get("id"):
                    tracks.append(self._format_track(track_data))
            
            # Paginate through remaining tracks if playlist has more than 100
            next_url = tracks_data.get("next")
            while next_url:
                logger.info(f"Fetching next page of playlist tracks... ({len(tracks)}/{playlist['total_tracks']})")
                try:
                    # Extract the path from the full URL
                    # next_url is like "https://api.spotify.com/v1/playlists/.../tracks?offset=100&limit=100"
                    next_response = await self.client.get(
                        next_url,
                        headers={"Authorization": f"Bearer {self.access_token}"}
                    )
                    next_response.raise_for_status()
                    next_data = next_response.json()
                    
                    for item in next_data.get("items", []):
                        track_data = item.get("track")
                        if track_data and track_data.get("id"):
                            tracks.append(self._format_track(track_data))
                    
                    next_url = next_data.get("next")
                except Exception as e:
                    logger.error(f"Error fetching next page: {e}")
                    break
            
            logger.info(f"Loaded {len(tracks)} tracks from playlist '{playlist['name']}'")
            playlist["tracks"] = tracks
            return playlist
        except Exception as e:
            logger.error(f"Error fetching Spotify playlist {playlist_id}: {e}")
            return None
    
    # ========== ARTIST METHODS ==========
    
    async def get_artist(self, artist_id: str) -> Optional[Dict[str, Any]]:
        """Get artist info with top tracks."""
        try:
            artist_data = await self._api_request(f"/artists/{artist_id}")
            artist = {
                "id": artist_data["id"],
                "type": "artist",
                "name": artist_data["name"],
                "image": self._get_best_image(artist_data.get("images", [])),
                "genres": artist_data.get("genres", []),
                "followers": artist_data.get("followers", {}).get("total", 0),
                "source": "spotify",
            }
            
            top_tracks = await self._api_request(f"/artists/{artist_id}/top-tracks", {"market": "US"})
            artist["tracks"] = [self._format_track(t) for t in top_tracks.get("tracks", [])]
            
            return artist
        except Exception as e:
            logger.error(f"Error fetching Spotify artist {artist_id}: {e}")
            return None
    
    # ========== AUDIO FEATURES & CAMELOT ==========
    
    # Camelot Wheel: Maps (pitch_class, mode) to Camelot notation
    # pitch_class: 0=C, 1=C#, 2=D, ..., 11=B
    # mode: 1=Major (B), 0=Minor (A)
    CAMELOT_MAP = {
        (0, 1): "8B",   (0, 0): "5A",   # C Major / C Minor
        (1, 1): "3B",   (1, 0): "12A",  # C# Major / C# Minor
        (2, 1): "10B",  (2, 0): "7A",   # D Major / D Minor
        (3, 1): "5B",   (3, 0): "2A",   # D# Major / D# Minor
        (4, 1): "12B",  (4, 0): "9A",   # E Major / E Minor
        (5, 1): "7B",   (5, 0): "4A",   # F Major / F Minor
        (6, 1): "2B",   (6, 0): "11A",  # F# Major / F# Minor
        (7, 1): "9B",   (7, 0): "6A",   # G Major / G Minor
        (8, 1): "4B",   (8, 0): "1A",   # G# Major / G# Minor
        (9, 1): "11B",  (9, 0): "8A",   # A Major / A Minor
        (10, 1): "6B",  (10, 0): "3A",  # A# Major / A# Minor
        (11, 1): "1B",  (11, 0): "10A", # B Major / B Minor
    }
    
    def _to_camelot(self, key: int, mode: int) -> str:
        """Convert Spotify key/mode to Camelot notation."""
        return self.CAMELOT_MAP.get((key, mode), "?")
    
    async def search_track_by_isrc(self, isrc: str) -> Optional[str]:
        """Search for a track by ISRC and return Spotify track ID."""
        try:
            data = await self._api_request("/search", {"q": f"isrc:{isrc}", "type": "track", "limit": 1})
            tracks = data.get("tracks", {}).get("items", [])
            if tracks:
                return tracks[0].get("id")
        except Exception as e:
            logger.warning(f"ISRC search failed for {isrc}: {e}")
        return None
    
    async def search_track_by_name(self, name: str, artist: str) -> Optional[str]:
        """Search for a track by name and artist, return Spotify track ID."""
        try:
            # 1. Try strict search first
            query = f"track:{name} artist:{artist}"
            data = await self._api_request("/search", {"q": query, "type": "track", "limit": 1, "market": "US"})
            tracks = data.get("tracks", {}).get("items", [])
            if tracks:
                return tracks[0].get("id")
            
            # 2. Fallback to loose search (just string matching)
            # Remove special chars and extra artists for better matching
            clean_name = name.split('(')[0].split('-')[0].strip()
            clean_artist = artist.split(',')[0].strip() 
            query = f"{clean_name} {clean_artist}"
            data = await self._api_request("/search", {"q": query, "type": "track", "limit": 1, "market": "US"})
            tracks = data.get("tracks", {}).get("items", [])
            if tracks:
                return tracks[0].get("id")
                
        except Exception as e:
            logger.warning(f"Name search failed for {name} by {artist}: {e}")
        return None

    async def get_audio_features(self, track_id: str, isrc: str = None, name: str = None, artist: str = None) -> Optional[Dict[str, Any]]:
        """Get audio features (BPM, key, energy) for a single track.
        
        If track_id starts with 'dz_' (Deezer), will try ISRC or name/artist lookup first.
        """
        spotify_id = track_id
        
        # Handle Deezer tracks - need to find Spotify equivalent
        if track_id.startswith("dz_"):
            spotify_id = None
            # Try ISRC first
            if isrc:
                spotify_id = await self.search_track_by_isrc(isrc)
            # Fallback to name/artist search
            if not spotify_id and name and artist:
                spotify_id = await self.search_track_by_name(name, artist)
            
            if not spotify_id:
                logger.warning(f"Could not find Spotify ID for Deezer track {track_id}")
                return None
        
        try:
            data = await self._api_request(f"/audio-features/{spotify_id}")
            return self._format_audio_features(data)
        except Exception as e:
            # 403 Forbidden likely means token lacks permission (scraper token) or ID is invalid
            if "403" in str(e):
                logger.warning(f"Spotify 403 Forbidden for {spotify_id} (token permissions?)")
            else:
                logger.error(f"Error fetching audio features for {spotify_id}: {e}")
            return None

    
    async def get_audio_features_batch(self, track_ids: List[str]) -> List[Optional[Dict[str, Any]]]:
        """Get audio features for multiple tracks (max 100 per request)."""
        if not track_ids:
            return []
        
        # Spotify API limit is 100 tracks per request
        results = []
        for i in range(0, len(track_ids), 100):
            batch = track_ids[i:i+100]
            try:
                data = await self._api_request("/audio-features", {"ids": ",".join(batch)})
                for features in data.get("audio_features", []):
                    if features:
                        results.append(self._format_audio_features(features))
                    else:
                        results.append(None)
            except Exception as e:
                logger.error(f"Error fetching batch audio features: {e}")
                results.extend([None] * len(batch))
        
        return results
    
    def _format_audio_features(self, data: dict) -> dict:
        """Format audio features for frontend."""
        key = data.get("key", -1)
        mode = data.get("mode", 0)
        return {
            "track_id": data.get("id"),
            "bpm": round(data.get("tempo", 0)),
            "key": key,
            "mode": mode,
            "camelot": self._to_camelot(key, mode) if key >= 0 else "?",
            "energy": round(data.get("energy", 0), 2),
            "danceability": round(data.get("danceability", 0), 2),
            "valence": round(data.get("valence", 0), 2),  # "happiness"
        }
    
    # ========== UTILITIES ==========
    
    def _get_best_image(self, images: List[Dict]) -> Optional[str]:
        if not images:
            return None
        sorted_images = sorted(images, key=lambda x: x.get("width", 0), reverse=True)
        return sorted_images[0]["url"] if sorted_images else None
    
    def _format_duration(self, ms: int) -> str:
        seconds = ms // 1000
        minutes = seconds // 60
        secs = seconds % 60
        return f"{minutes}:{secs:02d}"
    
    async def get_made_for_you_playlists(self) -> List[Dict[str, Any]]:
        """
        Get 'Made For You' playlists (Daily Mix, Discover Weekly, etc.).
        Uses search API with strict filtering for Spotify-owned playlists.
        Requires authenticated token (sp_dc cookie).
        """
        try:
            # Check if we have a valid token (will try cookie auth)
            token = await self._get_access_token()
            if not token:
                logger.warning("No Spotify token available for Made For You")
                return []
            
            mixes = []
            queries = ["Daily Mix", "Discover Weekly", "Release Radar", "On Repeat", "Repeat Rewind"]
            
            for q in queries:
                try:
                    data = await self._api_request("/search", {"q": q, "type": "playlist", "limit": 10})
                    if not data:
                        continue
                    
                    items = data.get("playlists", {}).get("items", [])
                    for item in items:
                        if not item:
                            continue
                        
                        owner_id = item.get("owner", {}).get("id", "")
                        name = item.get("name", "")
                        
                        # Filter: owned by "spotify" OR name starts with one of our keywords
                        # (Daily Mix 1, Daily Mix 2, etc. are personalized)
                        is_spotify_owned = owner_id == "spotify"
                        name_matches = any(name.startswith(kw) or name == kw for kw in queries)
                        
                        if is_spotify_owned or name_matches:
                            mixes.append({
                                "id": item["id"],
                                "name": name,
                                "description": item.get("description", ""),
                                "image": self._get_best_image(item.get("images", [])),
                                "owner": "Spotify",
                                "type": "playlist",
                                "source": "spotify"
                            })
                except Exception as e:
                    logger.warning(f"Failed to fetch mix '{q}': {e}")
            
            # Deduplicate by ID
            unique_mixes = {m['id']: m for m in mixes}.values()
            logger.info(f"Found {len(list(unique_mixes))} Made For You playlists")
            return list(unique_mixes)

        except Exception as e:
            logger.error(f"Error fetching Made For You playlists: {e}")
            return []

    async def close(self):
        await self.client.aclose()


# Singleton instance
spotify_service = SpotifyService()
