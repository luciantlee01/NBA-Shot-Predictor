// Site dashboard for predictor
import React, { useState, useEffect } from 'react';
import { Card, CardHeader, CardTitle, CardContent } from '@/components/ui/card';
import { LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip, Legend } from 'recharts';
import { Camera, Filter, RefreshCcw, Users, TrendingUp } from 'lucide-react';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Select } from '@/components/ui/select';

const BasketballCourt = ({ 
  heatmapData, 
  defensiveData, 
  showDefenders, 
  onCourtClick 
}) => {
  // Court dimensions
  const courtWidth = 500;
  const courtHeight = 470;

  return (
    <svg 
      viewBox={`0 0 ${courtWidth} ${courtHeight}`} 
      className="w-full h-full cursor-pointer"
      onClick={onCourtClick}
    >
      {/* Court outline */}
      <rect 
        width={courtWidth} 
        height={courtHeight}
        fill="#f8f9fa" 
        stroke="#000" 
        strokeWidth="2"
      />
      
      {/* Three point line */}
      <path
        d={`M 50,0 
            L 50,170 
            A 190 190 0 0 1 450,170 
            L 450,0`}
        fill="none"
        stroke="#000"
        strokeWidth="2"
      />
      
      {/* Key */}
      <rect
        x={170}
        y={0}
        width={160}
        height={190}
        fill="none"
        stroke="#000"
        strokeWidth="2"
      />
      
      {/* Free throw circle */}
      <circle
        cx={250}
        cy={190}
        r={60}
        fill="none"
        stroke="#000"
        strokeWidth="2"
      />
      
      {/* Basket */}
      <circle
        cx={250}
        cy={20}
        r={10}
        fill="none"
        stroke="#000"
        strokeWidth="2"
      />

      {/* Heatmap overlay */}
      {heatmapData && heatmapData.map((point, idx) => (
        <circle
          key={`heat-${idx}`}
          cx={point.x}
          cy={point.y}
          r={15}
          fill={`rgba(0, 0, 255, ${point.probability})`}
          opacity={0.5}
        />
      ))}

      {/* Defensive overlay */}
      {showDefenders && defensiveData && (
        <g className="defensive-overlay">
          {defensiveData.map((defender, idx) => (
            <g key={`defender-${idx}`}>
              <circle
                cx={defender.x}
                cy={defender.y}
                r={15}
                fill="rgba(255, 0, 0, 0.3)"
                stroke="red"
                strokeWidth={2}
              />
              {/* Movement vector */}
              <line
                x1={defender.x}
                y1={defender.y}
                x2={defender.x + defender.velocityX * 20}
                y2={defender.y + defender.velocityY * 20}
                stroke="red"
                strokeWidth={2}
                markerEnd="url(#arrowhead)"
              />
            </g>
          ))}
        </g>
      )}

      {/* Arrow marker definition */}
      <defs>
        <marker
          id="arrowhead"
          markerWidth={10}
          markerHeight={7}
          refX={9}
          refY={3.5}
          orient="auto"
        >
          <polygon points="0 0, 10 3.5, 0 7" fill="red" />
        </marker>
      </defs>
    </svg>
  );
};

const PlayerStats = ({ playerData }) => (
  <div className="grid grid-cols-3 gap-4">
    <Card>
      <CardContent className="pt-6">
        <div className="text-2xl font-bold">{playerData.fg_percentage}%</div>
        <div className="text-sm text-gray-500">FG Percentage</div>
      </CardContent>
    </Card>
    <Card>
      <CardContent className="pt-6">
        <div className="text-2xl font-bold">{playerData.points}</div>
        <div className="text-sm text-gray-500">Points</div>
      </CardContent>
    </Card>
    <Card>
      <CardContent className="pt-6">
        <div className="text-2xl font-bold">{playerData.hot_hand_index}</div>
        <div className="text-sm text-gray-500">Hot Hand Index</div>
      </CardContent>
    </Card>
  </div>
);

