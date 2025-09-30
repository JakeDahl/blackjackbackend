import time
import boto3
import boto3.dynamodb.conditions
from botocore.exceptions import ClientError
from typing import Dict, List, Optional


class SessionManager:
    """Manages WebSocket sessions and connection state"""

    def __init__(self, sessions_table):
        self.sessions_table = sessions_table

    def create_session(self, connection_id: str, user_id: str = None, apn_token: str = None) -> Dict:
        """Create a new WebSocket session"""
        current_time = int(time.time())
        ttl = current_time + (24 * 60 * 60)  # 24 hours

        session_item = {
            'connection_id': connection_id,
            'connected_at': current_time,
            'ttl': ttl
        }

        # Only add non-None values to avoid GSI issues
        if user_id is not None:
            session_item['user_id'] = user_id
        if apn_token is not None:
            session_item['apn_token'] = apn_token

        self.sessions_table.put_item(Item=session_item)
        return session_item

    def get_session(self, connection_id: str) -> Optional[Dict]:
        """Get session by connection ID"""
        try:
            response = self.sessions_table.get_item(Key={'connection_id': connection_id})
            return response.get('Item')
        except ClientError:
            return None

    def update_session(self, connection_id: str, updates: Dict, remove_attrs: List[str] = None) -> None:
        """Update session with new data and optionally remove attributes"""
        if not updates and not remove_attrs:
            return

        update_expressions = []
        expression_values = {}
        expression_names = {}

        # Handle SET operations
        if updates:
            set_expression = "SET "
            for key, value in updates.items():
                if key in ['connection_id']:  # Skip primary key
                    continue

                # Handle reserved keywords
                if key in ['user_id']:
                    attr_name = f"#{key}"
                    expression_names[attr_name] = key
                    set_expression += f"{attr_name} = :{key}, "
                else:
                    set_expression += f"{key} = :{key}, "

                expression_values[f":{key}"] = value

            # Remove trailing comma and space
            set_expression = set_expression.rstrip(', ')
            update_expressions.append(set_expression)

        # Handle REMOVE operations
        if remove_attrs:
            remove_expression = "REMOVE "
            for attr in remove_attrs:
                if attr in ['user_id']:
                    attr_name = f"#{attr}_rem"
                    expression_names[attr_name] = attr
                    remove_expression += f"{attr_name}, "
                else:
                    remove_expression += f"{attr}, "

            # Remove trailing comma and space
            remove_expression = remove_expression.rstrip(', ')
            update_expressions.append(remove_expression)

        # Combine expressions
        update_expression = " ".join(update_expressions)

        kwargs = {
            'Key': {'connection_id': connection_id},
            'UpdateExpression': update_expression
        }

        if expression_values:
            kwargs['ExpressionAttributeValues'] = expression_values
        if expression_names:
            kwargs['ExpressionAttributeNames'] = expression_names

        self.sessions_table.update_item(**kwargs)

    def remove_session(self, connection_id: str) -> None:
        """Remove a session"""
        try:
            self.sessions_table.delete_item(Key={'connection_id': connection_id})
        except ClientError as e:
            print(f"Error removing session {connection_id}: {str(e)}")

    def get_sessions_by_game(self, game_id: str) -> List[Dict]:
        """Get all sessions for a specific game"""
        try:
            response = self.sessions_table.query(
                IndexName='game-id-index',
                KeyConditionExpression=boto3.dynamodb.conditions.Key('game_id').eq(game_id)
            )
            return response.get('Items', [])
        except ClientError:
            return []

    def join_game(self, connection_id: str, game_id: str, user_id: str, apn_token: str, player_number: int) -> None:
        """Update session when user joins a game"""
        print(f"SessionManager.join_game - connection_id: {connection_id}, game_id: {game_id}, user_id: {user_id}, player_number: {player_number}")

        updates = {
            'game_id': game_id,
            'user_id': user_id,
            'apn_token': apn_token,
            'player_number': player_number
        }

        print(f"Updating session with: {updates}")
        self.update_session(connection_id, updates)
        print("Session join_game update completed")

    def leave_game(self, connection_id: str) -> None:
        """Update session when user leaves a game"""
        # Remove game_id and player_number attributes to avoid GSI issues
        self.update_session(connection_id, {}, remove_attrs=['game_id', 'player_number'])

    def get_player_session(self, game_id: str, player_number: int) -> Optional[Dict]:
        """Get session for a specific player in a game"""
        sessions = self.get_sessions_by_game(game_id)
        for session in sessions:
            if session.get('player_number') == player_number:
                return session
        return None

    def cleanup_stale_sessions(self) -> None:
        """Clean up expired sessions (called by a scheduled function)"""
        current_time = int(time.time())

        try:
            # Scan for expired sessions
            response = self.sessions_table.scan(
                FilterExpression=boto3.dynamodb.conditions.Attr('ttl').lt(current_time)
            )

            # Delete expired sessions
            for item in response.get('Items', []):
                connection_id = item['connection_id']
                self.remove_session(connection_id)
                print(f"Removed stale session: {connection_id}")

        except ClientError as e:
            print(f"Error cleaning up stale sessions: {str(e)}")