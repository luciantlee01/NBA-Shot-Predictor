import asyncio
import json
import random
from typing import Dict, List, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
import redis.asyncio as redis
from pydantic import BaseModel
import logging
from datetime import datetime
from contextlib import asynccontextmanager

# Global variables
redis_client = None
active_connections: Dict[str, List[WebSocket]] = {}

# Set up detailed logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Models (keep your existing models)
class GameState(BaseModel):
    game_id: str
    timestamp: datetime
    shot_clock: float
    game_clock: float
    quarter: int
    score_home: int
    score_away: int

class PlayerPosition(BaseModel):
    player_id: str
    x: float
    y: float
    velocity_x: float
    velocity_y: float
    team_id: str

class GameUpdate(BaseModel):
    game_state: GameState
    player_positions: List[PlayerPosition]
    shot_data: Optional[Dict] = None

# Global variables
redis_client = None
active_connections: Dict[str, List[WebSocket]] = {}

async def init_redis():
    """Initialize Redis connection with error handling"""
    try:
        client = await redis.Redis(
            host='localhost',
            port=6379,
            db=0,
            decode_responses=True,
            socket_timeout=5,
            socket_connect_timeout=5
        )
        # Test the connection
        await client.ping()
        logger.info("Successfully connected to Redis")
        return client
    except redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis: {str(e)}")
        return None
    except Exception as e:
        logger.error(f"Unexpected error connecting to Redis: {str(e)}")
        return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    global redis_client
    redis_client = await init_redis()
    if not redis_client:
        logger.error("Failed to initialize Redis. Server may not function correctly.")
    
    yield
    
    # Shutdown
    if redis_client:
        await redis_client.close()
        logger.info("Disconnected from Redis")

app = FastAPI(lifespan=lifespan)

async def broadcast_update(game_id: str, update: dict):
    """Broadcast updates to all connected clients for a game"""
    if game_id in active_connections:
        disconnected = []
        for websocket in active_connections[game_id]:
            try:
                await websocket.send_json(update)
            except Exception as e:
                disconnected.append(websocket)
                logger.error(f"Error broadcasting update: {str(e)}")
        
        # Clean up disconnected clients
        for websocket in disconnected:
            if game_id in active_connections:
                active_connections[game_id].remove(websocket)


# Add this route handler right after your app definition
@app.get("/")
async def root():
    return HTMLResponse(HTML_TEMPLATE)

# Setup CORS with more permissive settings for testing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add a health check endpoint
@app.get("/health")
async def health_check():
    """Check the health of the server and Redis connection"""
    try:
        if redis_client:
            await redis_client.ping()
            return {
                "status": "healthy",
                "redis": "connected",
                "timestamp": datetime.now().isoformat()
            }
        else:
            return {
                "status": "degraded",
                "redis": "disconnected",
                "timestamp": datetime.now().isoformat()
            }
    except Exception as e:
        logger.error(f"Health check failed: {str(e)}")
        return {
            "status": "unhealthy",
            "error": str(e),
            "timestamp": datetime.now().isoformat()
        }

@app.websocket("/ws/game/{game_id}")
async def websocket_endpoint(websocket: WebSocket, game_id: str):
    """Handle WebSocket connections with enhanced error handling"""
    try:
        # Check Redis connection before accepting
        if not redis_client:
            logger.error("Redis not connected, cannot accept WebSocket connection")
            await websocket.close(code=1013, reason="Redis connection not available")
            return

        # Accept the connection
        await websocket.accept()
        logger.info(f"WebSocket connection accepted for game {game_id}")

        # Send immediate confirmation
        await websocket.send_json({
            "type": "connection_status",
            "status": "connected",
            "game_id": game_id,
            "timestamp": datetime.now().isoformat()
        })

        # Add to active connections
        if game_id not in active_connections:
            active_connections[game_id] = []
        active_connections[game_id].append(websocket)
        
        try:
            # Ping Redis to ensure connection
            await redis_client.ping()
            
            # Send initial game state if it exists
            initial_state = await get_game_state(game_id)
            if initial_state:
                await websocket.send_json({
                    "type": "initial_state",
                    "data": initial_state
                })
            else:
                await websocket.send_json({
                    "type": "info",
                    "message": "No existing game state found"
                })

            # Handle incoming messages
            async for message in websocket.iter_json():
                try:
                    logger.debug(f"Received message: {message}")
                    if message.get("type") == "request_update":
                        game_state = await get_game_state(game_id)
                        await websocket.send_json({
                            "type": "game_state_update",
                            "data": game_state or {}
                        })
                except Exception as e:
                    logger.error(f"Error processing message: {str(e)}")
                    await websocket.send_json({
                        "type": "error",
                        "message": f"Error processing message: {str(e)}"
                    })

        except redis.RedisError as e:
            logger.error(f"Redis error during WebSocket connection: {str(e)}")
            await websocket.send_json({
                "type": "error",
                "message": "Database connection error"
            })
            
    except WebSocketDisconnect:
        logger.info(f"WebSocket disconnected normally for game {game_id}")
    except Exception as e:
        logger.error(f"Unexpected error in WebSocket connection: {str(e)}")
    finally:
        if game_id in active_connections and websocket in active_connections[game_id]:
            active_connections[game_id].remove(websocket)
            logger.info(f"Removed connection for game {game_id}")

