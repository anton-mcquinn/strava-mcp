from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
import os
import time  
import requests
import logging
from datetime import datetime
from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
load_dotenv()
logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)
strava_client = None

class StravaClient:
    def __init__(self, access_token, refresh_token, client_id, client_secret):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.client_id = client_id
        self.client_secret = client_secret
        self.token_expires_at = 0
        self.base_url = "https://www.strava.com/api/v3"
        
    def refresh_access_token_if_needed(self):
        current_time = time.time()
        if current_time >= (self.token_expires_at - 300):
            refresh_url = "https://www.strava.com/oauth/token"
            payload = {
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token"
            }
            response = requests.post(refresh_url, data=payload)
            if response.status_code == 200:
                data = response.json()
                self.access_token = data["access_token"]
                self.refresh_token = data["refresh_token"]
                self.token_expires_at = data["expires_at"]
                self._save_tokens()
            else:
                raise Exception(f"Failed to refresh token: {response.text}")
                
    def _save_tokens(self):
        logger.info(f"New access token obtained, expires at: {self.token_expires_at}")
        
    def get_activities(self, limit=100, before=None, after=None, activity_type=None, page=1):  
        """
        Get activities with filtering options.
        
        Args:
            limit: Number of activities to return per page
            before: Unix timestamp to get activities before this time
            after: Unix timestamp to get activities after this time
            activity_type: Filter by activity type (Run, Ride, Swim, etc.)
            page: Page number for pagination
            
        Returns:
            List of activities matching the criteria
        """
        self.refresh_access_token_if_needed() 
        headers = {"Authorization": f"Bearer {self.access_token}"}
        
        params = {
            "per_page": limit,
            "page": page
        }
        
        if before:
            params["before"] = before
        if after:
            params["after"] = after
            
        response = requests.get(
            f"{self.base_url}/athlete/activities",
            headers=headers,
            params=params
        )
        
        if response.status_code != 200:
            logger.error(f"Error fetching activities: {response.text}")
            raise Exception(f"Failed to fetch activities: {response.text}")
            
        activities = response.json()
        
        if activity_type:
            activities = [a for a in activities if a.get("type") == activity_type]
            
        return activities
    
    def get_activities_by_date_range(self, start_date, end_date, limit=100, activity_type=None):
        """
        Get activities within a specific date range using human-readable dates.
        
        Args:
            start_date: Start date string in format 'YYYY-MM-DD'
            end_date: End date string in format 'YYYY-MM-DD'
            limit: Maximum number of activities to return
            activity_type: Filter by activity type (Run, Ride, Swim, etc.)
            
        Returns:
            List of activities within the date range
        """
        after = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
        before = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp()) + 86400  # Add a day to include the end date
        
        return self.get_activities(limit=limit, before=before, after=after, activity_type=activity_type)
    
    def get_all_activities_by_date_range(self, start_date, end_date, activity_type=None, max_pages=10):
        """
        Get all activities within a date range, handling pagination automatically.
        
        Args:
            start_date: Start date string in format 'YYYY-MM-DD'
            end_date: End date string in format 'YYYY-MM-DD'
            activity_type: Filter by activity type (optional)
            max_pages: Maximum number of pages to fetch to prevent infinite loops
            
        Returns:
            List of all activities in the date range
        """
        after = int(datetime.strptime(start_date, "%Y-%m-%d").timestamp())
        before = int(datetime.strptime(end_date, "%Y-%m-%d").timestamp()) + 86400
        
        all_activities = []
        page = 1
        
        while page <= max_pages:
            activities = self.get_activities(limit=100, before=before, after=after, page=page)
            
            if not activities:
                break
                
            if activity_type:
                activities = [a for a in activities if a.get("type") == activity_type]
                
            all_activities.extend(activities)
            page += 1
            
            if len(activities) < 100:
                break
                
        return all_activities
        
    def get_activity_types(self):
        """
        Get a list of all unique activity types from recent activities.
        Useful for providing options to users.
        """
        activities = self.get_activities(limit=200)  # Get a good sample
        return list(set(a.get("type") for a in activities if a.get("type")))
        
    def get_athlete(self): 
        self.refresh_access_token_if_needed()
        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = requests.get(f"{self.base_url}/athlete", headers=headers)
        return response.json()
    
    def get_activity_by_id(self, activity_id):
        """
        Get detailed information about a specific activity.
        
        Args:
            activity_id: ID of the activity to retrieve
            
        Returns:
            Activity details
        """
        self.refresh_access_token_if_needed()
        headers = {"Authorization": f"Bearer {self.access_token}"}
        response = requests.get(f"{self.base_url}/activities/{activity_id}", headers=headers)
        
        if response.status_code != 200:
            logger.error(f"Error fetching activity {activity_id}: {response.text}")
            raise Exception(f"Failed to fetch activity: {response.text}")
            
        return response.json()

