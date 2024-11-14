import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.preprocessing import StandardScaler
import tensorflow as tf

class ShotPredictionModel:
    def __init__(self):
        self.scaler = StandardScaler()
        self.model = RandomForestClassifier(n_estimators=100, random_state=42)
        
    def preprocess_features(self, data):
        """
        Preprocess shot data with relevant features
        """
        features = [
            'shot_distance', 'shot_angle', 'defender_distance',
            'previous_fg_percentage', 'quarter', 'time_remaining',
            'score_differential', 'hot_hand_index'
        ]
        
        X = data[features]
        return self.scaler.fit_transform(X)
    
    def train(self, training_data):
        """
        Train the shot prediction model
        """
        X = self.preprocess_features(training_data)
        y = training_data['shot_made']
        self.model.fit(X, y)
    
    def predict_shot_probability(self, shot_features):
        """
        Predict probability of making a shot given features
        """
        X = self.scaler.transform(shot_features.reshape(1, -1))
        return self.model.predict_proba(X)[0][1]

class CourtHeatmap:
    def __init__(self, width=50, height=47):
        self.width = width
        self.height = height
        self.court_grid = np.zeros((height, width))
        
    def generate_heatmap(self, shots_data):
        """
        Generate shot probability heatmap
        """
        for shot in shots_data:
            x, y = self.convert_coordinates(shot['x'], shot['y'])
            if 0 <= x < self.width and 0 <= y < self.height:
                self.court_grid[y][x] = shot['probability']
        
        return self.court_grid
    
    def convert_coordinates(self, x, y):
        """
        Convert real court coordinates to grid coordinates
        """
        # Court dimensions in feet
        court_width = 50
        court_height = 47
        
        # Convert to grid coordinates
        grid_x = int((x + court_width/2) * self.width/court_width)
        grid_y = int(y * self.height/court_height)
        
        return grid_x, grid_y

class RealTimeAnalytics:
    def __init__(self, shot_model):
        self.shot_model = shot_model
        self.heatmap = CourtHeatmap()
        
    def update_recommendations(self, game_state, player_id):
        """
        Generate real-time shot recommendations
        """
        recommendations = []
        court_positions = self.generate_court_positions()
        
        for pos in court_positions:
            features = self.create_shot_features(game_state, player_id, pos)
            prob = self.shot_model.predict_shot_probability(features)
            recommendations.append({
                'x': pos[0],
                'y': pos[1],
                'probability': prob
            })
        
        return recommendations
    
    def generate_court_positions(self):
        """
        Generate grid of possible shot positions on court
        """
        x = np.linspace(-25, 25, 50)
        y = np.linspace(0, 47, 47)
        return [(i, j) for i in x for j in y]
    
    def create_shot_features(self, game_state, player_id, position):
        """
        Create feature vector for shot prediction
        """
        # Example feature creation - expand based on available data
        features = np.array([
            np.sqrt(position[0]**2 + position[1]**2),  # shot_distance
            np.arctan2(position[1], position[0]),      # shot_angle
            game_state['defender_distance'],
            game_state['player_fg_percentage'],
            game_state['quarter'],
            game_state['time_remaining'],
            game_state['score_differential'],
            game_state['hot_hand_index']
        ])
        
        return features

# Example usage:
def main():
    # Initialize models
    shot_model = ShotPredictionModel()
    analytics = RealTimeAnalytics(shot_model)
    
    # Simulate game state
    game_state = {
        'defender_distance': 5.0,
        'player_fg_percentage': 0.45,
        'quarter': 4,
        'time_remaining': 120,
        'score_differential': -2,
        'hot_hand_index': 0.6
    }
    
    # Generate recommendations
    recommendations = analytics.update_recommendations(game_state, player_id='example_player')
    
    # Generate heatmap
    heatmap = CourtHeatmap()
    court_visualization = heatmap.generate_heatmap(recommendations)
    
    return court_visualization

if __name__ == "__main__":
    main()