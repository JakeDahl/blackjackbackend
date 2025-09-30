import json
import random
import string
import time
import uuid
import boto3.dynamodb.conditions
from botocore.exceptions import ClientError
from decimal import Decimal
from typing import Dict, Optional, List
from session_manager import SessionManager
from blackjack_models import BlackjackGameState


class GameService:
    """Service class for multiplayer blackjack game logic"""

    def __init__(self, games_table, session_manager: SessionManager, ws_utils=None, hands_history_table=None, user_chips_table=None):
        self.games_table = games_table
        self.session_manager = session_manager
        self.ws_utils = ws_utils
        self.hands_history_table = hands_history_table
        self.user_chips_table = user_chips_table

    def create_game(self, connection_id: str, user_id: str, apn_token: str,
                   visibility: str = 'private', initial_balance: int = 1000) -> Dict:
        """Create a new multiplayer blackjack game"""
        try:
            print(f"GameService.create_game - connection_id: {connection_id}, user_id: {user_id}, visibility: {visibility}")

            # Get or initialize user's chip balance
            user_balance = self._get_user_chip_balance(user_id, initial_balance)

            # Generate unique game ID
            game_id = self._generate_unique_game_id()
            print(f"Generated game_id: {game_id}")

            current_time = int(time.time())
            ttl = current_time + (24 * 60 * 60)  # 24 hours

            # Initialize game state with first player using their actual chip balance
            game_state = BlackjackGameState()
            game_state.add_player(1, user_id, user_balance)

            # Create game item (store deck in DynamoDB)
            game_item = {
                'game_id': game_id,
                'game_state': game_state.to_dict(include_deck=True),
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

            # Return response without deck (reduced payload)
            result = {
                'game_id': game_id,
                'message': f'Game created successfully. Waiting for players (1/{BlackjackGameState.MAX_PLAYERS}).',
                'game_status': 'waiting_for_players',
                'player_number': 1,
                'game_state': game_state.to_dict(),  # Excludes deck by default
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

            # Get or initialize user's chip balance
            initial_balance = game.get('initial_balance', 1000)
            user_balance = self._get_user_chip_balance(user_id, initial_balance)

            # Add player to game with their actual chip balance
            game_state.add_player(player_number, user_id, user_balance)

            # Update game status (store deck in DynamoDB)
            self.games_table.update_item(
                Key={'game_id': game_id},
                UpdateExpression='SET game_state = :state, game_status = :status',
                ExpressionAttributeValues={
                    ':state': game_state.to_dict(include_deck=True),
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
                ExpressionAttributeValues={':state': game_state.to_dict(include_deck=True)}
            )

            result = {
                'game_id': game_id,
                'message': 'Betting phase started. All players place your bets.',
                'game_state': game_state.to_dict()  # Excludes deck
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
                ExpressionAttributeValues={':state': game_state.to_dict(include_deck=True)}
            )

            result = {
                'game_id': game_id,
                'message': 'Bet placed',
                'game_state': game_state.to_dict(),  # Excludes deck
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
                # Save hand history after round is complete
                self._save_hand_history(game_id, game_state)

            self.games_table.update_item(
                Key={'game_id': game_id},
                UpdateExpression='SET game_state = :state',
                ExpressionAttributeValues={':state': game_state.to_dict(include_deck=True)}
            )

            result = {
                'game_id': game_id,
                'message': 'Card dealt',
                'game_state': game_state.to_dict()  # Excludes deck
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
                # Save hand history after round is complete
                self._save_hand_history(game_id, game_state)

            self.games_table.update_item(
                Key={'game_id': game_id},
                UpdateExpression='SET game_state = :state',
                ExpressionAttributeValues={':state': game_state.to_dict(include_deck=True)}
            )

            result = {
                'game_id': game_id,
                'message': 'Player stood',
                'game_state': game_state.to_dict()  # Excludes deck
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
                # Save hand history after round is complete
                self._save_hand_history(game_id, game_state)

            self.games_table.update_item(
                Key={'game_id': game_id},
                UpdateExpression='SET game_state = :state',
                ExpressionAttributeValues={':state': game_state.to_dict(include_deck=True)}
            )

            result = {
                'game_id': game_id,
                'message': 'Doubled down',
                'game_state': game_state.to_dict()  # Excludes deck
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
                ExpressionAttributeValues={':state': game_state.to_dict(include_deck=True)}
            )

            result = {
                'game_id': game_id,
                'message': 'Hand split',
                'game_state': game_state.to_dict()  # Excludes deck
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

    def get_user_balance(self, user_id: str) -> Dict:
        """Get user's current chip balance"""
        try:
            chip_balance = self._get_user_chip_balance(user_id, default_balance=1000)

            return {
                'user_id': user_id,
                'chip_balance': chip_balance
            }

        except Exception as e:
            raise Exception(f"Failed to get user balance: {str(e)}")

    def send_chat(self, connection_id: str, game_id: str, message: str) -> Dict:
        """Send a chat message to all players in the game"""
        try:
            session = self.session_manager.get_session(connection_id)
            if not session or session.get('game_id') != game_id:
                raise Exception('You are not in this game')

            player_number = session.get('player_number')
            user_id = session.get('user_id')

            # Verify game exists
            response = self.games_table.get_item(Key={'game_id': game_id})
            if 'Item' not in response:
                raise Exception('Game not found')

            # Broadcast chat message to all players including sender
            timestamp = int(time.time())
            chat_message = {
                'type': 'chat_message',
                'game_id': game_id,
                'player_number': player_number,
                'user_id': user_id,
                'message': message,
                'timestamp': timestamp
            }

            self._broadcast_to_game(game_id, chat_message)

            return {
                'game_id': game_id,
                'message': 'Chat message sent',
                'timestamp': timestamp
            }

        except Exception as e:
            raise Exception(f"Failed to send chat: {str(e)}")

    def claim_ad_reward(self, user_id: str, ad_network: str = None, ad_unit_id: str = None) -> Dict:
        """Claim reward for watching a rewarded ad"""
        try:
            # Ad reward configuration
            AD_REWARD_AMOUNT = 100  # Chips earned per ad
            AD_COOLDOWN_SECONDS = 300  # 5 minutes between ads (configurable)

            timestamp = int(time.time())

            # Get user's current chip balance
            current_balance = self._get_user_chip_balance(user_id, default_balance=1000)

            # Check if user_chips_table exists (for cooldown tracking)
            if not self.user_chips_table:
                raise Exception('User chips table not configured')

            # Get user's chip record to check last ad claim time
            response = self.user_chips_table.get_item(Key={'user_id': user_id})

            last_ad_claim = 0
            if 'Item' in response:
                last_ad_claim = response['Item'].get('last_ad_claim', 0)

            # Check cooldown
            time_since_last_ad = timestamp - last_ad_claim
            if time_since_last_ad < AD_COOLDOWN_SECONDS:
                cooldown_remaining = AD_COOLDOWN_SECONDS - time_since_last_ad
                raise Exception(f'Ad cooldown active. Try again in {cooldown_remaining} seconds.')

            # Award chips
            new_balance = current_balance + AD_REWARD_AMOUNT

            # Update user's chip balance and last ad claim time
            self.user_chips_table.put_item(
                Item={
                    'user_id': user_id,
                    'chip_balance': new_balance,
                    'last_updated': timestamp,
                    'last_ad_claim': timestamp,
                    'total_ads_watched': response['Item'].get('total_ads_watched', 0) + 1 if 'Item' in response else 1
                }
            )

            print(f"User {user_id} claimed ad reward: +{AD_REWARD_AMOUNT} chips (new balance: {new_balance})")

            # Log ad claim for analytics (optional)
            if ad_network and ad_unit_id:
                print(f"Ad details - Network: {ad_network}, Unit: {ad_unit_id}")

            return {
                'user_id': user_id,
                'reward_amount': AD_REWARD_AMOUNT,
                'new_balance': new_balance,
                'previous_balance': current_balance,
                'message': f'Reward claimed! +{AD_REWARD_AMOUNT} chips',
                'cooldown_seconds': AD_COOLDOWN_SECONDS,
                'timestamp': timestamp
            }

        except Exception as e:
            raise Exception(f"Failed to claim ad reward: {str(e)}")

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

    def _save_hand_history(self, game_id: str, game_state: BlackjackGameState):
        """Save completed hand history to DynamoDB"""
        if not self.hands_history_table:
            print("Warning: hands_history_table not configured, skipping hand history save")
            return

        if game_state.phase != 'round_over':
            print(f"Warning: attempted to save hand history before round is over (phase: {game_state.phase})")
            return

        try:
            timestamp = int(time.time())
            dealer_hand_data = game_state.dealer_hand.to_dict()
            dealer_value = game_state.dealer_hand.calculate_value()

            # Create a hand history record for each player
            for player_number, player in game_state.players.items():
                hand_id = str(uuid.uuid4())

                # Calculate chip change
                initial_bet = player.current_bet
                if player.result == 'blackjack':
                    chip_change = int(initial_bet * 1.5)  # 3:2 payout net win
                elif player.result == 'win':
                    chip_change = initial_bet  # 2:1 payout net win
                elif player.result == 'push':
                    chip_change = 0
                else:  # lose
                    chip_change = -initial_bet

                # Add split hand chip change if applicable
                if player.has_split:
                    if player.split_result == 'win':
                        chip_change += player.split_bet
                    elif player.split_result == 'push':
                        pass  # No change
                    else:  # lose
                        chip_change -= player.split_bet

                hand_record = {
                    'hand_id': hand_id,
                    'user_id': player.user_id,
                    'game_id': game_id,
                    'timestamp': timestamp,
                    'player_number': player_number,
                    'player_hand': player.hand.to_dict(),
                    'player_hand_value': player.hand.calculate_value(),
                    'split_hand': player.split_hand.to_dict() if player.split_hand else None,
                    'split_hand_value': player.split_hand.calculate_value() if player.split_hand else None,
                    'dealer_hand': dealer_hand_data,
                    'dealer_value': dealer_value,
                    'bet_amount': player.current_bet,
                    'split_bet_amount': player.split_bet if player.has_split else 0,
                    'result': player.result,
                    'split_result': player.split_result if player.has_split else None,
                    'chip_change': chip_change,
                    'final_balance': player.balance
                }

                self.hands_history_table.put_item(Item=hand_record)
                print(f"Saved hand history: {hand_id} for user {player.user_id}")

                # Update user chips table
                self._update_user_chips(player.user_id, player.balance, timestamp)

        except Exception as e:
            print(f"Error saving hand history: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            # Don't raise exception - hand history is non-critical

    def _update_user_chips(self, user_id: str, chip_balance: int, timestamp: int):
        """Update user's chip balance in DynamoDB"""
        if not self.user_chips_table:
            print("Warning: user_chips_table not configured, skipping chip balance update")
            return

        try:
            self.user_chips_table.put_item(
                Item={
                    'user_id': user_id,
                    'chip_balance': chip_balance,
                    'last_updated': timestamp
                }
            )
            print(f"Updated chip balance for user {user_id}: {chip_balance}")

        except Exception as e:
            print(f"Error updating user chips: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            # Don't raise exception - chip update is non-critical

    def _get_user_chip_balance(self, user_id: str, default_balance: int = 1000) -> int:
        """Get user's chip balance from DynamoDB, or initialize with default if new user"""
        if not self.user_chips_table:
            print("Warning: user_chips_table not configured, using default balance")
            return default_balance

        try:
            response = self.user_chips_table.get_item(Key={'user_id': user_id})

            if 'Item' in response:
                chip_balance = int(response['Item']['chip_balance'])
                print(f"Retrieved chip balance for user {user_id}: {chip_balance}")
                return chip_balance
            else:
                # New user - initialize with default balance
                print(f"New user {user_id}, initializing with {default_balance} chips")
                timestamp = int(time.time())
                self.user_chips_table.put_item(
                    Item={
                        'user_id': user_id,
                        'chip_balance': default_balance,
                        'last_updated': timestamp
                    }
                )
                return default_balance

        except Exception as e:
            print(f"Error getting user chip balance: {str(e)}")
            import traceback
            print(f"Traceback: {traceback.format_exc()}")
            # Return default balance on error
            return default_balance