@asynccontextmanager
async def app_lifespan(server: FastMCP) -> AsyncIterator[None]:
    global strava_client
    
    access_token = os.getenv("STRAVA_ACCESS_TOKEN")
    refresh_token = os.getenv("STRAVA_REFRESH_TOKEN") 
    client_id = os.getenv("STRAVA_CLIENT_ID")
    client_secret = os.getenv("STRAVA_CLIENT_SECRET")
    
    strava_client = StravaClient(
        access_token=access_token,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret
    )
    
    try:
        yield
    finally:
        strava_client = None

mcp = FastMCP("Strava Assistant", lifespan=app_lifespan)

@mcp.tool()
def test_connection() -> dict:
    return {"status": "connected", "timestamp": time.time()}

@mcp.tool()
def get_recent_activities(limit: int) -> list:
    global strava_client
    
    if not strava_client:
        raise ValueError("Strava client not initialized. Check server logs.")
    
    activities = strava_client.get_activities(limit=limit)
    return activities

@mcp.tool()
def get_activities_by_date_range(start_date: str, end_date: str, activity_type: str = None) -> list:
    """
    Get activities within a specific date range.
    
    Args:
        start_date: Start date in format 'YYYY-MM-DD'
        end_date: End date in format 'YYYY-MM-DD'
        activity_type: Optional filter for activity type (Run, Ride, etc.)
        
    Returns:
        List of activities within the date range
    """
    global strava_client
    
    if not strava_client:
        raise ValueError("Strava client not initialized. Check server logs.")
    
    return strava_client.get_activities_by_date_range(
        start_date=start_date,
        end_date=end_date,
        activity_type=activity_type
    )

@mcp.tool()
def get_all_activities_in_year(year: int, activity_type: str = None) -> list:
    """
    Get all activities for a specific year.
    
    Args:
        year: The year to get activities for
        activity_type: Optional filter for activity type (Run, Ride, etc.)
        
    Returns:
        List of all activities in the year
    """
    global strava_client
    
    if not strava_client:
        raise ValueError("Strava client not initialized. Check server logs.")
    
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"
    
    return strava_client.get_all_activities_by_date_range(
        start_date=start_date,
        end_date=end_date,
        activity_type=activity_type
    )

@mcp.tool()
def get_available_activity_types() -> list:
    """
    Get a list of all available activity types.
    
    Returns:
        List of unique activity types
    """
    global strava_client
    
    if not strava_client:
        raise ValueError("Strava client not initialized. Check server logs.")
    
    return strava_client.get_activity_types()

@mcp.tool()
def get_athlete_profile() -> dict:
    global strava_client
    
    if not strava_client:
        logger.error("Strava client not initialized")
        raise ValueError("Strava client not initialized. Check server logs.")
    
    profile = strava_client.get_athlete()
    return profile

@mcp.tool()
def get_activity_details(activity_id: str) -> dict:
    """
    Get detailed information about a specific activity.
    
    Args:
        activity_id: ID of the activity to retrieve
        
    Returns:
        Detailed activity information
    """
    global strava_client
    
    if not strava_client:
        raise ValueError("Strava client not initialized. Check server logs.")
    
    return strava_client.get_activity_by_id(activity_id)
    
if __name__ == "__main__":
    mcp.run()
