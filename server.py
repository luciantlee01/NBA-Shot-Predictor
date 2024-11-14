import asyncio
import json
import random
import math
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
@app.post("/api/test/create/{game_id}")
async def create_test_data(game_id: str):
    """Create test data with defined player roles"""
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
                "score_away": 0,
                "last_action": "Game started"
            },
            "player_positions": [
                {
                    "player_id": "PG",
                    "role": "PG",
                    "x": 0.0,
                    "y": 30.0,
                    "velocity_x": 0.0,
                    "velocity_y": 0.0,
                    "team_id": "team1",
                    "is_shooting": False,
                    "shot_made": False
                },
                {
                    "player_id": "SG",
                    "role": "SG",
                    "x": -15.0,
                    "y": 25.0,
                    "velocity_x": 0.0,
                    "velocity_y": 0.0,
                    "team_id": "team1",
                    "is_shooting": False,
                    "shot_made": False
                },
                {
                    "player_id": "C",
                    "role": "C",
                    "x": 0.0,
                    "y": 10.0,
                    "velocity_x": 0.0,
                    "velocity_y": 0.0,
                    "team_id": "team1",
                    "is_shooting": False,
                    "shot_made": False
                }
            ]
        }

        await redis_client.set(f"game_state:{game_id}", json.dumps(test_data))
        await broadcast_update(game_id, test_data)
        
        return {"status": "success", "message": "Test data created"}
    except Exception as e:
        logger.error(f"Error creating test data: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))
    
@app.post("/api/test/simulate/{game_id}")
async def simulate_game_update(game_id: str):
    """Simulate a game update with basketball-specific movement patterns"""
    try:
        if not redis_client:
            raise HTTPException(status_code=503, detail="Redis connection not available")

        current_state = await get_game_state(game_id)
        if not current_state:
            raise HTTPException(status_code=404, detail="Game not found")

        game_state = current_state["game_state"]
        player_positions = current_state["player_positions"]

        # Update game state
        game_state["timestamp"] = datetime.now().isoformat()
        game_state["shot_clock"] = max(0, float(game_state["shot_clock"]) - 2.4)
        game_state["game_clock"] = max(0, float(game_state["game_clock"]) - 24.0)

        # First, clear any previous shooting states
        for player in player_positions:
            player["is_shooting"] = False
            player["shot_made"] = False

        # Simulate basketball play patterns
        shooting_chance = random.random()
        if shooting_chance > 0.7:  # 30% chance of shot attempt
            # Choose a random player to shoot
            shooter = random.choice(player_positions)
            
            # Calculate shot probability based on position
            distance_to_basket = math.sqrt(shooter["x"]**2 + (shooter["y"] - 5.5)**2)
            is_three_pointer = distance_to_basket > 23.75  # NBA 3-point line
            
            # Base probability affected by distance
            shot_probability = max(0.2, 1 - (distance_to_basket / 50))
            
            # Simulate shot
            shot_made = random.random() < shot_probability
            
            # Set shooting status for the shooter
            shooter["is_shooting"] = True
            shooter["shot_made"] = shot_made
            
            if shot_made:
                game_state["score_home"] += 3 if is_three_pointer else 2
                game_state["last_action"] = f"Player {shooter['player_id']} made a {'3-point' if is_three_pointer else '2-point'} shot!"
            else:
                game_state["last_action"] = f"Player {shooter['player_id']} missed a {'3-point' if is_three_pointer else '2-point'} shot!"
        else:
            game_state["last_action"] = "Players moving..."

        # Update player positions with role-based movement
        for player in player_positions:
            # Skip movement if player is shooting
            if player.get("is_shooting", False):
                continue

            role = player.get("role", "undefined")
            
            if role == "PG":  # Point Guard - handles the ball more
                # Stay near top of key
                target_x = random.uniform(-10, 10)
                target_y = random.uniform(25, 35)
            elif role == "SG":  # Shooting Guard - moves around perimeter
                # Move around three-point line
                angle = random.uniform(0, math.pi)
                target_x = 22 * math.cos(angle)
                target_y = 22 * math.sin(angle) + 15
            elif role == "C":  # Center - stays near paint
                # Stay in the paint area
                target_x = random.uniform(-8, 8)
                target_y = random.uniform(5, 15)
            
            # Calculate direction to target
            dx = target_x - player["x"]
            dy = target_y - player["y"]
            distance = math.sqrt(dx**2 + dy**2)
            
            if distance > 0:
                # Normalize and apply movement
                speed = random.uniform(0.5, 2.0)
                player["velocity_x"] = (dx / distance) * speed
                player["velocity_y"] = (dy / distance) * speed
                player["x"] += player["velocity_x"]
                player["y"] += player["velocity_y"]
            
            # Ensure players stay in bounds
            player["x"] = max(-23, min(23, player["x"]))
            player["y"] = max(2, min(45, player["y"]))

        update = {
            "game_state": game_state,
            "player_positions": player_positions
        }

        # Store in Redis and broadcast
        await redis_client.set(f"game_state:{game_id}", json.dumps(update))
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

HTML_TEMPLATE = """"
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

        /* Game visualization styles */
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
            background: #f8f9fa;
            margin: 20px 0;
        }
        
        .player-marker {
            position: absolute;
            width: 24px;
            height: 24px;
            border-radius: 50%;
            transform: translate(-50%, -50%);
            transition: all 0.3s ease;
            z-index: 2;
            display: flex;
            align-items: center;
            justify-content: center;
        }

        /* Player role colors */
        .player-pg {
            background: #ff4444;
            border: 2px solid #cc0000;
            box-shadow: 0 0 5px rgba(204, 0, 0, 0.5);
        }

        .player-sg {
            background: #33b5e5;
            border: 2px solid #0099cc;
            box-shadow: 0 0 5px rgba(0, 153, 204, 0.5);
        }

        .player-c {
            background: #aa66cc;
            border: 2px solid #9933cc;
            box-shadow: 0 0 5px rgba(153, 51, 204, 0.5);
        }

        .player-label {
            color: white;
            font-size: 12px;
            font-weight: bold;
            text-shadow: 1px 1px 1px rgba(0,0,0,0.5);
        }

        .velocity-vector {
            position: absolute;
            height: 2px;
            background: rgba(255, 255, 255, 0.7);
            transform-origin: left center;
            left: 50%;
            top: 50%;
        }

        .court-markings {
            position: absolute;
            width: 100%;
            height: 100%;
            pointer-events: none;
        }
        
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
        
        .free-throw-line {
            position: absolute;
            width: 40%;
            height: 0;
            border-top: 2px solid #666;
            left: 30%;
            top: 20%;
        }

        .basket {
            position: absolute;
            width: 10px;
            height: 10px;
            background: #ff0000;
            border-radius: 50%;
            bottom: 5px;
            left: calc(50% - 5px);
        }

        /* Enhanced shooting animations */
        .shooting {
            animation: pulse 0.8s infinite;
        }

        .shot-made {
            box-shadow: 0 0 20px #4CAF50 !important;
            animation: success-pulse 1s infinite !important;
        }

        .shot-missed {
            box-shadow: 0 0 20px #f44336 !important;
            animation: fail-pulse 1s infinite !important;
        }

        @keyframes pulse {
            0% { transform: translate(-50%, -50%) scale(1); }
            50% { transform: translate(-50%, -50%) scale(1.3); }
            100% { transform: translate(-50%, -50%) scale(1); }
        }
        @keyframes success-pulse {
            0% { 
                transform: translate(-50%, -50%) scale(1);
                box-shadow: 0 0 10px #4CAF50;
            }
            50% { 
                transform: translate(-50%, -50%) scale(1.2);
                box-shadow: 0 0 20px #4CAF50;
            }
            100% { 
                transform: translate(-50%, -50%) scale(1);
                box-shadow: 0 0 10px #4CAF50;
            }
        }

        @keyframes fail-pulse {
            0% { 
                transform: translate(-50%, -50%) scale(1);
                box-shadow: 0 0 10px #f44336;
            }
            50% { 
                transform: translate(-50%, -50%) scale(1.2);
                box-shadow: 0 0 20px #f44336;
            }
            100% { 
                transform: translate(-50%, -50%) scale(1);
                box-shadow: 0 0 10px #f44336;
            }
        }

        .debug-info {
            margin-top: 10px;
            padding: 10px;
            background: #f5f5f5;
            border-radius: 4px;
            font-family: monospace;
            white-space: pre-wrap;
        }

        #last-action {
            text-align: center;
            padding: 10px;
            font-weight: bold;
            margin-top: 10px;
            background: #f5f5f5;
            border-radius: 4px;
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
        
        <div id="last-action">Game started</div>
        
        <div id="basketball-court">
            <div class="court-markings">
                <div class="three-point-line"></div>
                <div class="free-throw-line"></div>
                <div class="basket"></div>
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
                const response = await fetch(`/api/test/create/${gameId}`, {  // Updated path
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
                const response = await fetch(`/api/test/simulate/${gameId}`, {  // Updated path
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

        function updateGameStats(gameState) {
            document.getElementById('shot-clock').textContent = 
                Number(gameState.shot_clock).toFixed(1);
            document.getElementById('game-clock').textContent = 
                Number(gameState.game_clock).toFixed(1);
            document.getElementById('score-home').textContent = 
                gameState.score_home;
            document.getElementById('quarter').textContent = 
                gameState.quarter;
            
            if (gameState.last_action) {
                document.getElementById('last-action').textContent = gameState.last_action;
            }
        }

        function updatePlayerPositions(players) {
            const court = document.getElementById('basketball-court');
            const existingMarkers = court.querySelectorAll('.player-marker');
            existingMarkers.forEach(marker => marker.remove());
            
            const courtWidth = court.offsetWidth;
            const courtHeight = court.offsetHeight;
            
            players.forEach((player) => {
                const marker = document.createElement('div');
                marker.className = 'player-marker';
                
                // Add role-specific styling
                const role = player.player_id || 'player';
                marker.classList.add(`player-${role.toLowerCase()}`);
                
                // Convert coordinates
                const x = ((player.x + 23) / 46) * courtWidth;
                const y = ((45 - player.y) / 43) * courtHeight;
                
                marker.style.left = `${x}px`;
                marker.style.top = `${y}px`;
                
                // Player label
                const label = document.createElement('div');
                label.className = 'player-label';
                label.textContent = role;
                marker.appendChild(label);
                
                // Enhanced shooting animation handling
                if (player.is_shooting === true) {  // Explicitly check for true
                    console.log(`Player ${player.player_id} is shooting! Made: ${player.shot_made}`);
                    marker.classList.add('shooting');
                    if (player.shot_made === true) {
                        marker.classList.add('shot-made');
                    } else {
                        marker.classList.add('shot-missed');
                    }
                }
                
                // Velocity vector
                if (player.velocity_x !== 0 || player.velocity_y !== 0) {
                    const vector = document.createElement('div');
                    vector.className = 'velocity-vector';
                    
                    const vectorLength = Math.sqrt(
                        Math.pow(player.velocity_x, 2) + 
                        Math.pow(player.velocity_y, 2)
                    ) * 15;
                    
                    const angle = Math.atan2(-player.velocity_y, player.velocity_x);
                    vector.style.width = `${vectorLength}px`;
                    vector.style.transform = `rotate(${angle}rad)`;
                    
                    marker.appendChild(vector);
                }
                
                court.appendChild(marker);
            });
            
            // Debug output to see shooting states
            console.log("Player States:", players.map(p => ({
                id: p.player_id,
                shooting: p.is_shooting,
                made: p.shot_made
            })));
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

            } catch (error) {
                updateStatus('Connection Failed', true);
                addMessage(`Failed to connect: ${error.message}`, true);
            }
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
    </script>
</body>
</html>
    

"""

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, log_level="debug")