const ShotPrediction = ({ prediction }) => (
  <Alert className="mt-4">
    <TrendingUp className="h-4 w-4" />
    <AlertDescription>
      Shot success probability: {(prediction.probability * 100).toFixed(1)}%
      {prediction.recommendation && (
        <span className="block text-sm text-gray-500 mt-1">
          {prediction.recommendation}
        </span>
      )}
    </AlertDescription>
  </Alert>
);

const ShotAnalyticsDashboard = () => {
  const [selectedPlayer, setSelectedPlayer] = useState(null);
  const [timeRange, setTimeRange] = useState('game');
  const [showDefenders, setShowDefenders] = useState(true);
  const [selectedPoint, setSelectedPoint] = useState(null);
  const [loading, setLoading] = useState(false);
  
  // Sample data - replace with real data from your backend
  const [gameData, setGameData] = useState({
    players: [],
    heatmapData: [],
    defensiveData: [],
    performanceData: []
  });

  useEffect(() => {
    // Fetch initial data
    fetchGameData();
    // Set up WebSocket connection for real-time updates
    const ws = new WebSocket('ws://your-backend/game-stream');
    ws.onmessage = handleRealTimeUpdate;
    
    return () => ws.close();
  }, []);

  const fetchGameData = async () => {
    setLoading(true);
    try {
      const response = await fetch('/api/game-data');
      const data = await response.json();
      setGameData(data);
    } catch (error) {
      console.error('Error fetching game data:', error);
    }
    setLoading(false);
  };

  const handleRealTimeUpdate = (event) => {
    const update = JSON.parse(event.data);
    setGameData(prevData => ({
      ...prevData,
      ...update
    }));
  };

  const handleCourtClick = (point) => {
    setSelectedPoint(point);
    // Fetch shot prediction for selected point
    fetchShotPrediction(point);
  };

  const fetchShotPrediction = async (point) => {
    // Implement shot prediction API call
  };

  return (
    <div className="p-4 space-y-4">
      <div className="flex justify-between items-center mb-6">
        <div className="flex items-center gap-4">
          <PlayerSelect 
            players={gameData.players}
            onSelect={setSelectedPlayer}
          />
          <TimeRangeFilter onRangeChange={setTimeRange} />
        </div>
        <div className="flex items-center gap-2">
          <button
            className="p-2 rounded hover:bg-gray-100"
            onClick={() => setShowDefenders(!showDefenders)}
          >
            <Users className={showDefenders ? 'text-blue-500' : 'text-gray-500'} />
          </button>
          <button
            className="p-2 rounded hover:bg-gray-100"
            onClick={fetchGameData}
          >
            <RefreshCcw className="h-5 w-5" />
          </button>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Camera className="h-6 w-6" />
              Shot Chart & Analysis
            </CardTitle>
          </CardHeader>
          <CardContent className="h-96">
            <BasketballCourt
              heatmapData={gameData.heatmapData}
              defensiveData={gameData.defensiveData}
              showDefenders={showDefenders}
              onCourtClick={handleCourtClick}
            />
            {selectedPoint && <ShotPrediction prediction={selectedPoint} />}
          </CardContent>
        </Card>

        <div className="space-y-4">
          <PlayerStats playerData={gameData.playerStats} />
          
          <Card>
            <CardHeader>
              <CardTitle>Performance Trends</CardTitle>
            </CardHeader>
            <CardContent>
              <LineChart width={500} height={300} data={gameData.performanceData}>
                <CartesianGrid strokeDasharray="3 3" />
                <XAxis dataKey="time" />
                <YAxis />
                <Tooltip />
                <Legend />
                <Line 
                  type="monotone" 
                  dataKey="fg_percentage" 
                  stroke="#8884d8" 
                  name="FG%" 
                />
                <Line 
                  type="monotone" 
                  dataKey="hot_hand_index" 
                  stroke="#82ca9d" 
                  name="Hot Hand Index" 
                />
              </LineChart>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
};


export default ShotAnalyticsDashboard;