# Add a test data endpoint
@app.post("/api/test/game-update/{game_id}")
async def create_test_data(game_id: str):
    """Create test data for a given game ID"""
    try:
        if not redis_client:
            raise HTTPException(status_code=503, detail="Redis connection not available")

        test_data = {
            "game_state": {
                "game_id": game_id,
                "timestamp": datetime.now().isoformat(),
                "shot_clock": 24.0,
                "game_clock": 720.0,
                "quarter": 1,
                "score_home": 0,
                "score_away": 0
            },
            "player_positions": [
                {
                    "player_id": "p1",
                    "x": 0.0,  # Center court
                    "y": 23.5,  # Half-court
                    "velocity_x": 0.0,
                    "velocity_y": 0.0,
                    "team_id": "team1"
                },
                {
                    "player_id": "p2",
                    "x": -10.0,  # Left side
                    "y": 35.0,
                    "velocity_x": 0.0,
                    "velocity_y": 0.0,
                    "team_id": "team1"
                },
                {
                    "player_id": "p3",
                    "x": 10.0,  # Right side
                    "y": 35.0,
                    "velocity_x": 0.0,
                    "velocity_y": 0.0,
                    "team_id": "team1"
                }
            ]
        }

        # Store in Redis
        await redis_client.set(f"game_state:{game_id}", json.dumps(test_data))
        
        # Broadcast to connected clients
        await broadcast_update(game_id, test_data)
        
        return {"status": "success", "message": "Test data created"}
    except Exception as e:
        logger.error(f"Error creating test data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/test/simulate-update/{game_id}")
