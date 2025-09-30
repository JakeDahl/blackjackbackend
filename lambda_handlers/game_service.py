import json
import random
import string
import time
import boto3.dynamodb.conditions
from botocore.exceptions import ClientError
from decimal import Decimal
from typing import Dict, Optional, List
from session_manager import SessionManager
from blackjack_models import BlackjackGameState


class GameService:
    """Service class for multiplayer blackjack game logic"""

    def __init__(self, games_table, session_manager: SessionManager, ws_utils=None):
        self.games_table = games_table
        self.session_manager = session_manager
        self.ws_utils = ws_utils

    def create_game(self, connection_id: str, user_id: str, apn_token: str,
                   visibility: str = 'private', initial_balance: int = 1000) -> Dict:
        """Create a new multiplayer blackjack game"""
        try:
            print(f"GameService.create_game - connection_id: {connection_id}, user_id: {user_id}, visibility: {visibility}")

            # Generate unique game ID
            game_id = self._generate_unique_game_id()
            print(f"Generated game_id: {game_id}")

            current_time = int(time.time())
            ttl = current_time + (24 * 60 * 60)  # 24 hours

            # Initialize game state with first player
            game_state = BlackjackGameState()
            game_state.add_player(1, user_id, initial_balance)

            # Create game item
            game_item = {
                'game_id': game_id,
                'game_state': game_state.to_dict(),
                'game_status': 'waiting_for_players',
                'visibility': visibility,
                'initial_balance': initial_balance,
                'created_at': current_time,
                'ttl': ttl,
                'max_players': BlackjackGameState.MAX_PLAYERS
            }

            print(f"Putting game item to DynamoDB")
            self.games_table.put_item(Item=game_item)
            print("Game item successfully stored")

            # Update session with game info
            self.session_manager.join_game(connection_id, game_id, user_id, apn_token, 1)

            result = {
                'game_id': game_id,
                'message': f'Game created successfully. Waiting for players (1/{BlackjackGameState.MAX_PLAYERS}).',
                'game_status': 'waiting_for_players',
                'player_number': 1,
                'game_state': game_state.to_dict(),
                'initial_balance': initial_balance
            }

            return result

        except Exception as e:
            print(f"GameService.create_game error: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            raise Exception(f"Failed to create game: {str(e)}")

    def join_game(self, connection_id: str, game_id: str, user_id: str, apn_token: str) -> Dict:
        """Join an existing multiplayer blackjack game"""
        try:
            response = self.games_table.get_item(Key={'game_id': game_id})

            if 'Item' not in response:
                raise Exception('Game not found')

            game = response['Item']
            game_state = BlackjackGameState.from_dict(game['game_state'])

            if len(game_state.players) >= BlackjackGameState.MAX_PLAYERS:
                raise Exception('Game is full')

            game_status = game.get('game_status')
            if game_status == 'tombstoned':
                raise Exception('Game has been tombstoned')
            elif game_status not in ['waiting_for_players', 'active']:
                raise Exception('Game is not accepting new players')

            # Find next available player number
            player_number = None
            for i in range(1, BlackjackGameState.MAX_PLAYERS + 1):
                if i not in game_state.players:
                    player_number = i
                    break

            if player_number is None:
                raise Exception('No available seat')

            # Add player to game
            initial_balance = game.get('initial_balance', 1000)
            game_state.add_player(player_number, user_id, initial_balance)

            # Update game status
            self.games_table.update_item(
                Key={'game_id': game_id},
                UpdateExpression='SET game_state = :state, game_status = :status',
                ExpressionAttributeValues={
                    ':state': game_state.to_dict(),
                    ':status': 'active'
                }
            )

            # Update session with game info
            self.session_manager.join_game(connection_id, game_id, user_id, apn_token, player_number)

            result = {
                'game_id': game_id,
                'message': f'Successfully joined the game as Player {player_number}',
                'game_status': 'active',
                'player_number': player_number,
                'game_state': self._decimal_to_int(game_state.to_dict()),
                'initial_balance': initial_balance
            }

            # Notify other players
            game_sessions = self.session_manager.get_sessions_by_game(game_id)
            if game_sessions and self.ws_utils:
                for session in game_sessions:
                    if session.get('connection_id') != connection_id:
                        self.ws_utils.send_message(session['connection_id'], {
                            'type': 'player_joined',
                            'message': f'Player {player_number} joined the game',
                            'player_number': player_number,
                            'total_players': len(game_state.players),
                            'game_state': self._decimal_to_int(game_state.to_dict())
                        })

            return result

        except Exception as e:
            raise Exception(f"Failed to join game: {str(e)}")

    def start_round(self, connection_id: str, game_id: str) -> Dict:
        """Start a new round of betting"""
        try:
            session = self.session_manager.get_session(connection_id)
            if not session or session.get('game_id') != game_id:
                raise Exception('You are not in this game')

            response = self.games_table.get_item(Key={'game_id': game_id})
            if 'Item' not in response:
                raise Exception('Game not found')

            game = response['Item']
            game_state = BlackjackGameState.from_dict(game['game_state'])

            if game_state.phase not in ['waiting', 'round_over']:
                raise Exception('Cannot start round in current phase')

            if not game_state.players:
                raise Exception('No players in game')

            # Start betting phase
            game_state.start_betting_phase()

            self.games_table.update_item(
                Key={'game_id': game_id},
                UpdateExpression='SET game_state = :state',
                ExpressionAttributeValues={':state': game_state.to_dict()}
            )

            result = {
                'game_id': game_id,
                'message': 'Betting phase started. All players place your bets.',
                'game_state': game_state.to_dict()
            }

            # Notify all players
            self._broadcast_to_game(game_id, {
                'type': 'betting_started',
                'message': 'Place your bets',
                'game_state': self._decimal_to_int(game_state.to_dict())
            })

            return result

        except Exception as e:
            raise Exception(f"Failed to start round: {str(e)}")

    def place_bet(self, connection_id: str, game_id: str, bet_amount: int) -> Dict:
        """Place a bet for the current round"""
        try:
            session = self.session_manager.get_session(connection_id)
            if not session or session.get('game_id') != game_id:
                raise Exception('You are not in this game')

            player_number = session.get('player_number')

            response = self.games_table.get_item(Key={'game_id': game_id})
            if 'Item' not in response:
                raise Exception('Game not found')

            game = response['Item']
            game_state = BlackjackGameState.from_dict(game['game_state'])

            if game_state.phase != 'betting':
                raise Exception('Not in betting phase')

            if player_number not in game_state.players:
                raise Exception('You are not a player in this game')

            # Place bet
            if not game_state.place_bet(player_number, bet_amount):
                raise Exception('Invalid bet amount')

            # Check if all bets are placed
            if game_state.all_bets_placed():
                game_state.start_playing_phase()

            self.games_table.update_item(
                Key={'game_id': game_id},
                UpdateExpression='SET game_state = :state',
                ExpressionAttributeValues={':state': game_state.to_dict()}
            )

            result = {
                'game_id': game_id,
                'message': 'Bet placed',
                'game_state': game_state.to_dict(),
                'bet_amount': bet_amount
            }

            # Notify other players
            self._broadcast_to_game(game_id, {
                'type': 'player_bet_placed',
                'player_number': player_number,
                'message': f'Player {player_number} placed bet',
                'game_state': self._decimal_to_int(game_state.to_dict())
            }, exclude_connection_id=connection_id)

            return result

        except Exception as e:
            raise Exception(f"Failed to place bet: {str(e)}")

    def hit(self, connection_id: str, game_id: str) -> Dict:
        """Player hits (takes another card)"""
        try:
            session = self.session_manager.get_session(connection_id)
            if not session or session.get('game_id') != game_id:
                raise Exception('You are not in this game')

            player_number = session.get('player_number')

            response = self.games_table.get_item(Key={'game_id': game_id})
            if 'Item' not in response:
                raise Exception('Game not found')

            game = response['Item']
            game_state = BlackjackGameState.from_dict(game['game_state'])

            # Perform hit
            game_state.hit(player_number)

            # Check if dealer should play
            if game_state.phase == 'dealer_turn':
                game_state.dealer_play()

            self.games_table.update_item(
                Key={'game_id': game_id},
                UpdateExpression='SET game_state = :state',
                ExpressionAttributeValues={':state': game_state.to_dict()}
            )

            result = {
                'game_id': game_id,
                'message': 'Card dealt',
                'game_state': game_state.to_dict()
            }

            # Notify other players
            self._broadcast_to_game(game_id, {
                'type': 'player_hit',
                'player_number': player_number,
                'message': f'Player {player_number} hit',
                'game_state': self._decimal_to_int(game_state.to_dict())
            }, exclude_connection_id=connection_id)

            return result

        except Exception as e:
            raise Exception(f"Failed to hit: {str(e)}")

    def stand(self, connection_id: str, game_id: str) -> Dict:
        """Player stands (ends turn)"""
        try:
            session = self.session_manager.get_session(connection_id)
            if not session or session.get('game_id') != game_id:
                raise Exception('You are not in this game')

            player_number = session.get('player_number')

            response = self.games_table.get_item(Key={'game_id': game_id})
            if 'Item' not in response:
                raise Exception('Game not found')

            game = response['Item']
            game_state = BlackjackGameState.from_dict(game['game_state'])

            # Player stands
            game_state.stand(player_number)

            # Check if dealer should play
            if game_state.phase == 'dealer_turn':
                game_state.dealer_play()

            self.games_table.update_item(
                Key={'game_id': game_id},
                UpdateExpression='SET game_state = :state',
                ExpressionAttributeValues={':state': game_state.to_dict()}
            )

            result = {
                'game_id': game_id,
                'message': 'Player stood',
                'game_state': game_state.to_dict()
            }

            # Notify other players
            self._broadcast_to_game(game_id, {
                'type': 'player_stood',
                'player_number': player_number,
                'message': f'Player {player_number} stood',
                'game_state': self._decimal_to_int(game_state.to_dict())
            }, exclude_connection_id=connection_id)

            return result

        except Exception as e:
            raise Exception(f"Failed to stand: {str(e)}")

    def double_down(self, connection_id: str, game_id: str) -> Dict:
        """Player doubles down"""
        try:
            session = self.session_manager.get_session(connection_id)
            if not session or session.get('game_id') != game_id:
                raise Exception('You are not in this game')

            player_number = session.get('player_number')

            response = self.games_table.get_item(Key={'game_id': game_id})
            if 'Item' not in response:
                raise Exception('Game not found')

            game = response['Item']
            game_state = BlackjackGameState.from_dict(game['game_state'])

            # Double down
            game_state.double_down(player_number)

            # Check if dealer should play
            if game_state.phase == 'dealer_turn':
                game_state.dealer_play()

            self.games_table.update_item(
                Key={'game_id': game_id},
                UpdateExpression='SET game_state = :state',
                ExpressionAttributeValues={':state': game_state.to_dict()}
            )

            result = {
                'game_id': game_id,
                'message': 'Doubled down',
                'game_state': game_state.to_dict()
            }

            # Notify other players
            self._broadcast_to_game(game_id, {
                'type': 'player_doubled_down',
                'player_number': player_number,
                'message': f'Player {player_number} doubled down',
                'game_state': self._decimal_to_int(game_state.to_dict())
            }, exclude_connection_id=connection_id)

            return result

        except Exception as e:
            raise Exception(f"Failed to double down: {str(e)}")

    def split(self, connection_id: str, game_id: str) -> Dict:
        """Player splits their hand"""
        try:
            session = self.session_manager.get_session(connection_id)
            if not session or session.get('game_id') != game_id:
                raise Exception('You are not in this game')

            player_number = session.get('player_number')

            response = self.games_table.get_item(Key={'game_id': game_id})
            if 'Item' not in response:
                raise Exception('Game not found')

            game = response['Item']
            game_state = BlackjackGameState.from_dict(game['game_state'])

            # Split hand
            game_state.split(player_number)

            self.games_table.update_item(
                Key={'game_id': game_id},
                UpdateExpression='SET game_state = :state',
                ExpressionAttributeValues={':state': game_state.to_dict()}
            )

            result = {
                'game_id': game_id,
                'message': 'Hand split',
                'game_state': game_state.to_dict()
            }

            # Notify other players
            self._broadcast_to_game(game_id, {
                'type': 'player_split',
                'player_number': player_number,
                'message': f'Player {player_number} split their hand',
                'game_state': self._decimal_to_int(game_state.to_dict())
            }, exclude_connection_id=connection_id)

            return result

        except Exception as e:
            raise Exception(f"Failed to split: {str(e)}")

    def get_game(self, game_id: str) -> Dict:
        """Get current game state"""
        try:
            response = self.games_table.get_item(Key={'game_id': game_id})

            if 'Item' not in response:
                raise Exception('Game not found')

            game = response['Item']
            return self._decimal_to_int(game)

        except Exception as e:
            raise Exception(f"Failed to get game: {str(e)}")

    def _broadcast_to_game(self, game_id: str, message: Dict, exclude_connection_id: str = None):
        """Broadcast a message to all players in the game"""
        if not self.ws_utils:
            return

        game_sessions = self.session_manager.get_sessions_by_game(game_id)
        for session in game_sessions:
            connection_id = session.get('connection_id')
            if connection_id and connection_id != exclude_connection_id:
                try:
                    self.ws_utils.send_message(connection_id, message)
                except Exception as e:
                    print(f"Failed to broadcast to {connection_id}: {str(e)}")

    def _generate_unique_game_id(self, max_attempts: int = 10) -> str:
        """Generate a unique 4-character alphanumeric game ID"""
        characters = string.ascii_uppercase + string.digits

        for _ in range(max_attempts):
            game_id = ''.join(random.choices(characters, k=4))

            try:
                response = self.games_table.get_item(Key={'game_id': game_id})
                if 'Item' not in response:
                    return game_id
            except ClientError:
                continue

        raise Exception("Unable to generate unique game ID after maximum attempts")

    def _decimal_to_int(self, obj):
        """Convert DynamoDB Decimal types to int for JSON serialization"""
        if isinstance(obj, list):
            return [self._decimal_to_int(item) for item in obj]
        elif isinstance(obj, dict):
            return {key: self._decimal_to_int(value) for key, value in obj.items()}
        elif isinstance(obj, Decimal):
            return int(obj)
        return obj