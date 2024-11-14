import requests
import pandas as pd
import numpy as np
from datetime import datetime
import asyncio
import aiohttp
from typing import Dict, List, Optional
import logging

class NBADataPipeline:
    def __init__(self, api_key: Optional[str] = None):
        self.base_url = "https://api.nba.com/stats"
        self.headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {api_key}" if api_key else None
        }
        self.logger = logging.getLogger(__name__)
        
    async def fetch_game_data(self, game_id: str) -> Dict:
        """
        Fetch real-time game data asynchronously
        """
        async with aiohttp.ClientSession() as session:
            endpoints = {
                'play_by_play': f"/playbyplayv2?GameID={game_id}",
                'shot_chart': f"/shotchartdetail?GameID={game_id}",
                'player_tracking': f"/boxscoreplayertrackv2?GameID={game_id}"
            }
            
            tasks = []
            for name, endpoint in endpoints.items():
                tasks.append(self.fetch_endpoint(session, endpoint))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            return dict(zip(endpoints.keys(), results))
    
    async def fetch_endpoint(self, session: aiohttp.ClientSession, endpoint: str) -> Dict:
        """
        Fetch data from a specific endpoint
        """
        try:
            async with session.get(f"{self.base_url}{endpoint}", headers=self.headers) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    self.logger.error(f"Error fetching {endpoint}: {response.status}")
                    return None
        except Exception as e:
            self.logger.error(f"Exception fetching {endpoint}: {str(e)}")
            return None

    def process_shot_data(self, raw_data: Dict) -> pd.DataFrame:
        """
        Process raw shot data into structured DataFrame
        """
        shots = pd.DataFrame(raw_data['shot_chart']['resultSets'][0]['rowSet'],
                           columns=['GAME_ID', 'PLAYER_ID', 'SHOT_TYPE', 'SHOT_ZONE',
                                  'SHOT_DISTANCE', 'LOC_X', 'LOC_Y', 'SHOT_MADE_FLAG'])
        
        # Add derived features
        shots['SHOT_ANGLE'] = np.arctan2(shots['LOC_Y'], shots['LOC_X'])
        shots['SHOT_CLOCK'] = self._calculate_shot_clock(raw_data['play_by_play'])
        shots['DEFENDER_DISTANCE'] = self._get_defender_distance(raw_data['player_tracking'])
        
        return shots

    def _calculate_shot_clock(self, play_by_play: Dict) -> pd.Series:
        """
        Calculate shot clock for each shot based on play-by-play data
        """
        # Implementation details for shot clock calculation
        pass

    def _get_defender_distance(self, tracking_data: Dict) -> pd.Series:
        """
        Calculate closest defender distance from player tracking data
        """
        # Implementation details for defender distance calculation
        pass

class StreamProcessor:
    def __init__(self, pipeline: NBADataPipeline):
        self.pipeline = pipeline
        self.current_game_data = {}
        
    async def process_stream(self, game_id: str):
        """
        Process real-time game stream
        """
        while True:
            try:
                # Fetch latest game data
                new_data = await self.pipeline.fetch_game_data(game_id)
                
                # Process and update current game state
                self._update_game_state(new_data)
                
                # Emit updated data to subscribers
                await self._emit_updates()
                
                # Wait for next update interval
                await asyncio.sleep(1)  # Adjust based on API rate limits
                
            except Exception as e:
                self.logger.error(f"Stream processing error: {str(e)}")
                await asyncio.sleep(5)  # Back off on error
    
    def _update_game_state(self, new_data: Dict):
        """
        Update current game state with new data
        """
        # Merge new data with current state
        self.current_game_data.update(new_data)
        
        # Process any derived metrics
        self._calculate_derived_metrics()
    
    def _calculate_derived_metrics(self):
        """
        Calculate derived metrics from current game state
        """
        # Implementation for derived metrics
        pass
    
    async def _emit_updates(self):
        """
        Emit updated data to subscribers
        """
        # Implementation for websocket or other real-time updates
        pass

# Example usage:
async def main():
    pipeline = NBADataPipeline(api_key="your_api_key")
    processor = StreamProcessor(pipeline)
    
    # Start processing stream for a specific game
    game_id = "0022000001"
    await processor.process_stream(game_id)

if __name__ == "__main__":
    asyncio.run(main())