async def simulate_game_update(game_id: str):
    """Simulate a game update with random changes and better boundary constraints"""
    try:
        if not redis_client:
            raise HTTPException(status_code=503, detail="Redis connection not available")

        # Get current game state
        current_state = await get_game_state(game_id)
        if not current_state:
            raise HTTPException(status_code=404, detail="Game not found")

        # Update game state with some changes
        game_state = current_state["game_state"]
        game_state["timestamp"] = datetime.now().isoformat()
        game_state["shot_clock"] = max(0, float(game_state["shot_clock"]) - 2.4)
        game_state["game_clock"] = max(0, float(game_state["game_clock"]) - 24.0)
        game_state["score_home"] = int(game_state["score_home"]) + 2

        # Update player positions with better boundary constraints
        player_positions = current_state["player_positions"]
        for player in player_positions:
            # Calculate potential new position
            new_x = player["x"] + random.uniform(-3, 3)  # Reduced movement range
            new_y = player["y"] + random.uniform(-3, 3)  # Reduced movement range
            
            # Constrain x position (court width)
            new_x = max(-23, min(23, new_x))  # Slightly inside the sidelines
            
            # Constrain y position (court length)
            new_y = max(2, min(45, new_y))  # Keep players away from baselines
            
            # Update position and velocity
            player["x"] = new_x
            player["y"] = new_y
            player["velocity_x"] = random.uniform(-1, 1)  # Reduced velocity
            player["velocity_y"] = random.uniform(-1, 1)  # Reduced velocity

        update = {
            "game_state": game_state,
            "player_positions": player_positions
        }

        # Store in Redis
        await redis_client.set(f"game_state:{game_id}", json.dumps(update))
        
        # Broadcast to connected clients
        await broadcast_update(game_id, update)
        
        return {"status": "success", "message": "Game updated"}
    except Exception as e:
        logger.error(f"Error simulating game update: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

async def get_game_state(game_id: str) -> Optional[Dict]:
    """Get game state from Redis with error handling"""
    try:
        if not redis_client:
            logger.error("Redis not connected")
            return None
            
        state = await redis_client.get(f"game_state:{game_id}")
        return json.loads(state) if state else None
    except Exception as e:
        logger.error(f"Error retrieving game state: {str(e)}")
        return None
    
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>NBA Shot Predictor API</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            line-height: 1.6;
        }
        .endpoint {
            background: #f5f5f5;
            padding: 15px;
            margin: 10px 0;
            border-radius: 5px;
        }
        #connection-status {
            padding: 10px;
            margin: 10px 0;
            border-radius: 5px;
            font-weight: bold;
        }
        #messages {
            margin-top: 20px;
            padding: 10px;
            background: #f5f5f5;
            border-radius: 5px;
            max-height: 300px;
            overflow-y: auto;
        }
        .message {
            margin: 5px 0;
            padding: 5px;
            border-bottom: 1px solid #ddd;
        }
        .controls {
            margin: 15px 0;
        }
        button {
            padding: 8px 16px;
            margin-right: 10px;
            border-radius: 4px;
            border: 1px solid #ddd;
            background: #fff;
            cursor: pointer;
        }
        button:hover {
            background: #f0f0f0;
        }
        input {
            padding: 8px;
            margin-right: 10px;
            border-radius: 4px;
            border: 1px solid #ddd;
        }
        .court-container {
            margin: 20px 0;
            padding: 20px;
            background: #f5f5f5;
            border-radius: 5px;
        }
        
        .game-stats {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
            gap: 10px;
            margin: 10px 0;
        }
        
        .stat-box {
            background: white;
            padding: 10px;
            border-radius: 4px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.1);
        }
        
        .stat-label {
            font-size: 0.8em;
            color: #666;
        }
        
        .stat-value {
            font-size: 1.2em;
            font-weight: bold;
            color: #333;
        }
        
        #basketball-court {
            width: 100%;
            height: 400px;
            border: 2px solid #333;
            position: relative;
            background: #fff;
        }
        
        .player-marker {
            position: absolute;
            width: 20px;
            height: 20px;
            background: blue;
            border-radius: 50%;
            transform: translate(-50%, -50%);
            transition: all 0.3s ease;
        }
        
        .velocity-vector {
            position: absolute;
            height: 2px;
            background: rgba(0, 0, 255, 0.5);
            transform-origin: left center;
        }
        #basketball-court {
            width: 100%;
            height: 400px;
            border: 2px solid #333;
            position: relative;
            background: #f8f9fa;
            margin: 20px 0;
        }
        
        /* Court markings */
        .court-markings {
            position: absolute;
            width: 100%;
            height: 100%;
            pointer-events: none;
        }
        
        /* Three-point line */
        .three-point-line {
            position: absolute;
            width: 80%;
            height: 70%;
            border: 2px solid #666;
            border-top: none;
            border-radius: 0 0 150px 150px;
            left: 10%;
            bottom: 0;
        }
        
        /* Free throw line */
        .free-throw-line {
            position: absolute;
            width: 40%;
            height: 0;
            border-top: 2px solid #666;
            left: 30%;
            top: 20%;
        }
        
        .player-marker {
            position: absolute;
            width: 20px;
            height: 20px;
            background: #2196F3;
            border: 2px solid #1976D2;
            border-radius: 50%;
            transform: translate(-50%, -50%);
            transition: all 0.3s ease;
            z-index: 2;
        }
        
        .velocity-vector {
            position: absolute;
            height: 2px;
            background: rgba(33, 150, 243, 0.5);
            transform-origin: left center;
            left: 50%;
            top: 50%;
        }

        .debug-info {
            margin-top: 10px;
            padding: 10px;
            background: #f5f5f5;
            border-radius: 4px;
            font-family: monospace;
            white-space: pre-wrap;
        }

    </style>
