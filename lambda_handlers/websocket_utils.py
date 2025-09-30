import json
import time
import boto3
from botocore.exceptions import ClientError
from typing import Dict, List
from decimal import Decimal


class WebSocketUtils:
    """Utility class for WebSocket message handling"""

    def __init__(self, apigateway_client):
        self.apigateway_client = apigateway_client

    def send_message(self, connection_id: str, message: Dict) -> Dict:
        """Send a message to a specific WebSocket connection"""
        try:
            # Convert Decimal types for JSON serialization
            message = self._decimal_to_int(message)

            response = self.apigateway_client.post_to_connection(
                ConnectionId=connection_id,
                Data=json.dumps(message)
            )
            print(f"Message sent to {connection_id}: {message.get('type', 'unknown')}")
            return {'statusCode': 200}

        except self.apigateway_client.exceptions.GoneException:
            print(f"Connection {connection_id} is gone")
            return {'statusCode': 410}
        except ClientError as e:
            print(f"Failed to send message to {connection_id}: {str(e)}")
            return {'statusCode': 500}
        except Exception as e:
            print(f"Error sending message to {connection_id}: {str(e)}")
            return {'statusCode': 500}

    def send_error(self, connection_id: str, error_message: str) -> Dict:
        """Send an error message to a WebSocket connection"""
        error_payload = {
            'type': 'error',
            'message': error_message,
            'timestamp': int(time.time())
        }
        return self.send_message(connection_id, error_payload)

    def broadcast_to_game(self, game_sessions: List[Dict], message: Dict, exclude_connection_id: str = None) -> None:
        """Broadcast a message to all players in a game"""
        for session in game_sessions:
            connection_id = session.get('connection_id')
            if connection_id and connection_id != exclude_connection_id:
                try:
                    self.send_message(connection_id, message)
                except Exception as e:
                    print(f"Failed to broadcast to {connection_id}: {str(e)}")
                    # Continue broadcasting to other connections

    def send_to_player(self, game_sessions: List[Dict], player_number: int, message: Dict) -> bool:
        """Send a message to a specific player in a game"""
        for session in game_sessions:
            if session.get('player_number') == player_number:
                connection_id = session.get('connection_id')
                if connection_id:
                    result = self.send_message(connection_id, message)
                    return result.get('statusCode') == 200
        return False

    def send_game_update(self, game_sessions: List[Dict], game_data: Dict, event_type: str = 'game_update') -> None:
        """Send game state update to all players in a game"""
        message = {
            'type': event_type,
            'data': game_data,
            'timestamp': int(time.time())
        }
        self.broadcast_to_game(game_sessions, message)

    def send_player_notification(self, game_sessions: List[Dict], player_number: int,
                                notification_type: str, message: str, data: Dict = None) -> None:
        """Send a notification to a specific player"""
        notification = {
            'type': 'notification',
            'notification_type': notification_type,
            'message': message,
            'data': data or {},
            'timestamp': int(time.time())
        }
        self.send_to_player(game_sessions, player_number, notification)

    def send_game_event(self, game_sessions: List[Dict], event_type: str, data: Dict,
                       exclude_connection_id: str = None) -> None:
        """Send a game event to all players"""
        event_message = {
            'type': 'game_event',
            'event_type': event_type,
            'data': data,
            'timestamp': int(time.time())
        }
        self.broadcast_to_game(game_sessions, event_message, exclude_connection_id)

    def _decimal_to_int(self, obj):
        """Convert DynamoDB Decimal types to int for JSON serialization"""
        if isinstance(obj, list):
            return [self._decimal_to_int(item) for item in obj]
        elif isinstance(obj, dict):
            return {key: self._decimal_to_int(value) for key, value in obj.items()}
        elif isinstance(obj, Decimal):
            return int(obj)
        return obj