</head>
<body>
    <h1>NBA Shot Predictor API</h1>
    
    <div class="endpoint">
        <h2>WebSocket Test Interface</h2>
        <div id="connection-status">Status: Not Connected</div>
        
        <div class="controls">
            <input type="text" id="game-id" value="test123" placeholder="Enter game ID">
            <button onclick="connectWebSocket()">Connect</button>
            <button onclick="disconnectWebSocket()">Disconnect</button>
            <button onclick="clearMessages()">Clear Messages</button>
        </div>

        <div id="messages"></div>
    </div>

    <h2>API Health</h2>
    <div class="endpoint">
        <button onclick="checkHealth()">Check Health</button>
        <div id="health-status"></div>
    </div>

    <h2>Test Data</h2>
    <div class="endpoint">
        <button onclick="createTestData()">Create Test Data</button>
        <button onclick="simulateUpdate()">Simulate Update</button>
        <div id="test-data-status"></div>
    </div>

    <!-- Remove the first court container and keep only this one -->
    <div class="court-container">
        <h2>Game Visualization</h2>
        <div class="game-stats">
            <div class="stat-box">
                <div class="stat-label">Shot Clock</div>
                <div class="stat-value" id="shot-clock">24.0</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Game Clock</div>
                <div class="stat-value" id="game-clock">720.0</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Score (Home)</div>
                <div class="stat-value" id="score-home">0</div>
            </div>
            <div class="stat-box">
                <div class="stat-label">Quarter</div>
                <div class="stat-value" id="quarter">1</div>
            </div>
        </div>
        <div id="basketball-court">
            <div class="court-markings">
                <div class="three-point-line"></div>
                <div class="free-throw-line"></div>
            </div>
        </div>
        <div class="debug-info" id="debug-info"></div>
    </div>
    

    <script>
        let ws = null;
        let reconnectAttempts = 0;
        const maxReconnectAttempts = 3;

        function updateStatus(message, isError = false) {
            const status = document.getElementById('connection-status');
            status.textContent = `Status: ${message}`;
            status.style.color = isError ? 'red' : 'green';
        }

        function addMessage(message, isError = false) {
            const messages = document.getElementById('messages');
            const messageDiv = document.createElement('div');
            messageDiv.className = 'message';
            messageDiv.style.color = isError ? 'red' : 'black';
            messageDiv.textContent = `${new Date().toLocaleTimeString()}: ${message}`;
            messages.insertBefore(messageDiv, messages.firstChild);
        }

        function clearMessages() {
            document.getElementById('messages').innerHTML = '';
        }

        async function checkHealth() {
            try {
                const response = await fetch('/health');
                const data = await response.json();
                document.getElementById('health-status').textContent = 
                    `Health Status: ${JSON.stringify(data, null, 2)}`;
            } catch (error) {
                document.getElementById('health-status').textContent = 
                    `Error checking health: ${error.message}`;
            }
        }

        async function createTestData() {
            const gameId = document.getElementById('game-id').value;
            try {
                const response = await fetch(`/api/test/game-update/${gameId}`, {
                    method: 'POST'
                });
                const data = await response.json();
                document.getElementById('test-data-status').textContent = 
                    `Test Data Status: ${JSON.stringify(data, null, 2)}`;
                addMessage(`Created test data for game ${gameId}`);
            } catch (error) {
                document.getElementById('test-data-status').textContent = 
                    `Error creating test data: ${error.message}`;
                addMessage(`Failed to create test data: ${error.message}`, true);
            }
        }

        async function simulateUpdate() {
            const gameId = document.getElementById('game-id').value;
            try {
                const response = await fetch(`/api/test/simulate-update/${gameId}`, {
                    method: 'POST'
                });
                const data = await response.json();
                document.getElementById('test-data-status').textContent = 
                    `Update Status: ${JSON.stringify(data, null, 2)}`;
                addMessage(`Simulated update for game ${gameId}`);
            } catch (error) {
                document.getElementById('test-data-status').textContent = 
                    `Error simulating update: ${error.message}`;
                addMessage(`Failed to simulate update: ${error.message}`, true);
            }
        }

        function connectWebSocket() {
            if (ws && ws.readyState === WebSocket.OPEN) {
                addMessage('Already connected');
                return;
            }

            const gameId = document.getElementById('game-id').value;
            if (!gameId) {
                addMessage('Please enter a game ID', true);
                return;
            }

            try {
                addMessage('Attempting to connect...');
                ws = new WebSocket(`ws://localhost:8000/ws/game/${gameId}`);
                updateStatus('Connecting...');

                ws.onopen = () => {
                    updateStatus('Connected');
                    addMessage('Connected successfully');
                    reconnectAttempts = 0;
                };

                ws.onclose = (event) => {
                    updateStatus('Disconnected', true);
                    addMessage(`Connection closed: ${event.reason || 'No reason provided'}`, true);
                    ws = null;
                };

                ws.onerror = (error) => {
                    updateStatus('Error occurred', true);
                    addMessage('WebSocket error occurred', true);
                    console.error('WebSocket error:', error);
                };

                ws.onmessage = (event) => {
                    try {
                        const data = JSON.parse(event.data);
                        addMessage(`Received: ${JSON.stringify(data, null, 2)}`);
                    } catch (e) {
                        addMessage(`Received: ${event.data}`);
                    }
                };

            } catch (error) {
                updateStatus('Connection Failed', true);
                addMessage(`Failed to connect: ${error.message}`, true);
            }

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    addMessage(`Received: ${JSON.stringify(data, null, 2)}`);
                    
                    if (data.type === "initial_state" && data.data) {
                        // Handle initial state
                        if (data.data.game_state) {
                            updateGameStats(data.data.game_state);
                            updatePlayerPositions(data.data.player_positions || []);
                        }
                    } else if (data.game_state && data.player_positions) {
                        // Handle updates
                        updateGameStats(data.game_state);
                        updatePlayerPositions(data.player_positions);
                    }
                } catch (e) {
                    addMessage(`Error processing message: ${e.message}`, true);
                    console.error('Error:', e);
                }
            };
        }

        function disconnectWebSocket() {
            if (ws) {
                ws.close();
                ws = null;
                updateStatus('Disconnected', true);
                addMessage('Disconnected by user');
            }
        }

        // Check health on page load
        checkHealth();

        function updateGameStats(gameState) {
            document.getElementById('shot-clock').textContent = 
                Number(gameState.shot_clock).toFixed(1);
            document.getElementById('game-clock').textContent = 
                Number(gameState.game_clock).toFixed(1);
            document.getElementById('score-home').textContent = 
                gameState.score_home;
            document.getElementById('quarter').textContent = 
                gameState.quarter;
        }

        function updatePlayerPositions(players) {
            const court = document.getElementById('basketball-court');
            // Remove only player markers, not court markings
            const existingMarkers = court.querySelectorAll('.player-marker');
            existingMarkers.forEach(marker => marker.remove());
            
            // Court dimensions
            const courtWidth = court.offsetWidth;
            const courtHeight = court.offsetHeight;
            
            // Add padding to keep players inside visible area
            const padding = 20;
            const effectiveWidth = courtWidth - (padding * 2);
            const effectiveHeight = courtHeight - (padding * 2);
            
            players.forEach((player, index) => {
                const marker = document.createElement('div');
                marker.className = 'player-marker';
                
                // Normalize coordinates with padding
                // Convert from -23,23 to padding,width-padding for x
                const x = padding + ((player.x + 23) / 46) * effectiveWidth;
                // Convert from 2,45 to height-padding,padding for y (inverted)
                const y = padding + ((45 - player.y) / 43) * effectiveHeight;
                
                // Ensure markers stay within bounds
                const boundedX = Math.max(padding, Math.min(courtWidth - padding, x));
                const boundedY = Math.max(padding, Math.min(courtHeight - padding, y));
                
                marker.style.left = `${boundedX}px`;
                marker.style.top = `${boundedY}px`;
                
                // Add player ID and position label
                marker.title = `Player ${player.player_id}\nPosition: (${player.x.toFixed(1)}, ${player.y.toFixed(1)})`;
                
                // Add velocity vector if moving
                if (player.velocity_x !== 0 || player.velocity_y !== 0) {
                    const vector = document.createElement('div');
                    vector.className = 'velocity-vector';
                    
                    const vectorLength = Math.sqrt(
                        Math.pow(player.velocity_x, 2) + 
                        Math.pow(player.velocity_y, 2)
                    ) * 15; // Scaled down velocity visualization
                    
                    const angle = Math.atan2(-player.velocity_y, player.velocity_x);
                    
                    vector.style.width = `${vectorLength}px`;
                    vector.style.transform = `rotate(${angle}rad)`;
                    
                    marker.appendChild(vector);
                }
                
                court.appendChild(marker);
            });
            
            // Update debug info with actual coordinates
            document.getElementById('debug-info').textContent = 
                `Players: ${players.map(p => 
                    `${p.player_id}: (${p.x.toFixed(1)}, ${p.y.toFixed(1)})`
                ).join(', ')}`;
        }

        // Update the existing onmessage handler in your connectWebSocket function
        ws.onmessage = (event) => {
            try {
                const data = JSON.parse(event.data);
                addMessage(`Received: ${JSON.stringify(data, null, 2)}`);
                
                // Update visualization if it's a game state update
                if (data.game_state && data.player_positions) {
                    updateGameStats(data.game_state);
                    updatePlayerPositions(data.player_positions);
                }
            } catch (e) {
                addMessage(`Received: ${event.data}`);
            }
        };
    </script>
</body>

</html>
"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="debug")
